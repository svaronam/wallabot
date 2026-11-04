"""Prueba sin internet: simula Wallapop y comprueba que salen los avisos correctos.

Ejecutar:  python -m tests.test_bot   (desde la carpeta server/)
"""
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wallabot.db import DB  # noqa: E402
from wallabot.market import search_stats  # noqa: E402
from wallabot.tracker import Tracker  # noqa: E402
from wallabot.wallapop import normalize  # noqa: E402


def raw(i, title, price, user="u%d", reserved=False, desc=""):
    """Anuncio con la forma real de la respuesta de /api/v3/search."""
    return {
        "id": f"it{i}", "user_id": (user % i) if "%d" in user else user,
        "title": title, "description": desc,
        "price": {"amount": price, "currency": "EUR"},
        "images": [{"urls": {"small": f"https://cdn/{i}s.jpg", "medium": f"https://cdn/{i}m.jpg"}}],
        "web_slug": f"anuncio-{i}", "location": {"city": "Madrid"},
        "reserved": {"flag": reserved}, "shipping": {"user_allows_shipping": True},
        "created_at": int((time.time() - 5 * 86400) * 1000),
    }


class FakeWallapop:
    def __init__(self):
        self.results = []
        self.details = {}
        self.requests = 0

    async def search(self, *a, **k):
        self.requests += 1
        return [normalize(o) for o in self.results]

    async def item(self, iid):
        self.requests += 1
        d = self.details.get(iid, "same")
        if d is None:
            return None
        if d == "same":
            o = next(o for o in self.results if o["id"] == iid)
            return normalize(o)
        return normalize(d)

    async def seller(self, uid):
        return {"reviews": 0, "sells": 0, "register_ts": time.time() - 3 * 86400}


def check(cond, msg):
    print(("  OK  " if cond else "  FALLO ") + msg)
    if not cond:
        check.failed += 1


check.failed = 0


async def scenario():
    tmp = tempfile.mkdtemp()
    db = DB(os.path.join(tmp, "t.db"))
    wp = FakeWallapop()
    tr = Tracker(db, wp)
    sid = db.add_search({"name": "PS5", "kind": "alert", "keywords": "ps5", "chollo_pct": 25,
                         "exclude_words": "caja", "notify_sold": 1})

    print("1) Primera pasada: toma base sin avisar de lo que ya existe")
    wp.results = [raw(i, f"PS5 consola modelo {i}", 300 + i * 5) for i in range(1, 11)]
    wp.results.append(raw(99, "Caja vacía PS5", 10))
    await tr.run_search(db.search(sid))
    evs = db.events_after(0)
    check(len(evs) == 1 and evs[0]["type"] == "sistema", f"solo aviso de puesta en marcha ({[e['type'] for e in evs]})")
    check(db.one("SELECT COUNT(*) n FROM items")["n"] == 10, "excluye 'caja'")

    print("2) Segunda pasada: chollo, prisa, republicado, bajada y reservado")
    last = db.latest_event_id()
    wp.results[1]["price"]["amount"] = 280          # it2: 310 -> 280 (bajada)
    wp.results[2]["reserved"]["flag"] = True        # it3 reservado
    wp.results += [
        raw(20, "PS5 digital como nueva", 200),                                       # chollo
        raw(21, "PS5 slim", 330, desc="Urge vender por mudanza"),                     # prisa
        raw(22, "PS5 consola modelo 4", 315, user="u4"),                              # republicado por u4
        raw(23, "PS5 estándar", 340),                                                 # nuevo normal
    ]
    await tr.run_search(db.search(sid))
    evs = db.events_after(last)
    types = {e["type"] for e in evs}
    print("   eventos:", [(e["type"], e["title"]) for e in evs])
    for t in ("chollo", "urgente", "republicado", "nuevo", "bajada", "reservado"):
        check(t in types, f"aviso '{t}'")
    ch = next(e for e in evs if e["type"] == "chollo")
    check(ch["image"] == "https://cdn/20m.jpg" and "200 €" in ch["body"], "el chollo lleva foto y precio")
    check("vendedor sin valoraciones" in ch["body"], "marca vendedor de riesgo en el chollo")
    check(ch["url"] == "https://es.wallapop.com/item/anuncio-20", "enlace al anuncio")

    print("3) Revisión de fichas: vendido y liberado")
    last = db.latest_event_id()
    db.x("UPDATE items SET last_checked=0")
    wp.details["it5"] = None                      # 404 -> retirado
    d3 = dict(wp.results[2]); d3["reserved"] = {"flag": False}
    wp.details["it3"] = d3                        # reservado -> libre
    wp.results[2]["reserved"] = {"flag": False}
    d6 = dict(wp.results[5]); d6["flags"] = {"sold": True}
    wp.details["it6"] = d6                        # vendido confirmado
    import wallabot.config as cfg
    cfg.RECHECK_BUDGET = 50
    await tr.rechecks()
    evs = db.events_after(last)
    print("   eventos:", [(e["type"], e["title"]) for e in evs])
    check(any(e["type"] == "reactivado" for e in evs), "aviso de reservado que vuelve a estar libre")
    check(len([e for e in evs if e["type"] == "vendido"]) == 2, "avisos de vendido / retirado")
    check(db.one("SELECT status FROM items WHERE id='it5'")["status"] == "gone", "it5 retirado")

    print("4) Estadísticas de mercado")
    st = search_stats(db, sid, with_detail=True)
    print("  ", {k: st[k] for k in ("active", "exits_7d", "ask_median", "exit_median", "days_to_exit_median", "sell_through_7d")})
    check(st["exits_7d"] == 2 and st["exit_median"] is not None, "cuenta ventas y precio de venta")
    check(st["days_to_exit_median"] and st["days_to_exit_median"] >= 4.9, "días hasta vender usando la fecha de publicación")

    print("5) Seguir un anuncio: se avisa aunque la búsqueda no lo pida")
    db.update_search(sid, {"notify_drop": 0})
    db.x("UPDATE searches SET baseline_done=1 WHERE id=?", (sid,))
    db.x("UPDATE items SET followed=1 WHERE id='it7'")
    last = db.latest_event_id()
    wp.results[6]["price"]["amount"] = 250
    await tr.run_search(db.search(sid))
    evs = db.events_after(last)
    check([e["type"] for e in evs] == ["bajada"], f"bajada de un anuncio seguido ({[e['type'] for e in evs]})")

    print("6) Resumen diario")
    last = db.latest_event_id()
    tr.daily_summary()
    evs = db.events_after(last)
    check(len(evs) == 1 and evs[0]["type"] == "resumen", "un único resumen")
    print("  ", evs[0]["body"].replace("\n", " | "))
    return db, wp


