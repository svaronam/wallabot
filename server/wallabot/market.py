"""Estadísticas de mercado a partir de lo que el bot va viendo 24/7."""
import re
import time
from collections import Counter

DAY = 86400
STOP = set("""de la el los las un una unos unas y o con sin para por en a del al mi tu su
se vende vendo nuevo nueva nuevos nuevas como muy buen buena estado perfecto perfecta
envio envío incluido incluye todo solo poco uso usado usada original originales mas más""".split())


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def percentile(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(round((len(xs) - 1) * p))))
    return xs[k]


def tokens(title):
    words = re.findall(r"[a-záéíóúñü0-9]+", (title or "").lower())
    return [w for w in words if len(w) > 1 and w not in STOP]


def similar(a, b):
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def asking_median(db, search_id, exclude_id=None, days=30):
    rows = db.q(
        "SELECT i.id, i.price FROM items i JOIN item_search s ON s.item_id=i.id "
        "WHERE s.search_id=? AND i.status IN ('active','reserved') AND i.last_seen>? AND i.price>0",
        (search_id, time.time() - days * DAY),
    )
    prices = [r["price"] for r in rows if r["id"] != exclude_id]
    return median(prices), len(prices)


def _age_ref(it):
    """Desde cuándo estaba publicado: fecha de creación si la conocemos, si no la primera vez visto."""
    c = it.get("created_ts")
    f = it.get("first_seen")
    return min(c, f) if c and f else (c or f)


def search_stats(db, search_id, with_detail=False):
    now = time.time()
    items = db.q(
        "SELECT i.* FROM items i JOIN item_search s ON s.item_id=i.id WHERE s.search_id=?",
        (search_id,),
    )
    active = [i for i in items if i["status"] in ("active", "reserved") and i["last_seen"] > now - 30 * DAY]
    reserved = [i for i in active if i["status"] == "reserved"]
    exits = [i for i in items if i["status"] in ("sold", "gone") and i["status_changed_at"]]
    exits30 = [i for i in exits if i["status_changed_at"] > now - 30 * DAY]
    exits7 = [i for i in exits if i["status_changed_at"] > now - 7 * DAY]
    new7 = [i for i in items if i["first_seen"] and i["first_seen"] > now - 7 * DAY]
    ask = [i["price"] for i in active if i["price"]]
    exit_prices = [i["price"] for i in exits30 if i["price"]]
    days_to_exit = []
    for i in exits30:
        ref = _age_ref(i)
        if ref:
            days_to_exit.append(max(0.0, (i["status_changed_at"] - ref) / DAY))
    discount = [
        (i["first_price"] - i["price"]) / i["first_price"] * 100
        for i in exits30 if i["first_price"] and i["price"] and i["first_price"] > 0
    ]
    st = {
        "search_id": search_id,
        "active": len(active),
        "reserved": len(reserved),
        "new_7d": len(new7),
        "exits_7d": len(exits7),
        "sold_confirmed_7d": len([i for i in exits7 if i["status"] == "sold"]),
        "exits_30d": len(exits30),
        "sell_through_7d": round(len(exits7) / (len(active) + len(exits7)) * 100, 1)
        if (active or exits7) else None,
        "ask_min": min(ask) if ask else None,
        "ask_p25": percentile(ask, 0.25),
        "ask_median": median(ask),
        "exit_median": median(exit_prices),
        "exit_p25": percentile(exit_prices, 0.25),
        "exit_p75": percentile(exit_prices, 0.75),
        "days_to_exit_median": round(median(days_to_exit), 1) if days_to_exit else None,
        "avg_discount_pct": round(sum(discount) / len(discount), 1) if discount else None,
    }
    if with_detail:
        cnt = Counter()
        for i in exits30:
            cnt.update(set(tokens(i["title"])))
        st["top_words"] = [{"word": w, "n": n} for w, n in cnt.most_common(15)]
        series = []
        for d in range(13, -1, -1):
            a, b = now - (d + 1) * DAY, now - d * DAY
            ex = [i for i in exits if a < i["status_changed_at"] <= b]
            series.append({
                "day": time.strftime("%d/%m", time.localtime(b)),
                "new": len([i for i in items if i["first_seen"] and a < i["first_seen"] <= b]),
                "exits": len(ex),
                "exit_median": median([i["price"] for i in ex]),
            })
        st["series"] = series
        recent = sorted(exits30, key=lambda i: i["status_changed_at"], reverse=True)[:25]
        st["recent_exits"] = [{
            "id": i["id"], "title": i["title"], "price": i["price"], "first_price": i["first_price"],
            "status": i["status"], "image": i["image"], "slug": i["slug"],
            "days": round((i["status_changed_at"] - (_age_ref(i) or i["status_changed_at"])) / DAY, 1),
            "at": i["status_changed_at"],
        } for i in recent]
        cheapest = sorted([i for i in active if i["price"]], key=lambda i: i["price"])[:10]
        st["cheapest_active"] = [{
            "id": i["id"], "title": i["title"], "price": i["price"], "image": i["image"],
            "slug": i["slug"], "status": i["status"], "city": i["city"],
        } for i in cheapest]
    return st


def ranking(db):
    out = []
    for s in db.searches():
        st = search_stats(db, s["id"])
        st.update({"name": s["name"], "kind": s["kind"], "keywords": s["keywords"], "active_search": s["active"]})
        out.append(st)
    out.sort(key=lambda r: (r["exits_7d"], r["sell_through_7d"] or 0), reverse=True)
    return out
