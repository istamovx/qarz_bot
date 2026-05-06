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

BOT_TOKEN    = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WEBHOOK_URL  = os.getenv("WEBHOOK_URL", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Translations ───────────────────────────────────────────────────────────────

TEXTS = {
    "uz": {
        "choose_lang":   "🌐 Tilni tanlang:",
        "lang_set":      "✅ Til saqlandi!",
        "welcome":       "Salom, <b>{name}</b>! 👋\n\n💰 <b>Qarz Bot</b> — qarz oldi-berdi hisobini yuritish uchun.\n\nNima qilmoqchisiz?",
        "menu":          "Nima qilmoqchisiz?",
        "ask_person":    "Kimning ismi?",
        "ask_amount":    "💵 Qancha miqdor? (masalan: <code>500000</code>)",
        "bad_amount":    "Faqat raqam kiriting, masalan: <code>250000</code>",
        "ask_due":       "📅 Qaytarish muddati? (masalan: <code>25.05.2026</code>)\nO'tkazish: /skip",
        "bad_due":       "Noto'g'ri format. (masalan: <code>25.05.2026</code>)\nO'tkazish: /skip",
        "cancelled":     "Bekor qilindi.",
        "saved":         "✅ Saqlandi!",
        "sum":           "so'm",
        "action_gave":   "berdingiz",
        "action_took":   "oldingiz",
        "due_none":      "belgilanmagan",
        "no_gave":       "Hozircha to'lanmagan qarzdorlar yo'q.",
        "no_took":       "Hozircha to'lanmagan qarzlarim yo'q.",
        "no_all":        "Hozircha to'lanmagan qarzlar yo'q.",
        "title_gave":    "👥 Menga qarzdorlar",
        "title_took":    "📋 Mening qarzlarim",
        "title_all":     "📊 Barcha qarzlar",
        "balance_line":  "💸 Bergan: <code>{g}</code> so'm\n🤝 Olgan: <code>{t}</code> so'm\n📈 Balans: <code>{b}</code> so'm",
        "no_hist":       "To'langan qarzlar tarixi yo'q.",
        "hist_title":    "To'langan qarzlar (oxirgi 20)",
        "mark_paid":     "✅ To'landi: {name} — {amt}",
        "paid_alert":    "✅ {name} — {amt} so'm to'landi!",
        "btn_gave":      "💸 Qarz berdim",
        "btn_took":      "🤝 Qarz oldim",
        "btn_lgave":     "👥 Menga qarzdorlar",
        "btn_ltook":     "📋 Mening qarzlarim",
        "btn_lall":      "📊 Barcha qarzlar",
        "btn_menu":      "🏠 Menyu",
        "btn_app":       "📱 Ilovani ochish",
        "btn_settings":  "⚙️ Sozlamalar",
        "label_gave":    "bergan",
        "label_took":    "olgan",
        "r7d":           "7 kun qoldi",
        "r3d":           "3 kun qoldi",
        "r1d":           "Ertaga muddat tugaydi!",
        "r0d":           "Bugun muddat tugaydi!",
        "rem_title":     "🔔 Qarz eslatmasi!",
        "overdue":       "⚠️ <b>Muddati o'tgan ({d} kun)</b>",
        "due_today":     "🔴 <b>Bugun!</b>",
        "due_soon":      "🟡 {dt} ({d} kun qoldi)",
        "due_far":       "📅 {dt}",
    },
    "ru": {
        "choose_lang":   "🌐 Выберите язык:",
        "lang_set":      "✅ Язык сохранён!",
        "welcome":       "Привет, <b>{name}</b>! 👋\n\n💰 <b>Qarz Bot</b> — учёт долгов.\n\nЧто хотите сделать?",
        "menu":          "Что хотите сделать?",
        "ask_person":    "Имя человека?",
        "ask_amount":    "💵 Сумма? (например: <code>500000</code>)",
        "bad_amount":    "Только цифры, например: <code>250000</code>",
        "ask_due":       "📅 Дата возврата? (например: <code>25.05.2026</code>)\nПропустить: /skip",
        "bad_due":       "Неверный формат. (например: <code>25.05.2026</code>)\nПропустить: /skip",
        "cancelled":     "Отменено.",
        "saved":         "✅ Сохранено!",
        "sum":           "сум",
        "action_gave":   "выдали",
        "action_took":   "взяли",
        "due_none":      "не указан",
        "no_gave":       "Нет должников.",
        "no_took":       "Нет долгов.",
        "no_all":        "Нет долгов.",
        "title_gave":    "👥 Мои должники",
        "title_took":    "📋 Мои долги",
        "title_all":     "📊 Все долги",
        "balance_line":  "💸 Выдано: <code>{g}</code> сум\n🤝 Взято: <code>{t}</code> сум\n📈 Баланс: <code>{b}</code> сум",
        "no_hist":       "История пуста.",
        "hist_title":    "Оплаченные долги (последние 20)",
        "mark_paid":     "✅ Оплачено: {name} — {amt}",
        "paid_alert":    "✅ {name} — {amt} сум оплачено!",
        "btn_gave":      "💸 Дал в долг",
        "btn_took":      "🤝 Взял в долг",
        "btn_lgave":     "👥 Мои должники",
        "btn_ltook":     "📋 Мои долги",
        "btn_lall":      "📊 Все долги",
        "btn_menu":      "🏠 Меню",
        "btn_app":       "📱 Открыть приложение",
        "btn_settings":  "⚙️ Настройки",
        "label_gave":    "выдал",
        "label_took":    "взял",
        "r7d":           "Осталось 7 дней",
        "r3d":           "Осталось 3 дня",
        "r1d":           "Срок истекает завтра!",
        "r0d":           "Срок истекает сегодня!",
        "rem_title":     "🔔 Напоминание о долге!",
        "overdue":       "⚠️ <b>Просрочен ({d} дн.)</b>",
        "due_today":     "🔴 <b>Сегодня!</b>",
        "due_soon":      "🟡 {dt} (ещё {d} дн.)",
        "due_far":       "📅 {dt}",
    },
    "en": {
        "choose_lang":   "🌐 Choose language:",
        "lang_set":      "✅ Language saved!",
        "welcome":       "Hello, <b>{name}</b>! 👋\n\n💰 <b>Qarz Bot</b> — track your loans.\n\nWhat would you like to do?",
        "menu":          "What would you like to do?",
        "ask_person":    "Person's name?",
        "ask_amount":    "💵 Amount? (e.g. <code>500000</code>)",
        "bad_amount":    "Numbers only, e.g. <code>250000</code>",
        "ask_due":       "📅 Due date? (e.g. <code>25.05.2026</code>)\nSkip: /skip",
        "bad_due":       "Wrong format. (e.g. <code>25.05.2026</code>)\nSkip: /skip",
        "cancelled":     "Cancelled.",
        "saved":         "✅ Saved!",
        "sum":           "sum",
        "action_gave":   "lent",
        "action_took":   "borrowed",
        "due_none":      "not set",
        "no_gave":       "No outstanding debtors.",
        "no_took":       "No outstanding debts.",
        "no_all":        "No outstanding loans.",
        "title_gave":    "👥 My Debtors",
        "title_took":    "📋 My Debts",
        "title_all":     "📊 All Loans",
        "balance_line":  "💸 Lent: <code>{g}</code> sum\n🤝 Borrowed: <code>{t}</code> sum\n📈 Balance: <code>{b}</code> sum",
        "no_hist":       "No payment history yet.",
        "hist_title":    "Paid loans (last 20)",
        "mark_paid":     "✅ Paid: {name} — {amt}",
        "paid_alert":    "✅ {name} — {amt} sum paid!",
        "btn_gave":      "💸 I lent money",
        "btn_took":      "🤝 I borrowed",
        "btn_lgave":     "👥 My Debtors",
        "btn_ltook":     "📋 My Debts",
        "btn_lall":      "📊 All Loans",
        "btn_menu":      "🏠 Menu",
        "btn_app":       "📱 Open App",
        "btn_settings":  "⚙️ Settings",
        "label_gave":    "lent",
        "label_took":    "borrowed",
        "r7d":           "7 days left",
        "r3d":           "3 days left",
        "r1d":           "Due tomorrow!",
        "r0d":           "Due today!",
        "rem_title":     "🔔 Loan reminder!",
        "overdue":       "⚠️ <b>Overdue ({d} days)</b>",
        "due_today":     "🔴 <b>Today!</b>",
        "due_soon":      "🟡 {dt} ({d} days left)",
        "due_far":       "📅 {dt}",
    },
}

REMINDER_THRESHOLDS = {7: "r7d", 3: "r3d", 1: "r1d", 0: "r0d"}

# ── Helpers ────────────────────────────────────────────────────────────────────

def h(t): return escape(str(t))
def fmt(n): return f"{int(n):,}".replace(",", " ")

def get_lang(user_id: int, context=None) -> str:
    if context and context.user_data.get("lang"):
        return context.user_data["lang"]
    try:
        rows = supabase.table("user_settings").select("language").eq("user_id", user_id).execute().data
        lang = rows[0]["language"] if rows else "uz"
    except Exception:
        lang = "uz"
    if context:
        context.user_data["lang"] = lang
    return lang

def set_lang(user_id: int, lang: str):
    supabase.table("user_settings").upsert({"user_id": user_id, "language": lang}).execute()

def tx(lang: str, key: str, **kw) -> str:
    text = TEXTS.get(lang, TEXTS["uz"]).get(key, key)
    return text.format(**kw) if kw else text

def parse_date(text):
    for f in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%y"):
        try: return datetime.strptime(text.strip(), f).date()
        except ValueError: pass
    return None

def due_label(s, lang="uz") -> str:
    if not s: return ""
    try:
        diff = (date.fromisoformat(s) - date.today()).days
        dt   = date.fromisoformat(s).strftime("%d.%m.%Y")
        if diff < 0:  return " " + tx(lang, "overdue", d=abs(diff))
        if diff == 0: return " " + tx(lang, "due_today")
        if diff <= 3: return " " + tx(lang, "due_soon", dt=dt, d=diff)
        return " " + tx(lang, "due_far", dt=dt)
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
    user = validate_init_data(req.headers.get("X-Init-Data", ""))
    if not user: raise HTTPException(401, "Unauthorized")
    return user

# ── Bot keyboards ──────────────────────────────────────────────────────────────

def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇺🇿 O'zbek",   callback_data="lang_uz"),
        InlineKeyboardButton("🇷🇺 Русский",  callback_data="lang_ru"),
        InlineKeyboardButton("🇬🇧 English",  callback_data="lang_en"),
    ]])

