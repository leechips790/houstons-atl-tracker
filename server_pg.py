#!/usr/bin/env python3
"""Houston's ATL Tracker v2 — aiohttp + asyncpg server for Render."""

import asyncio
import hashlib
import json
import logging
import math
import os
import secrets
import time
import threading
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from aiohttp import web
import aiohttp_cors

import db
import sheets_sync
from notifications import (
    notify_admin_new_signup,
    notify_admin_new_watch,
    notify_admin_feedback,
    send_email,
    is_test_email,
    ADMIN_EMAIL,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("houstons.server")

PORT = int(os.environ.get("PORT", 10000))
GOOGLE_CLIENT_ID = os.environ.get(
    "GOOGLE_CLIENT_ID",
    "23317478020-ertd12jqki1bus53piflgomlu6ctipjn.apps.googleusercontent.com",
)
PUSH_SCAN_KEY = os.environ.get("PUSH_SCAN_KEY", "")

DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------
# Scan / push caches (in-memory, same as original)
# ------------------------------------------------------------------
_scan_cache = {}
_scan_cache_lock = threading.Lock()
SCAN_CACHE_TTL = 120

_push_cache = {}
_push_cache_lock = threading.Lock()
PUSH_CACHE_TTL = 2700

# ------------------------------------------------------------------
# Wisely
# ------------------------------------------------------------------
WISELY_HEADERS = {
    "Origin": "https://reservations.getwisely.com",
    "Referer": "https://reservations.getwisely.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/json",
}

LOCATIONS = {
    "peachtree": {"merchant_id": 278258, "type_id": 1681, "name": "Houston's - Peachtree", "city": "Atlanta", "state": "GA", "brand": "Houston's", "lat": 33.8478, "lon": -84.3880},
    "west_paces": {"merchant_id": 278259, "type_id": 1682, "name": "Houston's - West Paces", "city": "Atlanta", "state": "GA", "brand": "Houston's", "lat": 33.8400, "lon": -84.3690},
    "houston_s_bergen_county": {"merchant_id": 278171, "type_id": 1703, "name": "Houston's - Bergen County", "city": "Hackensack", "state": "NJ", "brand": "Houston's", "lat": 40.8859, "lon": -74.0435},
    "houston_s_boca_raton": {"merchant_id": 278275, "type_id": 1704, "name": "Houston's - Boca Raton", "city": "Boca Raton", "state": "FL", "brand": "Houston's", "lat": 26.3683, "lon": -80.1289},
    "houston_s_saint_charles": {"merchant_id": 278261, "type_id": 1701, "name": "Houston's - Saint Charles", "city": "Chicago", "state": "IL", "brand": "Houston's", "lat": 41.8932, "lon": -87.6274},
    "houston_s_north_miami_beach": {"merchant_id": 278271, "type_id": 1692, "name": "Houston's - North Miami Beach", "city": "North Miami Beach", "state": "FL", "brand": "Houston's", "lat": 25.9331, "lon": -80.1625},
    "houston_s_pasadena": {"merchant_id": 278270, "type_id": 1696, "name": "Houston's - Pasadena", "city": "Pasadena", "state": "CA", "brand": "Houston's", "lat": 34.1478, "lon": -118.1445},
    "houston_s_pompano_beach": {"merchant_id": 278276, "type_id": 1697, "name": "Houston's - Pompano Beach", "city": "Pompano Beach", "state": "FL", "brand": "Houston's", "lat": 26.2379, "lon": -80.1248},
    "scottsdale": {"merchant_id": 278256, "type_id": 1685, "name": "Houston's - Scottsdale", "city": "Scottsdale", "state": "AZ", "brand": "Houston's", "lat": 33.5010, "lon": -111.9260},
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
    "rd_kitchen_newport_beach": {"merchant_id": 278273, "type_id": 1707, "name": "R+D Kitchen - Newport Beach", "city": "Newport Beach", "state": "CA", "brand": "R+D Kitchen", "lat": 33.6170, "lon": -117.8740},
    "rd_kitchen_santa_monica": {"merchant_id": 278268, "type_id": 4514, "name": "R+D Kitchen - Santa Monica", "city": "Los Angeles", "state": "CA", "brand": "R+D Kitchen", "lat": 34.0289, "lon": -118.4951},
    "rd_kitchen_yountville": {"merchant_id": 278254, "type_id": 1675, "name": "R+D Kitchen - Yountville", "city": "Napa", "state": "CA", "brand": "R+D Kitchen", "lat": 38.4016, "lon": -122.3611},
    "honor_bar_dallas": {"merchant_id": 278262, "type_id": 4240, "name": "Honor Bar - Dallas", "city": "Dallas", "state": "TX", "brand": "Honor Bar", "lat": 32.8374, "lon": -96.8050},
    "palm_beach_grill": {"merchant_id": 278274, "type_id": 1693, "name": "Palm Beach Grill", "city": "Palm Beach", "state": "FL", "brand": "Palm Beach Grill", "lat": 26.7056, "lon": -80.0364},
    "bandera_corona_del_mar": {"merchant_id": 278245, "type_id": 1705, "name": "Bandera - Corona del Mar", "city": "Newport Beach", "state": "CA", "brand": "Bandera", "lat": 33.6003, "lon": -117.8761},
    "south_beverly_grill": {"merchant_id": 278269, "type_id": 1700, "name": "South Beverly Grill", "city": "Beverly Hills", "state": "CA", "brand": "South Beverly Grill", "lat": 34.0597, "lon": -118.3989},
    "cherry_creek_grill": {"merchant_id": 278239, "type_id": 1690, "name": "Cherry Creek Grill", "city": "Denver", "state": "CO", "brand": "Cherry Creek Grill", "lat": 39.7170, "lon": -104.9536},
    "rutherford_grill": {"merchant_id": 278253, "type_id": 1676, "name": "Rutherford Grill", "city": "Rutherford", "state": "CA", "brand": "Rutherford Grill", "lat": 38.4566, "lon": -122.4184},
    "los_altos_grill": {"merchant_id": 278255, "type_id": 1677, "name": "Los Altos Grill", "city": "Los Altos", "state": "CA", "brand": "Los Altos Grill", "lat": 37.3795, "lon": -122.1141},
    "east_hampton_grill": {"merchant_id": 278240, "type_id": 1706, "name": "East Hampton Grill", "city": "East Hampton", "state": "NY", "brand": "East Hampton Grill", "lat": 40.9634, "lon": -72.1848},
}

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _default_serializer(obj):
    """JSON serializer for objects not serializable by default json module."""
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _json(data, status=200):
    import json as _json_mod
    body = _json_mod.dumps(data, default=_default_serializer)
    return web.Response(
        text=body, status=status,
        content_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )


def _parse_date(s):
    """Parse a date string to datetime.date for asyncpg DATE columns."""
    if not s:
        return None
    if isinstance(s, datetime):
        return s.date()
    if hasattr(s, 'date'):
        return s
    return datetime.strptime(str(s), "%Y-%m-%d").date()


def _parse_time(s):
    """Parse a time string like '18:00' to datetime.time for asyncpg TIME columns."""
    if not s:
        return None
    if hasattr(s, 'hour'):  # already a time object
        return s
    parts = str(s).split(":")
    from datetime import time as dt_time
    return dt_time(int(parts[0]), int(parts[1]))


def _parse_timestamp(s):
    """Parse an ISO timestamp string to datetime for asyncpg TIMESTAMPTZ columns."""
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(str(s))


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


async def _get_user(request) -> dict | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    row = await db.fetchrow(
        "SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id "
        "WHERE s.token=$1 AND s.expires_at > NOW()", token
    )
    return row


def _fetch_slots_sync(loc_key, loc, date_str, anchor_hour, party_size):
    """Blocking Wisely API call (used in thread pool)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=anchor_hour)
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


# ------------------------------------------------------------------
# Wisely proxy
# ------------------------------------------------------------------

async def proxy_inventory(request):
    qs = request.query_string
    url = f"https://loyaltyapi.wisely.io/v2/web/reservations/inventory?{qs}"
    try:
        req = urllib.request.Request(url, headers=WISELY_HEADERS)
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15))
        data = resp.read()
        return web.Response(body=data, content_type="application/json")
    except Exception as e:
        return _json({"error": str(e)}, 500)


async def proxy_book(request):
    body = await request.read()
    url = "https://loyaltyapi.wisely.io/v2/web/reservations"
    try:
        req = urllib.request.Request(url, data=body, method="POST", headers=WISELY_HEADERS)
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15))
        data = resp.read()
        return web.Response(body=data, content_type="application/json")
    except urllib.error.HTTPError as e:
        return web.Response(body=e.read(), status=e.code, content_type="application/json")
    except Exception as e:
        return _json({"error": str(e)}, 500)


# ------------------------------------------------------------------
# Scan (7-day availability)
# ------------------------------------------------------------------

async def handle_scan(request):
    params = request.query
    party_size = int(params.get("party_size", "2"))

    with _scan_cache_lock:
        cached = _scan_cache.get(party_size)
        if cached and (time.time() - cached[0]) < SCAN_CACHE_TTL:
            return _json(cached[1])

    days_out = min(int(params.get("days", "21")), 21)
    today = datetime.now()
    dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_out)]

    results = {}
    for loc_key, loc in LOCATIONS.items():
        results[loc_key] = {"name": loc["name"], "merchant_id": loc["merchant_id"], "days": {d: {} for d in dates}}

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=28) as pool:
        futures = []
        for loc_key, loc in LOCATIONS.items():
            for date_str in dates:
                for anchor_hour in [12, 17, 21]:
                    futures.append(pool.submit(_fetch_slots_sync, loc_key, loc, date_str, anchor_hour, party_size))

        done = await loop.run_in_executor(None, lambda: [f.result() for f in as_completed(futures)])

    for loc_key, date_str, slots in done:
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
    return _json(result)


# ------------------------------------------------------------------
# Push scan
# ------------------------------------------------------------------

async def handle_push_scan(request):
    key = request.headers.get("X-Push-Key", "")
    if not PUSH_SCAN_KEY or key != PUSH_SCAN_KEY:
        return _json({"error": "unauthorized"}, 401)
    data = await request.json()
    party_size = data.get("party_size", 2)
    scan_data = data.get("data", {})
    ts = data.get("timestamp", time.time())
    with _push_cache_lock:
        _push_cache[party_size] = {"data": scan_data, "timestamp": ts}
    return _json({"success": True, "party_size": party_size})


async def handle_availability(request):
    party_size = int(request.query.get("party_size", "2"))
    with _push_cache_lock:
        cached = _push_cache.get(party_size)
    if cached and (time.time() - cached["timestamp"]) < PUSH_CACHE_TTL:
        return _json({
            "locations": cached["data"],
            "scanned_at": datetime.fromtimestamp(cached["timestamp"]).isoformat(),
            "party_size": party_size,
            "source": "cache",
        })
    return await handle_scan(request)


# ------------------------------------------------------------------
# Alerts
# ------------------------------------------------------------------

async def get_alerts(request):
    rows = await db.fetch("SELECT * FROM alerts ORDER BY created_at DESC")
    count = await db.fetchval("SELECT COUNT(*) FROM alerts")
    return _json({"alerts": rows, "count": count})


async def post_alert(request):
    data = await request.json()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    if not name or not email:
        return _json({"error": "Name and email required"}, 400)
    await db.execute(
        "INSERT INTO alerts (name, email, party_size, preferred_date, preferred_time, location) "
        "VALUES ($1,$2,$3,$4,$5,$6)",
        name, email, data.get("party_size", 2),
        data.get("preferred_date", ""), data.get("preferred_time", ""),
        data.get("location", "both"),
    )
    count = await db.fetchval("SELECT COUNT(*) FROM alerts")
    return _json({"success": True, "count": count})


# ------------------------------------------------------------------
# Wait times
# ------------------------------------------------------------------

async def get_waittimes(request):
    result = {}
    for loc_key in LOCATIONS:
        rows = await db.fetch(
            "SELECT * FROM wait_reports WHERE location=$1 ORDER BY created_at DESC LIMIT 6",
            loc_key,
        )
        result[loc_key] = rows
    return _json({"waittimes": result})


async def post_waittime(request):
    data = await request.json()
    location = data.get("location", "").strip()
    wait_minutes = data.get("wait_minutes")
    source = data.get("source", "user")
    if not location or wait_minutes is None:
        return _json({"error": "location and wait_minutes required"}, 400)
    await db.execute(
        "INSERT INTO wait_reports (location, wait_minutes, source) VALUES ($1,$2,$3)",
        location, int(wait_minutes), source,
    )
    return _json({"success": True})


# ------------------------------------------------------------------
# History
# ------------------------------------------------------------------

async def get_history(request):
    scans = await db.fetch("SELECT * FROM scan_history ORDER BY scanned_at DESC LIMIT 200")
    drops = await db.fetch("SELECT * FROM slot_drops ORDER BY created_at DESC LIMIT 10")
    return _json({"scans": scans, "drops": drops})


async def post_history_record(request):
    data = await request.json()
    location = data.get("location", "")
    scan_date = data.get("scan_date", "")
    time_slot = data.get("time_slot", "")
    available = True if data.get("available") else False
    party_sizes = data.get("party_sizes", "")
    await db.execute(
        "INSERT INTO scan_history (location, scan_date, time_slot, party_sizes, available) VALUES ($1,$2,$3,$4,$5)",
        location, _parse_date(scan_date), time_slot, party_sizes, available,
    )
    # Check for slot drops
    scan_date_obj = _parse_date(scan_date)
    prev = await db.fetchrow(
        "SELECT available FROM scan_history WHERE location=$1 AND scan_date=$2 AND time_slot=$3 "
        "ORDER BY scanned_at DESC LIMIT 1 OFFSET 1",
        location, scan_date_obj, time_slot,
    )
    if prev and not prev["available"] and available:
        await db.execute(
            "INSERT INTO slot_drops (location, slot_date, slot_time, appeared_at) VALUES ($1,$2,$3,NOW())",
            location, scan_date_obj, time_slot,
        )
    return _json({"success": True})


# ------------------------------------------------------------------
# Calls (Bland.ai)
# ------------------------------------------------------------------

async def get_calls(request):
    location = request.query.get("location")
    if location:
        rows = await db.fetch(
            "SELECT * FROM call_logs WHERE location=$1 ORDER BY called_at DESC", location
        )
    else:
        rows = await db.fetch("SELECT * FROM call_logs ORDER BY called_at DESC")
    return _json({"calls": rows})


async def get_calls_latest(request):
    result = {}
    for loc_key, loc_info in LOCATIONS.items():
        row = await db.fetchrow(
            "SELECT * FROM call_logs WHERE location=$1 ORDER BY called_at DESC LIMIT 1",
            loc_info["name"],
        )
        if not row:
            row = await db.fetchrow(
                "SELECT * FROM call_logs WHERE location=$1 ORDER BY called_at DESC LIMIT 1",
                loc_key,
            )
        if row:
            result[loc_info["name"]] = row
    return _json({"latest": result})


async def get_calls_stats(request):
    by_dow = await db.fetch("""
        SELECT location,
               CASE EXTRACT(DOW FROM called_at)::int
                 WHEN 0 THEN 'Sun' WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue'
                 WHEN 3 THEN 'Wed' WHEN 4 THEN 'Thu' WHEN 5 THEN 'Fri' WHEN 6 THEN 'Sat'
               END as dow,
               ROUND(AVG(wait_count)::numeric, 1) as avg_wait,
               COUNT(*) as n
        FROM call_logs WHERE wait_count IS NOT NULL
        GROUP BY location, EXTRACT(DOW FROM called_at)::int
        ORDER BY EXTRACT(DOW FROM called_at)::int
    """)
    by_hour = await db.fetch("""
        SELECT location,
               EXTRACT(HOUR FROM called_at)::int as hour,
               ROUND(AVG(wait_count)::numeric, 1) as avg_wait,
               COUNT(*) as n
        FROM call_logs WHERE wait_count IS NOT NULL
        GROUP BY location, EXTRACT(HOUR FROM called_at)::int
        ORDER BY hour
    """)
    by_loc = await db.fetch("""
        SELECT location,
               ROUND(AVG(wait_count)::numeric, 1) as avg_wait,
               COUNT(*) as total_calls,
               SUM(CASE WHEN wait_count IS NOT NULL THEN 1 ELSE 0 END) as calls_with_data
        FROM call_logs
        GROUP BY location
    """)
    return _json({
        "by_day_of_week": by_dow,
        "by_hour": by_hour,
        "by_location": by_loc,
    })


async def post_call(request):
    data = await request.json()
    location = data.get("location", "").strip()
    called_at = _parse_timestamp(data.get("called_at")) or datetime.now()
    if not location:
        return _json({"error": "location required"}, 400)
    await db.execute(
        """INSERT INTO call_logs
           (location, phone, call_id, wait_count, wait_minutes, transcript, summary,
            recording_url, call_duration, answered_by, status, called_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
        location, data.get("phone"), data.get("call_id"),
        data.get("wait_count"), data.get("wait_minutes"),
        data.get("transcript"), data.get("summary"),
        data.get("recording_url"), data.get("call_duration"),
        data.get("answered_by"), data.get("status", "pending"),
        called_at,
    )
    return _json({"success": True})


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------

async def auth_signup(request):
    data = await request.json()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    if not name or not email or not password:
        return _json({"error": "Name, email, and password required"}, 400)
    if len(password) < 6:
        return _json({"error": "Password must be at least 6 characters"}, 400)
    existing = await db.fetchrow("SELECT id FROM users WHERE email=$1", email)
    if existing:
        return _json({"error": "Email already registered"}, 409)
    pw_hash = _hash_password(password)
    user = await db.fetchrow(
        "INSERT INTO users (email, password_hash, name) VALUES ($1,$2,$3) RETURNING *",
        email, pw_hash, name,
    )
    token = secrets.token_hex(32)
    await db.execute("INSERT INTO sessions (user_id, token) VALUES ($1,$2)", user["id"], token)
    return _json({"success": True, "token": token, "user": {
        "id": user["id"], "name": user["name"], "email": user["email"],
        "phone": user.get("phone", ""),
        "first_name": user.get("first_name", ""), "last_name": user.get("last_name", ""),
    }})


async def auth_login(request):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    if not email or not password:
        return _json({"error": "Email and password required"}, 400)
    user = await db.fetchrow("SELECT * FROM users WHERE email=$1", email)
    if not user or user["password_hash"] != _hash_password(password):
        return _json({"error": "Invalid email or password"}, 401)
    token = secrets.token_hex(32)
    await db.execute("INSERT INTO sessions (user_id, token) VALUES ($1,$2)", user["id"], token)
    return _json({"success": True, "token": token, "user": {
        "id": user["id"], "name": user["name"], "email": user["email"],
        "phone": user.get("phone", ""),
        "first_name": user.get("first_name", ""), "last_name": user.get("last_name", ""),
    }})


async def auth_logout(request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        await db.execute("DELETE FROM sessions WHERE token=$1", token)
    return _json({"success": True})


async def auth_me(request):
    user = await _get_user(request)
    if not user:
        return _json({"error": "Not authenticated"}, 401)
    return _json({"user": {
        "id": user["id"], "name": user["name"], "email": user["email"],
        "picture": user.get("picture", ""), "phone": user.get("phone", ""),
        "first_name": user.get("first_name", ""), "last_name": user.get("last_name", ""),
    }})


async def auth_get_alerts(request):
    user = await _get_user(request)
    if not user:
        return _json({"error": "Not authenticated"}, 401)
    rows = await db.fetch("SELECT * FROM alerts WHERE email=$1 ORDER BY created_at DESC", user["email"])
    return _json({"alerts": rows})


async def auth_google(request):
    data = await request.json()
    credential = data.get("credential", "")
    if not credential:
        return _json({"error": "No credential provided"}, 400)
    # Verify token with Google
    try:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
        req = urllib.request.Request(url)
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=10))
        token_info = json.loads(resp.read())
    except Exception as e:
        return _json({"error": f"Token verification failed: {e}"}, 401)
    if token_info.get("aud") != GOOGLE_CLIENT_ID:
        return _json({"error": "Invalid token audience"}, 401)
    google_id = token_info.get("sub")
    email = token_info.get("email", "").lower()
    name = token_info.get("name", "")
    picture = token_info.get("picture", "")
    if not google_id or not email:
        return _json({"error": "Invalid token data"}, 401)

    is_new = False
    user = await db.fetchrow("SELECT * FROM users WHERE google_id=$1", google_id)
    if not user:
        is_new = True
        user = await db.fetchrow("SELECT * FROM users WHERE email=$1", email)
        if user:
            await db.execute(
                "UPDATE users SET google_id=$1, picture=$2, last_login=NOW() WHERE id=$3",
                google_id, picture, user["id"],
            )
        else:
            await db.execute(
                "INSERT INTO users (email, password_hash, name, google_id, picture, last_login) "
                "VALUES ($1,'',$2,$3,$4,NOW())",
                email, name, google_id, picture,
            )
        user = await db.fetchrow("SELECT * FROM users WHERE google_id=$1", google_id)
    else:
        await db.execute(
            "UPDATE users SET picture=$1, name=$2, last_login=NOW() WHERE id=$3",
            picture, name, user["id"],
        )

    token = secrets.token_hex(32)
    await db.execute("INSERT INTO sessions (user_id, token) VALUES ($1,$2)", user["id"], token)

    # Notify admin of new signup (background)
    if is_new:
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, notify_admin_new_signup, name, email)

    return _json({
        "success": True, "token": token,
        "user": {
            "id": user["id"],
            "name": name or user["name"],
            "email": email,
            "picture": picture,
            "phone": user.get("phone", ""),
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
        },
    })


