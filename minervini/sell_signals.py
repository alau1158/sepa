import pandas as pd


def _pct_chg(a, b):
    return (a - b) / b * 100


def compute_exhaustion_score(df, pe_ratio=None):
    """Exhaustion / climax-run detection (0–100). Higher = more overextended."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]
    vol_50d = vol.rolling(50).mean()
    len_df = len(df)

    if len_df < 65:
        return 0, "Normal"

    score = 0

    # ── 1. Climax Run (25 pts) ──────────────────────────────────────
    recent_close = close.iloc[-30:]
    max_run = 0.0
    for i in range(len(recent_close) - 1):
        for j in range(i + 1, min(i + 15, len(recent_close))):
            ret = _pct_chg(recent_close.iloc[j], recent_close.iloc[i])
            if ret > max_run:
                max_run = ret
    if max_run >= 50:
        score += 25
    elif max_run >= 35:
        score += 20
    elif max_run >= 25:
        score += 15
    elif max_run >= 15:
        score += 8

    # ── 2. Concentrated Up Days (20 pts) ────────────────────────────
    last_15 = close.iloc[-16:-1]
    up_days = 0
    total_days = 0
    for i in range(1, len(last_15)):
        total_days += 1
        if last_15.iloc[i] > last_15.iloc[i - 1]:
            up_days += 1
    if total_days > 0:
        up_ratio = up_days / total_days
        if up_ratio >= 0.80:
            score += 20
        elif up_ratio >= 0.70:
            score += 14
        elif up_ratio >= 0.60:
            score += 8

    # ── 3. Extreme Price Spread (20 pts) ────────────────────────────
    daily_range_pct = (high - low) / close.shift() * 100
    trailing_65 = daily_range_pct.iloc[-65:]
    if len(trailing_65) >= 15:
        max_spread = trailing_65.max()
        recent_max = trailing_65.iloc[-15:].max()
        if recent_max >= max_spread and max_spread > 0:
            avg_range = trailing_65.mean()
            ratio = recent_max / avg_range if avg_range > 0 else 1
            if ratio >= 3:
                score += 20
            elif ratio >= 2.5:
                score += 16
            elif ratio >= 2.0:
                score += 12
            elif ratio >= 1.5:
                score += 6

    # ── 4. Exhaustion Gap (15 pts) ──────────────────────────────────
    sma_50 = close.rolling(50).mean()
    dist_from_50 = _pct_chg(close.iloc[-1], sma_50.iloc[-1]) if not pd.isna(sma_50.iloc[-1]) else 0
    for i in range(-5, 0):
        if (pd.isna(low.iloc[i]) or pd.isna(high.iloc[i - 1])
                or pd.isna(close.iloc[i]) or pd.isna(high.iloc[i])):
            continue
        gap_up = low.iloc[i] > high.iloc[i - 1]
        held_gain = close.iloc[i] > high.iloc[i - 1]
        if gap_up and held_gain and dist_from_50 > 20:
            score += 15
            break

    # ── 5. Churning (10 pts) ────────────────────────────────────────
    churn_count = 0
    for i in range(-10, 0):
        if pd.isna(vol.iloc[i]) or pd.isna(vol_50d.iloc[i]):
            continue
        vr = vol.iloc[i] / vol_50d.iloc[i] if vol_50d.iloc[i] > 0 else 0
        pct = abs(_pct_chg(close.iloc[i], close.iloc[i - 1])) if not pd.isna(close.iloc[i - 1]) else 0
        if vr > 1.5 and pct < 0.5:
            churn_count += 1
    if churn_count >= 5:
        score += 10
    elif churn_count >= 3:
        score += 6
    elif churn_count >= 1:
        score += 3

    # ── 6. P/E Expansion (10 pts) ─────────────────────────────
    # Requires a pre-fetched trailingPE to avoid live API calls during
    # screening. Callers can pass pe_ratio=<value> if available; otherwise
    # this component is skipped (10 pts not allocated).
    if pe_ratio and pe_ratio > 0:
        start_close = close.iloc[-130] if len(close) >= 130 else close.iloc[0]
        pe_start_est = pe_ratio * (start_close / close.iloc[-1])
        if pe_start_est > 0 and pe_ratio / pe_start_est >= 2:
            score += 10
        elif pe_start_est > 0 and pe_ratio / pe_start_est >= 1.5:
            score += 5

    score = min(100, max(0, score))

    if score >= 60:
        status = "Exhausted"
    elif score >= 35:
        status = "Late Stage"
    else:
        status = "Normal"

    return score, status


def compute_distribution_score(df):
    """Distribution / selling-into-weakness detection (0–100). Higher = breaking down.

    Only recent events (last 3–7 days) contribute, so a stock that had a
    shakeout 10 days ago but has recovered won't carry old penalty.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    open_ = df["Open"]
    vol = df["Volume"]
    vol_50d = vol.rolling(50).mean()
    sma_50 = close.rolling(50).mean()
    len_df = len(df)

    if len_df < 65:
        return 0, "Normal"

    score = 0

    # ── 1. Major Price Break (30 pts) ───────────────────────────────
    daily_declines = _pct_chg(close, close.shift(1))
    trailing_65 = daily_declines.iloc[-65:]
    if len(trailing_65) >= 15:
        declines_only = trailing_65[trailing_65 < 0].abs()
        if len(declines_only) >= 5:
            max_decline = declines_only.max()
            avg_decline = declines_only.mean()
            # look at last 5 trading days specifically
            recent_5_raw = trailing_65.iloc[-5:]
            recent_5_declines = recent_5_raw[recent_5_raw < 0].abs()
            if len(recent_5_declines) == 0:
                recent_5_max = 0
            else:
                recent_5_max = recent_5_declines.max()
            if (recent_5_max == max_decline and avg_decline > 0
                    and recent_5_max > avg_decline * 2):
                ratio = recent_5_max / avg_decline
                if ratio >= 3:
                    score += 30
                elif ratio >= 2.5:
                    score += 25
                elif ratio >= 2.0:
                    score += 18
                elif ratio >= 1.5:
                    score += 10

    # ── 2. High-Volume Reversal (25 pts) ────────────────────────────
    for i in range(-5, 0):
        if (pd.isna(close.iloc[i]) or pd.isna(open_.iloc[i])
                or pd.isna(close.iloc[i - 1]) or pd.isna(vol.iloc[i])
                or pd.isna(vol_50d.iloc[i])):
            continue
        reversed_ = close.iloc[i] < open_.iloc[i] and close.iloc[i] < close.iloc[i - 1]
        heavy_vol = vol.iloc[i] > vol_50d.iloc[i] * 1.5
        if reversed_ and heavy_vol:
            score += 25
            break

    # ── 3. MA Violation (25 pts) ────────────────────────────────────
    # Only count if still below SMA50 today (not recovered)
    if not pd.isna(close.iloc[-1]) and not pd.isna(sma_50.iloc[-1]):
        if close.iloc[-1] < sma_50.iloc[-1]:
            for i in range(-5, 0):
                if (pd.isna(close.iloc[i]) or pd.isna(sma_50.iloc[i])
                        or pd.isna(vol.iloc[i]) or pd.isna(vol_50d.iloc[i])):
                    continue
                below_50 = close.iloc[i] < sma_50.iloc[i]
                heavy_vol = vol.iloc[i] > vol_50d.iloc[i] * 1.3
                if below_50 and heavy_vol:
                    score += 25
                    break
            else:
                if close.iloc[-1] < sma_50.iloc[-1]:
                    score += 12

    # ── 4. Full Retracement (20 pts) ────────────────────────────────
    low_50d = low.iloc[-50:].min()
    close_now = close.iloc[-1]
    if low_50d > 0:
        dist_from_low = _pct_chg(close_now, low_50d)
        if dist_from_low <= 5:
            score += 20
        elif dist_from_low <= 10:
            score += 12
        elif dist_from_low <= 15:
            score += 6

    score = min(100, max(0, score))

    if score >= 60:
        status = "Distribution"
    elif score >= 35:
        status = "Weakening"
    else:
        status = "Normal"

    return score, status
