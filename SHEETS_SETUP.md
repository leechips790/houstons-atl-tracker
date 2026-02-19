# Google Sheets Sync Setup Summary

## ✅ Completed

1. **Google Sheet Created**
   - Title: "Houston's ATL - Watch Tracker"
   - URL: https://docs.google.com/spreadsheets/d/1hKePQ8hslMeHaUDO48oyDk3c_VVE0qCdFBPvsH9VND4
   - Worksheet: "Watches"
   - Headers: ID, User, Email, Phone, Location, Party Size, Date, Time Window, Auto-Book, Created, Status, Worked?

2. **Code Integration**
   - `sheets_sync.py` module created with async-safe background sync
   - `server_pg.py` updated:
     - Imports `sheets_sync`
     - Calls `sheets_sync.append_watch()` when watch created
     - Calls `sheets_sync.mark_cancelled()` when watch deleted
   - `worker.py` updated:
     - Calls `sheets_sync.mark_booked()` on successful auto-book
     - Calls `sheets_sync.mark_notified()` when notification sent
     - Calls `sheets_sync.mark_expired()` when watches expire

3. **Environment Variables Set**
   - Web service (srv-d6bk0hcr85hc73bcq810): ✅
   - Worker service (srv-d6bk0hkr85hc73bcq82g): ✅
   - `GOOGLE_SHEETS_ID`: 1hKePQ8hslMeHaUDO48oyDk3c_VVE0qCdFBPvsH9VND4
   - `GOOGLE_SHEETS_CREDS`: [base64-encoded service account JSON]

4. **Backfilled Existing Watches**
   - 2 active watches from database imported to sheet

5. **Git Commit & Deploy**
   - Commit: `37b88f6` - "feat: google sheets watch tracker sync"
   - Pushed to GitHub
   - Render auto-deploy triggered

## ⚠️ Manual Action Required

**Share with Kevin Mendel:**
The service account has writer permissions only and cannot share the sheet. The owner (leechips790@gmail.com) needs to:

1. Open https://docs.google.com/spreadsheets/d/1hKePQ8hslMeHaUDO48oyDk3c_VVE0qCdFBPvsH9VND4
2. Click "Share"
3. Add `kevin.mendel@gmail.com` with Editor access

## Current Permissions
- leechips790@gmail.com - owner
- houstons-sheets-sync@lee-chips-workspace.iam.gserviceaccount.com - writer

## Testing
Once deployed, create a new watch via the web UI. It should automatically appear in the Google Sheet within seconds.