# ------------------------------------------------------------------
# Profile
# ------------------------------------------------------------------

async def get_profile(request):
    user = await _get_user(request)
    if not user:
        return _json({"error": "Not authenticated"}, 401)
    return _json({
        "phone": user.get("phone", ""),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "picture": user.get("picture", ""),
    })


async def post_profile(request):
    user = await _get_user(request)
    if not user:
        return _json({"error": "Not authenticated"}, 401)
    data = await request.json()
    phone = data.get("phone", "").strip()
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    updates = []
    params = []
    idx = 1
    if phone:
        updates.append(f"phone=${idx}"); params.append(phone); idx += 1
    if first_name or first_name == "":
        # Only update if key was provided
        if "first_name" in data:
            updates.append(f"first_name=${idx}"); params.append(first_name); idx += 1
    if last_name or last_name == "":
        if "last_name" in data:
            updates.append(f"last_name=${idx}"); params.append(last_name); idx += 1
    if updates:
        params.append(user["id"])
        await db.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id=${idx}",
            *params,
        )
    return _json({"success": True})


# ------------------------------------------------------------------
# Watches
# ------------------------------------------------------------------

async def get_watches(request):
    user = await _get_user(request)
    if not user:
        return _json({"error": "Not authenticated"}, 401)
    rows = await db.fetch(
        "SELECT * FROM watches WHERE user_id=$1 AND status='active' ORDER BY target_date ASC",
        user["id"],
    )
    return _json({"watches": rows})


