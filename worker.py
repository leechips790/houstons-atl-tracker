#!/usr/bin/env python3
"""Houston's Background Worker — scans watches, sends notifications, auto-books."""

import json
import logging
import os
import re
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from apscheduler.schedulers.blocking import BlockingScheduler

from notifications import (
    notify_slot_found,
    was_recently_notified,
    log_notification,
    send_email,
    is_test_email,
    ADMIN_EMAIL,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("houstons.worker")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
REDIS_URL = os.environ.get("REDIS_URL", "")

WISELY_HEADERS = {
    "Origin": "https://reservations.getwisely.com",
    "Referer": "https://reservations.getwisely.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/json",
}

# Same LOCATIONS dict as server
LOCATIONS = {
    "peachtree": {"merchant_id": 278258, "type_id": 1681, "name": "Houston's - Peachtree"},
    "west_paces": {"merchant_id": 278259, "type_id": 1682, "name": "Houston's - West Paces"},
    "houston_s_bergen_county": {"merchant_id": 278171, "type_id": 1703, "name": "Houston's - Bergen County"},
    "houston_s_boca_raton": {"merchant_id": 278275, "type_id": 1704, "name": "Houston's - Boca Raton"},
    "houston_s_saint_charles": {"merchant_id": 278261, "type_id": 1701, "name": "Houston's - Saint Charles"},
    "houston_s_north_miami_beach": {"merchant_id": 278271, "type_id": 1692, "name": "Houston's - North Miami Beach"},
    "houston_s_pasadena": {"merchant_id": 278270, "type_id": 1696, "name": "Houston's - Pasadena"},
    "houston_s_pompano_beach": {"merchant_id": 278276, "type_id": 1697, "name": "Houston's - Pompano Beach"},
    "scottsdale": {"merchant_id": 278256, "type_id": 1685, "name": "Houston's - Scottsdale"},
    "hillstone_phoenix": {"merchant_id": 278170, "type_id": 1662, "name": "Hillstone - Phoenix"},
    "hillstone_bal_harbour": {"merchant_id": 278242, "type_id": 1702, "name": "Hillstone - Bal Harbour"},
    "hillstone_coral_gables": {"merchant_id": 278173, "type_id": 1664, "name": "Hillstone - Coral Gables"},
    "hillstone_winter_park": {"merchant_id": 278257, "type_id": 1684, "name": "Hillstone - Winter Park"},
    "hillstone_denver": {"merchant_id": 278243, "type_id": 1691, "name": "Hillstone - Denver"},
    "hillstone_park_cities": {"merchant_id": 278264, "type_id": 1694, "name": "Hillstone - Park Cities"},
    "hillstone_houston": {"merchant_id": 278244, "type_id": 1683, "name": "Hillstone - Houston"},
    "hillstone_park_avenue": {"merchant_id": 278278, "type_id": 1695, "name": "Hillstone - Park Avenue"},
    "hillstone_embarcadero": {"merchant_id": 278172, "type_id": 1663, "name": "Hillstone - San Francisco"},
    "hillstone_santa_monica": {"merchant_id": 278267, "type_id": 1689, "name": "Hillstone - Santa Monica"},
    "rd_kitchen_newport_beach": {"merchant_id": 278273, "type_id": 1707, "name": "R+D Kitchen - Newport Beach"},
    "rd_kitchen_santa_monica": {"merchant_id": 278268, "type_id": 4514, "name": "R+D Kitchen - Santa Monica"},
    "rd_kitchen_yountville": {"merchant_id": 278254, "type_id": 1675, "name": "R+D Kitchen - Yountville"},
    "honor_bar_dallas": {"merchant_id": 278262, "type_id": 4240, "name": "Honor Bar - Dallas"},
    "palm_beach_grill": {"merchant_id": 278274, "type_id": 1693, "name": "Palm Beach Grill"},
    "bandera_corona_del_mar": {"merchant_id": 278245, "type_id": 1705, "name": "Bandera - Corona del Mar"},
    "south_beverly_grill": {"merchant_id": 278269, "type_id": 1700, "name": "South Beverly Grill"},
    "cherry_creek_grill": {"merchant_id": 278239, "type_id": 1690, "name": "Cherry Creek Grill"},
    "rutherford_grill": {"merchant_id": 278253, "type_id": 1676, "name": "Rutherford Grill"},
    "los_altos_grill": {"merchant_id": 278255, "type_id": 1677, "name": "Los Altos Grill"},
    "east_hampton_grill": {"merchant_id": 278240, "type_id": 1706, "name": "East Hampton Grill"},
}


def get_conn():
    """Get a psycopg2 connection."""
    dsn = DATABASE_URL
    if dsn.startswith("postgres://"):
        dsn = dsn.replace("postgres://", "postgresql://", 1)
    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def _time_str_to_minutes(t: str) -> int:
    """Convert '18:00' or '6:00 PM' to minutes since midnight."""
    t = t.strip()
    m = re.match(r'(\d+):(\d+)\s*(AM|PM)', t, re.IGNORECASE)
    if m:
        h, mn, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if ap == 'PM' and h != 12:
            h += 12
        if ap == 'AM' and h == 12:
            h = 0
        return h * 60 + mn
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _fetch_inventory(loc_key: str, date_str: str, party_size: int) -> list:
    """Fetch available slots from Wisely for a location+date+party_size."""
    loc = LOCATIONS.get(loc_key)
    if not loc:
        return []
    slots = []
    for anchor_hour in [12, 17, 21]:
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


def _auto_book(watch: dict, slot: dict, loc: dict) -> bool:
    """Attempt to auto-book a slot. Returns True on success."""
    try:
        payload = json.dumps({
            "merchant_id": loc["merchant_id"],
            "party_size": watch["party_size"],
            "reserved_ts": slot["reserved_ts"],
            "name": f"{watch['book_first_name']} {watch['book_last_name']}",
            "first_name": watch["book_first_name"],
            "last_name": watch["book_last_name"],
            "email": watch.get("book_email") or watch["user_email"],
            "phone": watch["book_phone"],
            "country_code": "US",
            "reservation_type_id": slot["type_id"],
            "source": "web",
            "marketing_opt_in": False,
        }).encode()
        req = urllib.request.Request(
            "https://loyaltyapi.wisely.io/v2/web/reservations",
            data=payload, method="POST", headers=WISELY_HEADERS,
        )
        resp = urllib.request.urlopen(req, timeout=15)
        book_data = json.loads(resp.read())
        return bool(book_data.get("party"))
    except Exception:
        log.exception("Auto-book failed for watch %s", watch["id"])
        return False


def scan_watches(urgency: str = "all"):
    """
    Scan active watches, match against Wisely inventory, notify/book.
    urgency: 'urgent' (<24h), 'normal' (>=24h), 'all'
    """
    conn = get_conn()
    try:
        now_dt = datetime.now()
        today_str = now_dt.strftime("%Y-%m-%d")
        cur = conn.cursor()

        # Auto-expire past watches
        cur.execute("UPDATE watches SET status='expired' WHERE status='active' AND target_date < %s", (today_str,))
        conn.commit()

        # Load active watches with user info
        cur.execute(
            "SELECT w.*, u.email as user_email, u.name as user_name, u.phone as user_phone "
            "FROM watches w JOIN users u ON w.user_id=u.id WHERE w.status='active'"
        )
        watches = cur.fetchall()
        if not watches:
            log.info("No active watches")
            return {"matches": 0, "booked": [], "notified": [], "scanned": 0, "skipped": 0}

        # Tiered filtering
        scannable = []
        skipped = 0
        for w in watches:
            target_date = w["target_date"]
            if isinstance(target_date, str):
                target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            else:
                target_dt = datetime.combine(target_date, datetime.min.time())
            hours_until = (target_dt - now_dt).total_seconds() / 3600

            # Filter by urgency
            if urgency == "urgent" and hours_until >= 24:
                skipped += 1
                continue
            if urgency == "normal" and hours_until < 24:
                skipped += 1
                continue

            # Check last_scanned for rate limiting
            if urgency == "normal" and w.get("last_scanned"):
                last = w["last_scanned"]
                if isinstance(last, str):
                    last = datetime.fromisoformat(last)
                elapsed = (now_dt - last.replace(tzinfo=None)).total_seconds()
                if elapsed < 25 * 60:  # 25 min buffer for 30 min schedule
                    skipped += 1
                    continue

            scannable.append(w)

        if not scannable:
            log.info("scan(%s): nothing to scan (skipped=%d)", urgency, skipped)
            return {"matches": 0, "booked": [], "notified": [], "scanned": 0, "skipped": skipped}

        # Group by (location_key, target_date, party_size)
        groups = {}
        for w in scannable:
            td = w["target_date"]
            date_str = td.strftime("%Y-%m-%d") if hasattr(td, "strftime") else str(td)
            key = (w["location_key"], date_str, w["party_size"])
            groups.setdefault(key, []).append(w)

        # Fetch inventory in parallel
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
                    ts = w["time_start"]
                    te = w["time_end"]
                    start_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)
                    end_str = te.strftime("%H:%M") if hasattr(te, "strftime") else str(te)
                    start_min = _time_str_to_minutes(start_str)
                    end_min = _time_str_to_minutes(end_str)
                    for slot in slots:
                        slot_min = _time_str_to_minutes(slot["time"])
                        if start_min <= slot_min <= end_min:
                            matches.append({"watch": w, "slot": slot, "location_key": loc_key})

        # Process matches
        booked = []
        notified = []
        for m in matches:
            w = m["watch"]
            slot = m["slot"]
            loc = LOCATIONS[m["location_key"]]
            loc_name = loc.get("name", m["location_key"])
            was_booked = False

            # Auto-book
            if w["auto_book"] and w.get("book_first_name") and w.get("book_phone"):
                if _auto_book(w, slot, loc):
                    cur.execute("UPDATE watches SET status='booked', booked_at=NOW() WHERE id=%s", (w["id"],))
                    booked.append({"watch_id": w["id"], "slot": slot["time"], "location": loc_name})
                    was_booked = True

            # Notify
            notify_slot_found(conn, w, slot, loc_name, was_booked)

            # Update notified_at
            if not was_booked:
                cur.execute("UPDATE watches SET notified_at=NOW() WHERE id=%s", (w["id"],))
            notified.append({"watch_id": w["id"], "slot": slot["time"], "location": loc_name})

        # Update last_scanned
        watch_ids = [w["id"] for w in scannable]
        if watch_ids:
            cur.execute(
                "UPDATE watches SET last_scanned=NOW() WHERE id = ANY(%s)",
                (watch_ids,)
            )

        conn.commit()

        result = {
            "matches": len(matches),
            "booked": booked,
            "notified": notified,
            "scanned": len(scannable),
            "skipped": skipped,
        }
        log.info(
            "scan(%s): scanned=%d skipped=%d matches=%d booked=%d",
            urgency, result["scanned"], result["skipped"],
            result["matches"], len(booked),
        )
        return result

    except Exception:
        log.exception("scan_watches failed")
        conn.rollback()
        return {"matches": 0, "booked": [], "notified": [], "scanned": 0, "skipped": 0, "error": True}
    finally:
        conn.close()


