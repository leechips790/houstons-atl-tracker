# Migration Plan: Railway → Render

## Pre-Migration (Day -3 to -1)

### 1. Set up Render infrastructure
- Create Render account, connect GitHub repo
- Deploy `render.yaml` blueprint → provisions Postgres, Redis, web, worker
- Set all env vars (SMTP, Twilio, Google OAuth, etc.)
- Run `migrations/001_initial.sql` against Render Postgres
- Verify web service starts and serves `/api/locations`

### 2. Set up email/SMS
- Configure SendGrid (or Gmail App Password) for SMTP
- Verify Twilio sends from +18665746012
- Send test notifications to confirm both channels work

### 3. Rewrite `server.py` for Postgres
- Replace `sqlite3` with `asyncpg` connection pool
- Replace all `?` param placeholders with `$1, $2, ...`
- Replace `datetime('now')` with `NOW()`
- Replace `last_insert_rowid()` with `RETURNING id`
- Replace `gog` CLI calls with SMTP + Twilio enqueue
- Remove `/data/houstons.db` path logic
- Test locally against a local Postgres instance

### 4. Write `worker.py`
- Extract `do_scan_watches()` and `scanner_loop()` from server.py
- Use `psycopg2` (sync) for DB access
- Use `APScheduler` for cron-like scan scheduling
- Use `rq` for notification job processing
- Test locally

## Migration Day (Day 0)

### Step 1: Export SQLite data (5 min)
```bash
# SSH into Railway or download houstons.db
# On local machine with the .db file:
sqlite3 houstons.db ".mode csv" ".headers on" \
  ".output users.csv" "SELECT * FROM users;" \
  ".output sessions.csv" "SELECT * FROM sessions;" \
  ".output watches.csv" "SELECT * FROM watches;" \
  ".output alerts.csv" "SELECT * FROM alerts;" \
  ".output wait_reports.csv" "SELECT * FROM wait_reports;" \
  ".output feedback.csv" "SELECT * FROM feedback;" \
  ".output scan_history.csv" "SELECT * FROM scan_history;" \
  ".output slot_drops.csv" "SELECT * FROM slot_drops;"
```

### Step 2: Import into Postgres (10 min)
```bash
# Use psql with Render's external connection string
export PGCONN="postgres://houstons:xxx@xxx.render.com:5432/houstons"

# For each table, use \copy
psql $PGCONN -c "\copy users(id,email,password_hash,name,google_id,picture,phone,created_at,last_login) FROM 'users.csv' CSV HEADER"
psql $PGCONN -c "\copy watches(id,user_id,location_key,party_size,target_date,time_start,time_end,auto_book,book_first_name,book_last_name,book_email,book_phone,status,created_at,notified_at,booked_at,last_scanned) FROM 'watches.csv' CSV HEADER"
# ... repeat for other tables

# Reset sequences to max(id)+1
psql $PGCONN -c "SELECT setval('users_id_seq', (SELECT COALESCE(MAX(id),0)+1 FROM users));"
psql $PGCONN -c "SELECT setval('watches_id_seq', (SELECT COALESCE(MAX(id),0)+1 FROM watches));"
# ... repeat for all tables with SERIAL ids
```

### Step 3: Verify data integrity (5 min)
```bash
psql $PGCONN -c "SELECT COUNT(*) FROM users;"
psql $PGCONN -c "SELECT COUNT(*) FROM watches WHERE status='active';"
# Compare counts with SQLite
```

### Step 4: Deploy new code to Render (5 min)
- Push the Postgres-compatible `server.py` + `worker.py` to GitHub
- Render auto-deploys from GitHub
- Verify web service is healthy: `curl https://houstons-web.onrender.com/api/locations`
- Verify worker is running (check Render logs)

### Step 5: DNS cutover (5 min)
```
# In Cloudflare DNS for gethoustons.bar:
# Change CNAME from Railway → Render

# Old: gethoustons.bar → CNAME → xxx.railway.app
# New: gethoustons.bar → CNAME → houstons-web.onrender.com

# Cloudflare proxy (orange cloud) stays ON for CDN + SSL
```

### Step 6: Verify (10 min)
- Visit https://gethoustons.bar — confirm page loads
- Sign in with Google — confirm auth works
- Create a test watch — confirm it saves
- Check worker logs — confirm scanner runs
- Wait for scan cycle — confirm notification sends

## Post-Migration (Day +1 to +3)

### Monitoring
- Check Render dashboard for errors
- Verify email notifications are delivering (check SendGrid dashboard)
- Monitor Postgres connection count (should stay under pool max)
- Watch worker memory usage

### Rollback Plan
If something is critically broken:
1. Cloudflare DNS: change CNAME back to Railway
2. Railway is still running with the old SQLite — instant rollback
3. Any watches created on Render during the window are lost (acceptable for <1hr cutover)

### Cleanup (Day +7)
- Delete Railway deployment
- Remove SQLite-related code paths
- Remove `gog` CLI references
- Archive `scan_push.py` (no longer needed — worker handles scanning)

## Zero-Downtime Strategy

The key insight: **Railway stays running during the entire migration.** The cutover is just a DNS change (Cloudflare propagates in <30s with proxy mode). The gap between "DNS points to Render" and "Render is ready" is zero because we deploy and verify Render *before* touching DNS.

Data written to Railway between export and DNS cutover is lost. To minimize this:
- Do the export + import + DNS change in a single 20-minute window
- Ideally during low traffic (weekday morning, 8-9 AM ET)
- Active watches from that window can be re-created by users
