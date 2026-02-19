"""Notifications module — SMTP email (SendGrid) + Twilio SMS with dedup."""

import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

log = logging.getLogger("houstons.notifications")

# SMTP config
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.sendgrid.net")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "apikey")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "notifications@gethoustons.bar")

# Twilio config
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "+18665746012")

# Admin / notification emails
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "Kevin.mendel@gmail.com")
NOTIFICATION_EMAIL = os.environ.get("NOTIFICATION_EMAIL", "leechips790@gmail.com")

# Test domains to skip
TEST_DOMAINS = ("@test.com", "@example.com", "@fake.com")


def is_test_email(email: str) -> bool:
    return any(email.lower().endswith(d) for d in TEST_DOMAINS)


def send_email(to: str, subject: str, body: str, html: str | None = None) -> bool:
    """Send email via SMTP (SendGrid). Returns True on success."""
    if not SMTP_PASS:
        log.warning("SMTP_PASS not set, skipping email to %s", to)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = SMTP_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        if html:
            msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to, msg.as_string())
        log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception:
        log.exception("Failed to send email to %s", to)
        return False


def send_sms(to: str, body: str) -> bool:
    """Send SMS via Twilio. Returns True on success."""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        log.warning("Twilio not configured, skipping SMS to %s", to)
        return False
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=body,
            from_=TWILIO_FROM_NUMBER,
            to=to,
        )
        log.info("SMS sent to %s: sid=%s", to, message.sid)
        return True
    except Exception:
        log.exception("Failed to send SMS to %s", to)
        return False


def log_notification(conn, watch_id: int | None, user_id: int | None,
                     channel: str, recipient: str, subject: str | None,
                     body: str, status: str = "sent", error_message: str | None = None):
    """Log a notification to the notification_log table (sync psycopg2 conn)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO notification_log
                   (watch_id, user_id, channel, recipient, subject, body, status, error_message)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (watch_id, user_id, channel, recipient, subject, body, status, error_message)
            )
        conn.commit()
    except Exception:
        log.exception("Failed to log notification")


def was_recently_notified(conn, watch_id: int, channel: str, minutes: int = 60) -> bool:
    """Check if a notification was already sent for this watch+channel recently."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM notification_log
                   WHERE watch_id = %s AND channel = %s AND status = 'sent'
                   AND created_at > NOW() - (%s * INTERVAL '1 minute')
                   LIMIT 1""",
                (watch_id, channel, minutes)
            )
            return cur.fetchone() is not None
    except Exception:
        log.exception("Failed to check notification dedup")
        return False


def notify_slot_found(conn, watch: dict, slot: dict, location_name: str, was_booked: bool = False):
    """Send email + SMS notifications for a found slot. Handles dedup."""
    user_email = watch.get("user_email", "")
    user_phone = watch.get("book_phone") or watch.get("user_phone", "")
    watch_id = watch["id"]
    user_id = watch["user_id"]
    action = "Auto-booked" if was_booked else "Available"

    body_text = (
        f"{action}! {location_name} on {watch['target_date']} at {slot['time']} "
        f"for party of {watch['party_size']}."
    )
    if not was_booked:
        body_text += "\n\nBook now at https://www.gethoustons.bar"

    subject = f"🍖 Houston's Slot {action}!"

    # Email
    if user_email and not is_test_email(user_email):
        if not was_recently_notified(conn, watch_id, "email"):
            ok = send_email(user_email, subject, body_text)
            log_notification(conn, watch_id, user_id, "email", user_email, subject,
                             body_text, "sent" if ok else "failed")

    # SMS
    if user_phone:
        if not was_recently_notified(conn, watch_id, "sms"):
            ok = send_sms(user_phone, body_text)
            log_notification(conn, watch_id, user_id, "sms", user_phone, None,
                             body_text, "sent" if ok else "failed")


def notify_admin_new_signup(name: str, email: str):
    """Notify Kevin of a new signup."""
    subject = f"🔔 New GetHoustons Signup: {name}"
    body = f"New user signed up via Google:\n\nName: {name}\nEmail: {email}"
    send_email(ADMIN_EMAIL, subject, body)


def notify_admin_new_watch(user_name: str, user_email: str, loc_name: str,
                           party_size: int, target_date: str,
                           time_start: str, time_end: str, auto_book: bool):
    """Notify Kevin of a new watch."""
    subject = f"👀 New Slot Watch: {loc_name}"
    body = (
        f"New watch created:\n\n"
        f"User: {user_name} ({user_email})\n"
        f"Location: {loc_name}\n"
        f"Party: {party_size}\n"
        f"Date: {target_date}\n"
        f"Time: {time_start} - {time_end}\n"
        f"Auto-book: {'Yes' if auto_book else 'No'}"
    )
    send_email(ADMIN_EMAIL, subject, body)


def notify_admin_feedback(message: str, contact: str | None, ip: str):
    """Notify of new feedback."""
    body = f"New feedback on GetHoustons.bar:\n\n{message}"
    if contact:
        body += f"\n\nContact: {contact}"
    body += f"\n\nIP: {ip}"
    send_email(NOTIFICATION_EMAIL, "🍖 New Feedback on GetHoustons.bar", body)
