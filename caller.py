#!/usr/bin/env python3
"""
Houston's ATL Bar Wait Time Caller
Automated calls to both Houston's locations to check bar wait times.
Uses Twilio for calls, ElevenLabs for natural TTS, Whisper for transcription.
"""

import os
import sys
import json
import random
import time
import logging
import re
import tempfile
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Optional imports (graceful fallback)
try:
    from twilio.rest import Client as TwilioClient
    from twilio.twiml.voice_response import VoiceResponse
    HAS_TWILIO = True
except ImportError:
    HAS_TWILIO = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("caller")

# ─── CONFIG ───────────────────────────────────────────────────────────────────

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent / "houstons.db"))
API_BASE = os.environ.get("API_BASE", "https://www.gethoustons.bar")

# Twilio
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_PHONE_FROM", "")  # Your Twilio number

# ElevenLabs
ELEVEN_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

# Houston's phone numbers
LOCATIONS = {
    "Peachtree": {
        "phone": "+14048468005",  # Houston's Peachtree
        "merchant_id": 278258,
    },
    "West Paces": {
        "phone": "+14048464455",  # Houston's West Paces
        "merchant_id": 278259,
    },
}

# ─── VOICE PERSONAS ───────────────────────────────────────────────────────────

VOICES = [
    {
        "name": "Rachel",
        "eleven_id": "21m00Tcm4TlvDq8ikWAM",  # Rachel - warm female
        "style": "friendly",
    },
    {
        "name": "Josh",
        "eleven_id": "TxGEqnHWrfWFTfGW9XjX",  # Josh - casual male
        "style": "casual",
    },
    {
        "name": "Bella",
        "eleven_id": "EXAVITQu4vr4xnSDxMaL",  # Bella - young female
        "style": "upbeat",
    },
    {
        "name": "Sam",
        "eleven_id": "yoZ06aMxZJJ28mfd3POQ",  # Sam - chill male
        "style": "laid_back",
    },
]

# ─── SCRIPT VARIANTS ──────────────────────────────────────────────────────────

GREETINGS = [
    "Hi there,",
    "Hey,",
    "Hi,",
    "Hello,",
    "Hey there,",
]

QUESTIONS = [
    "how long is the wait at the bar right now?",
    "what's the bar wait looking like tonight?",
    "do you know the current wait for bar seating?",
    "quick question — how long for the bar right now?",
    "what's the wait time if we just walk in for the bar?",
    "I was wondering how long the bar wait is?",
    "any idea what the wait is at the bar currently?",
]

FILLERS_PRE = [
    "",
    "um, ",
    "yeah so, ",
    "so, ",
    "",
    "",
]

THANKS = [
    "Thanks so much!",
    "Awesome, thank you!",
    "Great, thanks!",
    "Perfect, appreciate it!",
    "Thank you!",
    "Cool, thanks!",
]


def build_script():
    """Generate a natural-sounding script with variance."""
    greeting = random.choice(GREETINGS)
    filler = random.choice(FILLERS_PRE)
    question = random.choice(QUESTIONS)
    thanks = random.choice(THANKS)
    return f"{greeting} {filler}{question}", thanks


# ─── ELEVENLABS TTS ───────────────────────────────────────────────────────────

def generate_tts(text, voice_id, output_path):
    """Generate speech audio using ElevenLabs API."""
    if not ELEVEN_API_KEY:
        log.warning("No ElevenLabs API key, using Twilio TTS fallback")
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json",
    }
    data = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {
            "stability": 0.4 + random.random() * 0.2,  # 0.4-0.6 variance
            "similarity_boost": 0.7 + random.random() * 0.15,
            "style": random.random() * 0.3,  # slight style variance
        },
    }

    resp = requests.post(url, headers=headers, json=data, timeout=15)
    if resp.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(resp.content)
        log.info(f"Generated TTS: {len(resp.content)} bytes -> {output_path}")
        return output_path
    else:
        log.error(f"ElevenLabs error {resp.status_code}: {resp.text[:200]}")
        return None


