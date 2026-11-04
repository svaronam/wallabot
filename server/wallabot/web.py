"""API HTTP (para la APK y el panel) y servidor del panel web. Starlette: ligero para una Pi 3."""
import asyncio
import os
import time
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__, config
from .db import DB, SEARCH_FIELDS
from .market import ranking, search_stats
from .tracker import Tracker
from .wallapop import item_url

STATIC = os.path.join(os.path.dirname(__file__), "static")


def build_app(db=None, client=None, start_loop=True):
    state = {}

    @asynccontextmanager
    async def lifespan(app):
        state["db"] = db or DB(config.DB_PATH)
        if client is None:
            from .wallapop import Wallapop
            state["wp"] = Wallapop(config.MIN_REQUEST_GAP)
        else:
            state["wp"] = client
        state["tracker"] = Tracker(state["db"], state["wp"])
        app.state.wb = state
        task = asyncio.create_task(state["tracker"].loop()) if start_loop else None
        yield
        state["tracker"].running = False
        if task:
            task.cancel()
        if hasattr(state["wp"], "close"):
            await state["wp"].close()

    def api(fn, auth=True):
        async def handler(request: Request):
            if auth and config.TOKEN:
                tok = request.headers.get("X-Token") or request.query_params.get("token")
                if tok != config.TOKEN:
                    return JSONResponse({"detail": "token incorrecto"}, status_code=401)
            try:
                out = await fn(request, state["db"], state["tracker"])
            except HTTPException as e:
                return JSONResponse({"detail": e.detail}, status_code=e.status_code)
            except (ValueError, TypeError) as e:
                return JSONResponse({"detail": f"valor no válido: {e}"}, status_code=400)
            return out if not isinstance(out, (dict, list)) else JSONResponse(out)
        return handler

    async def body(request):
        try:
            return await request.json()
        except Exception:
            return {}

    def qint(request, name, default):
        try:
            return int(request.query_params.get(name, default))
        except ValueError:
            return default

    # ------------------------------------------------------------ panel y estado
    async def index(request):
        return FileResponse(os.path.join(STATIC, "index.html"))

    async def health(request, db, tr):
        return {"ok": True, "version": __version__}

    async def status(request, db, tr):
        return {
            "version": __version__,
            "last_cycle": tr.last_cycle,
            "errors_in_row": tr.errors_in_row,
            "requests": getattr(state["wp"], "requests", 0),
            "searches": len(db.searches(only_active=True)),
            "items": db.one("SELECT COUNT(*) AS n FROM items")["n"],
            "tracked_active": db.one("SELECT COUNT(*) AS n FROM items WHERE status IN ('active','reserved')")["n"],
            "followed": db.one("SELECT COUNT(*) AS n FROM items WHERE followed=1")["n"],
            "latest_event": db.latest_event_id(),
        }

    # ------------------------------------------------------------ eventos (APK)
    async def events(request, db, tr):
        """Long-poll: si no hay nada nuevo espera hasta `wait` segundos a que llegue algo."""
        after = qint(request, "after", 0)
        wait = max(0, min(qint(request, "wait", 0), 90))
        limit = max(1, min(qint(request, "limit", 50), 100))
        deadline = time.time() + wait
        while True:
            rows = db.events_after(after, limit)
            if rows or time.time() >= deadline:
                return {"events": rows, "latest": db.latest_event_id(), "server_time": time.time()}
            try:
                await asyncio.wait_for(tr.new_event.wait(), timeout=max(0.1, deadline - time.time()))
            except asyncio.TimeoutError:
                pass

    async def feed(request, db, tr):
        limit = qint(request, "limit", 100)
        typ = request.query_params.get("type", "")
        if typ:
            rows = db.q("SELECT * FROM events WHERE type=? ORDER BY id DESC LIMIT ?", (typ, limit))
        else:
            rows = db.q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        ids = list({r["item_id"] for r in rows if r["item_id"]})
        followed = set()
        if ids:
            marks = ",".join("?" * len(ids))
            followed = {r["id"] for r in db.q(f"SELECT id FROM items WHERE followed=1 AND id IN ({marks})", ids)}
        for r in rows:
            r["followed"] = r["item_id"] in followed
        return rows

    async def test_notification(request, db, tr):
        eid = tr.emit("sistema", "Prueba de notificación", "Si ves esto en el móvil, todo funciona.", 3)
        return {"id": eid}

    # ------------------------------------------------------------ búsquedas
    def clean(data):
        out = {}
        for k in SEARCH_FIELDS:
            if k not in data:
                continue
            v = data[k]
            if v == "":
                v = None
            if k.startswith("notify_") or k in ("active", "shipping_only"):
                v = 1 if v in (1, True, "1", "true", "on") else 0
            elif k in ("min_price", "max_price", "lat", "lng", "distance_km", "interval_min", "chollo_pct") and v is not None:
                v = float(v)
            elif k in ("pages", "category_id") and v is not None:
                v = int(v)
            out[k] = v
        if out.get("kind") not in (None, "alert", "market"):
            raise HTTPException(400, "kind debe ser alert o market")
        if out.get("kind") is None:
            out.pop("kind", None)
        if out.get("interval_min") is not None:
            out["interval_min"] = max(2.0, out["interval_min"])  # no machacar a Wallapop
        else:
            out.pop("interval_min", None)
        if out.get("pages") is not None:
            out["pages"] = max(1, min(5, out["pages"]))
        else:
            out.pop("pages", None)
        if "chollo_pct" in out and out["chollo_pct"] is None:
            out.pop("chollo_pct")
        return out

    async def list_searches(request, db, tr):
        rows = db.searches()
        for r in rows:
            r["count"] = db.one("SELECT COUNT(*) AS n FROM item_search WHERE search_id=?", (r["id"],))["n"]
        return rows

    async def add_search(request, db, tr):
        data = clean(await body(request))
        if not data.get("keywords"):
            raise HTTPException(400, "faltan palabras clave")
        if not data.get("name"):
            data["name"] = data["keywords"]
        if data.get("kind") == "market":
            data.setdefault("interval_min", 30)
            data.setdefault("pages", 3)
            data.setdefault("notify_new", 0)
        sid = db.add_search(data)
        tr.run_now(sid)
        return db.search(sid)

    async def one_search(request, db, tr):
        sid = int(request.path_params["sid"])
        if not db.search(sid):
            raise HTTPException(404, "no existe")
        if request.method == "PUT":
            db.update_search(sid, clean(await body(request)))
            return db.search(sid)
        if request.method == "DELETE":
            db.delete_search(sid)
            return {"ok": True}
        return db.search(sid)

    async def run_search(request, db, tr):
        tr.run_now(int(request.path_params["sid"]))
        return {"ok": True}

    # ------------------------------------------------------------ anuncios
    async def follow(request, db, tr):
        iid = request.path_params["iid"]
        b = await body(request)
        val = 0 if b.get("follow") in (False, 0, "0") else 1
        if not db.one("SELECT id FROM items WHERE id=?", (iid,)):
            raise HTTPException(404, "no conozco ese anuncio")
        db.x("UPDATE items SET followed=? WHERE id=?", (val, iid))
        return {"ok": True, "followed": bool(val)}

    async def followed(request, db, tr):
        rows = db.q("SELECT * FROM items WHERE followed=1 ORDER BY last_seen DESC")
        for r in rows:
            r["url"] = item_url(r["slug"])
        return rows

    async def item(request, db, tr):
        iid = request.path_params["iid"]
        it = db.one("SELECT * FROM items WHERE id=?", (iid,))
        if not it:
            raise HTTPException(404, "no existe")
        it["url"] = item_url(it["slug"])
        it["prices"] = db.q("SELECT ts, price FROM price_history WHERE item_id=? ORDER BY ts", (iid,))
        return it

    # ------------------------------------------------------------ mercado
    async def market(request, db, tr):
        return ranking(db)

    async def market_one(request, db, tr):
        sid = int(request.path_params["sid"])
        s = db.search(sid)
        if not s:
            raise HTTPException(404, "no existe")
        st = search_stats(db, sid, with_detail=True)
        st["search"] = s
        return st

    # ------------------------------------------------------------ análisis
    async def analytics(request, db, tr):
        """Todos los anuncios del periodo en formato compacto; el cruce de datos lo hace el panel."""
        days = max(1, min(qint(request, "days", 90), 365))
        now = time.time()
        since = now - days * 86400
        rows = db.q(
            "SELECT id,title,price,first_price,status,first_seen,created_ts,status_changed_at,city,shipping,"
            "followed,slug,image FROM items "
            "WHERE first_seen>=? OR status_changed_at>=? OR (status IN ('active','reserved') AND last_seen>=?)",
            (since, since, since),
        )
        ids = {r["id"] for r in rows}
        links = {}
        for l in db.q("SELECT item_id, search_id FROM item_search"):
            if l["item_id"] in ids:
                links.setdefault(l["item_id"], []).append(l["search_id"])
        drops, prev = {}, {}
        for p in db.q("SELECT item_id, price FROM price_history ORDER BY item_id, ts"):
            iid = p["item_id"]
            if iid in ids:
                if iid in prev and p["price"] is not None and prev[iid] is not None and p["price"] < prev[iid]:
                    drops[iid] = drops.get(iid, 0) + 1
                prev[iid] = p["price"]
        cols = ["id", "title", "price", "first_price", "status", "first_seen", "created_ts", "changed",
                "city", "shipping", "followed", "slug", "image", "drops", "searches"]
        out = [[r["id"], r["title"], r["price"], r["first_price"], r["status"], r["first_seen"], r["created_ts"],
                r["status_changed_at"], r["city"], r["shipping"], r["followed"], r["slug"], r["image"],
                drops.get(r["id"], 0), links.get(r["id"], [])] for r in rows]
        return {
            "now": now, "days": days, "cols": cols, "rows": out,
            "searches": [{"id": s["id"], "name": s["name"], "kind": s["kind"]} for s in db.searches()],
        }

    routes = [
        Route("/", index),
        Route("/api/health", api(health, auth=False)),
        Route("/api/status", api(status)),
        Route("/api/events", api(events)),
        Route("/api/feed", api(feed)),
        Route("/api/test-notification", api(test_notification), methods=["POST"]),
        Route("/api/searches", api(list_searches), methods=["GET"]),
        Route("/api/searches", api(add_search), methods=["POST"]),
        Route("/api/searches/{sid:int}", api(one_search), methods=["GET", "PUT", "DELETE"]),
        Route("/api/searches/{sid:int}/run", api(run_search), methods=["POST"]),
        Route("/api/items/followed", api(followed)),
        Route("/api/items/{iid}", api(item)),
        Route("/api/items/{iid}/follow", api(follow), methods=["POST"]),
        Route("/api/market", api(market)),
        Route("/api/market/{sid:int}", api(market_one)),
        Route("/api/analytics", api(analytics)),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
    return Starlette(routes=routes, lifespan=lifespan)
