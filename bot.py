import os
import asyncio
import logging
from html import escape
from datetime import date, datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

PERSON_NAME, AMOUNT, DESCRIPTION, DUE_DATE = range(4)

def h(text: str) -> str:
    return escape(str(text))

def fmt_amount(amount) -> str:
    return f"{int(amount):,}".replace(",", " ")

def parse_date(text: str):
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None

def due_label(due_date_str) -> str:
    if not due_date_str:
        return ""
    try:
        d = date.fromisoformat(due_date_str)
        today = date.today()
        diff = (d - today).days
        if diff < 0:
            return f" ⚠️ <b>Muddati o'tgan ({abs(diff)} kun)</b>"
        elif diff == 0:
            return " 🔴 <b>Bugun!</b>"
        elif diff <= 3:
            return f" 🟡 {d.strftime('%d.%m.%Y')} ({diff} kun qoldi)"
        else:
            return f" 📅 {d.strftime('%d.%m.%Y')}"
    except Exception:
        return ""

# ─── Klaviatura ────────────────────────────────────────────────────────────────

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💸 Qarz berdim", callback_data="add_gave"),
            InlineKeyboardButton("🤝 Qarz oldim", callback_data="add_took"),
        ],
        [
            InlineKeyboardButton("👥 Menga qarzdorlar", callback_data="list_gave"),
            InlineKeyboardButton("📋 Mening qarzlarim", callback_data="list_took"),
        ],
        [InlineKeyboardButton("📊 Barcha qarzlar", callback_data="list_all")],
    ])

# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"Salom, <b>{h(name)}</b>! 👋\n\n"
        "💰 <b>Qarz Bot</b> — qarz oldi-berdi hisobini yuritish uchun.\n\n"
        "Nima qilmoqchisiz?",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Nima qilmoqchisiz?", reply_markup=main_menu())

# ─── Qarz qo'shish ────────────────────────────────────────────────────────────

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    loan_type = "gave" if query.data == "add_gave" else "took"
    context.user_data["loan_type"] = loan_type
    label = "berdingiz" if loan_type == "gave" else "oldingiz"
    await query.edit_message_text(
        f"Qarz <b>{label}</b>.\n\nKimning ismi? (to'liq ism yozing)",
        parse_mode="HTML",
    )
    return PERSON_NAME

async def get_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["person_name"] = update.message.text.strip()
    await update.message.reply_text(
        "💵 Qancha miqdor? (faqat raqam, masalan: <code>500000</code>)",
        parse_mode="HTML",
    )
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "").replace(" ", "")
    if not text.isdigit():
        await update.message.reply_text(
            "Faqat raqam kiriting, masalan: <code>250000</code>",
            parse_mode="HTML",
        )
        return AMOUNT
    context.user_data["amount"] = int(text)
    await update.message.reply_text("Izoh (ixtiyoriy). O'tkazish uchun /skip yozing.")
    return DESCRIPTION

async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = ""
    return await ask_due_date(update, context)

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = update.message.text.strip()
    return await ask_due_date(update, context)

async def ask_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 Qaytarish muddati? (masalan: <code>25.05.2026</code>)\n"
        "O'tkazish uchun /skip yozing.",
        parse_mode="HTML",
    )
    return DUE_DATE

async def skip_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["due_date"] = None
    return await save_loan(update, context)

async def get_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parse_date(update.message.text)
    if not parsed:
        await update.message.reply_text(
            "Noto'g'ri format. Qayta kiriting (masalan: <code>25.05.2026</code>)\n"
            "O'tkazish uchun /skip yozing.",
            parse_mode="HTML",
        )
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

    emoji = "💸" if data["loan_type"] == "gave" else "🤝"
    action = "berdingiz" if data["loan_type"] == "gave" else "oldingiz"
    desc_line = h(data["description"]) if data["description"] else "—"
    due_line = f"📅 Muddat: <b>{data['due_date']}</b>" if data["due_date"] else "📅 Muddat: belgilanmagan"

    await update.message.reply_text(
        f"{emoji} <b>Saqlandi!</b>\n\n"
        f"👤 Kim: <b>{h(data['person_name'])}</b>\n"
        f"💰 Miqdor: <b>{fmt_amount(data['amount'])} so'm</b>\n"
        f"Izoh: {desc_line}\n"
        f"{due_line}\n\n"
        f"Qarz <b>{action}</b> deb qayd etildi.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bekor qilindi.", reply_markup=main_menu())
    return ConversationHandler.END

