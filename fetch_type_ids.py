#!/usr/bin/env python3
import urllib.request
import json
import time

LOCATIONS = {
    "houston_s_bergen_county": 278171,
    "houston_s_boca_raton": 278275,
    "houston_s_saint_charles": 278261,
    "houston_s_north_miami_beach": 278271,
    "houston_s_pasadena": 278270,
    "houston_s_pompano_beach": 278276,
    "hillstone_phoenix": 278170,
    "hillstone_bal_harbour": 278242,
    "hillstone_coral_gables": 278173,
    "hillstone_winter_park": 278257,
    "hillstone_denver": 278243,
    "hillstone_park_cities": 278264,
    "hillstone_houston": 278244,
    "hillstone_park_avenue": 278278,
    "hillstone_embarcadero": 278172,
    "hillstone_santa_monica": 278267,
    "rd_kitchen_newport_beach": 278273,
    "rd_kitchen_santa_monica": 278268,
    "rd_kitchen_yountville": 278254,
    "honor_bar_dallas": 278262,
    "honor_bar_montecito": 278265,
    "honor_bar_palm_beach": 279077,
    "bandera_corona_del_mar": 278245,
    "south_beverly_grill": 278269,
    "cherry_creek_grill": 278239,
    "rutherford_grill": 278253,
    "los_altos_grill": 278255,
    "east_hampton_grill": 278240,
}

search_ts = int(time.time() * 1000) + 86400000

results = {}
for key, mid in LOCATIONS.items():
    url = f"https://loyaltyapi.wisely.io/v2/web/reservations/inventory?merchant_id={mid}&party_size=2&search_ts={search_ts}&show_reservation_types=1&limit=5"
    req = urllib.request.Request(url, headers={
        "Origin": "https://reservations.getwisely.com",
        "Referer": "https://reservations.getwisely.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        types = data.get("types", [])
        if types:
            tid = types[0]["reservation_type_id"]
            results[key] = tid
            print(f"{key}: {tid}")
        else:
            print(f"{key}: NO TYPES FOUND")
    except Exception as e:
        print(f"{key}: ERROR - {e}")

print("\n--- RESULTS ---")
for k, v in results.items():
    print(f'"{k}": {v}')
