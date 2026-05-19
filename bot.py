import json
import asyncio
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler,
)

# ── Config ─────────────────────────────────────────────────────────────────────
BOT_TOKEN = "8796607447:AAHPvCaZyKyVln2rIpdsZawbwY8TIgSDtt0"
WEB_APP_URL = "https://byte4breach.github.io/cinemamax"

DB_CONFIG = {
    "host":     "localhost",
    "port":     1234,
    "dbname":   "cinema_db",
    "user":     "postgres",
    "password": "postgres",
}

# Seat layout (same logic as Java)
STANDARD_ROWS = 8
STANDARD_COLS = 12
VIP_ROWS      = 4
VIP_COLS      = 6

STANDARD_PRICE = 20   # $ per seat
VIP_PRICE      = 50   # $ per seat

MOVIES_PER_PAGE = 6   # How many movies to show per page in Telegram

# Conversation states
CHOICE, GALLERY, TIMES, SEATS, CONFIRM = range(5)


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def db_get_movies():
    """Load all movies with showtime count."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT m.id, m.title,
                   COALESCE(m.genre, 'CINEMA') AS genre,
                   m.is_blockbuster,
                   COUNT(s.id) AS show_count
            FROM movies m
            LEFT JOIN showtimes s ON s.movie_id = m.id
            GROUP BY m.id, m.title, m.genre, m.is_blockbuster
            ORDER BY m.title
        """)
        return cur.fetchall()


def db_get_showtimes(movie_id: int):
    """Load showtimes with available seat count."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT s.id, s.hall_name, s.show_time, s.is_vip,
                   COUNT(b.id) AS booked_count
            FROM showtimes s
            LEFT JOIN booked_seats b ON b.showtime_id = s.id
            WHERE s.movie_id = %s
            GROUP BY s.id
            ORDER BY s.show_time
        """, (movie_id,))
        return cur.fetchall()


