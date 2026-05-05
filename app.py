import os, hmac, hashlib, json, logging
from html import escape
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, unquote
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)
from supabase import create_client, Client
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

BOT_TOKEN  = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WEBHOOK_URL  = os.getenv("WEBHOOK_URL", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Helpers ───────────────────────────────────────────────────────────────────

def h(t): return escape(str(t))
def fmt(n): return f"{int(n):,}".replace(",", " ")

def parse_date(text):
    for f in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%y"):
        try: return datetime.strptime(text.strip(), f).date()
        except ValueError: pass
    return None

def due_label(s):
    if not s: return ""
    try:
        diff = (date.fromisoformat(s) - date.today()).days
        if diff < 0: return f" ⚠️ <b>Muddati o'tgan ({abs(diff)} kun)</b>"
        if diff == 0: return " 🔴 <b>Bugun!</b>"
        if diff <= 3: return f" 🟡 {date.fromisoformat(s).strftime('%d.%m.%Y')} ({diff} kun)"
        return f" 📅 {date.fromisoformat(s).strftime('%d.%m.%Y')}"
    except: return ""

def validate_init_data(init_data: str) -> dict | None:
    try:
        vals = {k: v[0] for k, v in parse_qs(init_data).items()}
        hash_val = vals.pop("hash", None)
        if not hash_val: return None
        check_str = "\n".join(f"{k}={v}" for k, v in sorted(vals.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(
            hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest(), hash_val
        ): return None
        return json.loads(unquote(vals.get("user", "{}")))
    except: return None

def get_user(req: Request) -> dict:
    init_data = req.headers.get("X-Init-Data", "")
    user = validate_init_data(init_data)
    if not user:
        raise HTTPException(401, "Unauthorized")
    return user

# ── Bot handlers ──────────────────────────────────────────────────────────────

PERSON_NAME, AMOUNT, DESCRIPTION, DUE_DATE = range(4)

def main_menu():
    rows = []
    if WEBHOOK_URL:
        rows.append([InlineKeyboardButton("📱 Ilovani ochish", web_app=WebAppInfo(url=f"{WEBHOOK_URL}/"))])
    rows += [
        [InlineKeyboardButton("💸 Qarz berdim", callback_data="add_gave"),
         InlineKeyboardButton("🤝 Qarz oldim",  callback_data="add_took")],
        [InlineKeyboardButton("👥 Menga qarzdorlar", callback_data="list_gave"),
         InlineKeyboardButton("📋 Mening qarzlarim", callback_data="list_took")],
        [InlineKeyboardButton("📊 Barcha qarzlar", callback_data="list_all")],
    ]
    return InlineKeyboardMarkup(rows)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"Salom, <b>{h(name)}</b>! 👋\n\n💰 <b>Qarz Bot</b> — qarz oldi-berdi hisobini yuritish uchun.\n\nNima qilmoqchisiz?",
        reply_markup=main_menu(), parse_mode="HTML")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("Nima qilmoqchisiz?", reply_markup=main_menu())

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    loan_type = "gave" if q.data == "add_gave" else "took"
    context.user_data["loan_type"] = loan_type
    label = "berdingiz" if loan_type == "gave" else "oldingiz"
    await q.edit_message_text(f"Qarz <b>{label}</b>.\n\nKimning ismi?", parse_mode="HTML")
    return PERSON_NAME

async def get_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["person_name"] = update.message.text.strip()
    await update.message.reply_text("💵 Qancha miqdor? (<code>500000</code>)", parse_mode="HTML")
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",","").replace(" ","")
    if not text.isdigit():
        await update.message.reply_text("Faqat raqam kiriting!")
        return AMOUNT
    context.user_data["amount"] = int(text)
    await update.message.reply_text("Izoh (ixtiyoriy). O'tkazish: /skip")
    return DESCRIPTION

async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = ""
    await update.message.reply_text("📅 Qaytarish muddati? (<code>25.05.2026</code>)\nO'tkazish: /skip", parse_mode="HTML")
    return DUE_DATE

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = update.message.text.strip()
    await update.message.reply_text("📅 Qaytarish muddati? (<code>25.05.2026</code>)\nO'tkazish: /skip", parse_mode="HTML")
    return DUE_DATE

async def skip_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["due_date"] = None
    return await save_loan(update, context)

async def get_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parse_date(update.message.text)
    if not parsed:
        await update.message.reply_text("Noto'g'ri format. (<code>25.05.2026</code>)\nO'tkazish: /skip", parse_mode="HTML")
        return DUE_DATE
    context.user_data["due_date"] = parsed.isoformat()
    return await save_loan(update, context)

async def save_loan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = {
        "user_id": user.id,
        "loan_type": context.user_data["loan_type"],
        "person_name": context.user_data["person_name"],
        "amount": context.user_data["amount"],
        "description": context.user_data.get("description", ""),
        "due_date": context.user_data.get("due_date"),
        "is_paid": False,
    }
    supabase.table("loans").insert(data).execute()
    emoji  = "💸" if data["loan_type"] == "gave" else "🤝"
    action = "berdingiz" if data["loan_type"] == "gave" else "oldingiz"
    due_line = f"📅 Muddat: <b>{data['due_date']}</b>" if data["due_date"] else "📅 Muddat: belgilanmagan"
    await update.message.reply_text(
        f"{emoji} <b>Saqlandi!</b>\n\n👤 Kim: <b>{h(data['person_name'])}</b>\n"
        f"💰 Miqdor: <b>{fmt(data['amount'])} so'm</b>\n"
        f"Izoh: {h(data['description']) or '—'}\n{due_line}\n\nQarz <b>{action}</b> deb qayd etildi.",
        reply_markup=main_menu(), parse_mode="HTML")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bekor qilindi.", reply_markup=main_menu())
    return ConversationHandler.END

async def list_loans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    user_id = update.effective_user.id
    ft = q.data
    qb = supabase.table("loans").select("*").eq("user_id", user_id).eq("is_paid", False)
    if ft == "list_gave": qb = qb.eq("loan_type", "gave")
    elif ft == "list_took": qb = qb.eq("loan_type", "took")
    rows = qb.order("created_at", desc=False).execute().data
    if not rows:
        label = {"list_gave":"qarzdorlar","list_took":"qarzlarim","list_all":"qarzlar"}[ft]
        await q.edit_message_text(f"Hozircha to'lanmagan {label} yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menyu", callback_data="menu")]]))
        return
    title = {"list_gave":"👥 Menga qarzdorlar","list_took":"📋 Mening qarzlarim","list_all":"📊 Barcha qarzlar"}[ft]
    lines = [f"<b>{h(title)}</b>\n"]
    buttons = []
    for r in rows:
        arrow = "💸" if r["loan_type"] == "gave" else "🤝"
        amt = fmt(r["amount"])
        desc = f" — {h(r['description'])}" if r["description"] else ""
        lines.append(f"{arrow} <b>{h(r['person_name'])}</b> | <code>{amt}</code> so'm{desc}{due_label(r.get('due_date'))}")
        buttons.append([InlineKeyboardButton(f"✅ To'landi: {r['person_name']} — {amt}", callback_data=f"paid_{r['id']}")])
    if ft == "list_all":
        tg = sum(r["amount"] for r in rows if r["loan_type"] == "gave")
        tk = sum(r["amount"] for r in rows if r["loan_type"] == "took")
        lines.append(f"\n💸 Bergan: <code>{fmt(tg)}</code> so'm\n🤝 Olgan: <code>{fmt(tk)}</code> so'm\n📈 Balans: <code>{fmt(tg-tk)}</code> so'm")
    buttons.append([InlineKeyboardButton("🏠 Menyu", callback_data="menu")])
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