def main_menu(lang: str):
    rows = []
    if WEBHOOK_URL:
        rows.append([InlineKeyboardButton(tx(lang,"btn_app"), web_app=WebAppInfo(url=f"{WEBHOOK_URL}/"))])
    rows += [
        [InlineKeyboardButton(tx(lang,"btn_gave"), callback_data="add_gave"),
         InlineKeyboardButton(tx(lang,"btn_took"), callback_data="add_took")],
        [InlineKeyboardButton(tx(lang,"btn_lgave"), callback_data="list_gave"),
         InlineKeyboardButton(tx(lang,"btn_ltook"), callback_data="list_took")],
        [InlineKeyboardButton(tx(lang,"btn_lall"), callback_data="list_all")],
        [InlineKeyboardButton(tx(lang,"btn_settings"), callback_data="settings")],
    ]
    return InlineKeyboardMarkup(rows)

# ── Handlers ───────────────────────────────────────────────────────────────────

PERSON_NAME, AMOUNT, DUE_DATE = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rows = supabase.table("user_settings").select("language").eq("user_id", update.effective_user.id).execute().data
    except Exception as e:
        logging.error(f"start/user_settings error: {e}")
        rows = []
    if rows:
        lang = rows[0]["language"]
        context.user_data["lang"] = lang
        await update.message.reply_text(
            tx(lang, "welcome", name=h(update.effective_user.first_name)),
            reply_markup=main_menu(lang), parse_mode="HTML")
    else:
        await update.message.reply_text(
            "🌐 Tilni tanlang / Choose language / Выберите язык:",
            reply_markup=lang_keyboard())