# ─── CALL LOGIC ───────────────────────────────────────────────────────────────

def make_call(location_name, location_info, voice, script_question, script_thanks):
    """Place a call via Twilio and record the response."""
    if not HAS_TWILIO or not TWILIO_SID:
        log.error("Twilio not configured")
        return None

    client = TwilioClient(TWILIO_SID, TWILIO_AUTH)

    # Build TwiML
    # If we have ElevenLabs audio, host it; otherwise use Twilio's <Say>
    response = VoiceResponse()

    # Small pause before speaking (natural)
    response.pause(length=random.choice([1, 1, 2]))

    # Use Twilio's built-in TTS as fallback (or ElevenLabs via <Play>)
    twilio_voices = [
        "Polly.Joanna", "Polly.Matthew", "Polly.Salli", "Polly.Joey",
        "Polly.Kendra", "Polly.Justin",
    ]
    say_voice = random.choice(twilio_voices)

    response.say(script_question, voice=say_voice)

    # Record their answer (max 15 seconds)
    response.record(
        max_length=15,
        timeout=5,
        transcribe=True,
        transcribe_callback=None,  # We'll transcribe ourselves with Whisper
        play_beep=False,
        action=None,  # Hang up after recording
    )

    # Say thanks
    response.say(script_thanks, voice=say_voice)
    response.hangup()

    log.info(f"Calling {location_name}: {location_info['phone']}")
    log.info(f"Script: {script_question}")
    log.info(f"Voice: {say_voice}")

    try:
        call = client.calls.create(
            twiml=str(response),
            to=location_info["phone"],
            from_=TWILIO_FROM,
            record=True,
            recording_status_callback=None,
            timeout=30,
        )
        log.info(f"Call SID: {call.sid}")

        # Wait for call to complete
        for _ in range(60):  # Max 60 seconds
            time.sleep(2)
            call = client.calls(call.sid).fetch()
            if call.status in ("completed", "failed", "busy", "no-answer", "canceled"):
                break

        log.info(f"Call status: {call.status}, duration: {call.duration}s")

        result = {
            "call_id": call.sid,
            "phone": location_info["phone"],
            "status": call.status,
            "call_duration": call.duration,
            "answered_by": getattr(call, "answered_by", None),
        }

        # Get recording
        if call.status == "completed":
            recordings = client.recordings.list(call_sid=call.sid)
            if recordings:
                rec = recordings[0]
                result["recording_url"] = f"https://api.twilio.com{rec.uri.replace('.json', '.mp3')}"
                log.info(f"Recording: {result['recording_url']}")

                # Transcribe with Whisper if available
                transcript = transcribe_recording(result["recording_url"])
                if transcript:
                    result["transcript"] = transcript
                    wait_info = parse_wait_time(transcript)
                    result.update(wait_info)

        return result

    except Exception as e:
        log.error(f"Call failed: {e}")
        return {"status": "error", "error": str(e)}


# ─── TRANSCRIPTION ────────────────────────────────────────────────────────────

