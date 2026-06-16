"""
Quotex ICT Signal Bot — Telegram Self-Running Version
======================================================
Runs 24/7 on Railway.app (free cloud hosting)
You control it 100% from Telegram on your phone

Commands you can send in Telegram:
  /start   - Start the bot
  /scan    - Scan all pairs now
  /auto    - Turn on auto signals every 1 minute
  /stop    - Turn off auto signals
  /status  - Check if bot is running
  /pairs   - See which pairs are being scanned
"""

import urllib.request
import urllib.parse
import json
import time
import threading
from datetime import datetime
import os

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8758667468:AAGjQhPgjC6sFmfcpuxqsYrb_X7VgfN6C5o")
TWELVE_DATA_KEY    = os.environ.get("TWELVE_DATA_KEY", "79effd4d5f714ff49fa73bc7f906d6c1")

SYMBOLS        = ["EUR/USD", "GBP/USD", "XAU/USD", "AUD/USD", "USD/JPY"]
EXPIRY_MINUTES = 5
SWING_LOOKBACK = 5
FVG_THRESHOLD  = 0.0001
# ────────────────────────────────────────────────────────────────────────────────

auto_mode   = {}   # chat_id → True/False
last_signal = {}   # symbol → timestamp
last_update = 0    # last Telegram update ID


# ── TELEGRAM HELPERS ──────────────────────────────────────────────────────────

def tg_request(method, params={}):
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
        data = urllib.parse.urlencode(params).encode("utf-8")
        req  = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"TG error: {e}")
        return {}


def send_msg(chat_id, text):
    tg_request("sendMessage", {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "HTML"
    })


def get_updates(offset=0):
    result = tg_request("getUpdates", {
        "offset":  offset,
        "timeout": 30
    })
    return result.get("result", [])


# ── DATA ──────────────────────────────────────────────────────────────────────

def get_candles(symbol):
    try:
        sym = urllib.parse.quote(symbol)
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={sym}&interval=1min&outputsize=60"
            f"&apikey={TWELVE_DATA_KEY}"
        )
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
        if "values" not in data:
            return []
        candles = []
        for v in reversed(data["values"]):
            candles.append({
                "o": float(v["open"]),
                "h": float(v["high"]),
                "l": float(v["low"]),
                "c": float(v["close"]),
            })
        return candles
    except:
        return []


# ── ICT LOGIC ─────────────────────────────────────────────────────────────────

def find_swings(candles, lookback):
    highs, lows = [], []
    n = len(candles)
    for i in range(lookback, n - lookback):
        wh = [candles[j]["h"] for j in range(i - lookback, i + lookback + 1)]
        wl = [candles[j]["l"] for j in range(i - lookback, i + lookback + 1)]
        if candles[i]["h"] == max(wh):
            highs.append((i, candles[i]["h"]))
        if candles[i]["l"] == min(wl):
            lows.append((i, candles[i]["l"]))
    return highs, lows


def detect_sweep(candles, highs, lows):
    last = candles[-2]
    n    = len(candles)

    if lows:
        recent = [p for (i, p) in lows if i < n - 2]
        if recent:
            lvl = max(recent)
            if last["l"] < lvl and last["c"] > lvl:
                return ("CALL", lvl)

    if highs:
        recent = [p for (i, p) in highs if i < n - 2]
        if recent:
            lvl = min(recent)
            if last["h"] > lvl and last["c"] < lvl:
                return ("PUT", lvl)

    return None


def detect_fvg(candles, direction):
    if len(candles) < 4:
        return None
    c1, c3 = candles[-4], candles[-2]
    if direction == "CALL" and (c1["l"] - c3["h"]) >= FVG_THRESHOLD:
        return (c1["l"], c3["h"])
    if direction == "PUT"  and (c3["l"] - c1["h"]) >= FVG_THRESHOLD:
        return (c3["l"], c1["h"])
    return None


def price_in_fvg(price, fvg):
    return fvg[1] <= price <= fvg[0]


# ── SIGNAL ────────────────────────────────────────────────────────────────────

