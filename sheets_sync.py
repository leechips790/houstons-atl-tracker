#!/usr/bin/env python3
"""
Google Sheets sync module for Houston's ATL Tracker.

Manages the "Houston's ATL - Watch Tracker" spreadsheet.
Set env vars:
  GOOGLE_SHEETS_CREDS  - base64-encoded service account JSON (preferred for Render)
  GOOGLE_SHEETS_KEY_PATH - path to service account JSON file (local fallback)
  GOOGLE_SHEETS_ID     - Google Sheet ID
"""

import base64
import json
import logging
import os
import threading
from datetime import datetime

log = logging.getLogger("houstons.sheets")

# ------------------------------------------------------------------
# Lazy client initialization
# ------------------------------------------------------------------

_client = None
_worksheet = None
_client_lock = threading.Lock()


def _get_worksheet():
    """Return the gspread worksheet, lazily initialized."""
    global _client, _worksheet

    sheet_id = os.environ.get("GOOGLE_SHEETS_ID", "")
    if not sheet_id:
        return None  # silently skip if not configured

    with _client_lock:
        if _worksheet is not None:
            return _worksheet

        try:
            import gspread
            from google.oauth2.service_account import Credentials

            SCOPES = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]

            # Prefer base64-encoded JSON (Render-compatible)
            creds_b64 = os.environ.get("GOOGLE_SHEETS_CREDS", "")
            key_path = os.environ.get("GOOGLE_SHEETS_KEY_PATH", "")

            if creds_b64:
                creds_dict = json.loads(base64.b64decode(creds_b64))
                creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            elif key_path and os.path.exists(key_path):
                creds = Credentials.from_service_account_file(key_path, scopes=SCOPES)
            else:
                log.warning("sheets_sync: no credentials configured (GOOGLE_SHEETS_CREDS or GOOGLE_SHEETS_KEY_PATH)")
                return None

            gc = gspread.authorize(creds)
            sh = gc.open_by_key(sheet_id)
            _worksheet = sh.sheet1
            log.info("sheets_sync: connected to sheet %s", sheet_id)

        except Exception as e:
            log.error("sheets_sync: failed to initialize: %s", e)
            return None

    return _worksheet


# ------------------------------------------------------------------
# Column headers (must match sheet order)
# ------------------------------------------------------------------
# ID | User | Email | Phone | Location | Party Size | Date | Time Window | Auto-Book | Created | Status | Worked?
HEADERS = ["ID", "User", "Email", "Phone", "Location", "Party Size",
           "Date", "Time Window", "Auto-Book", "Created", "Status", "Worked?"]


def _run_in_thread(fn, *args, **kwargs):
    """Fire-and-forget: run fn in a background thread."""
    t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
    t.start()


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def append_watch(watch_id, user_name, email, phone, location, party_size,
                 target_date, time_start, time_end, auto_book, created_at=None):
    """Append a new watch row to the tracker sheet (non-blocking)."""
    def _do():
        ws = _get_worksheet()
        if ws is None:
            return
        try:
            created_str = (created_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
            row = [
                str(watch_id),
                user_name or "",
                email or "",
                phone or "",
                location or "",
                str(party_size),
                str(target_date),
                f"{time_start}-{time_end}",
                "Y" if auto_book else "N",
                created_str,
                "Active",
                "Pending",
            ]
            ws.append_row(row, value_input_option="USER_ENTERED")
            log.info("sheets_sync: appended watch %s", watch_id)
        except Exception as e:
            log.error("sheets_sync: append_watch failed for %s: %s", watch_id, e)

    _run_in_thread(_do)


def update_watch_status(watch_id, status, worked):
    """
    Find the row for watch_id and update Status + Worked? columns (non-blocking).

    status: str  e.g. "Notified", "Booked", "Expired", "Cancelled"
    worked: str  "Y" or "N" or "Pending"
    """
    def _do():
        ws = _get_worksheet()
        if ws is None:
            return
        try:
            # Find the row by watch ID in column A
            cell = ws.find(str(watch_id), in_column=1)
            if cell is None:
                log.warning("sheets_sync: watch %s not found in sheet", watch_id)
                return
            row = cell.row
            # Status is col 11 (K), Worked? is col 12 (L)
            ws.update_cell(row, 11, status)
            ws.update_cell(row, 12, worked)
            log.info("sheets_sync: updated watch %s → status=%s worked=%s", watch_id, status, worked)
        except Exception as e:
            log.error("sheets_sync: update_watch_status failed for %s: %s", watch_id, e)

    _run_in_thread(_do)


def mark_notified(watch_id):
    """Mark a watch as notified (slot found, not auto-booked)."""
    update_watch_status(watch_id, "Notified", "Y")


def mark_booked(watch_id):
    """Mark a watch as auto-booked."""
    update_watch_status(watch_id, "Booked", "Y")


def mark_expired(watch_id):
    """Mark a watch as expired (no slot found before date passed)."""
    update_watch_status(watch_id, "Expired", "N")


def mark_cancelled(watch_id):
    """Mark a watch as cancelled by user."""
    update_watch_status(watch_id, "Cancelled", "N")