async def choose_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = query.data.replace("lang_", "")
    user_id = update.effective_user.id
    try:
        set_lang(user_id, lang)
    except Exception as e:
        logging.error(f"choose_lang/set_lang error: {e}")
    context.user_data["lang"] = lang
    await query.edit_message_text(
        tx(lang, "welcome", name=h(update.effective_user.first_name)),
        reply_markup=main_menu(lang), parse_mode="HTML")

async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌐 Tilni tanlang / Choose language / Выберите язык:",
        reply_markup=lang_keyboard())

async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = get_lang(q.from_user.id, context)
    await q.edit_message_text(tx(lang, "menu"), reply_markup=main_menu(lang))

async def settings_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = get_lang(q.from_user.id, context)
    await q.edit_message_text(
        f"⚙️ {tx(lang,'btn_settings')}\n\n🌐 {tx(lang,'choose_lang')}",
        reply_markup=lang_keyboard())

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = get_lang(q.from_user.id, context)
    loan_type = "gave" if q.data == "add_gave" else "took"
    context.user_data["loan_type"] = loan_type
    action = tx(lang, "action_gave") if loan_type == "gave" else tx(lang, "action_took")
    await q.edit_message_text(f"Qarz <b>{action}</b>.\n\n{tx(lang,'ask_person')}", parse_mode="HTML")
    return PERSON_NAME

