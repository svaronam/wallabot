"""Cliente mínimo de la API pública (no oficial) de Wallapop.

No usa tu cuenta: solo búsquedas y fichas públicas. Wallapop cambia la API de vez en cuando,
así que el parseo es tolerante con varias formas de respuesta. Si algo deja de funcionar,
casi siempre se arregla tocando solo este fichero.
"""
import asyncio
import random
import time

API = "https://api.wallapop.com/api/v3"
WEB_ITEM = "https://es.wallapop.com/item/"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/129.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "Origin": "https://es.wallapop.com",
    "Referer": "https://es.wallapop.com/",
    "X-DeviceOS": "0",
}


class WallapopError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def _ts(v):
    """Wallapop devuelve fechas en milisegundos; se pasan a segundos."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v / 1000 if v > 1e11 else v


def _text(v):
    if isinstance(v, dict):
        return v.get("original") or v.get("translated") or ""
    return v or ""


def _price(o):
    p = o.get("price")
    if isinstance(p, dict):
        if "cash" in p and isinstance(p["cash"], dict):
            p = p["cash"]
        return p.get("amount"), p.get("currency") or "EUR"
    if p is None and "sale_price" in o:
        return o.get("sale_price"), o.get("currency") or "EUR"
    return p, o.get("currency") or "EUR"


def _image(o):
    imgs = o.get("images") or []
    if not imgs:
        return None
    im = imgs[0]
    urls = im.get("urls") or {}
    return (urls.get("medium") or urls.get("big") or urls.get("small")
            or im.get("medium") or im.get("big") or im.get("original") or im.get("small"))


def _flag(v):
    if isinstance(v, dict):
        return bool(v.get("flag"))
    return bool(v)


def normalize(o):
    """Convierte un anuncio de Wallapop (búsqueda o ficha) a un dict propio."""
    price, cur = _price(o)
    flags = o.get("flags") or {}
    shipping = o.get("shipping") or {}
    if not isinstance(shipping, dict):
        shipping = {"user_allows_shipping": bool(shipping)}
    user = o.get("user") if isinstance(o.get("user"), dict) else {}
    loc = o.get("location") or {}
    if not isinstance(flags, dict):
        flags = {}
    slug = o.get("web_slug") or o.get("slug") or o.get("id")
    reserved = _flag(o.get("reserved")) or bool(flags.get("reserved"))
    sold = _flag(o.get("sold")) or bool(flags.get("sold"))
    gone = bool(flags.get("banned") or flags.get("expired") or flags.get("onhold"))
    return {
        "id": str(o.get("id")),
        "title": _text(o.get("title")).strip(),
        "description": _text(o.get("description")).strip(),
        "price": float(price) if price is not None else None,
        "currency": cur,
        "image": _image(o),
        "slug": slug,
        "user_id": str(o.get("user_id") or user.get("id") or "") or None,
        "city": (loc.get("city") if isinstance(loc, dict) else None),
        "shipping": 1 if (shipping.get("user_allows_shipping") or o.get("supports_shipping")) else 0,
        "reserved": 1 if reserved else 0,
        "sold": sold,
        "gone": gone,
        "created_ts": _ts(o.get("created_at") or o.get("creation_date")),
    }


def item_url(slug):
    return WEB_ITEM + str(slug)


def _search_items(data):
    try:
        return data["data"]["section"]["payload"]["items"]
    except (KeyError, TypeError):
        pass
    for k in ("search_objects", "items"):
        if isinstance(data.get(k), list):
            return data[k]
    return []


class Wallapop:
    def __init__(self, min_gap=3.0):
        self.min_gap = min_gap
        self._last = 0.0
        self._lock = asyncio.Lock()
        import httpx  # import aquí para poder probar el resto sin httpx
        self._httpx = httpx
        self.client = httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True)
        self.requests = 0

    async def close(self):
        await self.client.aclose()

    async def _get(self, path, params=None):
        async with self._lock:
            wait = self._last + self.min_gap + random.uniform(0, self.min_gap * 0.5) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                r = await self.client.get(API + path, params=params)
            except self._httpx.HTTPError as e:
                raise WallapopError(f"red: {e.__class__.__name__}") from e
            finally:
                self._last = time.time()
                self.requests += 1
        return r

    async def search(self, keywords, lat, lng, distance_km=None, min_price=None, max_price=None,
                     category_id=None, shipping_only=False, pages=1, order="newest"):
        params = {
            "source": "search_box",
            "keywords": keywords,
            "latitude": lat,
            "longitude": lng,
            "order_by": order,
        }
        if distance_km:
            params["distance"] = int(float(distance_km) * 1000)
        if min_price is not None:
            params["min_sale_price"] = min_price
        if max_price is not None:
            params["max_sale_price"] = max_price
        if category_id:
            params["category_id"] = int(category_id)
        if shipping_only:
            params["is_shippable"] = "true"

        out, seen, next_page = [], set(), None
        for _ in range(max(1, int(pages or 1))):
            r = await self._get("/search", {"next_page": next_page} if next_page else params)
            if r.status_code != 200:
                raise WallapopError(f"búsqueda HTTP {r.status_code}", r.status_code)
            data = r.json()
            for o in _search_items(data):
                it = normalize(o)
                if it["id"] not in seen:
                    seen.add(it["id"])
                    out.append(it)
            next_page = (data.get("meta") or {}).get("next_page") or r.headers.get("X-NextPage")
            if not next_page:
                break
        return out

    async def item(self, item_id):
        """Ficha de un anuncio. Devuelve None si ya no existe (vendido o borrado)."""
        r = await self._get(f"/items/{item_id}")
        if r.status_code in (404, 410):
            return None
        if r.status_code != 200:
            raise WallapopError(f"ficha HTTP {r.status_code}", r.status_code)
        return normalize(r.json())

    async def seller(self, user_id):
        """Datos básicos del vendedor para detectar cuentas de riesgo."""
        info = {"reviews": None, "sells": None, "register_ts": None}
        r = await self._get(f"/users/{user_id}")
        if r.status_code == 200:
            d = r.json()
            info["register_ts"] = _ts(d.get("register_date") or d.get("registered_at"))
        r = await self._get(f"/users/{user_id}/stats")
        if r.status_code == 200:
            d = r.json()
            for blk in (d.get("ratings") or []) + (d.get("counters") or []):
                t, v = blk.get("type"), blk.get("value")
                if t == "reviews":
                    info["reviews"] = v
                elif t == "sells":
                    info["sells"] = v
        return info
