"""Base de datos SQLite (un único fichero en la microSD)."""
import json
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'alert',          -- 'alert' (avisos) o 'market' (solo estudio de mercado)
    keywords TEXT NOT NULL,
    exclude_words TEXT DEFAULT '',
    min_price REAL, max_price REAL,
    lat REAL, lng REAL, distance_km REAL,
    category_id INTEGER,
    shipping_only INTEGER DEFAULT 0,
    interval_min REAL DEFAULT 5,
    pages INTEGER DEFAULT 1,
    chollo_pct REAL DEFAULT 25,
    notify_new INTEGER DEFAULT 1,
    notify_chollo INTEGER DEFAULT 1,
    notify_drop INTEGER DEFAULT 1,
    notify_urgent INTEGER DEFAULT 1,
    notify_reactivated INTEGER DEFAULT 1,
    notify_republished INTEGER DEFAULT 1,
    notify_sold INTEGER DEFAULT 0,
    notify_risk INTEGER DEFAULT 1,
    notify_daily INTEGER DEFAULT 1,
    active INTEGER DEFAULT 1,
    baseline_done INTEGER DEFAULT 0,
    created_at REAL, last_run REAL, last_results_at REAL, last_error TEXT,
    noresults_warned_at REAL
);
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    title TEXT, description TEXT,
    price REAL, first_price REAL, currency TEXT,
    image TEXT, slug TEXT, user_id TEXT, city TEXT,
    shipping INTEGER, reserved INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',                -- active | reserved | sold | gone
    followed INTEGER DEFAULT 0,
    created_ts REAL, first_seen REAL, last_seen REAL, last_checked REAL,
    status_changed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_user ON items(user_id);
CREATE TABLE IF NOT EXISTS item_search (
    item_id TEXT, search_id INTEGER, linked_at REAL,
    PRIMARY KEY (item_id, search_id)
);
CREATE INDEX IF NOT EXISTS idx_is_search ON item_search(search_id);
CREATE TABLE IF NOT EXISTS price_history (
    item_id TEXT, ts REAL, price REAL
);
CREATE INDEX IF NOT EXISTS idx_ph_item ON price_history(item_id);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL, type TEXT, priority INTEGER DEFAULT 3,
    title TEXT, body TEXT, image TEXT, url TEXT,
    item_id TEXT, search_id INTEGER, extra TEXT
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""

SEARCH_FIELDS = [
    "name", "kind", "keywords", "exclude_words", "min_price", "max_price", "lat", "lng",
    "distance_km", "category_id", "shipping_only", "interval_min", "pages", "chollo_pct",
    "notify_new", "notify_chollo", "notify_drop", "notify_urgent", "notify_reactivated",
    "notify_republished", "notify_sold", "notify_risk", "notify_daily", "active",
]


class DB:
    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # --- utilidades ---
    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def kv_get(self, k, default=None):
        r = self.one("SELECT v FROM kv WHERE k=?", (k,))
        return r["v"] if r else default

    def kv_set(self, k, v):
        self.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))

    # --- búsquedas ---
    def searches(self, only_active=False):
        sql = "SELECT * FROM searches"
        if only_active:
            sql += " WHERE active=1"
        return self.q(sql + " ORDER BY kind, name")

    def search(self, sid):
        return self.one("SELECT * FROM searches WHERE id=?", (sid,))

    def add_search(self, data):
        cols = [f for f in SEARCH_FIELDS if f in data]
        vals = [data[c] for c in cols]
        sql = f"INSERT INTO searches({','.join(cols)},created_at) VALUES({','.join('?' * len(cols))},?)"
        return self.x(sql, vals + [time.time()])

    def update_search(self, sid, data):
        cols = [f for f in SEARCH_FIELDS if f in data]
        if not cols:
            return
        sets = ",".join(f"{c}=?" for c in cols)
        self.x(f"UPDATE searches SET {sets} WHERE id=?", [data[c] for c in cols] + [sid])
        # si cambian los criterios, se vuelve a tomar una base sin avisar de todo lo que ya existe
        if any(c in data for c in ("keywords", "min_price", "max_price", "lat", "lng", "distance_km",
                                   "category_id", "shipping_only", "exclude_words")):
            self.x("UPDATE searches SET baseline_done=0 WHERE id=?", (sid,))

    def delete_search(self, sid):
        self.x("DELETE FROM searches WHERE id=?", (sid,))
        self.x("DELETE FROM item_search WHERE search_id=?", (sid,))

    # --- eventos ---
    def add_event(self, type_, title, body="", priority=3, image=None, url=None,
                  item_id=None, search_id=None, extra=None):
        return self.x(
            "INSERT INTO events(ts,type,priority,title,body,image,url,item_id,search_id,extra) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (time.time(), type_, priority, title, body, image, url, item_id, search_id,
             json.dumps(extra) if extra else None),
        )

    def events_after(self, after, limit=50):
        return self.q("SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?", (after, limit))

    def latest_event_id(self):
        r = self.one("SELECT MAX(id) AS m FROM events")
        return r["m"] or 0

    def cleanup(self, keep_days):
        now = time.time()
        self.x("DELETE FROM events WHERE ts<?", (now - 30 * 86400,))
        old = now - keep_days * 86400
        self.x("DELETE FROM price_history WHERE item_id IN (SELECT id FROM items WHERE last_seen<? AND followed=0)", (old,))
        self.x("DELETE FROM item_search WHERE item_id IN (SELECT id FROM items WHERE last_seen<? AND followed=0)", (old,))
        self.x("DELETE FROM items WHERE last_seen<? AND followed=0", (old,))
