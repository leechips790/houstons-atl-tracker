#!/usr/bin/env python3
"""Houston's ATL Tracker v2 — Server with Wisely proxy, SQLite, and full API."""

import http.server
import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
import subprocess
import shutil

def safe_gog_send(args):
    """Run gog command only if gog is installed (not available on Railway)."""
    if not shutil.which("gog"):
        return
    try:
        subprocess.run(args, capture_output=True, timeout=30)
    except Exception:
        pass
import threading

GOOGLE_CLIENT_ID = "23317478020-ertd12jqki1bus53piflgomlu6ctipjn.apps.googleusercontent.com"

PORT = int(os.environ.get('PORT', 3001))
PUSH_SCAN_KEY = os.environ.get('PUSH_SCAN_KEY', '')

# Scan cache: key = party_size, value = (timestamp, result)
_scan_cache = {}
_scan_cache_lock = threading.Lock()
SCAN_CACHE_TTL = 120  # seconds

# Push cache: key = party_size, value = {"data": {...}, "timestamp": epoch}
_push_cache = {}
_push_cache_lock = threading.Lock()
PUSH_CACHE_TTL = 2700  # 45 minutes
DIR = os.path.dirname(os.path.abspath(__file__))
if os.environ.get("RAILWAY_ENVIRONMENT") and os.path.isdir("/data"):
    DB_PATH = "/data/houstons.db"
else:
    DB_PATH = os.path.join(DIR, "houstons.db")

WISELY_HEADERS = {
    "Origin": "https://reservations.getwisely.com",
    "Referer": "https://reservations.getwisely.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/json",
}