async def mark_paid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    loan_id = q.data.replace("paid_", "")
    loan = supabase.table("loans").select("*").eq("id", loan_id).single().execute().data
    supabase.table("loans").update({"is_paid": True, "paid_at": datetime.now(timezone.utc).isoformat()}).eq("id", loan_id).execute()
    await q.answer(f"✅ {loan['person_name']} — {fmt(loan['amount'])} so'm to'landi!", show_alert=True)
    q.data = "list_gave" if loan["loan_type"] == "gave" else "list_took"
    await list_loans(update, context)

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = supabase.table("loans").select("*").eq("user_id", update.effective_user.id).eq("is_paid", True).order("paid_at", desc=True).limit(20).execute().data
    if not rows:
        await update.message.reply_text("To'langan qarzlar tarixi yo'q.")
        return
    lines = ["<b>To'langan qarzlar (oxirgi 20)</b>\n"]
    for r in rows:
        arrow = "💸" if r["loan_type"] == "gave" else "🤝"
        lines.append(f"{arrow} {h(r['person_name'])} | <code>{fmt(r['amount'])}</code> so'm | {(r.get('paid_at',''))[:10]}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=main_menu())

# ── Reminders ─────────────────────────────────────────────────────────────────

# days_left -> (reminder_type, label)
REMINDER_THRESHOLDS = {
    7: ("7d", "7 kun qoldi"),
    3: ("3d", "3 kun qoldi"),
    1: ("1d", "Ertaga muddat tugaydi!"),
    0: ("1h", "Bugun muddat tugaydi!"),
}

async def keep_alive():
    if not WEBHOOK_URL:
        return
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            await client.get(f"{WEBHOOK_URL}/health", timeout=10)
        logging.info("Keep-alive ping OK")
    except Exception as e:
        logging.warning(f"Keep-alive ping failed: {e}")

async def send_reminders():
    if not tg_app:
        return
    try:
        today = date.today()
        all_loans = (
            supabase.table("loans")
            .select("id,user_id,loan_type,person_name,amount,due_date")
            .eq("is_paid", False)
            .execute()
            .data
        )
        loans = [l for l in all_loans if l.get("due_date")]

        for loan in loans:
            days_left = (date.fromisoformat(loan["due_date"]) - today).days
            if days_left not in REMINDER_THRESHOLDS:
                continue

            r_type, r_label = REMINDER_THRESHOLDS[days_left]

            already_sent = (
                supabase.table("reminders_sent")
                .select("id")
                .eq("loan_id", loan["id"])
                .eq("reminder_type", r_type)
                .execute()
                .data
            )
            if already_sent:
                continue

            arrow  = "💸" if loan["loan_type"] == "gave" else "🤝"
            action = "bergan" if loan["loan_type"] == "gave" else "olgan"
            emoji  = "🚨" if days_left == 0 else ("⚠️" if days_left == 1 else "🔔")
            due_str = date.fromisoformat(loan["due_date"]).strftime("%d.%m.%Y")

            text = (
                f"{emoji} <b>Qarz eslatmasi!</b>\n\n"
                f"{arrow} <b>{h(loan['person_name'])}</b> ({action})\n"
                f"💰 <b>{fmt(loan['amount'])} so'm</b>\n"
                f"📅 Muddat: <b>{due_str}</b>\n\n"
                f"⏳ <b>{r_label}</b>"
            )

            try:
                await tg_app.bot.send_message(
                    chat_id=loan["user_id"],
                    text=text,
                    parse_mode="HTML",
                )
                supabase.table("reminders_sent").insert({
                    "loan_id": loan["id"],
                    "reminder_type": r_type,
                }).execute()
                logging.info(f"Reminder sent: loan={loan['id']} type={r_type}")
            except Exception as e:
                logging.warning(f"Reminder send failed user={loan['user_id']}: {e}")

    except Exception as e:
        logging.error(f"send_reminders error: {e}")

def build_tg_app():
    app = Application.builder().token(BOT_TOKEN).updater(None).build()
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_start, pattern="^add_(gave|took)$")],
        states={
            PERSON_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_person)],
            AMOUNT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            DESCRIPTION:  [CommandHandler("skip", skip_description), MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
            DUE_DATE:     [CommandHandler("skip", skip_due_date),    MessageHandler(filters.TEXT & ~filters.COMMAND, get_due_date)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tarix", history_cmd))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(menu, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(list_loans, pattern="^list_(gave|took|all)$"))
    app.add_handler(CallbackQueryHandler(mark_paid_cb, pattern="^paid_"))
    return app

# ── FastAPI ───────────────────────────────────────────────────────────────────

tg_app = None

@asynccontextmanager
async def lifespan(_: FastAPI):
    global tg_app
    tg_app = build_tg_app()
    await tg_app.initialize()
    await tg_app.start()
    if WEBHOOK_URL:
        wh = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
        await tg_app.bot.set_webhook(wh)
        logging.info(f"Webhook: {wh}")

    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    scheduler.add_job(send_reminders, "interval", minutes=30, id="reminders",
                      next_run_time=datetime.now(timezone.utc))
    scheduler.add_job(keep_alive, "interval", minutes=10, id="keep_alive")
    scheduler.start()
    logging.info("Scheduler started: reminders (30 min), keep-alive (10 min)")

    yield

    scheduler.shutdown(wait=False)
    await tg_app.bot.delete_webhook()
    await tg_app.stop()
    await tg_app.shutdown()

fast_app = FastAPI(lifespan=lifespan)

@fast_app.post(f"/webhook/{BOT_TOKEN}")
async def webhook(request: Request):
    data = await request.json()
    await tg_app.process_update(Update.de_json(data, tg_app.bot))
    return {"ok": True}

@fast_app.get("/", response_class=HTMLResponse)
async def webapp():
    return HTMLResponse(Path("webapp.html").read_text(encoding="utf-8"))

@fast_app.get("/api/summary")
async def api_summary(request: Request):
    user = get_user(request)
    rows = supabase.table("loans").select("loan_type,amount").eq("user_id", user["id"]).eq("is_paid", False).execute().data
    tg = sum(r["amount"] for r in rows if r["loan_type"] == "gave")
    tk = sum(r["amount"] for r in rows if r["loan_type"] == "took")
    return {"total_gave": tg, "total_took": tk, "balance": tg - tk,
            "count_gave": sum(1 for r in rows if r["loan_type"] == "gave"),
            "count_took": sum(1 for r in rows if r["loan_type"] == "took")}

@fast_app.get("/api/loans")
async def api_loans(request: Request, loan_type: str = "all", paid: bool = False):
    user = get_user(request)
    q = supabase.table("loans").select("*").eq("user_id", user["id"]).eq("is_paid", paid)
    if loan_type != "all": q = q.eq("loan_type", loan_type)
    rows = q.order("created_at", desc=True).execute().data
    rows.sort(key=lambda r: (r.get("due_date") or "9999-99-99"))
    return rows

@fast_app.post("/api/loans")
async def api_create(request: Request):
    user = get_user(request)
    body = await request.json()
    data = {
        "user_id": user["id"],
        "loan_type": body["loan_type"],
        "person_name": body["person_name"],
        "amount": int(body["amount"]),
        "description": body.get("description", ""),
        "due_date": body.get("due_date") or None,
        "is_paid": False,
    }
    return supabase.table("loans").insert(data).execute().data[0]

@fast_app.patch("/api/loans/{loan_id}/paid")
async def api_paid(loan_id: str, request: Request):
    user = get_user(request)
    loan = supabase.table("loans").select("user_id").eq("id", loan_id).single().execute().data
    if loan["user_id"] != user["id"]: raise HTTPException(403)
    return supabase.table("loans").update({"is_paid": True, "paid_at": datetime.now(timezone.utc).isoformat()}).eq("id", loan_id).execute().data[0]

@fast_app.get("/api/history")
async def api_history(request: Request):
    user = get_user(request)
    return supabase.table("loans").select("*").eq("user_id", user["id"]).eq("is_paid", True).order("paid_at", desc=True).limit(30).execute().data

@fast_app.get("/health")
async def health():
    return {"status": "ok"}

@fast_app.post("/api/reminders/run")
async def run_reminders_now():
    """Testlash uchun: reminderni qo'lda ishga tushirish."""
    await send_reminders()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fast_app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