def scan_one(symbol):
    """Scan one symbol. Returns signal message or None."""
    candles = get_candles(symbol)
    if len(candles) < 20:
        return None

    sh, sl  = find_swings(candles, SWING_LOOKBACK)
    sweep   = detect_sweep(candles, sh, sl)
    if not sweep:
        return None

    direction, sweep_lvl = sweep
    fvg = detect_fvg(candles, direction)
    if not fvg:
        return None

    price = candles[-1]["c"]
    if not price_in_fvg(price, fvg):
        return None

    # Deduplicate within 5 min
    now = time.time()
    key = f"{symbol}_{direction}"
    if key in last_signal and (now - last_signal[key]) < 300:
        return None
    last_signal[key] = now

    emoji = "🟢" if direction == "CALL" else "🔴"
    ts    = datetime.utcnow().strftime("%H:%M UTC")
    return (
        f"{emoji} <b>QUOTEX SIGNAL</b> {emoji}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Pair    :</b> {symbol}\n"
        f"📊 <b>Signal  :</b> <b>{direction}</b>\n"
        f"⏱ <b>Candle  :</b> 1 Minute\n"
        f"⏳ <b>Expiry  :</b> {EXPIRY_MINUTES} minutes\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💧 <b>Sweep   :</b> {sweep_lvl:.5f}\n"
        f"📐 <b>FVG Zone:</b> {fvg[1]:.5f} – {fvg[0]:.5f}\n"
        f"💲 <b>Entry   :</b> {price:.5f}\n"
        f"🕐 <b>Time    :</b> {ts}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>Max 2% risk per trade!</i>"
    )


def scan_all(chat_id):
    """Scan all symbols and send signals to chat."""
    send_msg(chat_id, "🔍 Scanning all pairs... please wait")
    found = 0
    for sym in SYMBOLS:
        msg = scan_one(sym)
        if msg:
            send_msg(chat_id, msg)
            found += 1
        time.sleep(2)
    if found == 0:
        send_msg(chat_id, "😴 No valid setups right now. Try again in 1-2 minutes.")


# ── AUTO MODE THREAD ──────────────────────────────────────────────────────────

def auto_scan_loop(chat_id):
    """Runs in background, sends signals every 60s while auto mode is on."""
    while auto_mode.get(chat_id):
        for sym in SYMBOLS:
            if not auto_mode.get(chat_id):
                break
            msg = scan_one(sym)
            if msg:
                send_msg(chat_id, msg)
            time.sleep(2)
        time.sleep(60)
    send_msg(chat_id, "⏹ Auto scan stopped.")


# ── COMMAND HANDLER ───────────────────────────────────────────────────────────

def handle_command(chat_id, text):
    cmd = text.strip().lower().split()[0]

    if cmd == "/start":
        send_msg(chat_id,
            "👋 <b>Welcome to Quotex ICT Signal Bot!</b>\n\n"
            "Commands:\n"
            "📡 /scan — Scan all pairs now\n"
            "🤖 /auto — Auto signals every 1 min\n"
            "⏹ /stop — Stop auto signals\n"
            "📊 /pairs — Show scanned pairs\n"
            "✅ /status — Bot status\n\n"
            "Strategy: <b>Liquidity Sweep + FVG</b>\n"
            "Timeframe: <b>1 Minute</b>"
        )

    elif cmd == "/scan":
        threading.Thread(target=scan_all, args=(chat_id,), daemon=True).start()

    elif cmd == "/auto":
        if auto_mode.get(chat_id):
            send_msg(chat_id, "⚡ Auto mode is already ON!")
        else:
            auto_mode[chat_id] = True
            send_msg(chat_id,
                "🤖 <b>Auto mode ON!</b>\n"
                "Signals will be sent automatically.\n"
                "Send /stop to turn off."
            )
            threading.Thread(target=auto_scan_loop, args=(chat_id,), daemon=True).start()

    elif cmd == "/stop":
        auto_mode[chat_id] = False
        send_msg(chat_id, "⏹ Stopping auto scan...")

    elif cmd == "/pairs":
        pairs_list = "\n".join([f"  • {s}" for s in SYMBOLS])
        send_msg(chat_id, f"📊 <b>Scanning pairs:</b>\n{pairs_list}")

    elif cmd == "/status":
        mode = "🟢 AUTO ON" if auto_mode.get(chat_id) else "🔴 AUTO OFF"
        send_msg(chat_id,
            f"✅ <b>Bot is running!</b>\n"
            f"Mode: {mode}\n"
            f"Pairs: {len(SYMBOLS)}\n"
            f"Time: {datetime.utcnow().strftime('%H:%M UTC')}"
        )

    else:
        send_msg(chat_id,
            "❓ Unknown command. Send /start to see all commands."
        )


# ── MAIN POLLING LOOP ─────────────────────────────────────────────────────────

def main():
    global last_update
    print("🤖 Quotex Signal Bot starting...")
    print(f"   Pairs: {', '.join(SYMBOLS)}")

    # Send startup message to anyone who last used bot
    print("   Bot is ready! Send /start in Telegram.")

    while True:
        try:
            updates = get_updates(offset=last_update + 1)
            for update in updates:
                last_update = update["update_id"]
                msg = update.get("message", {})
                if not msg:
                    continue
                chat_id = msg["chat"]["id"]
                text    = msg.get("text", "")
                if text.startswith("/"):
                    print(f"  CMD: {text} from {chat_id}")
                    handle_command(chat_id, text)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(5)
        time.sleep(1)


if __name__ == "__main__":
    main()