async def post_watch(request):
    user = await _get_user(request)
    if not user:
        return _json({"error": "Not authenticated"}, 401)
    data = await request.json()
    location_key = data.get("location_key", "")
    party_size = data.get("party_size", 2)
    target_date = data.get("target_date", "")
    time_start = data.get("time_start", "18:00")
    time_end = data.get("time_end", "20:00")
    auto_book = True if data.get("auto_book") else False
    if not location_key or not target_date:
        return _json({"error": "location_key and target_date required"}, 400)
    if location_key not in LOCATIONS:
        return _json({"error": "Invalid location"}, 400)

    watch_id = await db.fetchval(
        """INSERT INTO watches (user_id, location_key, party_size, target_date, time_start, time_end,
           auto_book, book_first_name, book_last_name, book_email, book_phone)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id""",
        user["id"], location_key, party_size, _parse_date(target_date),
        _parse_time(time_start), _parse_time(time_end), auto_book,
        data.get("book_first_name", ""), data.get("book_last_name", ""),
        data.get("book_email", user["email"]), data.get("book_phone", ""),
    )

    # Save phone to user if provided
    book_phone = data.get("book_phone", "")
    if book_phone and not user.get("phone"):
        await db.execute("UPDATE users SET phone=$1 WHERE id=$2", book_phone, user["id"])

    # Notify admin (background)
    loc_name = LOCATIONS.get(location_key, {}).get("name", location_key)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        None, notify_admin_new_watch,
        user["name"], user["email"], loc_name, party_size,
        target_date, time_start, time_end, auto_book,
    )

    # Sheets sync (non-blocking)
    sheets_sync.append_watch(
        watch_id,
        user["name"],
        user["email"],
        user.get("phone", "") or data.get("book_phone", ""),
        loc_name,
        party_size,
        target_date,
        time_start,
        time_end,
        auto_book,
    )

    return _json({"success": True, "watch_id": watch_id})