LOCATIONS = {
    # Houston's
    "peachtree": {"merchant_id": 278258, "type_id": 1681, "name": "Houston's - Peachtree", "city": "Atlanta", "state": "GA", "brand": "Houston's", "lat": 33.8478, "lon": -84.3880},
    "west_paces": {"merchant_id": 278259, "type_id": 1682, "name": "Houston's - West Paces", "city": "Atlanta", "state": "GA", "brand": "Houston's", "lat": 33.8400, "lon": -84.3690},
    "houston_s_bergen_county": {"merchant_id": 278171, "type_id": 1703, "name": "Houston's - Bergen County", "city": "Hackensack", "state": "NJ", "brand": "Houston's", "lat": 40.8859, "lon": -74.0435},
    "houston_s_boca_raton": {"merchant_id": 278275, "type_id": 1704, "name": "Houston's - Boca Raton", "city": "Boca Raton", "state": "FL", "brand": "Houston's", "lat": 26.3683, "lon": -80.1289},
    "houston_s_saint_charles": {"merchant_id": 278261, "type_id": 1701, "name": "Houston's - Saint Charles", "city": "Chicago", "state": "IL", "brand": "Houston's", "lat": 41.8932, "lon": -87.6274},
    "houston_s_north_miami_beach": {"merchant_id": 278271, "type_id": 1692, "name": "Houston's - North Miami Beach", "city": "North Miami Beach", "state": "FL", "brand": "Houston's", "lat": 25.9331, "lon": -80.1625},
    "houston_s_pasadena": {"merchant_id": 278270, "type_id": 1696, "name": "Houston's - Pasadena", "city": "Pasadena", "state": "CA", "brand": "Houston's", "lat": 34.1478, "lon": -118.1445},
    "houston_s_pompano_beach": {"merchant_id": 278276, "type_id": 1697, "name": "Houston's - Pompano Beach", "city": "Pompano Beach", "state": "FL", "brand": "Houston's", "lat": 26.2379, "lon": -80.1248},
    "scottsdale": {"merchant_id": 278256, "type_id": 1685, "name": "Houston's - Scottsdale", "city": "Scottsdale", "state": "AZ", "brand": "Houston's", "lat": 33.5010, "lon": -111.9260},
    # Hillstone
    "hillstone_phoenix": {"merchant_id": 278170, "type_id": 1662, "name": "Hillstone - Phoenix", "city": "Phoenix", "state": "AZ", "brand": "Hillstone", "lat": 33.5098, "lon": -112.0147},
    "hillstone_bal_harbour": {"merchant_id": 278242, "type_id": 1702, "name": "Hillstone - Bal Harbour", "city": "Bal Harbour", "state": "FL", "brand": "Hillstone", "lat": 25.8884, "lon": -80.1264},
    "hillstone_coral_gables": {"merchant_id": 278173, "type_id": 1664, "name": "Hillstone - Coral Gables", "city": "Coral Gables", "state": "FL", "brand": "Hillstone", "lat": 25.7498, "lon": -80.2617},
    "hillstone_winter_park": {"merchant_id": 278257, "type_id": 1684, "name": "Hillstone - Winter Park", "city": "Orlando", "state": "FL", "brand": "Hillstone", "lat": 28.5994, "lon": -81.3514},
    "hillstone_denver": {"merchant_id": 278243, "type_id": 1691, "name": "Hillstone - Denver", "city": "Denver", "state": "CO", "brand": "Hillstone", "lat": 39.7178, "lon": -104.9554},
    "hillstone_park_cities": {"merchant_id": 278264, "type_id": 1694, "name": "Hillstone - Park Cities", "city": "Dallas", "state": "TX", "brand": "Hillstone", "lat": 32.8374, "lon": -96.8074},
    "hillstone_houston": {"merchant_id": 278244, "type_id": 1683, "name": "Hillstone - Houston", "city": "Houston", "state": "TX", "brand": "Hillstone", "lat": 29.7524, "lon": -95.4610},
    "hillstone_park_avenue": {"merchant_id": 278278, "type_id": 1695, "name": "Hillstone - Park Avenue", "city": "New York", "state": "NY", "brand": "Hillstone", "lat": 40.7614, "lon": -73.9776},
    "hillstone_embarcadero": {"merchant_id": 278172, "type_id": 1663, "name": "Hillstone - San Francisco", "city": "San Francisco", "state": "CA", "brand": "Hillstone", "lat": 37.7956, "lon": -122.3933},
    "hillstone_santa_monica": {"merchant_id": 278267, "type_id": 1689, "name": "Hillstone - Santa Monica", "city": "Los Angeles", "state": "CA", "brand": "Hillstone", "lat": 34.0259, "lon": -118.5083},
    # R+D Kitchen
    "rd_kitchen_newport_beach": {"merchant_id": 278273, "type_id": 1707, "name": "R+D Kitchen - Newport Beach", "city": "Newport Beach", "state": "CA", "brand": "R+D Kitchen", "lat": 33.6170, "lon": -117.8740},
    "rd_kitchen_santa_monica": {"merchant_id": 278268, "type_id": 4514, "name": "R+D Kitchen - Santa Monica", "city": "Los Angeles", "state": "CA", "brand": "R+D Kitchen", "lat": 34.0289, "lon": -118.4951},
    "rd_kitchen_yountville": {"merchant_id": 278254, "type_id": 1675, "name": "R+D Kitchen - Yountville", "city": "Napa", "state": "CA", "brand": "R+D Kitchen", "lat": 38.4016, "lon": -122.3611},
    # Honor Bar
    "honor_bar_dallas": {"merchant_id": 278262, "type_id": 4240, "name": "Honor Bar - Dallas", "city": "Dallas", "state": "TX", "brand": "Honor Bar", "lat": 32.8374, "lon": -96.8050},
    # Standalone brands
    "palm_beach_grill": {"merchant_id": 278274, "type_id": 1693, "name": "Palm Beach Grill", "city": "Palm Beach", "state": "FL", "brand": "Palm Beach Grill", "lat": 26.7056, "lon": -80.0364},
    "bandera_corona_del_mar": {"merchant_id": 278245, "type_id": 1705, "name": "Bandera - Corona del Mar", "city": "Newport Beach", "state": "CA", "brand": "Bandera", "lat": 33.6003, "lon": -117.8761},
    "south_beverly_grill": {"merchant_id": 278269, "type_id": 1700, "name": "South Beverly Grill", "city": "Beverly Hills", "state": "CA", "brand": "South Beverly Grill", "lat": 34.0597, "lon": -118.3989},
    "cherry_creek_grill": {"merchant_id": 278239, "type_id": 1690, "name": "Cherry Creek Grill", "city": "Denver", "state": "CO", "brand": "Cherry Creek Grill", "lat": 39.7170, "lon": -104.9536},
    "rutherford_grill": {"merchant_id": 278253, "type_id": 1676, "name": "Rutherford Grill", "city": "Rutherford", "state": "CA", "brand": "Rutherford Grill", "lat": 38.4566, "lon": -122.4184},
    "los_altos_grill": {"merchant_id": 278255, "type_id": 1677, "name": "Los Altos Grill", "city": "Los Altos", "state": "CA", "brand": "Los Altos Grill", "lat": 37.3795, "lon": -122.1141},
    "east_hampton_grill": {"merchant_id": 278240, "type_id": 1706, "name": "East Hampton Grill", "city": "East Hampton", "state": "NY", "brand": "East Hampton Grill", "lat": 40.9634, "lon": -72.1848},
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            party_size INTEGER DEFAULT 2,
            preferred_date TEXT,
            preferred_time TEXT,
            location TEXT DEFAULT 'both',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            name TEXT NOT NULL,
            google_id TEXT UNIQUE,
            picture TEXT,
            phone TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            last_login TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS watches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            location_key TEXT NOT NULL,
            party_size INTEGER DEFAULT 2,
            target_date TEXT NOT NULL,
            time_start TEXT DEFAULT '18:00',
            time_end TEXT DEFAULT '20:00',
            auto_book BOOLEAN DEFAULT 0,
            book_first_name TEXT,
            book_last_name TEXT,
            book_email TEXT,
            book_phone TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now')),
            notified_at TEXT,
            booked_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS wait_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT NOT NULL,
            wait_minutes INTEGER NOT NULL,
            source TEXT DEFAULT 'user',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT NOT NULL,
            scan_date TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            party_sizes TEXT,
            available INTEGER DEFAULT 0,
            scanned_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now')),
            message TEXT NOT NULL,
            contact TEXT,
            ip TEXT
        );
        CREATE TABLE IF NOT EXISTS slot_drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT NOT NULL,
            slot_date TEXT NOT NULL,
            slot_time TEXT NOT NULL,
            appeared_at TEXT,
            gone_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    # Migrate: add columns if missing
    try:
        c.execute("SELECT google_id FROM users LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE users ADD COLUMN google_id TEXT")
        c.execute("ALTER TABLE users ADD COLUMN picture TEXT")
        c.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        c.execute("ALTER TABLE users ADD COLUMN last_login TEXT")
        # Create unique index separately
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id) WHERE google_id IS NOT NULL")
        conn.commit()
    # Migrate: add last_scanned to watches if missing
    try:
        c.execute("SELECT last_scanned FROM watches LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE watches ADD COLUMN last_scanned TEXT")
        conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def json_response(handler, data, status=200):
    body = json.dumps(data, default=str).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw)
    except Exception:
        return {}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    # ---------- routing ----------
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Push-Key, Authorization")
        self.end_headers()

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/watches/"):
            self.delete_watch()
        else:
            self.send_error(404)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/inventory":
            self.proxy_inventory()
        elif path == "/api/scan":
            self.handle_scan()
        elif path == "/api/alerts":
            self.get_alerts()
        elif path == "/api/waittimes":
            self.get_waittimes()
        elif path == "/api/history":
            self.get_history()
        elif path == "/api/config":
            self.serve_config()
        elif path == "/api/locations":
            self.get_locations()
        elif path == "/api/geolocate":
            self.geolocate()
        elif path == "/api/calls":
            self.get_calls()
        elif path == "/api/calls/latest":
            self.get_calls_latest()
        elif path == "/api/calls/stats":
            self.get_calls_stats()
        elif path == "/api/availability":
            self.handle_availability()
        elif path == "/api/auth/me":
            self.auth_me()
        elif path == "/api/auth/alerts":
            self.auth_get_alerts()
        elif path == "/api/watches":
            self.get_watches()
        elif path == "/api/admin/feedback":
            self.admin_get_feedback()
        else:
            super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/book":
            self.proxy_book()
        elif path == "/api/alerts":
            self.post_alert()
        elif path == "/api/waittimes":
            self.post_waittime()
        elif path == "/api/history/record":
            self.post_history_record()
        elif path == "/api/calls":
            self.post_call()
        elif path == "/api/auth/signup":
            self.auth_signup()
        elif path == "/api/auth/login":
            self.auth_login()
        elif path == "/api/auth/logout":
            self.auth_logout()
        elif path == "/api/auth/google":
            self.auth_google()
        elif path == "/api/feedback":
            self.post_feedback()
        elif path == "/api/push-scan":
            self.handle_push_scan()
        elif path == "/api/watches":
            self.post_watch()
        elif path == "/api/watches/scan":
            self.scan_watches()
        else:
            self.send_error(404)

    # ---------- Wisely proxy ----------
    def proxy_inventory(self):
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        url = f"https://loyaltyapi.wisely.io/v2/web/reservations/inventory?{qs}"
        try:
            req = urllib.request.Request(url, headers=WISELY_HEADERS)
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            json_response(self, {"error": str(e)}, 500)

    def proxy_book(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        url = "https://loyaltyapi.wisely.io/v2/web/reservations"
        try:
            req = urllib.request.Request(url, data=body, method="POST", headers=WISELY_HEADERS)
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            json_response(self, {"error": str(e)}, 500)

    # ---------- scan (7-day availability) ----------
    def handle_scan(self):
        """Scan both locations for next 7 days. Returns structured availability."""
        party_size = 2
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        if "party_size" in params:
            party_size = int(params["party_size"][0])

        # Check cache
        with _scan_cache_lock:
            cached = _scan_cache.get(party_size)
            if cached and (time.time() - cached[0]) < SCAN_CACHE_TTL:
                json_response(self, cached[1])
                return

        results = {}

        today = datetime.now()
        days_out = 21
        if "days" in params:
            days_out = min(int(params["days"][0]), 21)
        dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_out)]

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch_slots(loc_key, loc, date_str, anchor_hour, party_size):
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=anchor_hour, minute=0)
            ts = int(dt.timestamp() * 1000)
            url = (
                f"https://loyaltyapi.wisely.io/v2/web/reservations/inventory"
                f"?merchant_id={loc['merchant_id']}&party_size={party_size}"
                f"&search_ts={ts}&show_reservation_types=1&limit=20"
            )
            try:
                req = urllib.request.Request(url, headers=WISELY_HEADERS)
                resp = urllib.request.urlopen(req, timeout=10)
                data = json.loads(resp.read())
                slots = []
                for t in data.get("types", []):
                    for slot in t.get("times", []):
                        display = slot.get("display_time", "")
                        if display:
                            slots.append({
                                "time": display,
                                "available": slot.get("is_available", 0) == 1,
                                "reserved_ts": slot.get("reserved_ts"),
                                "type_id": t.get("reservation_type_id"),
                            })
                return (loc_key, date_str, slots)
            except Exception:
                return (loc_key, date_str, [])

        for loc_key, loc in LOCATIONS.items():
            results[loc_key] = {"name": loc["name"], "merchant_id": loc["merchant_id"], "days": {d: {} for d in dates}}

        # Fire all requests in parallel
        futures = []
        with ThreadPoolExecutor(max_workers=28) as pool:
            for loc_key, loc in LOCATIONS.items():
                for date_str in dates:
                    for anchor_hour in [12, 17, 21]:
                        futures.append(pool.submit(fetch_slots, loc_key, loc, date_str, anchor_hour, party_size))

            for f in as_completed(futures):
                loc_key, date_str, slots = f.result()
                day_data = results[loc_key]["days"]
                if not isinstance(day_data[date_str], dict):
                    existing = {s["time"]: s for s in day_data[date_str]}
                else:
                    existing = {}
                for s in slots:
                    if s["time"] not in existing:
                        existing[s["time"]] = s
                day_data[date_str] = list(existing.values())

        result = {
            "locations": results,
            "scanned_at": datetime.now().isoformat(),
            "party_size": party_size,
            "dates": dates,
        }
        with _scan_cache_lock:
            _scan_cache[party_size] = (time.time(), result)
        json_response(self, result)

    # ---------- push-scan cache ----------
    def handle_push_scan(self):
        """Receive scan results pushed from Mac mini."""
        key = self.headers.get("X-Push-Key", "")
        if not PUSH_SCAN_KEY or key != PUSH_SCAN_KEY:
            json_response(self, {"error": "unauthorized"}, 401)
            return
        data = read_body(self)
        party_size = data.get("party_size", 2)
        scan_data = data.get("data", {})
        ts = data.get("timestamp", time.time())
        with _push_cache_lock:
            _push_cache[party_size] = {"data": scan_data, "timestamp": ts}
        json_response(self, {"success": True, "party_size": party_size})

    def handle_availability(self):
        """Return cached push data if fresh, else fall back to live scan."""
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        party_size = int(params.get("party_size", ["2"])[0])

        with _push_cache_lock:
            cached = _push_cache.get(party_size)

        if cached and (time.time() - cached["timestamp"]) < PUSH_CACHE_TTL:
            json_response(self, {
                "locations": cached["data"],
                "scanned_at": datetime.fromtimestamp(cached["timestamp"]).isoformat(),
                "party_size": party_size,
                "source": "cache",
            })
            return

        # Fallback to live scan
        self.handle_scan()

    # ---------- alerts ----------
    def get_alerts(self):
        conn = get_db()
        rows = conn.execute("SELECT * FROM alerts ORDER BY created_at DESC").fetchall()
        count = conn.execute("SELECT COUNT(*) as c FROM alerts").fetchone()["c"]
        conn.close()
        json_response(self, {"alerts": [dict(r) for r in rows], "count": count})

    def post_alert(self):
        data = read_body(self)
        name = data.get("name", "").strip()
        email = data.get("email", "").strip()
        if not name or not email:
            json_response(self, {"error": "Name and email required"}, 400)
            return
        conn = get_db()
        conn.execute(
            "INSERT INTO alerts (name, email, party_size, preferred_date, preferred_time, location) VALUES (?,?,?,?,?,?)",
            (name, email, data.get("party_size", 2), data.get("preferred_date", ""),
             data.get("preferred_time", ""), data.get("location", "both"))
        )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) as c FROM alerts").fetchone()["c"]
        conn.close()
        json_response(self, {"success": True, "count": count})

    # ---------- wait times ----------
    def get_waittimes(self):
        conn = get_db()
        result = {}
        for loc_key in LOCATIONS:
            rows = conn.execute(
                "SELECT * FROM wait_reports WHERE location=? ORDER BY created_at DESC LIMIT 6",
                (loc_key,)
            ).fetchall()
            result[loc_key] = [dict(r) for r in rows]
        conn.close()
        json_response(self, {"waittimes": result})

    def post_waittime(self):
        data = read_body(self)
        location = data.get("location", "").strip()
        wait_minutes = data.get("wait_minutes")
        source = data.get("source", "user")
        if not location or wait_minutes is None:
            json_response(self, {"error": "location and wait_minutes required"}, 400)
            return
        conn = get_db()
        conn.execute(
            "INSERT INTO wait_reports (location, wait_minutes, source) VALUES (?,?,?)",
            (location, int(wait_minutes), source)
        )
        conn.commit()
        conn.close()
        json_response(self, {"success": True})

    # ---------- history ----------
    def get_history(self):
        conn = get_db()
        scans = conn.execute(
            "SELECT * FROM scan_history ORDER BY scanned_at DESC LIMIT 200"
        ).fetchall()
        drops = conn.execute(
            "SELECT * FROM slot_drops ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        conn.close()
        json_response(self, {
            "scans": [dict(r) for r in scans],
            "drops": [dict(r) for r in drops],
        })

    def post_history_record(self):
        data = read_body(self)
        location = data.get("location", "")
        scan_date = data.get("scan_date", "")
        time_slot = data.get("time_slot", "")
        available = 1 if data.get("available") else 0
        party_sizes = data.get("party_sizes", "")
        conn = get_db()
        conn.execute(
            "INSERT INTO scan_history (location, scan_date, time_slot, party_sizes, available) VALUES (?,?,?,?,?)",
            (location, scan_date, time_slot, party_sizes, available)
        )
        # Check for slot drops: was previously unavailable, now available?
        prev = conn.execute(
            "SELECT available FROM scan_history WHERE location=? AND scan_date=? AND time_slot=? ORDER BY scanned_at DESC LIMIT 1 OFFSET 1",
            (location, scan_date, time_slot)
        ).fetchone()
        if prev and prev["available"] == 0 and available == 1:
            conn.execute(
                "INSERT INTO slot_drops (location, slot_date, slot_time, appeared_at) VALUES (?,?,?,datetime('now'))",
                (location, scan_date, time_slot)
            )
        conn.commit()
        conn.close()
        json_response(self, {"success": True})

    # ---------- calls (Bland.ai call logs) ----------
    def get_calls(self):
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        conn = get_db()
        if "location" in params:
            rows = conn.execute(
                "SELECT * FROM call_logs WHERE location=? ORDER BY called_at DESC",
                (params["location"][0],)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM call_logs ORDER BY called_at DESC").fetchall()
        conn.close()
        json_response(self, {"calls": [dict(r) for r in rows]})

    def get_calls_latest(self):
        conn = get_db()
        result = {}
        for loc_key, loc_info in LOCATIONS.items():
            row = conn.execute(
                "SELECT * FROM call_logs WHERE location=? ORDER BY called_at DESC LIMIT 1",
                (loc_info["name"],)
            ).fetchone()
            if not row:
                # Try matching by key as well
                row = conn.execute(
                    "SELECT * FROM call_logs WHERE location=? ORDER BY called_at DESC LIMIT 1",
                    (loc_key,)
                ).fetchone()
            if row:
                result[loc_info["name"]] = dict(row)
        conn.close()
        json_response(self, {"latest": result})

    def get_calls_stats(self):
        conn = get_db()
        # Avg wait_count by day of week
        by_dow = conn.execute("""
            SELECT location,
                   CASE cast(strftime('%w', called_at) as int)
                     WHEN 0 THEN 'Sun' WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue'
                     WHEN 3 THEN 'Wed' WHEN 4 THEN 'Thu' WHEN 5 THEN 'Fri' WHEN 6 THEN 'Sat'
                   END as dow,
                   ROUND(AVG(wait_count),1) as avg_wait,
                   COUNT(*) as n
            FROM call_logs WHERE wait_count IS NOT NULL
            GROUP BY location, strftime('%w', called_at)
            ORDER BY cast(strftime('%w', called_at) as int)
        """).fetchall()
        # Avg wait_count by hour
        by_hour = conn.execute("""
            SELECT location,
                   cast(strftime('%H', called_at) as int) as hour,
                   ROUND(AVG(wait_count),1) as avg_wait,
                   COUNT(*) as n
            FROM call_logs WHERE wait_count IS NOT NULL
            GROUP BY location, strftime('%H', called_at)
            ORDER BY hour
        """).fetchall()
        # By location overall
        by_loc = conn.execute("""
            SELECT location,
                   ROUND(AVG(wait_count),1) as avg_wait,
                   COUNT(*) as total_calls,
                   SUM(CASE WHEN wait_count IS NOT NULL THEN 1 ELSE 0 END) as calls_with_data
            FROM call_logs
            GROUP BY location
        """).fetchall()
        conn.close()
        json_response(self, {
            "by_day_of_week": [dict(r) for r in by_dow],
            "by_hour": [dict(r) for r in by_hour],
            "by_location": [dict(r) for r in by_loc],
        })

    def post_call(self):
        data = read_body(self)
        location = data.get("location", "").strip()
        called_at = data.get("called_at", datetime.now().isoformat())
        if not location:
            json_response(self, {"error": "location required"}, 400)
            return
        conn = get_db()
        conn.execute(
            """INSERT INTO call_logs
               (location, phone, call_id, wait_count, wait_minutes, transcript, summary,
                recording_url, call_duration, answered_by, status, called_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (location, data.get("phone"), data.get("call_id"),
             data.get("wait_count"), data.get("wait_minutes"),
             data.get("transcript"), data.get("summary"),
             data.get("recording_url"), data.get("call_duration"),
             data.get("answered_by"), data.get("status", "pending"),
             called_at)
        )
        conn.commit()
        conn.close()
        json_response(self, {"success": True})

    # ---------- auth ----------
    def _hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()

    def _get_user_from_token(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        token = auth[7:]
        conn = get_db()
        row = conn.execute(
            "SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token=?",
            (token,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def auth_signup(self):
        data = read_body(self)
        name = data.get("name", "").strip()
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        if not name or not email or not password:
            json_response(self, {"error": "Name, email, and password required"}, 400)
            return
        if len(password) < 6:
            json_response(self, {"error": "Password must be at least 6 characters"}, 400)
            return
        conn = get_db()
        existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            conn.close()
            json_response(self, {"error": "Email already registered"}, 409)
            return
        pw_hash = self._hash_password(password)
        conn.execute("INSERT INTO users (email, password_hash, name) VALUES (?,?,?)", (email, pw_hash, name))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        token = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (user_id, token) VALUES (?,?)", (user["id"], token))
        conn.commit()
        conn.close()
        json_response(self, {"success": True, "token": token, "user": {"id": user["id"], "name": user["name"], "email": user["email"]}})

    def auth_login(self):
        data = read_body(self)
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        if not email or not password:
            json_response(self, {"error": "Email and password required"}, 400)
            return
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user or user["password_hash"] != self._hash_password(password):
            conn.close()
            json_response(self, {"error": "Invalid email or password"}, 401)
            return
        token = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (user_id, token) VALUES (?,?)", (user["id"], token))
        conn.commit()
        conn.close()
        json_response(self, {"success": True, "token": token, "user": {"id": user["id"], "name": user["name"], "email": user["email"]}})

    def auth_logout(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            conn = get_db()
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            conn.commit()
            conn.close()
        json_response(self, {"success": True})

    def auth_me(self):
        user = self._get_user_from_token()
        if not user:
            json_response(self, {"error": "Not authenticated"}, 401)
            return
        json_response(self, {"user": {"id": user["id"], "name": user["name"], "email": user["email"], "picture": user.get("picture", "")}})

    def auth_get_alerts(self):
        user = self._get_user_from_token()
        if not user:
            json_response(self, {"error": "Not authenticated"}, 401)
            return
        conn = get_db()
        rows = conn.execute("SELECT * FROM alerts WHERE email=? ORDER BY created_at DESC", (user["email"],)).fetchall()
        conn.close()
        json_response(self, {"alerts": [dict(r) for r in rows]})

    # ---------- Google auth ----------
    def auth_google(self):
        data = read_body(self)
        credential = data.get("credential", "")
        if not credential:
            json_response(self, {"error": "No credential provided"}, 400)
            return
        # Verify token with Google
        try:
            url = f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=10)
            token_info = json.loads(resp.read())
        except Exception as e:
            json_response(self, {"error": f"Token verification failed: {e}"}, 401)
            return
        # Verify audience matches our client ID
        if token_info.get("aud") != GOOGLE_CLIENT_ID:
            json_response(self, {"error": "Invalid token audience"}, 401)
            return
        google_id = token_info.get("sub")
        email = token_info.get("email", "").lower()
        name = token_info.get("name", "")
        picture = token_info.get("picture", "")
        if not google_id or not email:
            json_response(self, {"error": "Invalid token data"}, 401)
            return
        conn = get_db()
        # Check if user exists by google_id
        had_google_id = True
        user = conn.execute("SELECT * FROM users WHERE google_id=?", (google_id,)).fetchone()
        if not user:
            had_google_id = False
            # Check if user exists by email (might have signed up with password before)
            user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if user:
                conn.execute("UPDATE users SET google_id=?, picture=?, last_login=datetime('now') WHERE id=?",
                             (google_id, picture, user["id"]))
            else:
                conn.execute("INSERT INTO users (email, password_hash, name, google_id, picture, last_login) VALUES (?,?,?,?,?,datetime('now'))",
                             (email, '', name, google_id, picture))
            conn.commit()
            user = conn.execute("SELECT * FROM users WHERE google_id=?", (google_id,)).fetchone()
        else:
            conn.execute("UPDATE users SET picture=?, name=?, last_login=datetime('now') WHERE id=?",
                         (picture, name, user["id"]))
            conn.commit()
        # Create session
        token = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (user_id, token) VALUES (?,?)", (user["id"], token))
        conn.commit()
        conn.close()
        # Notify Kevin of new signup
        try:
            if not had_google_id:
                threading.Thread(target=lambda: safe_gog_send(
                    ["gog", "gmail", "send", "--to", "Kevin.mendel@gmail.com",
                     "--subject", f"🔔 New GetHoustons Signup: {name}",
                     "--body", f"New user signed up via Google:\n\nName: {name}\nEmail: {email}",
                     "--account", "leechips790@gmail.com"]
                ), daemon=True).start()
        except: pass
        json_response(self, {
            "success": True, "token": token,
            "user": {"id": user["id"], "name": name or user["name"], "email": email, "picture": picture}
        })

    # ---------- watches ----------
    def get_watches(self):
        user = self._get_user_from_token()
        if not user:
            json_response(self, {"error": "Not authenticated"}, 401)
            return
        conn = get_db()
        rows = conn.execute("SELECT * FROM watches WHERE user_id=? AND status='active' ORDER BY target_date ASC", (user["id"],)).fetchall()
        conn.close()
        json_response(self, {"watches": [dict(r) for r in rows]})

    def post_watch(self):
        user = self._get_user_from_token()
        if not user:
            json_response(self, {"error": "Not authenticated"}, 401)
            return
        data = read_body(self)
        location_key = data.get("location_key", "")
        party_size = data.get("party_size", 2)
        target_date = data.get("target_date", "")
        time_start = data.get("time_start", "18:00")
        time_end = data.get("time_end", "20:00")
        auto_book = 1 if data.get("auto_book") else 0
        if not location_key or not target_date:
            json_response(self, {"error": "location_key and target_date required"}, 400)
            return
        if location_key not in LOCATIONS:
            json_response(self, {"error": "Invalid location"}, 400)
            return
        conn = get_db()
        conn.execute(
            """INSERT INTO watches (user_id, location_key, party_size, target_date, time_start, time_end, auto_book,
               book_first_name, book_last_name, book_email, book_phone)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (user["id"], location_key, party_size, target_date, time_start, time_end, auto_book,
             data.get("book_first_name", ""), data.get("book_last_name", ""),
             data.get("book_email", user["email"]), data.get("book_phone", ""))
        )
        conn.commit()
        watch_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        # Notify Kevin of new watch
        try:
            loc_name = LOCATIONS.get(location_key, {}).get("name", location_key)
            threading.Thread(target=lambda: safe_gog_send(
                ["gog", "gmail", "send", "--to", "Kevin.mendel@gmail.com",
                 "--subject", f"👀 New Slot Watch: {loc_name}",
                 "--body", f"New watch created:\n\nUser: {user['name']} ({user['email']})\nLocation: {loc_name}\nParty: {party_size}\nDate: {target_date}\nTime: {time_start} - {time_end}\nAuto-book: {'Yes' if auto_book else 'No'}",
                 "--account", "leechips790@gmail.com"]
            ), daemon=True).start()
        except: pass
        json_response(self, {"success": True, "watch_id": watch_id})

    def delete_watch(self):
        user = self._get_user_from_token()
        if not user:
            json_response(self, {"error": "Not authenticated"}, 401)
            return
        path = self.path.split("?")[0]
        watch_id = path.split("/")[-1]
        try:
            watch_id = int(watch_id)
        except ValueError:
            json_response(self, {"error": "Invalid watch ID"}, 400)
            return
        conn = get_db()
        watch = conn.execute("SELECT * FROM watches WHERE id=? AND user_id=?", (watch_id, user["id"])).fetchone()
        if not watch:
            conn.close()
            json_response(self, {"error": "Watch not found"}, 404)
            return
        conn.execute("UPDATE watches SET status='cancelled' WHERE id=?", (watch_id,))
        conn.commit()
        conn.close()
        json_response(self, {"success": True})

    def scan_watches(self):
        """Endpoint wrapper for the standalone scan_watches function."""
        result = do_scan_watches()
        json_response(self, result)

    # ---------- feedback ----------
    def post_feedback(self):
        data = read_body(self)
        message = data.get("message", "").strip()
        contact = data.get("contact", "").strip()
        if not message:
            json_response(self, {"error": "Message is required"}, 400)
            return
        ip = self.client_address[0] if self.client_address else ""
        conn = get_db()
        conn.execute(
            "INSERT INTO feedback (message, contact, ip) VALUES (?,?,?)",
            (message, contact or None, ip)
        )
        conn.commit()
        conn.close()
        # Send email notification via gog in background
        body = f"New feedback on GetHoustons.bar:\n\n{message}"
        if contact:
            body += f"\n\nContact: {contact}"
        body += f"\n\nIP: {ip}"
        threading.Thread(target=lambda: safe_gog_send(
            ["gog", "gmail", "send", "--to", "leechips790@gmail.com",
             "--subject", "🍖 New Feedback on GetHoustons.bar",
             "--body", body]
        ), daemon=True).start()
        json_response(self, {"success": True})

    def admin_get_feedback(self):
        user = self._get_user_from_token()
        if not user:
            json_response(self, {"error": "Not authenticated"}, 401)
            return
        conn = get_db()
        rows = conn.execute("SELECT * FROM feedback ORDER BY timestamp DESC").fetchall()
        conn.close()
        json_response(self, {"feedback": [dict(r) for r in rows]})

    # ---------- locations ----------
    def get_locations(self):
        locs = []
        for key, loc in LOCATIONS.items():
            locs.append({"key": key, "name": loc["name"], "city": loc.get("city", ""), "state": loc.get("state", ""), "brand": loc.get("brand", ""), "lat": loc.get("lat"), "lon": loc.get("lon"), "merchant_id": loc["merchant_id"]})
        json_response(self, {"locations": locs})

    def geolocate(self):
        """Use client IP to find nearest location."""
        import math
        # Get client IP
        ip = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not ip:
            ip = self.client_address[0]
        # Use free IP geolocation API
        try:
            req = urllib.request.Request(f"http://ip-api.com/json/{ip}?fields=lat,lon,city,regionName,status")
            resp = urllib.request.urlopen(req, timeout=5)
            geo = json.loads(resp.read())
            if geo.get("status") != "success":
                json_response(self, {"location": list(LOCATIONS.keys())[0], "method": "default"})
                return
            user_lat, user_lon = geo["lat"], geo["lon"]
        except Exception:
            json_response(self, {"location": list(LOCATIONS.keys())[0], "method": "default"})
            return

        # Find nearest location
        def haversine(lat1, lon1, lat2, lon2):
            R = 3959  # miles
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
            return R * 2 * math.asin(math.sqrt(a))

        nearest = None
        nearest_dist = float("inf")
        for key, loc in LOCATIONS.items():
            if loc.get("lat") and loc.get("lon"):
                d = haversine(user_lat, user_lon, loc["lat"], loc["lon"])
                if d < nearest_dist:
                    nearest_dist = d
                    nearest = key

        json_response(self, {
            "location": nearest or list(LOCATIONS.keys())[0],
            "distance_miles": round(nearest_dist, 1),
            "user_city": geo.get("city", ""),
            "user_region": geo.get("regionName", ""),
            "method": "ip"
        })

    # ---------- config ----------
    def serve_config(self):
        config_path = os.path.join(os.path.dirname(DIR), "scripts", "houstons-config.json")
        try:
            with open(config_path) as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data.encode())
        except Exception:
            json_response(self, {"error": "Config not found"}, 500)

    def log_message(self, fmt, *args):
        # Minimal logging
        pass


def _time_str_to_minutes(t):
    """Convert '18:00' to 1080 or '6:00 PM' to 1080"""
    import re as _re
    if 'AM' in t.upper() or 'PM' in t.upper():
        m = _re.match(r'(\d+):(\d+)\s*(AM|PM)', t, _re.IGNORECASE)
        if not m:
            return 0
        h, mn, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if ap == 'PM' and h != 12:
            h += 12
        if ap == 'AM' and h == 12:
            h = 0
        return h * 60 + mn
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _fetch_inventory(loc_key, date_str, party_size):
    loc = LOCATIONS.get(loc_key)
    if not loc:
        return []
    slots = []
    for anchor_hour in [12, 17, 21]:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=anchor_hour)
        ts = int(dt.timestamp() * 1000)
        url = (f"https://loyaltyapi.wisely.io/v2/web/reservations/inventory"
               f"?merchant_id={loc['merchant_id']}&party_size={party_size}"
               f"&search_ts={ts}&show_reservation_types=1&limit=20")
        try:
            req = urllib.request.Request(url, headers=WISELY_HEADERS)
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            for t_type in data.get("types", []):
                for slot in t_type.get("times", []):
                    if slot.get("is_available") == 1 and slot.get("display_time"):
                        slots.append({
                            "time": slot["display_time"],
                            "reserved_ts": slot.get("reserved_ts"),
                            "type_id": t_type.get("reservation_type_id"),
                        })
        except Exception:
            pass
    return slots