def transcribe_recording(recording_url):
    """Download recording and transcribe with Whisper."""
    try:
        # Download recording
        resp = requests.get(recording_url, auth=(TWILIO_SID, TWILIO_AUTH), timeout=30)
        if resp.status_code != 200:
            log.error(f"Failed to download recording: {resp.status_code}")
            return None

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name

        # Try local whisper first
        import subprocess
        result = subprocess.run(
            ["whisper", tmp_path, "--model", "base", "--output_format", "txt", "--language", "en"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            txt_path = tmp_path.replace(".mp3", ".txt")
            if os.path.exists(txt_path):
                transcript = open(txt_path).read().strip()
                os.unlink(txt_path)
                os.unlink(tmp_path)
                log.info(f"Transcript: {transcript}")
                return transcript

        os.unlink(tmp_path)
        log.warning("Whisper transcription failed")
        return None

    except Exception as e:
        log.error(f"Transcription error: {e}")
        return None


# ─── PARSE WAIT TIME ──────────────────────────────────────────────────────────

def parse_wait_time(transcript):
    """Extract wait time from transcript text."""
    text = transcript.lower()
    result = {}

    # Look for party/group count mentions
    count_patterns = [
        r'(\d+)\s*(?:parties|groups|people|tables)\s*(?:ahead|waiting|in line)',
        r'(?:about|around|roughly)\s*(\d+)\s*(?:parties|groups|people|tables)',
        r'(\d+)\s*(?:party|group)\s*wait',
    ]
    for pat in count_patterns:
        m = re.search(pat, text)
        if m:
            result["wait_count"] = int(m.group(1))
            break

    # Look for time mentions
    time_patterns = [
        r'(\d+)\s*(?:to|-)\s*(\d+)\s*(?:minutes|mins|min)',  # "30 to 45 minutes"
        r'(?:about|around|roughly|approximately)\s*(\d+)\s*(?:minutes|mins|min)',  # "about 30 minutes"
        r'(\d+)\s*(?:minutes|mins|min)',  # "30 minutes"
        r'(?:an?\s*)?hour',  # "an hour" = 60
        r'hour\s*(?:and\s*)?(?:a\s*)?half',  # "hour and a half" = 90
    ]

    for i, pat in enumerate(time_patterns):
        m = re.search(pat, text)
        if m:
            if i == 0:  # Range: take average
                result["wait_minutes"] = (int(m.group(1)) + int(m.group(2))) // 2
            elif "hour" in pat and "half" in pat:
                result["wait_minutes"] = 90
            elif "hour" in pat:
                result["wait_minutes"] = 60
            else:
                result["wait_minutes"] = int(m.group(1))
            break

    # No wait
    if any(phrase in text for phrase in ["no wait", "right away", "come on in", "seats available", "open seats"]):
        result["wait_count"] = 0
        result["wait_minutes"] = 0

    # Generate summary
    parts = []
    if "wait_count" in result:
        parts.append(f"{result['wait_count']} parties ahead")
    if "wait_minutes" in result:
        parts.append(f"~{result['wait_minutes']} min wait")
    if not parts and ("no wait" in text or result.get("wait_minutes") == 0):
        parts.append("No wait")

    result["summary"] = "; ".join(parts) if parts else "Could not determine wait time"
    return result


# ─── DATABASE ─────────────────────────────────────────────────────────────────

def save_call_result(location, result):
    """Save call result to local DB and POST to API."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS call_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        location TEXT, phone TEXT, call_id TEXT,
        wait_count INTEGER, wait_minutes INTEGER,
        transcript TEXT, summary TEXT,
        recording_url TEXT, call_duration INTEGER,
        answered_by TEXT, status TEXT,
        called_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.execute(
        """INSERT INTO call_logs
           (location, phone, call_id, wait_count, wait_minutes, transcript, summary,
            recording_url, call_duration, answered_by, status, called_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            location,
            result.get("phone"),
            result.get("call_id"),
            result.get("wait_count"),
            result.get("wait_minutes"),
            result.get("transcript"),
            result.get("summary"),
            result.get("recording_url"),
            result.get("call_duration"),
            result.get("answered_by"),
            result.get("status", "unknown"),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    log.info(f"Saved to DB: {location} - {result.get('summary', 'no summary')}")

    # Also POST to live API if running remotely
    if API_BASE:
        try:
            requests.post(
                f"{API_BASE}/api/calls",
                json={**result, "location": location, "called_at": datetime.now().isoformat()},
                timeout=10,
            )
        except Exception as e:
            log.warning(f"API POST failed: {e}")


# ─── SCHEDULING LOGIC ─────────────────────────────────────────────────────────

def should_call_now():
    """Check if current time is within calling hours."""
    now = datetime.now()
    hour = now.hour
    dow = now.weekday()  # 0=Mon, 6=Sun

    # Restaurant hours roughly:
    # Lunch: 11 AM - 2 PM (Mon-Sun)
    # Dinner: 4 PM - 10 PM (Mon-Sun)
    if 11 <= hour < 14:
        return "lunch"
    if 16 <= hour < 22:
        return "dinner"
    return None


def get_call_interval():
    """Get minutes between calls based on time/day."""
    now = datetime.now()
    hour = now.hour
    dow = now.weekday()

    # Peak: Fri/Sat dinner (6-8 PM) -> 20-30 min
    if dow in (4, 5) and 18 <= hour <= 20:
        return random.randint(20, 30)

    # Moderate peak: any dinner 5-9 PM -> 30-45 min
    if 17 <= hour <= 21:
        return random.randint(30, 45)

    # Off-peak lunch or early dinner -> 45-60 min
    return random.randint(45, 60)


def add_jitter(minutes, jitter_range=5):
    """Add random jitter to interval."""
    return minutes + random.randint(-jitter_range, jitter_range)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def call_location(location_name):
    """Make a single call to a location."""
    location_info = LOCATIONS[location_name]
    voice = random.choice(VOICES)
    script_q, script_thanks = build_script()

    full_script = f"{script_q}"
    log.info(f"═══ Calling {location_name} ═══")
    log.info(f"Voice: {voice['name']} ({voice['style']})")
    log.info(f"Script: {full_script}")

    result = make_call(location_name, location_info, voice, script_q, script_thanks)

    if result:
        save_call_result(location_name, result)
        return result
    return None


def call_both():
    """Call both locations with a stagger."""
    period = should_call_now()
    if not period:
        log.info("Outside calling hours, skipping")
        return

    log.info(f"Period: {period}")

    # Randomize order
    locations = list(LOCATIONS.keys())
    random.shuffle(locations)

    for loc in locations:
        call_location(loc)
        # Stagger: 2-5 min between locations
        if loc != locations[-1]:
            stagger = random.randint(120, 300)
            log.info(f"Staggering {stagger}s before next call...")
            time.sleep(stagger)


def daemon_mode():
    """Run continuously with smart intervals."""
    log.info("Starting caller daemon...")
    while True:
        period = should_call_now()
        if period:
            call_both()
            interval = add_jitter(get_call_interval())
            log.info(f"Next call in {interval} minutes")
            time.sleep(interval * 60)
        else:
            # Check every 15 min if we're in calling hours
            log.info("Outside calling hours, checking again in 15 min")
            time.sleep(900)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Houston's Bar Wait Time Caller")
    parser.add_argument("command", choices=["call", "call-both", "daemon", "test-script", "test-parse"],
                        help="Command to run")
    parser.add_argument("--location", "-l", choices=["Peachtree", "West Paces"],
                        help="Location to call (for 'call' command)")
    parser.add_argument("--text", "-t", help="Text to parse (for 'test-parse' command)")
    args = parser.parse_args()

    if args.command == "call":
        if not args.location:
            print("--location required for 'call' command")
            sys.exit(1)
        call_location(args.location)

    elif args.command == "call-both":
        call_both()

    elif args.command == "daemon":
        daemon_mode()

    elif args.command == "test-script":
        for _ in range(5):
            q, t = build_script()
            voice = random.choice(VOICES)
            print(f"[{voice['name']}] {q}")
            print(f"  -> {t}")
            print()

    elif args.command == "test-parse":
        if args.text:
            result = parse_wait_time(args.text)
            print(json.dumps(result, indent=2))
        else:
            # Test cases
            tests = [
                "The wait is about 30 minutes right now",
                "We have 5 parties ahead of you, about 45 minutes",
                "No wait at the bar, come on in",
                "It's about an hour wait tonight",
                "We're looking at 20 to 30 minutes",
                "There are 3 groups waiting, probably 15 minutes",
                "Hour and a half wait right now",
            ]
            for t in tests:
                result = parse_wait_time(t)
                print(f"  '{t}'")
                print(f"  -> {json.dumps(result)}\n")
