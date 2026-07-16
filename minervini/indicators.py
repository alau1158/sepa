import pandas as pd
import numpy as np

WEEK_LOOKBACK = 252  # 52 weeks of trading days; SEPA Trend Template uses 52w lookback


def compute_sma(series, period):
    return series.rolling(window=period).mean()


def check_price_above_ma(df, period):
    sma = compute_sma(df["Close"], period)
    if pd.isna(sma.iloc[-1]):
        return False
    return df["Close"].iloc[-1] > sma.iloc[-1]


def check_ma_above_ma(df, period_upper, period_lower):
    sma_upper = compute_sma(df["Close"], period_upper)
    sma_lower = compute_sma(df["Close"], period_lower)
    if pd.isna(sma_upper.iloc[-1]) or pd.isna(sma_lower.iloc[-1]):
        return False
    return sma_upper.iloc[-1] > sma_lower.iloc[-1]


def check_ma_slope(df, period, lookback=22):
    sma = compute_sma(df["Close"], period)
    if len(sma) <= lookback or pd.isna(sma.iloc[-1]) or pd.isna(sma.iloc[-(lookback + 1)]):
        return False
    return sma.iloc[-1] > sma.iloc[-(lookback + 1)]


def compute_atr(df, period=22):
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period).mean()


def above_52w_low_pct(df, lookback=WEEK_LOOKBACK):
    if len(df) < lookback:
        return 0.0
    current = df["Close"].iloc[-1]
    low_52w = df["Close"].iloc[-lookback:].min()
    return ((current - low_52w) / low_52w) * 100


def within_52w_high_pct(df, lookback=WEEK_LOOKBACK):
    if len(df) < lookback:
        return 100.0
    current = df["Close"].iloc[-1]
    high_52w = df["Close"].iloc[-lookback:].max()
    return ((high_52w - current) / high_52w) * 100


def price_distance_from_sma(df, period):
    sma = compute_sma(df["Close"], period)
    if pd.isna(sma.iloc[-1]):
        return None
    return ((df["Close"].iloc[-1] - sma.iloc[-1]) / sma.iloc[-1]) * 100


def compute_atr_value(df, period=22):
    atr = compute_atr(df, period)
    if pd.isna(atr.iloc[-1]):
        return None
    pct = (atr.iloc[-1] / df["Close"].iloc[-1]) * 100
    return round(pct, 2)


def volume_near_50d_low(df, threshold_pct=10):
    vol = df["Volume"]
    if len(vol) < 50:
        return None, False
    low_50d = vol.rolling(50).min()
    current_low = low_50d.iloc[-1]
    current_vol = vol.iloc[-1]
    if current_low == 0:
        return None, False
    pct_above = round((current_vol - current_low) / current_low * 100, 1)
    return pct_above, pct_above <= threshold_pct


def compute_rs_line(stock_close, benchmark_close):
    """Return RS line series (stock / benchmark ratio)."""
    rs = stock_close / benchmark_close
    stock_close = stock_close.reindex(benchmark_close.index)
    rs = stock_close / benchmark_close
    return rs


def check_rs_line_trend(rs_line, min_days=65):
    """Check if RS line has been trending up for min_days.

    Returns (uptrend: bool, slope_pct: float).
    Slope is the % change over the period.
    """
    if len(rs_line) < min_days:
        return False, 0
    start = rs_line.iloc[-min_days]
    end = rs_line.iloc[-1]
    if pd.isna(start) or pd.isna(end) or start <= 0:
        return False, 0
    slope = (end - start) / start * 100
    return slope > 0, round(slope, 2)


