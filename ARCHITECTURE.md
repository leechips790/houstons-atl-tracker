# Architecture — Houston's Reservation Tracker on Render

## Overview

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Cloudflare  │────▶│  Web Service  │────▶│   Postgres   │
│  (DNS/CDN)   │     │  (aiohttp)    │     │  (Render)    │
└─────────────┘     └──────┬───────┘     └──────────────┘
                           │                      ▲
                           │ enqueue               │
                           ▼                      │
                    ┌──────────────┐              │
                    │    Redis     │              │
                    │  (Render)    │              │
                    └──────┬───────┘              │
                           │                      │
                           ▼                      │
                    ┌──────────────┐              │
                    │   Worker     │──────────────┘
                    │  (rq + apscheduler)
                    └──────┬───────┘
                           │
                    ┌──────┴───────┐
                    │  Notifications│
                    │  SMTP + Twilio│
                    └──────────────┘
```

## Components

### 1. Web Service (`server.py`)
- **Runtime:** Python 3.11 + aiohttp
- **Database:** asyncpg with connection pool (min=2, max=10)
- **Responsibilities:**
  - Serve `index.html` and static assets
  - All `/api/*` endpoints (unchanged routes)
  - Google OAuth verification
  - Wisely API proxy (inventory + booking)
  - Enqueue notification jobs to Redis when watches are created
- **No scanning logic** — that moves to the worker

### 2. Background Worker (`worker.py`)
- **Runtime:** Python 3.11 + `rq` (Redis Queue) + `apscheduler`
- **Database:** psycopg2 (sync, simpler for batch operations)
- **Scheduled jobs via APScheduler:**

  | Job | Interval | Description |
  |-----|----------|-------------|
  | `scan_urgent_watches` | 10 min | Watches with target_date < 24h away |
  | `scan_normal_watches` | 30 min | Watches with target_date >= 24h away |
  | `expire_watches` | 1 hour | Set status='expired' where target_date < today |
  | `cleanup_sessions` | 6 hours | Delete sessions where expires_at < now |

- **On-demand jobs (enqueued via Redis):**
  - `send_email_notification(user_id, watch_id, slot_info)`
  - `send_sms_notification(user_id, watch_id, slot_info)`
  - `auto_book_reservation(watch_id, slot_info)`

### 3. Scanner Logic (inside worker)

```python
def scan_watches(urgency='normal'):
    """
    1. Load active watches (filtered by urgency tier)
    2. Group by (location_key, target_date, party_size) to minimize API calls
    3. Fetch Wisely inventory for each group (ThreadPoolExecutor, max_workers=10)
    4. Match slots against watch time windows
    5. For matches:
       a. If auto_book → enqueue auto_book_reservation job
       b. Always → enqueue email notification job
       c. If user has phone → enqueue SMS notification job
    6. Update last_scanned timestamps
    7. Log to notification_log table
    """
```

**Deduplication:** Don't re-notify for the same watch+slot combo. Check `notification_log` before sending.

### 4. Notifications

#### Email (SMTP via SendGrid or Gmail)
- Library: `aiosmtplib` (in web) / `smtplib` (in worker)
- From: `notifications@gethoustons.bar` (or `leechips790@gmail.com`)
- Templates: HTML emails with slot details + book-now link
- Env vars: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`

#### SMS (Twilio)
- From: +18665746012 (existing Twilio number)
- Only for auto-book confirmations and urgent (<2h) slot matches
- Env vars: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`

### 5. Database Connection Strategy

| Component | Library | Pool |
|-----------|---------|------|
| Web service | asyncpg | async pool, min=2, max=10 |
| Worker | psycopg2 | sync, single connection per job |

### 6. Error Handling & Resilience

- **Wisely API failures:** Log and skip, retry on next scan cycle
- **Notification failures:** Retry 3x with exponential backoff (rq built-in)
- **DB connection drops:** asyncpg pool auto-reconnects
- **Worker crashes:** Render auto-restarts the process
- **Rate limiting:** Max 10 concurrent Wisely API calls; 1s delay between batches

### 7. Environment Variables

```
DATABASE_URL          # Render Postgres (auto-set)
REDIS_URL             # Render Redis (auto-set)
GOOGLE_CLIENT_ID      # Google OAuth client ID
PUSH_SCAN_KEY         # Key for push-scan endpoint
SMTP_HOST             # smtp.sendgrid.net or smtp.gmail.com
SMTP_PORT             # 587
SMTP_USER             # apikey (SendGrid) or email (Gmail)
SMTP_PASS             # SendGrid API key or Gmail app password
SMTP_FROM             # notifications@gethoustons.bar
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM_NUMBER    # +18665746012
ADMIN_EMAIL           # Kevin.mendel@gmail.com
NOTIFICATION_EMAIL    # leechips790@gmail.com
```

### 8. Logging

- Structured logging with Python `logging` module
- Worker logs scan results: `scanned=X skipped=Y matches=Z booked=W`
- Notification results logged to `notification_log` table
- Render captures stdout/stderr automatically

### 9. Key Differences from Current Architecture

| Aspect | Railway (current) | Render (new) |
|--------|-------------------|--------------|
| Database | SQLite file on /data volume | Managed Postgres |
| Scanner | Background thread in web process | Separate worker process |
| Email | `gog` CLI (local only) | SMTP (SendGrid/Gmail) |
| SMS | None | Twilio |
| Job queue | None | Redis + rq |
| Connection pooling | None (sqlite3) | asyncpg pool |
| Session expiry | Never | 30-day TTL + cleanup job |
