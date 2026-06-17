"""
TFX D-RSI Signal Bot — Telegram Bot for XAUUSD + EURUSD
Converted from Pine Script V26 BLACK-GOLD strategy.
Auto-scans every 15 minutes + supports on-demand /signal commands.
"""
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from drsi_strategy import DRSIStrategy
from price_feed import fetch_ohlc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── CONFIG ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = "8871976486:AAH-XZDgn2zC5dL41Wbv9cLZs7zwt-nhYCA"

PAIRS = ["XAUUSD", "EURUSD"]
SCAN_INTERVAL_SECONDS = 900  # 15 minutes
TIMEFRAME = "15min"

strategy = DRSIStrategy(
    rsi_length=14,
    window=28,
    degree=2,
    signal_length=2,
    entry_mode="signal_cross",   # "zero_cross" | "signal_cross" | "direction_change"
    rmse_filter=False,
    rmse_threshold=0.10,
    rr=2.0,
)

# Track subscribed chat IDs for auto-alerts + last alerted signal (avoid duplicate spam)
subscribed_chats = set()
last_signal_state = {pair: "NONE" for pair in PAIRS}


# ── FORMATTING ───────────────────────────────────────────────────────────────
def format_signal_message(pair, result):
    if "error" in result:
        return None

    signal = result["signal"]
    if signal == "NONE":
        return None

    emoji = "🟢" if signal == "BUY" else "🔴"
    fire = "🔥"

    msg = f"""{fire} *{pair} {signal}*
━━━━━━━━━━━━━━━━━━━━
📊 *Strategy:* TFX D-RSI (V26 Black-Gold)
📍 *Entry:* `{result['entry']}`
🛑 *Stop Loss:* `{result['stop_loss']}`
🎯 *Take Profit:* `{result['take_profit']}`
⚖️ *Risk:Reward:* 1:{result['rr']}
━━━━━━━━━━━━━━━━━━━━
📈 *D-RSI:* {result['drsi']}
📉 *Signal Line:* {result['signal_line']}
🧮 *RSI(14):* {result['rsi_value']}
📐 *Fit Error (NRMSE):* {result['nrmse_pct']}%
━━━━━━━━━━━━━━━━━━━━
🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | {TIMEFRAME} candle"""
    return msg


def format_status_message(pair, result):
    if "error" in result:
        return f"⚠️ *{pair}* — Data error: {result['error']}"

    signal = result["signal"]
    state_emoji = "🟢 BUY ZONE" if signal == "BUY" else "🔴 SELL ZONE" if signal == "SELL" else "⚪ NO SIGNAL"

    return f"""📊 *{pair}*
Status: {state_emoji}
D-RSI: {result['drsi']} | Signal Line: {result['signal_line']}
RSI(14): {result['rsi_value']}
Fit Error: {result['nrmse_pct']}%"""


# ── ANALYSIS CORE ────────────────────────────────────────────────────────────
def run_analysis(pair):
    data = fetch_ohlc(pair, interval=TIMEFRAME, outputsize=120)
    if "error" in data:
        return {"error": data["error"]}
    result = strategy.analyze(data["closes"], data["highs"], data["lows"])
    return result


# ── COMMAND HANDLERS ─────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subscribed_chats.add(chat_id)
    await update.message.reply_text(
        "🔥 *TFX D-RSI Signal Bot*\n"
        "_XAUUSD + EURUSD | Polynomial RSI Differentiator Strategy_\n\n"
        "✅ You're now subscribed to auto-alerts (every 15 min scan)\n\n"
        "*Commands:*\n"
        "/signal XAUUSD — Get current signal\n"
        "/signal EURUSD — Get current signal\n"
        "/status — Check both pairs now\n"
        "/stop — Unsubscribe from auto-alerts\n"
        "/rules — Strategy explanation",
        parse_mode=ParseMode.MARKDOWN,
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subscribed_chats.discard(chat_id)
    await update.message.reply_text("🔕 Unsubscribed from auto-alerts. Use /start to resume.")


async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    pair = args[0].upper() if args else "XAUUSD"

    if pair not in PAIRS:
        await update.message.reply_text(f"⚠️ Supported pairs: {', '.join(PAIRS)}\nUsage: /signal XAUUSD")
        return

    thinking = await update.message.reply_text(f"⚡ Fetching live {pair} data and calculating D-RSI...")

    result = run_analysis(pair)
    await thinking.delete()

    if "error" in result:
        await update.message.reply_text(f"❌ Error fetching {pair} data: {result['error']}")
        return

    msg = format_signal_message(pair, result)
    if msg:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        status_msg = format_status_message(pair, result)
        await update.message.reply_text(
            f"⚪ *NO ACTIVE SIGNAL*\n\n{status_msg}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["📊 *Live Status — All Pairs*\n"]
    for pair in PAIRS:
        result = run_analysis(pair)
        lines.append(format_status_message(pair, result))
        lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *TFX D-RSI Strategy Logic*\n\n"
        "1️⃣ Calculate RSI(14) on price\n"
        "2️⃣ Fit a 2nd-degree polynomial over a rolling 28-period window\n"
        "3️⃣ Take the derivative at the latest point → *D-RSI*\n"
        "4️⃣ Smooth D-RSI with EMA(2) → *Signal Line*\n\n"
        "*Entry Trigger (Signal Line Crossing mode):*\n"
        "🟢 BUY — D-RSI crosses ABOVE signal line\n"
        "🔴 SELL — D-RSI crosses BELOW signal line\n\n"
        "*Risk Management:*\n"
        "• SL = previous candle's low (BUY) / high (SELL)\n"
        "• TP = Entry ± (Risk × RR), default RR = 1:2\n\n"
        "*Optional Filter:*\n"
        "NRMSE (fit error) filter can suppress signals when the "
        "polynomial fit doesn't represent price well (choppy/noisy data)\n\n"
        f"⏱ Timeframe: {TIMEFRAME} | Scan interval: {SCAN_INTERVAL_SECONDS // 60} min",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── AUTO-SCAN JOB ─────────────────────────────────────────────────────────────
async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    if not subscribed_chats:
        return

    for pair in PAIRS:
        result = run_analysis(pair)
        if "error" in result:
            logger.warning(f"Auto-scan error for {pair}: {result['error']}")
            continue

        signal = result["signal"]
        if signal != "NONE" and signal != last_signal_state.get(pair):
            msg = format_signal_message(pair, result)
            if msg:
                for chat_id in list(subscribed_chats):
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
                    except Exception as e:
                        logger.error(f"Failed to send to {chat_id}: {e}")
            last_signal_state[pair] = signal
        elif signal == "NONE":
            last_signal_state[pair] = "NONE"


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("signal", signal_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))

    app.job_queue.run_repeating(auto_scan_job, interval=SCAN_INTERVAL_SECONDS, first=10)

    logger.info("TFX D-RSI Bot started — scanning XAUUSD + EURUSD every 15 min...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
