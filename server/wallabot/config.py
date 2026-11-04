"""Configuración leída de variables de entorno (fichero .env cargado por systemd)."""
import os


def _f(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def _i(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return int(default)


DB_PATH = os.environ.get("WALLABOT_DB", os.path.expanduser("~/wallabot/data/wallabot.db"))
HOST = os.environ.get("WALLABOT_HOST", "0.0.0.0")
PORT = _i("WALLABOT_PORT", 8788)
# Token opcional. Tailscale ya limita quién llega a la Pi, pero así nadie de tu WiFi toca el bot.
TOKEN = os.environ.get("WALLABOT_TOKEN", "").strip()

# Ubicación por defecto para las búsquedas (Wallapop la exige).
DEFAULT_LAT = _f("WALLABOT_LAT", 40.4168)
DEFAULT_LNG = _f("WALLABOT_LNG", -3.7038)

# Ritmo de peticiones a Wallapop: mínimo de segundos entre dos peticiones.
MIN_REQUEST_GAP = _f("WALLABOT_REQUEST_GAP", 3.0)
# Cada cuántas horas se vuelve a comprobar un anuncio (vendido, reservado, precio).
RECHECK_HOURS_ALERT = _f("WALLABOT_RECHECK_ALERT_H", 3)
RECHECK_HOURS_MARKET = _f("WALLABOT_RECHECK_MARKET_H", 8)
# Cuántas comprobaciones de anuncios se hacen por vuelta del bucle (30 s).
RECHECK_BUDGET = _i("WALLABOT_RECHECK_BUDGET", 6)
# Hora local del resumen diario.
DAILY_HOUR = _i("WALLABOT_DAILY_HOUR", 21)
# Días que se conservan anuncios retirados para las estadísticas.
KEEP_DAYS = _i("WALLABOT_KEEP_DAYS", 180)

URGENT_WORDS = [
    w.strip().lower()
    for w in os.environ.get(
        "WALLABOT_URGENT_WORDS",
        "urge,urgente,mudanza,negociable,acepto ofertas,escucho ofertas,liquido,liquidación,"
        "me voy,traslado,regalo,rebajado,precio negociable,hoy mismo,necesito vender",
    ).split(",")
    if w.strip()
]