def db_get_booked_seats(showtime_id: int):
    """Return set of 'row-col' strings for booked seats."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT seat_row, seat_col FROM booked_seats WHERE showtime_id = %s",
            (showtime_id,)
        )
        return {f"{r['seat_row']}-{r['seat_col']}" for r in cur.fetchall()}


def db_book_seats(showtime_id: int, seats: list[str]):
    """Insert booked seats."""
    with get_conn() as conn, conn.cursor() as cur:
        for pos in seats:
            row, col = pos.split("-")
            cur.execute(
                "INSERT INTO booked_seats (showtime_id, seat_row, seat_col) "
                "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (showtime_id, int(row), int(col))
            )
        conn.commit()


# ── Formatting helpers ─────────────────────────────────────────────────────────

def seat_label(pos: str) -> str:
    row, col = pos.split("-")
    return f"{chr(65 + int(row))}{int(col) + 1}"

def capacity(is_vip: bool) -> int:
    return VIP_ROWS * VIP_COLS if is_vip else STANDARD_ROWS * STANDARD_COLS

def price(is_vip: bool) -> int:
    return VIP_PRICE if is_vip else STANDARD_PRICE

def avail_label(avail: int) -> str:
    return f"⚠️ {avail} left" if avail < 15 else f"✅ {avail} seats"


# ── /start & Choice ────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    
    keyboard = [
        [InlineKeyboardButton("📱 Open Web App", web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton("🤖 Book in Telegram", callback_data="choice:telegram")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    text = "Welcome to CinemaMax! 🎬\n\nHow would you like to book your tickets?"

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)

    return CHOICE

async def on_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "choice:telegram":
        ctx.user_data['page'] = 0
        return await show_gallery(update, ctx)
        
    return CHOICE


# ── Step 1: Movie gallery (With Pagination) ────────────────────────────────────

async def show_gallery(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    movies = db_get_movies()
    page = ctx.user_data.get('page', 0)
    
    total_pages = (len(movies) + MOVIES_PER_PAGE - 1) // MOVIES_PER_PAGE
    start_idx = page * MOVIES_PER_PAGE
    end_idx = start_idx + MOVIES_PER_PAGE
    page_movies = movies[start_idx:end_idx]

    keyboard = []
    for m in page_movies:
        star = "⭐ " if m["is_blockbuster"] else ""
        label = f"{star}{m['title']}  [{m['genre']}]  ({m['show_count']} showings)"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"movie:{m['id']}:{m['title']}")])

    # Pagination controls
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"page:{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="back:start")])

    text = f"🎬 *CinemaMax — Now Showing*\n\nPick a movie (Page {page+1} of {total_pages}):"
    markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    return GALLERY

async def on_page_change(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    _, new_page = query.data.split(":")
    ctx.user_data['page'] = int(new_page)
    
    return await show_gallery(update, ctx)

async def on_movie_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, movie_id, title = query.data.split(":", 2)
    ctx.user_data["movie_id"]    = int(movie_id)
    ctx.user_data["movie_title"] = title

    return await show_showtimes(update, ctx)


# ── Step 2: Showtimes ──────────────────────────────────────────────────────────

async def show_showtimes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    movie_id = ctx.user_data["movie_id"]
    title    = ctx.user_data["movie_title"]
    rows     = db_get_showtimes(movie_id)

    keyboard = []
    for s in rows:
        cap   = capacity(s["is_vip"])
        avail = cap - s["booked_count"]
        time  = str(s["show_time"])[:5]
        vip   = "★ VIP  " if s["is_vip"] else ""
        label = f"{vip}{s['hall_name']}  {time}  — {avail_label(avail)}"
        keyboard.append([InlineKeyboardButton(
            label,
            callback_data=f"show:{s['id']}:{s['hall_name']}:{time}:{1 if s['is_vip'] else 0}"
        )])

    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back:gallery")])

    await update.callback_query.edit_message_text(
        f"🎭 *{title}*\n\nChoose a showtime:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return TIMES


async def on_showtime_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, sid, hall, time, vip_flag = query.data.split(":", 4)
    ctx.user_data["showtime_id"] = int(sid)
    ctx.user_data["hall"]        = hall
    ctx.user_data["time"]        = time
    ctx.user_data["is_vip"]      = (vip_flag == "1")
    ctx.user_data["selected"]    = []

    return await show_seat_map(update, ctx)


# ── Step 3: Seat selection ─────────────────────────────────────────────────────

async def show_seat_map(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    sid    = ctx.user_data["showtime_id"]
    is_vip = ctx.user_data["is_vip"]
    title  = ctx.user_data["movie_title"]
    hall   = ctx.user_data["hall"]
    time   = ctx.user_data["time"]
    sel    = set(ctx.user_data.get("selected", []))

    rows = VIP_ROWS      if is_vip else STANDARD_ROWS
    cols = VIP_COLS      if is_vip else STANDARD_COLS
    booked = db_get_booked_seats(sid)

    keyboard = []

    # Header row: column numbers
    header = []
    for c in range(cols):
        header.append(InlineKeyboardButton(str(c + 1), callback_data="noop"))
    keyboard.append(header)

    # Seat rows
    for r in range(rows):
        row_label = chr(65 + r)
        row_btns  = [InlineKeyboardButton(row_label, callback_data="noop")]
        for c in range(cols):
            pos = f"{r}-{c}"
            if pos in booked:
                emoji = "🔴"
                cb    = "noop"
            elif pos in sel:
                emoji = "🟢"
                cb    = f"seat:deselect:{pos}"
            else:
                emoji = "⬜"
                cb    = f"seat:select:{pos}"
            row_btns.append(InlineKeyboardButton(emoji, callback_data=cb))
        keyboard.append(row_btns)

    count = len(sel)
    total = count * price(is_vip)
    seat_labels = sorted(seat_label(p) for p in sel)
    summary = (
        f"Selected: {', '.join(seat_labels) if seat_labels else '—'}\n"
        f"Total: ${total}.00"
    )

    keyboard.append([
        InlineKeyboardButton("✅ Confirm Booking", callback_data="confirm"),
        InlineKeyboardButton("⬅️ Back",            callback_data="back:times"),
    ])

    vip_tag = "  ★ VIP" if is_vip else ""
    header_text = (
        f"🎬 *{title}*{vip_tag}\n"
        f"📍 {hall}  🕐 {time}\n"
        f"⬜ Available  🟢 Selected  🔴 Booked\n\n"
        f"{summary}"
    )

    await update.callback_query.edit_message_text(
        header_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SEATS


async def on_seat_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, action, pos = query.data.split(":", 2)
    sel = ctx.user_data.setdefault("selected", [])

    if action == "select" and pos not in sel:
        sel.append(pos)
    elif action == "deselect" and pos in sel:
        sel.remove(pos)

    return await show_seat_map(update, ctx)


# ── Step 4: Confirm & book ─────────────────────────────────────────────────────

async def on_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    sel = ctx.user_data.get("selected", [])
    if not sel:
        await query.answer("❗ Please select at least one seat first.", show_alert=True)
        return SEATS

    is_vip  = ctx.user_data["is_vip"]
    sid     = ctx.user_data["showtime_id"]
    title   = ctx.user_data["movie_title"]
    hall    = ctx.user_data["hall"]
    time    = ctx.user_data["time"]
    total   = len(sel) * price(is_vip)
    labels  = sorted(seat_label(p) for p in sel)

    ticket = (
        f"🎟 *Booking Summary*\n\n"
        f"🎬 *Film:* {title}\n"
        f"📍 *Hall:* {'★ VIP Platinum' if is_vip else hall}\n"
        f"🕐 *Time:* {time}\n"
        f"💺 *Seats:* {', '.join(labels)}\n"
        f"🎫 *Tickets:* {len(sel)} × ${price(is_vip)}.00\n"
        f"💰 *Total:* ${total}.00"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Pay & Book", callback_data="book"),
        InlineKeyboardButton("⬅️ Back",       callback_data="back:seats"),
    ]])

    await query.edit_message_text(ticket, parse_mode="Markdown", reply_markup=keyboard)
    return CONFIRM


async def on_book(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    sid   = ctx.user_data["showtime_id"]
    sel   = ctx.user_data.get("selected", [])
    title = ctx.user_data["movie_title"]

    try:
        db_book_seats(sid, sel)
        labels = sorted(seat_label(p) for p in sel)
        await query.edit_message_text(
            f"✅ *Booking Confirmed!*\n\n"
            f"🎬 {title}\n"
            f"💺 Seats: {', '.join(labels)}\n\n"
            f"Enjoy the show! 🍿\n\n"
            f"Type /start to book again.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Booking failed: {e}\n\nType /start to try again."
        )

    ctx.user_data.clear()
    return ConversationHandler.END


# ── Back navigation ────────────────────────────────────────────────────────────

async def on_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    dest = query.data.split(":")[1]
    if dest == "start":
        return await start(update, ctx)
    elif dest == "gallery":
        return await show_gallery(update, ctx)
    elif dest == "times":
        return await show_showtimes(update, ctx)
    elif dest == "seats":
        return await show_seat_map(update, ctx)


async def noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOICE: [
                CallbackQueryHandler(on_choice, pattern=r"^choice:"),
            ],
            GALLERY: [
                CallbackQueryHandler(on_movie_selected, pattern=r"^movie:"),
                CallbackQueryHandler(on_page_change,    pattern=r"^page:"),
                CallbackQueryHandler(on_back,           pattern=r"^back:start"),
            ],
            TIMES: [
                CallbackQueryHandler(on_showtime_selected, pattern=r"^show:"),
                CallbackQueryHandler(on_back,              pattern=r"^back:"),
            ],
            SEATS: [
                CallbackQueryHandler(on_seat_toggle, pattern=r"^seat:"),
                CallbackQueryHandler(on_confirm,     pattern=r"^confirm$"),
                CallbackQueryHandler(on_back,        pattern=r"^back:"),
                CallbackQueryHandler(noop,           pattern=r"^noop$"),
            ],
            CONFIRM: [
                CallbackQueryHandler(on_book, pattern=r"^book$"),
                CallbackQueryHandler(on_back, pattern=r"^back:"),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )

    app.add_handler(conv)
    print("✅ CinemaMax bot running with PostgreSQL…  (Ctrl-C to stop)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()