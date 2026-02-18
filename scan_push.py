#!/usr/bin/env python3
"""Scan all Houston's/Hillstone locations and push results to the Railway app cache."""

import json
import time
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

PUSH_URL = "https://www.gethoustons.bar/api/push-scan"
PUSH_KEY = "houstons_push_2026"

WISELY_HEADERS = {
    "Origin": "https://reservations.getwisely.com",
    "Referer": "https://reservations.getwisely.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

LOCATIONS = {
    "peachtree": {"merchant_id": 278258, "name": "Houston's - Peachtree"},
    "west_paces": {"merchant_id": 278259, "name": "Houston's - West Paces"},
    "houston_s_bergen_county": {"merchant_id": 278171, "name": "Houston's - Bergen County"},
    "houston_s_boca_raton": {"merchant_id": 278275, "name": "Houston's - Boca Raton"},
    "houston_s_saint_charles": {"merchant_id": 278261, "name": "Houston's - Saint Charles"},
    "houston_s_north_miami_beach": {"merchant_id": 278271, "name": "Houston's - North Miami Beach"},
    "houston_s_pasadena": {"merchant_id": 278270, "name": "Houston's - Pasadena"},
    "houston_s_pompano_beach": {"merchant_id": 278276, "name": "Houston's - Pompano Beach"},
    "scottsdale": {"merchant_id": 278256, "name": "Houston's - Scottsdale"},
    "hillstone_phoenix": {"merchant_id": 278170, "name": "Hillstone - Phoenix"},
    "hillstone_bal_harbour": {"merchant_id": 278242, "name": "Hillstone - Bal Harbour"},
    "hillstone_coral_gables": {"merchant_id": 278173, "name": "Hillstone - Coral Gables"},
    "hillstone_winter_park": {"merchant_id": 278257, "name": "Hillstone - Winter Park"},
    "hillstone_denver": {"merchant_id": 278243, "name": "Hillstone - Denver"},
    "hillstone_park_cities": {"merchant_id": 278264, "name": "Hillstone - Park Cities"},
    "hillstone_houston": {"merchant_id": 278244, "name": "Hillstone - Houston"},
    "hillstone_park_avenue": {"merchant_id": 278278, "name": "Hillstone - Park Avenue"},
    "hillstone_embarcadero": {"merchant_id": 278172, "name": "Hillstone - San Francisco"},
    "hillstone_santa_monica": {"merchant_id": 278267, "name": "Hillstone - Santa Monica"},
    "rd_kitchen_newport_beach": {"merchant_id": 278273, "name": "R+D Kitchen - Newport Beach"},
    "rd_kitchen_santa_monica": {"merchant_id": 278268, "name": "R+D Kitchen - Santa Monica"},
    "rd_kitchen_yountville": {"merchant_id": 278254, "name": "R+D Kitchen - Yountville"},
    "honor_bar_dallas": {"merchant_id": 278262, "name": "Honor Bar - Dallas"},
    "palm_beach_grill": {"merchant_id": 278274, "name": "Palm Beach Grill"},
    "bandera_corona_del_mar": {"merchant_id": 278245, "name": "Bandera - Corona del Mar"},
    "south_beverly_grill": {"merchant_id": 278269, "name": "South Beverly Grill"},
    "cherry_creek_grill": {"merchant_id": 278239, "name": "Cherry Creek Grill"},
    "rutherford_grill": {"merchant_id": 278253, "name": "Rutherford Grill"},
    "los_altos_grill": {"merchant_id": 278255, "name": "Los Altos Grill"},
    "east_hampton_grill": {"merchant_id": 278240, "name": "East Hampton Grill"},
}

PARTY_SIZES = [2, 3, 4]
DAYS_OUT = 21
ANCHOR_HOURS = [12, 17, 21]
MAX_WORKERS = 28

# Shared session for connection pooling
session = requests.Session()
session.headers.update(WISELY_HEADERS)


def fetch_slots(loc_key, loc, date_str, anchor_hour, party_size):
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=anchor_hour, minute=0)
    ts = int(dt.timestamp() * 1000)
    url = (
        f"https://loyaltyapi.wisely.io/v2/web/reservations/inventory"
        f"?merchant_id={loc['merchant_id']}&party_size={party_size}"
        f"&search_ts={ts}&show_reservation_types=1&limit=20"
    )
    try:
        resp = session.get(url, timeout=15)
        data = resp.json()
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
    except Exception as e:
        return (loc_key, date_str, [])


def scan_party_size(party_size):
    today = datetime.now()
    dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(DAYS_OUT)]

    results = {}
    for loc_key, loc in LOCATIONS.items():
        results[loc_key] = {"name": loc["name"], "merchant_id": loc["merchant_id"], "days": {d: {} for d in dates}}

    futures = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for loc_key, loc in LOCATIONS.items():
            for date_str in dates:
                for anchor_hour in ANCHOR_HOURS:
                    futures.append(pool.submit(fetch_slots, loc_key, loc, date_str, anchor_hour, party_size))

        done = 0
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
            done += 1
            if done % 200 == 0:
                print(f"    ...{done}/{len(futures)} requests done")

    return results, dates


def push_results(party_size, locations_data, dates):
    now = time.time()
    payload = {
        "party_size": party_size,
        "timestamp": now,
        "data": locations_data,
    }
    resp = requests.post(
        PUSH_URL,
        json=payload,
        headers={"X-Push-Key": PUSH_KEY},
        timeout=30,
    )
    return resp.json()


def main():
    total_start = time.time()
    for ps in PARTY_SIZES:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Scanning party_size={ps} across {len(LOCATIONS)} locations, {DAYS_OUT} days...")
        t0 = time.time()
        locations_data, dates = scan_party_size(ps)
        elapsed = time.time() - t0

        # Count available slots
        total_slots = 0
        for loc in locations_data.values():
            for day_slots in loc["days"].values():
                if isinstance(day_slots, list):
                    total_slots += sum(1 for s in day_slots if s.get("available"))

        print(f"  Scanned in {elapsed:.1f}s — {total_slots} available slots found")

        print(f"  Pushing to {PUSH_URL}...")
        try:
            result = push_results(ps, locations_data, dates)
            print(f"  Push response: {result}")
        except Exception as e:
            print(f"  Push FAILED: {e}")

    total_elapsed = time.time() - total_start
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] All done in {total_elapsed:.1f}s")


if __name__ == "__main__":
    main()