async def get_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id, context)
    context.user_data["person_name"] = update.message.text.strip()
    await update.message.reply_text(tx(lang, "ask_amount"), parse_mode="HTML")
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id, context)
    text = update.message.text.strip().replace(",","").replace(" ","")
    if not text.isdigit():
        await update.message.reply_text(tx(lang, "bad_amount"), parse_mode="HTML")
        return AMOUNT
    context.user_data["amount"] = int(text)
    await update.message.reply_text(tx(lang, "ask_due"), parse_mode="HTML")
    return DUE_DATE

async def skip_due(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["due_date"] = None
    return await save_loan(update, context)

async def get_due(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id, context)
    parsed = parse_date(update.message.text)
    if not parsed:
        await update.message.reply_text(tx(lang, "bad_due"), parse_mode="HTML")
        return DUE_DATE
    context.user_data["due_date"] = parsed.isoformat()
    return await save_loan(update, context)

async def save_loan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id, context)
    user = update.effective_user
    data = {
        "user_id":     user.id,
        "loan_type":   context.user_data["loan_type"],
        "person_name": context.user_data["person_name"],
        "amount":      context.user_data["amount"],
        "description": "",
        "due_date":    context.user_data.get("due_date"),
        "is_paid":     False,
    }
    supabase.table("loans").insert(data).execute()
    arrow  = "💸" if data["loan_type"] == "gave" else "🤝"
    action = tx(lang, "action_gave") if data["loan_type"] == "gave" else tx(lang, "action_took")
    due_line = f"📅 {tx(lang,'label_due') if False else ''}{data['due_date']}" if data["due_date"] else f"📅 {tx(lang,'due_none')}"
    await update.message.reply_text(
        f"{arrow} <b>{tx(lang,'saved')}</b>\n\n"
        f"👤 <b>{h(data['person_name'])}</b>\n"
        f"💰 <b>{fmt(data['amount'])} {tx(lang,'sum')}</b>\n"
        f"{due_line}\n\n"
        f"Qarz <b>{action}</b> deb qayd etildi.",
        reply_markup=main_menu(lang), parse_mode="HTML")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id, context)
    context.user_data.clear()
    await update.message.reply_text(tx(lang, "cancelled"), reply_markup=main_menu(lang))
    return ConversationHandler.END

