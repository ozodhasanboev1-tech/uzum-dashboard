"""
Uzum Dashboard - Telegram bot.

Buyruqlar:
  /start <maxfiy_kod>  - botga ro'yxatdan o'tish (faqat to'g'ri kod bilan)
  /today               - bugungi savdo xulosasi
  /month               - joriy oy xulosasi
  /stock               - ombordagi qoldiqlar
  /expenses            - so'nggi 7 kunlik xarajatlar (kategoriya bo'yicha)
  /help                - buyruqlar ro'yxati

Kunlik avtomatik hisobot: har kuni DAILY_REPORT_HOUR (default 9:00, server vaqti
bo'yicha) da ro'yxatdan o'tgan barcha chat'larga yuboriladi.

Ishga tushirish:
  pip install -r requirements.txt
  export DATABASE_URL=postgresql://...
  export TELEGRAM_BOT_TOKEN=123456:ABC...
  export BOT_REGISTER_CODE=maxfiy-soz
  python bot.py

BotFather orqali bot yaratish:
  1. Telegram'da @BotFather ga /newbot yozing
  2. Bot nomini kiriting, u sizga token beradi (masalan 123456789:AAExxxxxxx)
  3. Shu tokenni TELEGRAM_BOT_TOKEN muhit o'zgaruvchisiga qo'ying
"""

import os
import sys
import logging
from datetime import datetime, timedelta, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import text  # noqa: E402
from db import get_conn  # noqa: E402
import queries  # noqa: E402

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
REGISTER_CODE = os.environ.get("BOT_REGISTER_CODE", "changeme")
DAILY_REPORT_HOUR = int(os.environ.get("DAILY_REPORT_HOUR", "9"))


def fmt(n):
    return f"{n:,.0f}".replace(",", " ")


def is_registered(chat_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(text("SELECT 1 FROM telegram_users WHERE chat_id=:c"), {"c": chat_id}).fetchone()
        return row is not None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    chat_id = update.effective_chat.id
    if is_registered(chat_id):
        await update.message.reply_text("Assalomu alaykum! Siz allaqachon ro'yxatdan o'tgansiz. /help - buyruqlar.")
        return
    if not args or args[0] != REGISTER_CODE:
        await update.message.reply_text("Ro'yxatdan o'tish uchun: /start <maxfiy_kod>")
        return
    with get_conn() as conn:
        conn.execute(text("""
            INSERT INTO telegram_users (chat_id, name) VALUES (:c, :n)
            ON CONFLICT (chat_id) DO NOTHING
        """), {"c": chat_id, "n": update.effective_user.full_name})
    await update.message.reply_text("Ro'yxatdan o'tdingiz! /help - buyruqlar ro'yxati.")


async def require_auth(update: Update) -> bool:
    if not is_registered(update.effective_chat.id):
        await update.message.reply_text("Avval ro'yxatdan o'ting: /start <maxfiy_kod>")
        return False
    return True


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/today - bugungi savdo\n"
        "/month - joriy oy xulosasi\n"
        "/stock - ombordagi qoldiq\n"
        "/expenses - so'nggi 7 kun xarajatlari\n"
    )


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_auth(update):
        return
    d = date.today().isoformat()
    s = queries.get_summary(d, d)
    text_out = (
        f"📊 Bugungi savdo ({d})\n\n"
        f"Tushum: {fmt(s['revenue'])} so'm\n"
        f"To'lanadigan: {fmt(s['payout'])} so'm\n"
        f"Sof foyda: {fmt(s['net_profit'])} so'm\n"
        f"Buyurtmalar: {s['total_orders']} (bekor: {s['cancelled_orders']})"
    )
    await update.message.reply_text(text_out)


async def month_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_auth(update):
        return
    today = date.today()
    df = today.replace(day=1).isoformat()
    dt = today.isoformat()
    s = queries.get_summary(df, dt)
    lines = [
        f"📅 Oylik xulosa ({df} - {dt})",
        "",
        f"Tushum: {fmt(s['revenue'])} so'm",
        f"To'lanadigan: {fmt(s['payout'])} so'm",
        f"Sof foyda: {fmt(s['net_profit'])} so'm",
        f"Buyurtmalar: {s['total_orders']} (bekor: {s['cancelled_orders']})",
        "",
        "Xarajatlar:",
    ]
    for e in s["expenses_by_category"][:8]:
        lines.append(f"  {e['category'] or 'Boshqa'}: {fmt(e['amount'])} so'm")
    await update.message.reply_text("\n".join(lines))


async def stock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_auth(update):
        return
    today = date.today().isoformat()
    s = queries.get_summary(today, today)
    lines = ["📦 Ombordagi qoldiq:"]
    for row in s["stock_by_type"]:
        lines.append(f"  {row['type'] or '-'}: {fmt(row['qty'])} dona, {fmt(row['cost'])} so'm")
    await update.message.reply_text("\n".join(lines))


async def expenses_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_auth(update):
        return
    dt = date.today()
    df = dt - timedelta(days=7)
    s = queries.get_summary(df.isoformat(), dt.isoformat())
    lines = [f"💸 So'nggi 7 kun xarajatlari ({df.isoformat()} - {dt.isoformat()}):"]
    for e in s["expenses_by_category"]:
        lines.append(f"  {e['category'] or 'Boshqa'}: {fmt(e['amount'])} so'm")
    await update.message.reply_text("\n".join(lines))


async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    with get_conn() as conn:
        chats = conn.execute(text("SELECT chat_id FROM telegram_users")).fetchall()
    if not chats:
        return
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    s = queries.get_summary(yesterday, yesterday)
    msg = (
        f"🌅 Kunlik hisobot ({yesterday})\n\n"
        f"Tushum: {fmt(s['revenue'])} so'm\n"
        f"Sof foyda: {fmt(s['net_profit'])} so'm\n"
        f"Buyurtmalar: {s['total_orders']} (bekor: {s['cancelled_orders']})"
    )
    for row in chats:
        try:
            await context.bot.send_message(chat_id=row.chat_id, text=msg)
        except Exception:
            logger.exception("Xabar yuborilmadi: %s", row.chat_id)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("month", month_cmd))
    app.add_handler(CommandHandler("stock", stock_cmd))
    app.add_handler(CommandHandler("expenses", expenses_cmd))

    app.job_queue.run_daily(daily_report_job, time=datetime.now().replace(
        hour=DAILY_REPORT_HOUR, minute=0, second=0, microsecond=0).timetz())

    logger.info("Bot ishga tushdi (polling)")
    app.run_polling()


if __name__ == "__main__":
    main()
