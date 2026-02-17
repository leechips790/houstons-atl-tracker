#!/usr/bin/env python3
"""
Houston's ATL Bar Wait Time Caller (Bland.ai)
2 random calls per location between 6-8 PM EST, every day.
"""

import os
import sys
import json
import random
import re
import time
import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bland_caller")

# ─── CONFIG ───────────────────────────────────────────────────────────────────

BLAND_API_KEY = os.environ.get("BLAND_API_KEY", "")
DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent / "houstons.db"))
API_BASE = os.environ.get("API_BASE", "https://www.gethoustons.bar")
EST = ZoneInfo("America/New_York")

LOCATIONS = {
    "Peachtree": {
        "phone": "+14048468005",
        "merchant_id": 278258,
    },
    "West Paces": {
        "phone": "+14048464455",
        "merchant_id": 278259,
    },
}

# ─── VOICE & SCRIPT VARIANCE ─────────────────────────────────────────────────

VOICES = ["mason", "josh", "matt", "ryan"]

TASKS = [
    "You are calling a restaurant to ask about bar wait times. When someone answers, say: '{greeting} {filler}{question}' Then listen to their response. Once they give you a wait time or answer, say '{thanks}' and end the call. Be natural and conversational. Do NOT identify yourself as AI.",
]

GREETINGS = ["Hi there,", "Hey,", "Hi,", "Hello,", "Hey there,"]
FILLERS = ["", "um, ", "so, ", "yeah so, ", "", ""]
QUESTIONS = [
    "how long is the wait at the bar right now?",
    "what's the bar wait looking like tonight?",
    "do you know the current wait for bar seating?",
    "what's the wait time if we just walk in for the bar?",
    "I was wondering how long the bar wait is?",
    "any idea what the wait is at the bar currently?",
]
THANKS = [
    "Thanks so much!", "Awesome, thank you!", "Great, thanks!",
    "Perfect, appreciate it!", "Thank you!", "Cool, thanks!",
]


def build_task():
    """Generate a natural task prompt with variance."""
    greeting = random.choice(GREETINGS)
    filler = random.choice(FILLERS)
    question = random.choice(QUESTIONS)
    thanks = random.choice(THANKS)
    template = random.choice(TASKS)
    return template.format(greeting=greeting, filler=filler, question=question, thanks=thanks)


# ─── WAIT TIME PARSING ────────────────────────────────────────────────────────