async def delete_watch(request):
    user = await _get_user(request)
    if not user:
        return _json({"error": "Not authenticated"}, 401)
    watch_id_str = request.match_info.get("watch_id", "")
    try:
        watch_id = int(watch_id_str)
    except ValueError:
        return _json({"error": "Invalid watch ID"}, 400)
    watch = await db.fetchrow(
        "SELECT * FROM watches WHERE id=$1 AND user_id=$2", watch_id, user["id"]
    )
    if not watch:
        return _json({"error": "Watch not found"}, 404)
    await db.execute("UPDATE watches SET status='cancelled' WHERE id=$1", watch_id)
    sheets_sync.mark_cancelled(watch_id)
    return _json({"success": True})


async def scan_watches_endpoint(request):
    """Trigger a scan from the web — delegates to worker in production, but kept for compat."""
    return _json({"info": "Scanning is handled by the background worker"})


# ------------------------------------------------------------------
# Feedback
# ------------------------------------------------------------------

async def post_feedback(request):
    data = await request.json()
    message = data.get("message", "").strip()
    contact = data.get("contact", "").strip()
    if not message:
        return _json({"error": "Message is required"}, 400)
    peername = request.transport.get_extra_info("peername")
    ip = ""
    if peername:
        ip = peername[0]
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        ip = xff.split(",")[0].strip()
    await db.execute(
        "INSERT INTO feedback (message, contact, ip) VALUES ($1,$2,$3)",
        message, contact or None, ip,
    )
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, notify_admin_feedback, message, contact, ip)
    return _json({"success": True})