# ─── Ro'yxat ──────────────────────────────────────────────────────────────────

async def list_loans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    filter_type = query.data

    q = supabase.table("loans").select("*").eq("user_id", user_id).eq("is_paid", False)
    if filter_type == "list_gave":
        q = q.eq("loan_type", "gave")
    elif filter_type == "list_took":
        q = q.eq("loan_type", "took")

    rows = q.order("due_date", desc=False, nullsfirst=False).order("created_at", desc=False).execute().data

    if not rows:
        label = {"list_gave": "qarzdorlar", "list_took": "qarzlarim", "list_all": "qarzlar"}[filter_type]
        await query.edit_message_text(
            f"Hozircha to'lanmagan {label} yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menyu", callback_data="menu")]]),
        )
        return

    title = {
        "list_gave": "👥 Menga qarzdorlar",
        "list_took": "📋 Mening qarzlarim",
        "list_all": "📊 Barcha qarzlar",
    }[filter_type]

    lines = [f"<b>{h(title)}</b>\n"]
    buttons = []

    total_gave = sum(r["amount"] for r in rows if r["loan_type"] == "gave")
    total_took = sum(r["amount"] for r in rows if r["loan_type"] == "took")

    for r in rows:
        arrow = "💸" if r["loan_type"] == "gave" else "🤝"
        amt = fmt_amount(r["amount"])
        desc = f" — {h(r['description'])}" if r["description"] else ""
        deadline = due_label(r.get("due_date"))
        lines.append(f"{arrow} <b>{h(r['person_name'])}</b> | <code>{amt}</code> so'm{desc}{deadline}")
        buttons.append([
            InlineKeyboardButton(
                f"✅ To'landi: {r['person_name']} — {amt}",
                callback_data=f"paid_{r['id']}",
            )
        ])

    if filter_type == "list_all":
        lines.append(
            f"\n💸 Bergan: <code>{fmt_amount(total_gave)}</code> so'm\n"
            f"🤝 Olgan: <code>{fmt_amount(total_took)}</code> so'm\n"
            f"📈 Balans: <code>{fmt_amount(total_gave - total_took)}</code> so'm"
        )

    buttons.append([InlineKeyboardButton("🏠 Menyu", callback_data="menu")])

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )

# ─── To'landi ─────────────────────────────────────────────────────────────────

async def mark_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    loan_id = query.data.replace("paid_", "")

    result = supabase.table("loans").select("*").eq("id", loan_id).single().execute()
    loan = result.data
    supabase.table("loans").update({
        "is_paid": True,
        "paid_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", loan_id).execute()

    amt = fmt_amount(loan["amount"])
    await query.answer(f"✅ {loan['person_name']} — {amt} so'm to'landi!", show_alert=True)

    query.data = "list_gave" if loan["loan_type"] == "gave" else "list_took"
    await list_loans(update, context)

# ─── Tarix ────────────────────────────────────────────────────────────────────

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = (
        supabase.table("loans")
        .select("*")
        .eq("user_id", user_id)
        .eq("is_paid", True)
        .order("paid_at", desc=True)
        .limit(20)
        .execute()
        .data
    )
    if not rows:
        await update.message.reply_text("To'langan qarzlar tarixi yo'q.")
        return

    lines = ["<b>To'langan qarzlar (oxirgi 20)</b>\n"]
    for r in rows:
        arrow = "💸" if r["loan_type"] == "gave" else "🤝"
        amt = fmt_amount(r["amount"])
        date_str = r.get("paid_at", "")[:10]
        lines.append(f"{arrow} {h(r['person_name'])} | <code>{amt}</code> so'm | {date_str}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=main_menu())

# ─── Main ─────────────────────────────────────────────────────────────────────

def build_app():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_start, pattern="^add_(gave|took)$")],
        states={
            PERSON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_person)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            DESCRIPTION: [
                CommandHandler("skip", skip_description),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_description),
            ],
            DUE_DATE: [
                CommandHandler("skip", skip_due_date),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_due_date),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tarix", history))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(menu, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(list_loans, pattern="^list_(gave|took|all)$"))
    app.add_handler(CallbackQueryHandler(mark_paid, pattern="^paid_"))
    return app

def main():
    app = build_app()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if WEBHOOK_URL:
        PORT = int(os.getenv("PORT", 8080))
        print(f"Webhook rejimi: {WEBHOOK_URL}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            url_path=BOT_TOKEN,
        )
    else:
        print("Polling rejimi (lokal)...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