def scan_urgent():
    """Scan watches with target_date < 24h away."""
    scan_watches(urgency="urgent")


def scan_normal():
    """Scan watches with target_date >= 24h away."""
    scan_watches(urgency="normal")


def expire_watches():
    """Set status='expired' for past-date watches."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        today_str = datetime.now().strftime("%Y-%m-%d")
        cur.execute("UPDATE watches SET status='expired' WHERE status='active' AND target_date < %s", (today_str,))
        count = cur.rowcount
        conn.commit()
        if count:
            log.info("Expired %d watches", count)
    except Exception:
        log.exception("expire_watches failed")
        conn.rollback()
    finally:
        conn.close()


def cleanup_sessions():
    """Delete expired sessions."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE expires_at < NOW()")
        count = cur.rowcount
        conn.commit()
        if count:
            log.info("Cleaned up %d expired sessions", count)
    except Exception:
        log.exception("cleanup_sessions failed")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    log.info("🔍 Houston's Worker starting...")

    # Verify DB connection
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM watches WHERE status='active'")
        row = cur.fetchone()
        log.info("Active watches: %s", row["c"])
        conn.close()
    except Exception:
        log.exception("Failed to connect to database")
        raise

    scheduler = BlockingScheduler()

    # Tiered scanning
    scheduler.add_job(scan_urgent, "interval", minutes=10, id="scan_urgent",
                      next_run_time=datetime.now() + timedelta(seconds=30))
    scheduler.add_job(scan_normal, "interval", minutes=30, id="scan_normal",
                      next_run_time=datetime.now() + timedelta(seconds=60))

    # Maintenance
    scheduler.add_job(expire_watches, "interval", hours=1, id="expire_watches")
    scheduler.add_job(cleanup_sessions, "interval", hours=6, id="cleanup_sessions")

    log.info("🔍 Scheduler started: urgent=10min, normal=30min, expire=1h, cleanup=6h")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Worker shutting down")