async def list_loans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    user_id = update.effective_user.id
    lang = get_lang(user_id, context)
    ft = q.data
    qb = supabase.table("loans").select("*").eq("user_id", user_id).eq("is_paid", False)
    if ft == "list_gave": qb = qb.eq("loan_type", "gave")
    elif ft == "list_took": qb = qb.eq("loan_type", "took")
    rows = qb.order("created_at", desc=False).execute().data
    if not rows:
        no_key = {"list_gave":"no_gave","list_took":"no_took","list_all":"no_all"}[ft]
        await q.edit_message_text(tx(lang, no_key),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(tx(lang,"btn_menu"), callback_data="menu")]]))
        return
    title_key = {"list_gave":"title_gave","list_took":"title_took","list_all":"title_all"}[ft]
    lines = [f"<b>{tx(lang, title_key)}</b>\n"]
    buttons = []
    for r in rows:
        arrow = "💸" if r["loan_type"] == "gave" else "🤝"
        amt = fmt(r["amount"])
        lines.append(f"{arrow} <b>{h(r['person_name'])}</b> | <code>{amt}</code> {tx(lang,'sum')}{due_label(r.get('due_date'), lang)}")
        buttons.append([InlineKeyboardButton(
            tx(lang, "mark_paid", name=r["person_name"], amt=amt),
            callback_data=f"paid_{r['id']}")])
    if ft == "list_all":
        tg = sum(r["amount"] for r in rows if r["loan_type"] == "gave")
        tk = sum(r["amount"] for r in rows if r["loan_type"] == "took")
        lines.append("\n" + tx(lang, "balance_line", g=fmt(tg), t=fmt(tk), b=fmt(tg-tk)))
    buttons.append([InlineKeyboardButton(tx(lang,"btn_menu"), callback_data="menu")])
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

