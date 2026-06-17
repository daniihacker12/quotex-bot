"""
Live price data fetcher.
Uses Twelve Data free API (800 requests/day free tier) for OHLC candles.
Get a free key at: https://twelvedata.com/apikey
"""
import requests

TWELVE_DATA_KEY = "90bbe33955ca4f93ab6998d133e87618"

SYMBOL_MAP = {
    "XAUUSD": "XAU/USD",
    "EURUSD": "EUR/USD",
}


def fetch_ohlc(symbol, interval="15min", outputsize=120, api_key=TWELVE_DATA_KEY):
    """
    Fetch recent OHLC candles for a symbol.
    Returns dict with 'closes', 'highs', 'lows' (oldest first) or None on failure.
    """
    td_symbol = SYMBOL_MAP.get(symbol, symbol)
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": td_symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key,
        "format": "JSON",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        if data.get("status") == "error" or "values" not in data:
            return {"error": data.get("message", "Unknown API error")}

        values = data["values"]
        values.reverse()  # API returns newest first; we need oldest first

        closes = [float(v["close"]) for v in values]
        highs = [float(v["high"]) for v in values]
        lows = [float(v["low"]) for v in values]

        return {"closes": closes, "highs": highs, "lows": lows, "latest_time": values[-1]["datetime"]}

    except Exception as e:
        return {"error": str(e)}
