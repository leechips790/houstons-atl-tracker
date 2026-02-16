# 🥩 Houston's ATL Tracker — Launch Plan

**One-Pager | February 2026**

---

## What Is It?

The only app dedicated to getting you into Houston's in Atlanta. Real-time reservation availability, automated wait time checks, and instant alerts when slots open up.

**Two locations. Zero excuses.**
- Houston's Peachtree — 2166 Peachtree Rd NW
- Houston's West Paces — 3539 Northside Pkwy NW

---

## The Problem

Everyone in Atlanta wants to eat at Houston's. Reservations are gone in minutes. Bar wait times are a mystery unless you call. There's no centralized way to know what's available or when slots open up.

---

## MVP Features

### 1. 📅 7-Day Availability Scanner
Live calendar grid showing open slots across both locations for the next 7 days. Color-coded: 🟢 open, 🟡 limited, 🔴 full. Auto-refreshes every 15 minutes.

### 2. 🔔 Slot Alerts
Enter your name, email, preferred date/time/party size. When a matching slot opens → instant email notification. "A 7:30 PM table for 4 just opened at Peachtree — book now."

### 3. ⏱️ Live Bar Wait Times (AI-Powered)
An AI voice agent calls both Houston's locations during peak hours and asks: *"How long is the current wait for the bar?"* Wait times are displayed in real-time on the app. No other service does this.

- **Call frequency:** Every 45 min, 5:00–9:00 PM, Thu–Sat
- **Fallback:** Crowd-sourced "I just called" reports from users
- **Display:** "~40 min wait at Peachtree — checked 12 min ago"

### 4. 📊 Availability Heatmap
Historical data visualization: which days/times have the most openings. Helps users learn the patterns. "Thursday 6:30 PM has 3x more availability than Friday 7:30 PM."

### 5. 🏆 Slot Drop Tracker
Logs when cancellations happen. "Last Friday, a 7:30 PM slot appeared at 2:14 PM and was gone by 2:22 PM." Teaches users when to check.

### 6. 🗺️ Location Cards
Beautiful cards for each location: address, Google Maps link, parking tips, dress code, vibe description, popular dishes, tap-to-call button.

### 7. 📱 Mobile-First Design
90% of users will be on phones. Thumb-friendly, fast-loading, dark luxury aesthetic matching Houston's brand vibe.

### 8. 📈 Live Status Banner
Top of page hero: "🟢 3 slots open tonight" or "🔴 Fully booked through Saturday — next opening: Monday 6:15 PM"

---

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | Static HTML/CSS/JS | Fast, no build step, easy to deploy |
| Backend/API | Python (Flask or FastAPI) | Wisely API proxy, data storage, alert engine |
| Database | SQLite → PostgreSQL | Start simple, migrate if needed |
| Hosting | **Railway** or **Render** | Free tier for MVP, easy deploy, custom domains |
| AI Calling | **Bland.ai** | Simple API: POST phone number + prompt → get transcript |
| Email Alerts | **Resend** or gog (Gmail) | Transactional emails for slot alerts |
| Domain | houstonatl.com or houstonsatl.com | TBD |
| Monitoring | Cron jobs | Inventory scans, AI calls, alert checks |

---

## Cost Breakdown (Monthly)

### Hosting
| Service | Tier | Cost |
|---------|------|------|
| Railway/Render | Starter | **$0–$7/mo** |
| Custom domain | .com | **$12/yr** (~$1/mo) |

### AI Calling (Bland.ai)
| Item | Calculation | Cost |
|------|------------|------|
| Calls per day | 2 locations × ~6 calls each (every 45 min, 5-9 PM) = 12 calls | |
| Days per week | Thu, Fri, Sat = 3 days | |
| Calls per month | 12 × 3 × 4 weeks = **~144 calls** | |
| Duration | ~30 sec avg per call | |
| Minutes | 144 × 0.5 min = **72 min** | |
| Bland.ai rate | ~$0.07–0.09/min | **$5–7/mo** |

### Email Alerts
| Service | Tier | Cost |
|---------|------|------|
| Resend | Free tier (100 emails/day) | **$0** |
| Or Resend Pro | 50k emails/mo | **$20/mo** (if needed later) |

### Wisely API
| Item | Cost |
|------|------|
| API calls | **$0** (unauthenticated, public API) |

### Total Monthly Cost

| Item | Cost |
|------|------|
| Hosting | $0–7 |
| AI Calling | $5–7 |
| Email | $0 |
| Domain | $1 |
| **Total** | **$6–15/mo** |

---

## Timeline

| Day | Milestone |
|-----|-----------|
| **Day 1** | Mobile-first redesign + 7-day scanner + live status banner |
| **Day 2** | Bland.ai integration + wait time display + location cards |
| **Day 3** | Alert signup + email notifications + slot drop tracking |
| **Day 4** | Heatmap + historical data + polish |
| **Day 5** | Deploy to Railway/Render + custom domain + beta invite 50 people |

---

## Growth Path

**Phase 1 — Private Beta (50 people)**
- Invite-only link shared via text/social
- Gather feedback, watch usage patterns
- Validate that people actually use alerts + wait times

**Phase 2 — Public Launch**
- SEO: "Houston's Atlanta reservations", "Houston's wait time"
- Instagram/TikTok: "I built an app that tells you the wait at Houston's in real-time"
- Reddit: r/Atlanta, r/FoodAtlanta
- Word of mouth from the 50 beta users

**Phase 3 — Monetization (Optional)**
- Premium alerts (text/SMS instead of email, priority notifications)
- Sponsored by Houston's? (if they like the traffic)
- Expand to other hard-to-book Atlanta restaurants (but Houston's first and only for now)

---

## What Makes This Different

1. **AI-powered wait times** — Nobody else calls the restaurant for you
2. **Real-time availability** — Not a static menu page, live data from Wisely
3. **Smart alerts** — Don't refresh the page, we'll tell you when it opens
4. **Houston's-only focus** — Not trying to be Yelp or Resy. Just Houston's. Just Atlanta.

---

## Bottom Line

**$6–15/month** to run an app that 50+ Houston's fans in Atlanta will love. The AI calling feature is the hook nobody else has. Build in 5 days, launch to beta, and see what happens.

Let's cook. 🍟
