# CinemaMax — Telegram Mini App

Full port of the JavaFX cinema booking app to a Telegram Mini App.
Same design, same flow, same seat grid — runs inside Telegram on any phone.

---

## Files

| File | Purpose |
|------|---------|
| `index.html` | The entire Mini App (self-contained, no build step) |
| `bot.py` | Telegram bot that shows the Launch button |
| `requirements.txt` | Python dependency |

---

## Step 1 — Host `index.html` (free, 2 minutes)

Telegram Mini Apps **must** be served over HTTPS.  
The easiest free option is **GitHub Pages**:

1. Go to https://github.com/new and create a public repo called `cinemamax`
2. Upload `index.html` to the repo root
3. Go to **Settings → Pages → Source → Deploy from branch → main / root**
4. Your URL will be: `https://YOUR_USERNAME.github.io/cinemamax`

> **Alternatives:** Netlify Drop (drag & drop at netlify.com/drop), Vercel, or any static host.

---

## Step 2 — Update `bot.py`

Open `bot.py` and replace the placeholder:

```python
WEB_APP_URL = "https://YOUR_USERNAME.github.io/cinemamax"
```

---

## Step 3 — Run the bot

```bash
pip install -r requirements.txt
python bot.py
```

---

## Step 4 — Register the Mini App with BotFather (required)

Telegram only allows Mini Apps from bots that have registered a domain.

1. Open @BotFather in Telegram
2. Send `/newapp` (or `/editapp` if the bot already exists)
3. Select `@moviecinemaxbot`
4. Follow the prompts — when asked for the Web App URL enter your GitHub Pages URL
5. Done! Telegram will now trust that domain.

---

## How it works

```
User taps /start
  → Bot sends message with "🎬 Open CinemaMax" button (WebAppInfo)
  → Telegram opens index.html in a full-screen in-app browser
  → User books tickets
  → App calls Telegram.WebApp.sendData() on confirm
  → Bot receives the data and sends a confirmation message
```

---

## App pages (mirrors the JavaFX app exactly)

1. **Gallery** — 8 demo movies, searchable, card animations
2. **Showtime** — 5 time slots per movie (Standard + VIP Platinum)
3. **Seats** — 8×12 standard hall or 4×6 VIP, wave-in animation, tap to toggle
4. **Ticket** — animated ticket reveal with QR code
5. **Success** — pulsing checkmark confirmation

---

## No database?

The web app uses the same **demo fallback data** as the Java app (triggered when PostgreSQL is unavailable). Seat booked-status is generated with the same seeded LCG random as `new Random(showtimeId)` in Java — so the same seats appear "taken" across sessions.

To connect a real backend, replace the `MOVIES`, `SHOWTIMES`, and `genBooked()` sections in `index.html` with `fetch()` calls to your API.