async def mark_paid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    lang = get_lang(q.from_user.id, context)
    loan_id = q.data.replace("paid_", "")
    loan = supabase.table("loans").select("*").eq("id", loan_id).single().execute().data
    supabase.table("loans").update({"is_paid": True, "paid_at": datetime.now(timezone.utc).isoformat()}).eq("id", loan_id).execute()
    await q.answer(tx(lang, "paid_alert", name=loan["person_name"], amt=fmt(loan["amount"])), show_alert=True)
    q.data = "list_gave" if loan["loan_type"] == "gave" else "list_took"
    await list_loans(update, context)

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id, context)
    rows = supabase.table("loans").select("*").eq("user_id", update.effective_user.id).eq("is_paid", True).order("paid_at", desc=True).limit(20).execute().data
    if not rows:
        await update.message.reply_text(tx(lang, "no_hist"))
        return
    lines = [f"<b>{tx(lang,'hist_title')}</b>\n"]
    for r in rows:
        arrow = "💸" if r["loan_type"] == "gave" else "🤝"
        lines.append(f"{arrow} {h(r['person_name'])} | <code>{fmt(r['amount'])}</code> {tx(lang,'sum')} | {(r.get('paid_at',''))[:10]}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=main_menu(lang))

# ── Reminders ──────────────────────────────────────────────────────────────────

async def send_reminders():
    if not tg_app: return
    try:
        today = date.today()
        all_loans = supabase.table("loans").select("id,user_id,loan_type,person_name,amount,due_date").eq("is_paid", False).execute().data
        loans = [l for l in all_loans if l.get("due_date")]
        for loan in loans:
            days_left = (date.fromisoformat(loan["due_date"]) - today).days
            if days_left not in REMINDER_THRESHOLDS: continue
            r_type = REMINDER_THRESHOLDS[days_left]
            if supabase.table("reminders_sent").select("id").eq("loan_id", loan["id"]).eq("reminder_type", r_type).execute().data:
                continue
            lang = get_lang(loan["user_id"])
            arrow  = "💸" if loan["loan_type"] == "gave" else "🤝"
            action = tx(lang, "label_gave") if loan["loan_type"] == "gave" else tx(lang, "label_took")
            emoji  = "🚨" if days_left == 0 else ("⚠️" if days_left == 1 else "🔔")
            due_str = date.fromisoformat(loan["due_date"]).strftime("%d.%m.%Y")
            text = (
                f"{emoji} <b>{tx(lang,'rem_title')}</b>\n\n"
                f"{arrow} <b>{h(loan['person_name'])}</b> ({action})\n"
                f"💰 <b>{fmt(loan['amount'])} {tx(lang,'sum')}</b>\n"
                f"📅 {due_str}\n\n"
                f"⏳ <b>{tx(lang, r_type)}</b>"
            )
            try:
                await tg_app.bot.send_message(chat_id=loan["user_id"], text=text, parse_mode="HTML")
                supabase.table("reminders_sent").insert({"loan_id": loan["id"], "reminder_type": r_type}).execute()
                logging.info(f"Reminder sent: loan={loan['id']} type={r_type}")
            except Exception as e:
                logging.warning(f"Reminder failed user={loan['user_id']}: {e}")
    except Exception as e:
        logging.error(f"send_reminders error: {e}")

# ── Telegram app ───────────────────────────────────────────────────────────────

def build_tg_app():
    app = Application.builder().token(BOT_TOKEN).updater(None).build()
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_start, pattern="^add_(gave|took)$")],
        states={
            PERSON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_person)],
            AMOUNT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            DUE_DATE:    [CommandHandler("skip", skip_due),
                          MessageHandler(filters.TEXT & ~filters.COMMAND, get_due)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lang",  lang_cmd))
    app.add_handler(CommandHandler("tarix", history_cmd))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(choose_lang,  pattern="^lang_(uz|ru|en)$"))
    app.add_handler(CallbackQueryHandler(menu_cb,      pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(settings_cb,  pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(list_loans,   pattern="^list_(gave|took|all)$"))
    app.add_handler(CallbackQueryHandler(mark_paid_cb, pattern="^paid_"))
    return app

# ── FastAPI ────────────────────────────────────────────────────────────────────

tg_app = None

@asynccontextmanager
async def lifespan(_: FastAPI):
    global tg_app
    tg_app = build_tg_app()
    await tg_app.initialize()
    await tg_app.start()
    if WEBHOOK_URL:
        wh = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
        await tg_app.bot.delete_webhook(drop_pending_updates=True)
        await tg_app.bot.set_webhook(wh)
        logging.info(f"Webhook set: {wh}")

    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    scheduler.add_job(send_reminders, "interval", minutes=30, id="reminders",
                      next_run_time=datetime.now(timezone.utc))
    scheduler.start()
    logging.info("Scheduler started")

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

@fast_app.get("/health")
async def health():
    return {"status": "ok"}


@fast_app.get("/api/me")
async def api_me(request: Request):
    user = get_user(request)
    rows = supabase.table("user_settings").select("language").eq("user_id", user["id"]).execute().data
    return {"language": rows[0]["language"] if rows else "uz"}

@fast_app.patch("/api/me")
async def api_update_me(request: Request):
    user = get_user(request)
    body = await request.json()
    lang = body.get("language")
    if lang not in ("uz", "ru", "en"):
        raise HTTPException(400, "Invalid language")
    set_lang(user["id"], lang)
    return {"language": lang}

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
        "user_id":     user["id"],
        "loan_type":   body["loan_type"],
        "person_name": body["person_name"],
        "amount":      int(body["amount"]),
        "description": body.get("description", ""),
        "due_date":    body.get("due_date") or None,
        "is_paid":     False,
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

@fast_app.post("/api/reminders/run")
async def run_reminders_now():
    await send_reminders()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fast_app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