async def admin_get_feedback(request):
    user = await _get_user(request)
    if not user:
        return _json({"error": "Not authenticated"}, 401)
    rows = await db.fetch("SELECT * FROM feedback ORDER BY created_at DESC")
    return _json({"feedback": rows})


async def admin_get_watches(request):
    admin_key = request.query.get("key")
    if admin_key != "leechips790admin":
        user = await _get_user(request)
        if not user:
            return _json({"error": "Not authenticated"}, 401)
    rows = await db.fetch(
        "SELECT w.*, u.email as user_email, u.name as user_name "
        "FROM watches w LEFT JOIN users u ON w.user_id=u.id ORDER BY w.id"
    )
    return _json({"watches": rows})


# ------------------------------------------------------------------
# Locations / Geolocate / Config
# ------------------------------------------------------------------

async def get_locations(request):
    locs = []
    for key, loc in LOCATIONS.items():
        locs.append({
            "key": key, "name": loc["name"], "city": loc.get("city", ""),
            "state": loc.get("state", ""), "brand": loc.get("brand", ""),
            "lat": loc.get("lat"), "lon": loc.get("lon"),
            "merchant_id": loc["merchant_id"],
        })
    return _json({"locations": locs})


async def geolocate(request):
    xff = request.headers.get("X-Forwarded-For", "")
    ip = xff.split(",")[0].strip() if xff else ""
    if not ip:
        peername = request.transport.get_extra_info("peername")
        ip = peername[0] if peername else ""
    try:
        req = urllib.request.Request(f"http://ip-api.com/json/{ip}?fields=lat,lon,city,regionName,status")
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=5))
        geo = json.loads(resp.read())
        if geo.get("status") != "success":
            return _json({"location": list(LOCATIONS.keys())[0], "method": "default"})
        user_lat, user_lon = geo["lat"], geo["lon"]
    except Exception:
        return _json({"location": list(LOCATIONS.keys())[0], "method": "default"})

    def haversine(lat1, lon1, lat2, lon2):
        R = 3959
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        return R * 2 * math.asin(math.sqrt(a))

    nearest = None
    nearest_dist = float("inf")
    for key, loc in LOCATIONS.items():
        if loc.get("lat") and loc.get("lon"):
            d = haversine(user_lat, user_lon, loc["lat"], loc["lon"])
            if d < nearest_dist:
                nearest_dist = d
                nearest = key

    return _json({
        "location": nearest or list(LOCATIONS.keys())[0],
        "distance_miles": round(nearest_dist, 1),
        "user_city": geo.get("city", ""),
        "user_region": geo.get("regionName", ""),
        "method": "ip",
    })