def api_test(db, wp):
    print("7) API HTTP + long-poll (como la APK)")
    import uvicorn
    from wallabot.web import build_app
    app = build_app(db=db, client=wp, start_loop=False)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    base = f"http://127.0.0.1:{port}"

    def call(path, method="GET", data=None):
        req = urllib.request.Request(base + path, method=method,
                                     data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, (json.loads(r.read()) if r.headers.get("content-type", "").startswith("application/json") else r.read())

    st, _ = call("/")
    check(st == 200, "sirve el panel")
    latest = call("/api/status")[1]["latest_event"]
    # long-poll: lanza la espera y crea un evento a los 1,5 s
    result = {}

    def poll():
        t0 = time.time()
        result["r"] = call(f"/api/events?after={latest}&wait=20")[1]
        result["dt"] = time.time() - t0
    t = threading.Thread(target=poll); t.start()
    time.sleep(1.5)
    call("/api/test-notification", "POST")
    t.join(25)
    check(result.get("r") and len(result["r"]["events"]) == 1 and result["dt"] < 5,
          f"el long-poll recibe el aviso al momento ({result.get('dt', 0):.1f} s)")
    st, s2 = call("/api/searches", "POST", {"keywords": "pokemon charizard", "kind": "market"})
    check(s2["kind"] == "market" and s2["pages"] == 3 and s2["interval_min"] == 30, "crea búsqueda de mercado con valores por defecto")
    st, s3 = call(f"/api/searches/{s2['id']}", "PUT", {"max_price": "150", "notify_daily": False})
    check(s3["max_price"] == 150 and s3["notify_daily"] == 0, "edita búsqueda")
    check(len(call("/api/market")[1]) == 2, "ranking de mercado")
    m = call("/api/market/1")[1]
    check(len(m["series"]) == 14 and m["recent_exits"], "detalle de mercado con serie y ventas")
    check(call("/api/items/it20/follow", "POST", {"follow": True})[1]["followed"], "seguir desde la API")
    check(len(call("/api/items/followed")[1]) == 2, "lista de seguidos")
    check(len(call("/api/feed?type=chollo")[1]) == 1, "filtro de avisos por tipo")
    an = call("/api/analytics?days=30")[1]
    check(len(an["rows"]) >= 10 and "drops" in an["cols"], "datos de análisis")
    c = {k: i for i, k in enumerate(an["cols"])}
    it7 = next(r for r in an["rows"] if r[c["id"]] == "it7")
    check(it7[c["drops"]] == 1 and it7[c["searches"]] == [1], "cuenta bajadas y búsquedas de cada anuncio")
    check(call("/static/analytics.js")[0] == 200, "sirve el módulo de análisis")
    server.should_exit = True
    th.join(5)


if __name__ == "__main__":
    db, wp = asyncio.run(scenario())
    api_test(db, wp)
    print("\n" + ("TODO BIEN" if not check.failed else f"{check.failed} FALLOS"))
    sys.exit(1 if check.failed else 0)