WAIT_PATTERNS = [
    (r"(\d+)\s*(?:to|[-–])\s*(\d+)\s*min", lambda m: (int(m.group(1)) + int(m.group(2))) // 2),
    (r"about\s+(?:an?\s+)?hour", lambda m: 60),
    (r"(?:about|around|approximately)\s+(\d+)\s*min", lambda m: int(m.group(1))),
    (r"(\d+)\s*min", lambda m: int(m.group(1))),
    (r"no wait|right away|immediately|walk.?in|no line|seats? available|come on in", lambda m: 0),
    (r"(\d+)\s*hour", lambda m: int(m.group(1)) * 60),
    (r"half\s*(?:an?\s*)?hour", lambda m: 30),
    (r"fifteen|15", lambda m: 15),
    (r"twenty|20", lambda m: 20),
    (r"thirty|30", lambda m: 30),
    (r"forty.five|45", lambda m: 45),
]


def parse_wait_time(transcript):
    """Extract wait time in minutes from transcript."""
    if not transcript:
        return None
    text = transcript.lower()
    for pattern, extractor in WAIT_PATTERNS:
        match = re.search(pattern, text)
        if match:
            minutes = extractor(match)
            if 0 <= minutes <= 180:
                return minutes
    return None


# ─── BLAND.AI CALL ────────────────────────────────────────────────────────────

def make_call(location_name, location_info):
    """Place a call via Bland.ai and return call_id."""
    task = build_task()
    voice = random.choice(VOICES)

    log.info(f"Calling {location_name} ({location_info['phone']}) with voice={voice}")

    resp = requests.post(
        "https://api.bland.ai/v1/calls",
        headers={
            "authorization": BLAND_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "phone_number": location_info["phone"],
            "task": task,
            "voice": voice,
            "wait_for_greeting": True,
            "max_duration": 60,
            "record": True,
        },
        timeout=15,
    )

    data = resp.json()
    if data.get("status") == "success":
        call_id = data["call_id"]
        log.info(f"Call queued: {call_id}")
        return call_id
    else:
        log.error(f"Bland.ai error: {data}")
        return None


def get_call_result(call_id, max_wait=120):
    """Poll Bland.ai for call result."""
    for i in range(max_wait // 5):
        time.sleep(5)
        resp = requests.get(
            f"https://api.bland.ai/v1/calls/{call_id}",
            headers={"authorization": BLAND_API_KEY},
            timeout=10,
        )
        data = resp.json()
        status = data.get("status") or data.get("queue_status")

        if status in ("completed", "failed", "error"):
            return data
        if data.get("completed"):
            return data

        log.info(f"  Waiting... status={status} ({(i+1)*5}s)")

    log.warning(f"Timed out waiting for call {call_id}")
    return None


# ─── DATABASE ─────────────────────────────────────────────────────────────────

def save_call_result(location_name, call_data):
    """Save call result to SQLite and push to API."""
    if not call_data:
        return None

    transcript = ""
    concatenated = call_data.get("concatenated_transcript", "")
    if concatenated:
        transcript = concatenated
    elif call_data.get("transcripts"):
        transcript = " ".join(t.get("text", "") for t in call_data["transcripts"])

    wait_minutes = parse_wait_time(transcript)

    log.info(f"  Transcript: {transcript[:200]}")
    log.info(f"  Parsed wait time: {wait_minutes} min")

    # Save to local DB
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS call_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT,
                call_id TEXT,
                timestamp TEXT,
                transcript TEXT,
                wait_minutes INTEGER,
                status TEXT,
                raw_json TEXT
            )
        """)
        conn.execute(
            "INSERT INTO call_logs (location, call_id, timestamp, transcript, wait_minutes, status, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                location_name,
                call_data.get("call_id", ""),
                datetime.now(EST).isoformat(),
                transcript,
                wait_minutes,
                call_data.get("status", "unknown"),
                json.dumps(call_data)[:5000],
            ),
        )
        conn.commit()
        conn.close()
        log.info(f"  Saved to DB")
    except Exception as e:
        log.error(f"  DB error: {e}")

    # Push to API
    if wait_minutes is not None:
        try:
            requests.post(
                f"{API_BASE}/api/waittimes",
                json={
                    "location": location_name,
                    "wait_minutes": wait_minutes,
                    "source": "bland",
                },
                timeout=10,
            )
            log.info(f"  Pushed to API: {location_name} = {wait_minutes} min")
        except Exception as e:
            log.error(f"  API push error: {e}")

    return wait_minutes


# ─── MAIN COMMANDS ────────────────────────────────────────────────────────────

def call_location(loc_name):
    """Call one location and get result."""
    if loc_name not in LOCATIONS:
        log.error(f"Unknown location: {loc_name}. Options: {list(LOCATIONS.keys())}")
        return

    call_id = make_call(loc_name, LOCATIONS[loc_name])
    if not call_id:
        return

    result = get_call_result(call_id)
    wait = save_call_result(loc_name, result)
    return wait


def call_both():
    """Call both locations."""
    for loc in LOCATIONS:
        call_location(loc)
        # Small gap between calls
        time.sleep(random.randint(5, 15))


def schedule_info():
    """Show what tonight's random call times would be."""
    now = datetime.now(EST)
    today = now.date()

    print(f"Current time: {now.strftime('%I:%M %p EST')}")
    print(f"Call window: 6:00 PM – 8:00 PM EST")
    print(f"Calls per location: 2\n")

    for loc in LOCATIONS:
        times = generate_call_times(today)
        print(f"{loc}:")
        for t in times:
            print(f"  {t.strftime('%I:%M %p')}")
    print()


def generate_call_times(date):
    """Generate 2 random call times between 6-8 PM for a given date."""
    window_start = datetime(date.year, date.month, date.day, 18, 0, tzinfo=EST)  # 6 PM
    window_end = datetime(date.year, date.month, date.day, 20, 0, tzinfo=EST)    # 8 PM
    window_seconds = int((window_end - window_start).total_seconds())

    # Pick 2 random times, at least 20 min apart
    for _ in range(100):
        t1 = window_start + timedelta(seconds=random.randint(0, window_seconds))
        t2 = window_start + timedelta(seconds=random.randint(0, window_seconds))
        if abs((t2 - t1).total_seconds()) >= 1200:  # 20 min apart minimum
            return sorted([t1, t2])

    # Fallback: 6:20 and 7:30
    return [
        window_start + timedelta(minutes=20),
        window_start + timedelta(minutes=90),
    ]


def daemon():
    """Run as daemon — waits for call windows and makes calls."""
    log.info("Starting Bland caller daemon")
    log.info(f"Window: 6-8 PM EST, 2 calls/location/night")

    while True:
        now = datetime.now(EST)
        today = now.date()

        # Generate today's random call times
        call_times = generate_call_times(today)
        log.info(f"Today's call times: {[t.strftime('%I:%M %p') for t in call_times]}")

        for call_time in call_times:
            # Wait until call time
            wait_seconds = (call_time - datetime.now(EST)).total_seconds()
            if wait_seconds > 0:
                log.info(f"Sleeping {wait_seconds/60:.0f} min until {call_time.strftime('%I:%M %p')}")
                time.sleep(wait_seconds)
            elif wait_seconds < -300:  # More than 5 min past
                log.info(f"Skipping past call time {call_time.strftime('%I:%M %p')}")
                continue

            # Call both locations
            log.info(f"=== Calling round at {datetime.now(EST).strftime('%I:%M %p')} ===")
            call_both()

        # Sleep until tomorrow 5:55 PM
        tomorrow = today + timedelta(days=1)
        next_start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 17, 55, tzinfo=EST)
        sleep_seconds = (next_start - datetime.now(EST)).total_seconds()
        if sleep_seconds > 0:
            log.info(f"Done for tonight. Sleeping until tomorrow {next_start.strftime('%I:%M %p')}")
            time.sleep(sleep_seconds)
        else:
            time.sleep(60)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not BLAND_API_KEY:
        # Try loading from .env file
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("BLAND_API_KEY="):
                    BLAND_API_KEY = line.split("=", 1)[1].strip()
                    break

    if not BLAND_API_KEY:
        print("ERROR: BLAND_API_KEY not set")
        sys.exit(1)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "call":
        loc = sys.argv[2] if len(sys.argv) > 2 else "Peachtree"
        call_location(loc)
    elif cmd == "call-both":
        call_both()
    elif cmd == "schedule":
        schedule_info()
    elif cmd == "daemon":
        daemon()
    elif cmd == "test-script":
        for _ in range(5):
            task = build_task()
            print(task[:120])
            print()
    else:
        print("Usage: bland_caller.py <command>")
        print("  call <location>  - Call one location (Peachtree|West Paces)")
        print("  call-both        - Call both locations now")
        print("  schedule         - Show tonight's random call times")
        print("  daemon           - Run as daemon (continuous)")
        print("  test-script      - Preview generated scripts")