def do_scan_watches():
    """Scan all active watches with tiered frequency. Returns result dict."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    conn = get_db()
    now_dt = datetime.now()
    now_iso = now_dt.isoformat()
    today_str = now_dt.strftime("%Y-%m-%d")

    # Auto-expire watches where target_date has passed
    conn.execute(
        "UPDATE watches SET status='expired' WHERE status='active' AND target_date < ?",
        (today_str,)
    )
    conn.commit()

    # Load all active watches with user info
    watches = conn.execute(
        "SELECT w.*, u.email as user_email, u.name as user_name FROM watches w "
        "JOIN users u ON w.user_id=u.id WHERE w.status='active'"
    ).fetchall()
    if not watches:
        conn.close()
        return {"matches": 0, "booked": [], "notified": [], "scanned": 0, "skipped": 0}
    watches = [dict(w) for w in watches]

    # Tiered filtering
    scannable = []
    skipped = 0
    for w in watches:
        try:
            target_dt = datetime.strptime(w["target_date"], "%Y-%m-%d")
        except ValueError:
            continue
        hours_until = (target_dt - now_dt).total_seconds() / 3600

        # Determine scan interval based on urgency
        if hours_until <= 24:
            min_interval = 0  # always scan (called every 10 min by loop)
        else:
            min_interval = 30 * 60  # 30 minutes in seconds

        # Check last_scanned
        if min_interval > 0 and w.get("last_scanned"):
            try:
                last = datetime.fromisoformat(w["last_scanned"])
                elapsed = (now_dt - last).total_seconds()
                if elapsed < min_interval:
                    skipped += 1
                    continue
            except ValueError:
                pass

        scannable.append(w)

    if not scannable:
        conn.close()
        return {"matches": 0, "booked": [], "notified": [], "scanned": 0, "skipped": skipped}

    # Group by (location_key, target_date, party_size) to minimize API calls
    groups = {}
    for w in scannable:
        key = (w["location_key"], w["target_date"], w["party_size"])
        groups.setdefault(key, []).append(w)

    matches = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {}
        for (loc_key, date_str, ps), watch_list in groups.items():
            f = pool.submit(_fetch_inventory, loc_key, date_str, ps)
            futures[f] = (loc_key, date_str, ps, watch_list)
        for f in as_completed(futures):
            loc_key, date_str, ps, watch_list = futures[f]
            slots = f.result()
            for w in watch_list:
                start_min = _time_str_to_minutes(w["time_start"])
                end_min = _time_str_to_minutes(w["time_end"])
                for slot in slots:
                    slot_min = _time_str_to_minutes(slot["time"])
                    if start_min <= slot_min <= end_min:
                        matches.append({"watch": w, "slot": slot, "location_key": loc_key})

    # Process matches
    booked = []
    notified = []
    booked_ids = set()
    for m in matches:
        w = m["watch"]
        slot = m["slot"]
        loc = LOCATIONS[m["location_key"]]

        # Auto-book if enabled
        if w["auto_book"] and w.get("book_first_name") and w.get("book_phone"):
            try:
                payload = json.dumps({
                    "merchant_id": loc["merchant_id"],
                    "party_size": w["party_size"],
                    "reserved_ts": slot["reserved_ts"],
                    "name": f"{w['book_first_name']} {w['book_last_name']}",
                    "first_name": w["book_first_name"],
                    "last_name": w["book_last_name"],
                    "email": w.get("book_email", w["user_email"]),
                    "phone": w["book_phone"],
                    "country_code": "US",
                    "reservation_type_id": slot["type_id"],
                    "source": "web",
                    "marketing_opt_in": False,
                }).encode()
                req = urllib.request.Request(
                    "https://loyaltyapi.wisely.io/v2/web/reservations",
                    data=payload, method="POST", headers=WISELY_HEADERS
                )
                resp = urllib.request.urlopen(req, timeout=15)
                book_data = json.loads(resp.read())
                if book_data.get("party"):
                    conn.execute("UPDATE watches SET status='booked', booked_at=? WHERE id=?", (now_iso, w["id"]))
                    booked.append({"watch_id": w["id"], "slot": slot["time"], "location": loc["name"]})
                    booked_ids.add(w["id"])
            except Exception:
                pass

        # Send email notification
        if w.get("user_email"):
            loc_name = loc.get("name", m["location_key"])
            action = "Auto-booked" if w["id"] in booked_ids else "Available"
            body = f"{action}! {loc_name} on {w['target_date']} at {slot['time']} for party of {w['party_size']}."
            if action == "Available":
                body += "\n\nBook now at https://www.gethoustons.bar"
            try:
                threading.Thread(target=lambda email=w["user_email"], subj=f"🍖 Houston's Slot {action}!", b=body: safe_gog_send(
                    ["gog", "gmail", "send", "--to", email,
                     "--subject", subj,
                     "--body", b]
                ), daemon=True).start()
            except Exception:
                pass

        # Log notification
        conn.execute("UPDATE watches SET notified_at=? WHERE id=?", (now_iso, w["id"]))
        notified.append({"watch_id": w["id"], "slot": slot["time"], "location": loc.get("name", "")})

        # Write to notifications.log
        try:
            log_path = os.path.join(DIR, "notifications.log")
            with open(log_path, "a") as f:
                status = "BOOKED" if w["id"] in booked_ids else "FOUND"
                f.write(f"[{now_iso}] {status}: {loc.get('name','')} {w['target_date']} {slot['time']} party={w['party_size']} user={w['user_email']}\n")
        except Exception:
            pass

    # Update last_scanned for all scannable watches
    for w in scannable:
        conn.execute("UPDATE watches SET last_scanned=? WHERE id=?", (now_iso, w["id"]))

    conn.commit()
    conn.close()
    return {"matches": len(matches), "booked": booked, "notified": notified, "scanned": len(scannable), "skipped": skipped}


def scanner_loop():
    """Background scanner thread - runs every 10 min, tiering handled internally."""
    while True:
        try:
            result = do_scan_watches()
            print(f"🔍 Scanner: scanned={result['scanned']} skipped={result['skipped']} matches={result['matches']}")
        except Exception as e:
            print(f"Scanner error: {e}")
        time.sleep(600)


if __name__ == "__main__":
    init_db()
    # Start background scanner thread
    scanner_thread = threading.Thread(target=scanner_loop, daemon=True)
    scanner_thread.start()
    print("🔍 Background watch scanner started (10 min interval)")
    class ThreadedHTTPServer(http.server.ThreadingHTTPServer):
        allow_reuse_address = True
    server = ThreadedHTTPServer(("", PORT), Handler)
    print(f"🥩 GetHoustons Tracker running on http://localhost:{PORT} ({len(LOCATIONS)} locations)")
    server.serve_forever()
