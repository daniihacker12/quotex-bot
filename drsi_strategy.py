"""
TFX D-RSI Strategy Engine
Converts the Pine Script V26 BLACK-GOLD polynomial RSI differentiator
into Python for use with live market data.
"""
import numpy as np


def calc_rsi(prices, period=14):
    """Standard RSI calculation (Wilder's smoothing, matches Pine Script rsi())."""
    prices = np.array(prices, dtype=float)
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed > 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi_values = np.zeros(len(prices))
    rsi_values[:period] = 100.0 - 100.0 / (1.0 + rs)

    up_val, down_val = up, down
    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        upval = max(delta, 0)
        downval = -min(delta, 0)
        up_val = (up_val * (period - 1) + upval) / period
        down_val = (down_val * (period - 1) + downval) / period
        rs = up_val / down_val if down_val != 0 else 0
        rsi_values[i] = 100.0 - 100.0 / (1.0 + rs)
    return rsi_values


def poly_diff(rsi_series, window=28, degree=2):
    """
    Polynomial differentiator — replicates Pine Script's QR-decomposition
    based 'diff()' function using numpy least-squares polyfit (equivalent result).
    Returns (derivative_at_latest_point, normalized_rmse).
    """
    if len(rsi_series) < window:
        return None, None

    y = np.array(rsi_series[-window:], dtype=float)
    x = np.arange(window, dtype=float)

    coeffs = np.polyfit(x, y, degree)
    deriv_coeffs = np.polyder(coeffs)
    derivative = float(np.polyval(deriv_coeffs, window - 1))

    y_hat = np.polyval(coeffs, x)
    mse = np.mean((y - y_hat) ** 2)
    rmse = np.sqrt(mse)
    mean_y = np.mean(y)
    nrmse = float(rmse / mean_y) if mean_y != 0 else 0.0

    return derivative, nrmse


def ema(series, length):
    series = np.array(series, dtype=float)
    alpha = 2 / (length + 1)
    out = np.zeros(len(series))
    out[0] = series[0]
    for i in range(1, len(series)):
        out[i] = alpha * series[i] + (1 - alpha) * out[i - 1]
    return out


class DRSIStrategy:
    """
    Full conversion of TFX Gold Sniper V26 BLACK-GOLD logic:
    - RSI(14) base
    - Polynomial differentiator (window=28, degree=2) -> D-RSI value
    - Signal line = EMA(D-RSI, 2)
    - Entry triggers: Signal Line Crossing (default), Zero-Crossing, or Direction Change
    - RR box projection (default RR = 2.0)
    """

    def __init__(self, rsi_length=14, window=28, degree=2, signal_length=2,
                 entry_mode="signal_cross", rmse_filter=False, rmse_threshold=0.10,
                 rr=2.0):
        self.rsi_length = rsi_length
        self.window = window
        self.degree = degree
        self.signal_length = signal_length
        self.entry_mode = entry_mode  # "zero_cross" | "signal_cross" | "direction_change"
        self.rmse_filter = rmse_filter
        self.rmse_threshold = rmse_threshold
        self.rr = rr

    def analyze(self, closes, highs, lows):
        """
        closes/highs/lows: lists of recent OHLC values, oldest first.
        Returns a dict with signal, D-RSI value, NRMSE, and RR levels.
        """
        min_needed = self.rsi_length + self.window + 5
        if len(closes) < min_needed:
            return {"error": f"Need at least {min_needed} candles, got {len(closes)}"}

        rsi_series = calc_rsi(closes, self.rsi_length)
        valid_rsi = rsi_series[self.rsi_length:]

        # Rolling D-RSI series (need last few points for crossover detection)
        drsi_points = []
        lookback_points = max(self.signal_length + 3, 5)
        for i in range(lookback_points, 0, -1):
            sub_series = valid_rsi[: len(valid_rsi) - i + 1]
            if len(sub_series) < self.window:
                continue
            d, nrmse = poly_diff(sub_series, self.window, self.degree)
            drsi_points.append(d)

        if len(drsi_points) < 3:
            return {"error": "Not enough data points for D-RSI signal"}

        signal_line = ema(drsi_points, self.signal_length)

        drsi_now = drsi_points[-1]
        drsi_prev = drsi_points[-2]
        drsi_prev2 = drsi_points[-3] if len(drsi_points) >= 3 else drsi_prev
        sig_now = signal_line[-1]
        sig_prev = signal_line[-2]

        _, nrmse_now = poly_diff(valid_rsi, self.window, self.degree)
        filter_ok = (nrmse_now < self.rmse_threshold) if self.rmse_filter else True

        # Crossover detections
        cross_up = drsi_prev <= 0 and drsi_now > 0
        cross_dw = drsi_prev >= 0 and drsi_now < 0
        cross_sig_up = drsi_prev <= sig_prev and drsi_now > sig_now
        cross_sig_dw = drsi_prev >= sig_prev and drsi_now < sig_now
        dir_change_up = (drsi_now > drsi_prev) and (drsi_prev < drsi_prev2) and drsi_prev < 0
        dir_change_dw = (drsi_now < drsi_prev) and (drsi_prev > drsi_prev2) and drsi_prev > 0

        if self.entry_mode == "zero_cross":
            go_long, go_short = cross_up, cross_dw
        elif self.entry_mode == "direction_change":
            go_long, go_short = dir_change_up, dir_change_dw
        else:
            go_long, go_short = cross_sig_up, cross_sig_dw

        go_long = go_long and filter_ok
        go_short = go_short and filter_ok

        last_close = closes[-1]
        prev_low = lows[-2]
        prev_high = highs[-2]

        signal = "NONE"
        entry = sl = tp = None

        if go_long:
            signal = "BUY"
            entry = last_close
            sl = prev_low
            risk = entry - sl
            tp = entry + risk * self.rr if risk > 0 else None
        elif go_short:
            signal = "SELL"
            entry = last_close
            sl = prev_high
            risk = sl - entry
            tp = entry - risk * self.rr if risk > 0 else None

        return {
            "signal": signal,
            "drsi": round(drsi_now, 4),
            "signal_line": round(sig_now, 4),
            "nrmse_pct": round(nrmse_now * 100, 2) if nrmse_now else None,
            "filter_passed": filter_ok,
            "entry": round(entry, 5) if entry else None,
            "stop_loss": round(sl, 5) if sl else None,
            "take_profit": round(tp, 5) if tp else None,
            "rr": self.rr,
            "rsi_value": round(valid_rsi[-1], 2),
        }