def check_rs_divergence(rs_line, price, lookback=65):
    """Check if RS line made a new high before price.

    Returns 'Yes' if RS line 13-day high > previous 65-day high while
    price didn't. 'Partial' if both made new highs together.
    'No' otherwise.
    """
    if len(rs_line) < lookback + 13 or len(price) < lookback + 13:
        return "No"

    rs_recent = rs_line.iloc[-(lookback + 13):]
    pr_recent = price.iloc[-(lookback + 13):]

    rs_prior_high = rs_recent.iloc[:-13].max()
    rs_new_high = rs_recent.iloc[-13:].max()

    pr_prior_high = pr_recent.iloc[:-13].max()
    pr_new_high = pr_recent.iloc[-13:].max()

    rs_broke_out = rs_new_high > rs_prior_high * 1.01
    pr_broke_out = pr_new_high > pr_prior_high * 1.01

    if rs_broke_out and not pr_broke_out:
        return "Yes"
    if rs_broke_out and pr_broke_out:
        return "Partial"
    return "No"


def find_market_corrections(price_series, min_decline=5):
    """Find market correction periods (peak-to-trough declines >= min_decline%).

    Returns list of (peak_idx, trough_idx, decline_pct).
    """
    prices = price_series.values
    n = len(prices)
    corrections = []
    peak_idx = 0
    peak_val = prices[0]

    for i in range(1, n):
        if prices[i] > peak_val:
            peak_val = prices[i]
            peak_idx = i
        decline = (peak_val - prices[i]) / peak_val * 100
        if decline >= min_decline:
            # Find the actual trough (lowest price) after the peak
            trough_idx = i
            trough_val = prices[i]
            for j in range(i + 1, n):
                if prices[j] < trough_val:
                    trough_val = prices[j]
                    trough_idx = j
                # Check if recovery from the lowest point reaches half the decline
                recovery = (prices[j] - trough_val) / trough_val * 100
                if recovery >= decline * 0.5:
                    break
            corrections.append({
                "peak_idx": peak_idx,
                "peak_val": peak_val,
                "trough_idx": trough_idx,
                "trough_val": trough_val,
                "decline_pct": round(decline, 1),
            })
            peak_val = prices[trough_idx]
            peak_idx = trough_idx

    return corrections


def check_correction_divergence(stock_df, spy_df, min_decline=5):
    """Check if stock made higher lows during market corrections.

    Returns 'Strong' (higher lows during all major corrections),
    'Moderate' (mixed), or 'Weak' (followed market down).
    """
    spy_corrections = find_market_corrections(spy_df["Close"], min_decline)
    if not spy_corrections:
        return "Neutral"

    # Reindex stock data onto SPY's date index so positional indices align
    stock_low = stock_df["Low"].reindex(spy_df.index)
    stock_close = stock_df["Close"].reindex(spy_df.index)

    stock_lows = []
    for corr in spy_corrections:
        pk, tr = corr["peak_idx"], corr["trough_idx"]
        if pk >= len(stock_low) or tr >= len(stock_low):
            continue
        stock_peak = stock_low.iloc[pk:tr + 1].min()
        stock_before = stock_low.iloc[max(0, pk - 20):pk + 1].min()
        if stock_before > 0 and not pd.isna(stock_before) and not pd.isna(stock_peak):
            stock_lows.append(stock_peak > stock_before)

    if not stock_lows:
        return "Neutral"

    ratio = sum(stock_lows) / len(stock_lows)
    if ratio >= 0.7:
        return "Strong"
    elif ratio >= 0.4:
        return "Moderate"
    else:
        return "Weak"