async def serve_config(request):
    config_path = os.path.join(os.path.dirname(DIR), "scripts", "houstons-config.json")
    try:
        with open(config_path) as f:
            data = f.read()
        return web.Response(text=data, content_type="application/json")
    except Exception:
        return _json({"error": "Config not found"}, 500)


# ------------------------------------------------------------------
# App setup
# ------------------------------------------------------------------

async def on_startup(app):
    await db.get_pool()
    log.info("Database pool ready")
    # Ensure first_name / last_name columns exist (added in v2)
    try:
        await db.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT DEFAULT ''"
        )
        await db.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name TEXT DEFAULT ''"
        )
        log.info("Ensured first_name/last_name columns on users table")
    except Exception as e:
        log.warning(f"Migration check (first_name/last_name): {e}")


async def on_cleanup(app):
    await db.close_pool()


def create_app():
    app = web.Application()

    # CORS
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=False,
            expose_headers="*",
            allow_headers=("Content-Type", "X-Push-Key", "Authorization"),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        )
    })

    # Routes
    routes = [
        ("GET", "/api/inventory", proxy_inventory),
        ("GET", "/api/scan", handle_scan),
        ("GET", "/api/alerts", get_alerts),
        ("GET", "/api/waittimes", get_waittimes),
        ("GET", "/api/history", get_history),
        ("GET", "/api/config", serve_config),
        ("GET", "/api/locations", get_locations),
        ("GET", "/api/geolocate", geolocate),
        ("GET", "/api/calls", get_calls),
        ("GET", "/api/calls/latest", get_calls_latest),
        ("GET", "/api/calls/stats", get_calls_stats),
        ("GET", "/api/availability", handle_availability),
        ("GET", "/api/auth/me", auth_me),
        ("GET", "/api/auth/alerts", auth_get_alerts),
        ("GET", "/api/watches", get_watches),
        ("GET", "/api/profile", get_profile),
        ("GET", "/api/admin/feedback", admin_get_feedback),
        ("GET", "/api/admin/watches", admin_get_watches),
        ("POST", "/api/book", proxy_book),
        ("POST", "/api/alerts", post_alert),
        ("POST", "/api/waittimes", post_waittime),
        ("POST", "/api/history/record", post_history_record),
        ("POST", "/api/calls", post_call),
        ("POST", "/api/auth/signup", auth_signup),
        ("POST", "/api/auth/login", auth_login),
        ("POST", "/api/auth/logout", auth_logout),
        ("POST", "/api/auth/google", auth_google),
        ("POST", "/api/feedback", post_feedback),
        ("POST", "/api/push-scan", handle_push_scan),
        ("POST", "/api/watches", post_watch),
        ("POST", "/api/profile", post_profile),
        ("POST", "/api/watches/scan", scan_watches_endpoint),
        ("DELETE", "/api/watches/{watch_id}", delete_watch),
    ]

    for method, path, handler in routes:
        resource = cors.add(app.router.add_resource(path))
        cors.add(resource.add_route(method, handler))

    # Serve index.html for root and any non-API path (SPA support)
    async def serve_index(request):
        return web.FileResponse(os.path.join(DIR, "index.html"))

    app.router.add_get("/", serve_index)
    # Static files (CSS, JS, images)
    app.router.add_static("/", DIR, show_index=False)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app


if __name__ == "__main__":
    app = create_app()
    log.info("🥩 GetHoustons Tracker starting on port %d (%d locations)", PORT, len(LOCATIONS))
    web.run_app(app, port=PORT, print=None)
