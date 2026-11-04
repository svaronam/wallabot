"""Bucle 24/7: lanza búsquedas, vuelve a mirar anuncios y genera los avisos."""
import asyncio
import logging
import time

from . import config
from .market import asking_median, search_stats, similar
from .wallapop import WallapopError, item_url

log = logging.getLogger("wallabot")
DAY = 86400

# Prioridades (el móvil usa un canal distinto para cada tipo)
P_HIGH, P_DEFAULT, P_LOW = 5, 3, 2


def eur(v):
    if v is None:
        return "?"
    return (f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}").replace(",", "X").replace(".", ",").replace("X", ".") + " €"


class Tracker:
    def __init__(self, db, client):
        self.db = db
        self.wp = client
        self.new_event = asyncio.Event()
        self.errors_in_row = 0
        self.blocked_warned_at = 0
        self.last_cycle = None
        self.running = True
        self._run_now = set()
        self._seller_cache = {}

    # ---------------------------------------------------------------- eventos
    def emit(self, type_, title, body="", priority=P_DEFAULT, **kw):
        eid = self.db.add_event(type_, title, body, priority, **kw)
        self.new_event.set()
        self.new_event = asyncio.Event()
        log.info("evento %s: %s", type_, title)
        return eid

    def run_now(self, sid):
        self._run_now.add(int(sid))

    # ---------------------------------------------------------------- bucle
    async def loop(self):
        while self.running:
            t0 = time.time()
            try:
                await self.cycle()
            except Exception:  # nunca se para el bot por un fallo puntual
                log.exception("fallo en el ciclo")
            self.last_cycle = time.time()
            pause = 30 if self.errors_in_row < 5 else min(600, 30 * self.errors_in_row)
            await asyncio.sleep(max(1, pause - (time.time() - t0)))

    async def cycle(self):
        now = time.time()
        for s in self.db.searches(only_active=True):
            due = (s["last_run"] or 0) + float(s["interval_min"] or 5) * 60 <= now
            if due or s["id"] in self._run_now:
                self._run_now.discard(s["id"])
                await self.guarded(self.run_search(s), s)
        await self.guarded(self.rechecks())
        self.daily_tasks()

    async def guarded(self, coro, search=None):
        try:
            await coro
            if self.errors_in_row >= 5:
                self.emit("sistema", "Rastreo recuperado", "Wallapop vuelve a responder con normalidad.", P_LOW)
            self.errors_in_row = 0
        except WallapopError as e:
            self.errors_in_row += 1
            log.warning("Wallapop: %s (%d seguidos)", e, self.errors_in_row)
            if search:
                self.db.x("UPDATE searches SET last_error=?, last_run=? WHERE id=?", (str(e), time.time(), search["id"]))
            if self.errors_in_row >= 5 and time.time() - self.blocked_warned_at > 2 * 3600:
                self.blocked_warned_at = time.time()
                blocked = e.status in (403, 429)
                self.emit("sistema",
                          "Wallapop está bloqueando peticiones" if blocked else "Problemas para llegar a Wallapop",
                          f"{self.errors_in_row} errores seguidos ({e}). El bot baja el ritmo y sigue intentándolo.",
                          P_DEFAULT)

    # ---------------------------------------------------------------- búsquedas
    async def run_search(self, s):
        lat = s["lat"] if s["lat"] is not None else config.DEFAULT_LAT
        lng = s["lng"] if s["lng"] is not None else config.DEFAULT_LNG
        results = await self.wp.search(
            s["keywords"], lat, lng, s["distance_km"], s["min_price"], s["max_price"],
            s["category_id"], bool(s["shipping_only"]), s["pages"] or 1,
        )
        now = time.time()
        excl = [w.strip().lower() for w in (s["exclude_words"] or "").split(",") if w.strip()]
        kept = []
        for it in results:
            title = (it["title"] or "").lower()
            if excl and any(w in title for w in excl):
                continue
            if it["price"] is not None:
                if s["min_price"] is not None and it["price"] < s["min_price"]:
                    continue
                if s["max_price"] is not None and it["price"] > s["max_price"]:
                    continue
            kept.append(it)

        baseline = not s["baseline_done"]
        fresh = []
        for it in kept:
            old = self.db.one("SELECT * FROM items WHERE id=?", (it["id"],))
            if old is None:
                self.insert_item(it, now)
                self.link(it["id"], s["id"], now)
                if not baseline:
                    fresh.append(it)
            else:
                linked = self.db.one("SELECT 1 AS x FROM item_search WHERE item_id=? AND search_id=?", (it["id"], s["id"]))
                self.link(it["id"], s["id"], now)
                self.apply_update(old, it, now, source="search")
                if not linked and not baseline and old["status"] in ("active", "reserved"):
                    fresh.append(it)  # ya lo conocía otra búsqueda, pero para esta es nuevo

        upd = {"last_run": now, "last_error": None}
        if kept:
            upd["last_results_at"] = now
        self.db.x("UPDATE searches SET last_run=?, last_error=?, last_results_at=COALESCE(?, last_results_at) WHERE id=?",
                  (now, None, upd.get("last_results_at"), s["id"]))

        if baseline:
            self.db.x("UPDATE searches SET baseline_done=1 WHERE id=?", (s["id"],))
            self.emit("sistema", f"Búsqueda «{s['name']}» en marcha",
                      f"{len(kept)} anuncios tomados como base. A partir de ahora solo te aviso de lo nuevo.",
                      P_LOW, search_id=s["id"])
            return
        if s["kind"] == "alert":
            # los más antiguos primero, para que el más reciente quede arriba en el móvil
            for it in reversed(fresh):
                await self.notify_new_item(s, it)

    def insert_item(self, it, now):
        status = "reserved" if it["reserved"] else "active"
        self.db.x(
            "INSERT INTO items(id,title,description,price,first_price,currency,image,slug,user_id,city,shipping,"
            "reserved,status,created_ts,first_seen,last_seen,last_checked,status_changed_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            (it["id"], it["title"], it["description"], it["price"], it["price"], it["currency"], it["image"],
             it["slug"], it["user_id"], it["city"], it["shipping"], it["reserved"], status,
             it["created_ts"], now, now, now),
        )
        if it["price"] is not None:
            self.db.x("INSERT INTO price_history(item_id,ts,price) VALUES(?,?,?)", (it["id"], now, it["price"]))

    def link(self, item_id, sid, now):
        self.db.x("INSERT OR IGNORE INTO item_search(item_id,search_id,linked_at) VALUES(?,?,?)", (item_id, sid, now))

    # ---------------------------------------------------------------- avisos de anuncio nuevo
    async def notify_new_item(self, s, it):
        med, n = asking_median(self.db, s["id"], exclude_id=it["id"])
        price = it["price"]
        lines = [eur(price)]
        if med and n >= 6:
            lines[0] += f" · mediana {eur(med)}"
        extra = []
        if it["city"]:
            extra.append(it["city"])
        extra.append("con envío" if it["shipping"] else "sin envío")
        lines.append(" · ".join(extra))

        is_chollo = bool(price and med and n >= 6 and price <= med * (1 - (s["chollo_pct"] or 25) / 100))
        pct_below = round((1 - price / med) * 100) if (price and med) else None

        text = f"{it['title']} {it['description']}".lower()
        urgent = [w for w in config.URGENT_WORDS if w in text]

        # ¿lo ha vuelto a subir el mismo vendedor?
        repub = None
        if it["user_id"]:
            for o in self.db.q("SELECT * FROM items WHERE user_id=? AND id<>? ORDER BY first_seen DESC LIMIT 30",
                               (it["user_id"], it["id"])):
                if similar(o["title"], it["title"]) >= 0.6:
                    repub = o
                    break

        risk = []
        too_cheap = bool(price and med and n >= 6 and price < med * 0.4)
        if s["notify_risk"] and it["user_id"] and (is_chollo or too_cheap):
            risk = await self.seller_risk(it["user_id"])
        if too_cheap:
            risk.insert(0, "precio demasiado bajo")

        # se elige UN aviso por anuncio, el más importante
        if is_chollo and s["notify_chollo"]:
            type_, prio = "chollo", P_HIGH
            title = f"🔥 Chollo −{pct_below}% · {it['title']}"
        elif repub and s["notify_republished"]:
            type_, prio = "republicado", P_DEFAULT
            title = f"🔁 Republicado · {it['title']}"
            if repub["price"] and price is not None and repub["price"] != price:
                lines.insert(1, f"antes {eur(repub['price'])} en otro anuncio")
            else:
                lines.insert(1, "el vendedor lo ha vuelto a subir (señal de prisa)")
        elif urgent and s["notify_urgent"]:
            type_, prio = "urgente", P_DEFAULT
            title = f"⏱️ Vende con prisa · {it['title']}"
        elif s["notify_new"] or (s["notify_chollo"] and is_chollo):
            type_, prio = "nuevo", P_DEFAULT
            title = f"🆕 {it['title']}"
        else:
            return

        if urgent:
            lines.append("«" + ", ".join(urgent[:3]) + "»")
        if risk:
            lines.append("⚠️ " + ", ".join(risk))
        self.emit(type_, title, "\n".join(lines), prio, image=it["image"], url=item_url(it["slug"]),
                  item_id=it["id"], search_id=s["id"],
                  extra={"price": price, "median": med, "search": s["name"], "risk": risk})

    async def seller_risk(self, user_id):
        cached = self._seller_cache.get(user_id)
        if cached and time.time() - cached[0] < DAY:
            return list(cached[1])
        try:
            info = await self.wp.seller(user_id)
        except WallapopError:
            return []
        risk = []
        if info["reviews"] == 0:
            risk.append("vendedor sin valoraciones")
        if info["register_ts"] and time.time() - info["register_ts"] < 30 * DAY:
            risk.append("cuenta de menos de un mes")
        self._seller_cache[user_id] = (time.time(), risk)
        return list(risk)

    # ---------------------------------------------------------------- cambios en anuncios conocidos
    def _linked_alerts(self, item_id):
        return self.db.q(
            "SELECT s.* FROM searches s JOIN item_search l ON l.search_id=s.id "
            "WHERE l.item_id=? AND s.active=1 AND s.kind='alert'", (item_id,))

    def _wants(self, old, flag):
        """¿Hay que avisar de este cambio? Siempre si lo sigues; si no, según la búsqueda."""
        if old["followed"]:
            return None, True
        for s in self._linked_alerts(old["id"]):
            if s[flag]:
                return s, True
        return None, False

    def apply_update(self, old, new, now, source):
        """Compara lo guardado con lo nuevo (de una búsqueda o de la ficha) y avisa de los cambios."""
        iid = old["id"]
        if source == "search" and old["status"] in ("sold", "gone"):
            # el buscador de Wallapop tarda en quitar los vendidos: manda lo que dijo la ficha
            return
        sets = {"last_seen": now}
        if source == "check":
            sets["last_checked"] = now
        for k in ("title", "image", "slug", "city"):
            if new.get(k):
                sets[k] = new[k]
        if new.get("description"):
            sets["description"] = new["description"]
        url = item_url(new.get("slug") or old["slug"])
        title = new.get("title") or old["title"]
        image = new.get("image") or old["image"]

        # precio
        np_, op = new.get("price"), old["price"]
        if np_ is not None and op is not None and abs(np_ - op) >= 0.01:
            sets["price"] = np_
            self.db.x("INSERT INTO price_history(item_id,ts,price) VALUES(?,?,?)", (iid, now, np_))
            if np_ < op:
                s, ok = self._wants(old, "notify_drop")
                if ok:
                    pct = round((1 - np_ / op) * 100)
                    first = old["first_price"]
                    body = f"{eur(op)} → {eur(np_)} (−{pct}%)"
                    if first and first > op:
                        body += f"\nPrecio inicial: {eur(first)}"
                    self.emit("bajada", f"📉 Baja de precio · {title}", body, P_DEFAULT, image=image, url=url,
                              item_id=iid, search_id=s["id"] if s else None)
        elif np_ is not None and op is None:
            sets["price"] = np_

        # reservado / vendido
        status = old["status"]
        if new.get("sold"):
            new_status = "sold"
        elif new.get("gone"):
            new_status = "gone"
        else:
            new_status = "reserved" if new.get("reserved") else "active"
        sets["reserved"] = 1 if new_status == "reserved" else 0
        if new_status != status:
            sets["status"] = new_status
            sets["status_changed_at"] = now
            self._status_event(old, status, new_status, title, image, url, np_ if np_ is not None else op)

        cols = ",".join(f"{k}=?" for k in sets)
        self.db.x(f"UPDATE items SET {cols} WHERE id=?", list(sets.values()) + [iid])

    def _status_event(self, old, before, after, title, image, url, price):
        iid = old["id"]
        if before == "reserved" and after == "active":
            s, ok = self._wants(old, "notify_reactivated")
            if ok:
                self.emit("reactivado", f"↩️ Vuelve a estar disponible · {title}",
                          f"{eur(price)} · estaba reservado y lo han liberado", P_HIGH, image=image, url=url,
                          item_id=iid, search_id=s["id"] if s else None)
        elif after == "reserved":
            s, ok = self._wants(old, "notify_sold")
            if ok:
                self.emit("reservado", f"🔒 Reservado · {title}", f"{eur(price)}", P_LOW, image=image, url=url,
                          item_id=iid, search_id=s["id"] if s else None)
        elif after in ("sold", "gone"):
            s, ok = self._wants(old, "notify_sold")
            if ok:
                ref = old["created_ts"] or old["first_seen"]
                days = (time.time() - ref) / DAY if ref else None
                txt = "Vendido" if after == "sold" else "Retirado (probablemente vendido)"
                body = f"{eur(price)}"
                if days is not None:
                    body += f" · tardó {days:.1f} días" if days >= 1 else f" · tardó {days * 24:.0f} h"
                self.emit("vendido", f"✅ {txt} · {title}", body, P_LOW, image=image, url=url,
                          item_id=iid, search_id=s["id"] if s else None)

    async def check_item(self, row):
        now = time.time()
        fresh = await self.wp.item(row["id"])
        if fresh is None:
            self.apply_update(row, {"gone": True, "price": None}, now, source="check")
            # gone no actualiza last_seen: se guarda cuándo se le vio por última vez
            self.db.x("UPDATE items SET last_seen=?, last_checked=? WHERE id=?", (row["last_seen"], now, row["id"]))
        else:
            self.apply_update(row, fresh, now, source="check")

    async def rechecks(self):
        now = time.time()
        rows = self.db.q(
            """SELECT i.*, MAX(CASE WHEN s.kind='alert' THEN 1 ELSE 0 END) AS in_alert
               FROM items i LEFT JOIN item_search l ON l.item_id=i.id LEFT JOIN searches s ON s.id=l.search_id
               WHERE i.status IN ('active','reserved') AND i.last_seen>? AND (s.active=1 OR i.followed=1)
               GROUP BY i.id
               ORDER BY i.followed DESC, i.last_checked ASC
               LIMIT 200""",
            (now - 30 * DAY,),
        )
        due = []
        for r in rows:
            hours = 1 if r["followed"] else (config.RECHECK_HOURS_ALERT if r["in_alert"] else config.RECHECK_HOURS_MARKET)
            if (r["last_checked"] or 0) + hours * 3600 <= now:
                due.append(r)
            if len(due) >= config.RECHECK_BUDGET:
                break
        for r in due:
            await self.check_item(r)

    # ---------------------------------------------------------------- tareas diarias
    def daily_tasks(self):
        lt = time.localtime()
        today = time.strftime("%Y-%m-%d", lt)
        if lt.tm_hour >= config.DAILY_HOUR and self.db.kv_get("daily_done") != today:
            self.db.kv_set("daily_done", today)
            self.daily_summary()
            self.db.cleanup(config.KEEP_DAYS)
        self.no_results_check()

    def daily_summary(self):
        now = time.time()
        lines, best = [], None
        for s in self.db.searches(only_active=True):
            if not s["notify_daily"]:
                continue
            st = search_stats(self.db, s["id"])
            new24 = self.db.one(
                "SELECT COUNT(*) AS n FROM items i JOIN item_search l ON l.item_id=i.id "
                "WHERE l.search_id=? AND i.first_seen>?", (s["id"], now - DAY))["n"]
            out24 = self.db.one(
                "SELECT COUNT(*) AS n FROM items i JOIN item_search l ON l.item_id=i.id "
                "WHERE l.search_id=? AND i.status IN ('sold','gone') AND i.status_changed_at>?",
                (s["id"], now - DAY))["n"]
            line = f"• {s['name']}: {new24} nuevos, {out24} vendidos"
            if st["ask_min"] is not None:
                line += f", desde {eur(st['ask_min'])}"
            if st["exit_median"] is not None:
                line += f", se vende a ~{eur(st['exit_median'])}"
            lines.append(line)
            if out24 and (best is None or out24 > best[1]):
                best = (s["name"], out24)
        if lines:
            head = f"Lo que más se ha movido hoy: {best[0]}\n" if best else ""
            self.emit("resumen", "📊 Resumen del día", head + "\n".join(lines), P_LOW)

    def no_results_check(self):
        now = time.time()
        for s in self.db.searches(only_active=True):
            ref = s["last_results_at"] or s["created_at"] or now
            if now - ref > 3 * DAY and now - (s["noresults_warned_at"] or 0) > 3 * DAY:
                self.db.x("UPDATE searches SET noresults_warned_at=? WHERE id=?", (now, s["id"]))
                self.emit("sistema", f"«{s['name']}» lleva 3 días sin resultados",
                          "Revisa las palabras o el rango de precio de la búsqueda.", P_LOW, search_id=s["id"])