def compute_ad_rating(df):
    """Minervini-style composite A/D rating (0-100).

    Components:
      1. Magnitude-weighted volume ratio  (30 pts) — up/down volume weight balance
      2. Follow-through up-day count      (20 pts) — % up days in last 10
      3. Volume dry-up at pivot           (20 pts) — recent 5d vol vs 50d avg
      4. RS line trend proxy             (15 pts) — close/SMA50 slope
      5. Tennis-ball snapback & churning  (15 pts) — pullback recovery speed + low churn
    """
    if len(df) < 65:
        return "C", 50

    vol_50d = df["Volume"].iloc[-50:].mean()

    # ── 1. Magnitude-weighted volume ratio (30 pts) ──────────────────
    pos_w = 0.0
    neg_w = 0.0
    for i in range(-64, 0):
        chg = df["Close"].iloc[i] - df["Close"].iloc[i - 1]
        vr = df["Volume"].iloc[i] / vol_50d
        if vr < 1.0:
            continue
        w = min(vr, 3.0)  # cap at 3×
        if chg > 0:
            pos_w += w
        elif chg < 0:
            neg_w += w

    total_w = pos_w + neg_w
    mag_ratio = pos_w / total_w if total_w > 0 else 0.5
    mag_pts = mag_ratio * 30

    # ── 2. Follow-through ratio (20 pts) ────────────────────────────
    last_10 = df.iloc[-11:-1]
    up = 0
    dn = 0
    for j in range(1, len(last_10)):
        if last_10["Close"].iloc[j] > last_10["Close"].iloc[j - 1]:
            up += 1
        else:
            dn += 1
    total_days = up + dn
    up_ratio = up / total_days if total_days > 0 else 0.5
    # 50% up-days → 10 pts, 80% up-days → 20 pts
    follow_pts = max(0, min(20, up_ratio * 25))

    # ── 3. Volume dry-up at pivot (20 pts) ──────────────────────────
    recent_vol = df["Volume"].iloc[-5:].mean()
    vol_dry_ratio = recent_vol / vol_50d
    if vol_dry_ratio <= 0.4:
        dry_pts = 20
    elif vol_dry_ratio <= 1.0:
        dry_pts = 20 * (1 - (vol_dry_ratio - 0.4) / 0.6)
    else:
        dry_pts = 0

    # ── 4. RS line trend proxy (15 pts) ────────────────────────────
    sma_50 = compute_sma(df["Close"], 50)
    if len(sma_50) >= 65 and not pd.isna(sma_50.iloc[-31]):
        r30 = df["Close"].iloc[-31] / sma_50.iloc[-31]
        r0  = df["Close"].iloc[-1] / sma_50.iloc[-1]
        rs_slope = (r0 - r30) / r30 * 100 if r30 > 0 else 0
    else:
        rs_slope = 0

    if rs_slope > 2:
        rs_pts = 15
    elif rs_slope > 0:
        rs_pts = 10
    elif rs_slope > -2:
        rs_pts = 5
    else:
        rs_pts = 0

    # ── 5. Tennis-ball snapback & churning (15 pts) ─────────────────
    # Churning: high-volume days with tiny price moves
    churn = 0
    for i in range(-64, 0):
        vr = df["Volume"].iloc[i] / vol_50d
        pct = abs(df["Close"].iloc[i] - df["Close"].iloc[i - 1]) / df["Close"].iloc[i - 1] * 100
        if vr > 1.5 and pct < 0.5:
            churn += 1
    if churn <= 3:
        churn_pts = 7
    elif churn <= 8:
        churn_pts = 4
    else:
        churn_pts = 1

    # Tennis ball: check if price has recovered to near the 50-day high
    high_50d = df["High"].iloc[-50:].max()
    close_now = df["Close"].iloc[-1]
    snap = close_now / high_50d if high_50d > 0 else 0.9
    if snap >= 1.0:
        snap_pts = 8
    elif snap >= 0.97:
        snap_pts = 5
    elif snap >= 0.93:
        snap_pts = 2
    else:
        snap_pts = 0

    tennis_pts = min(15, churn_pts + snap_pts)

    # ── Composite ───────────────────────────────────────────────────
    total = mag_pts + follow_pts + dry_pts + rs_pts + tennis_pts
    total = round(min(100, max(0, total)))

    if total >= 68:
        letter = "A"
    elif total >= 61:
        letter = "B"
    elif total >= 42:
        letter = "C"
    elif total >= 33:
        letter = "D"
    else:
        letter = "E"

    return letter, total
