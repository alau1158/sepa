import pandas as pd


def _pct(a, b):
    return (a - b) / b * 100


def compute_violations(df, entry_price=None):
    """Minervini post-purchase violation detection.

    Checks for abnormal price/volume activity that suggests a
    trade is failing to meet expectations.

    Returns (count, score, status) where:
      count  = number of active violations (0–8)
      score  = weighted score 0–100
      status = Clean / Minor / Warning / Multiple
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]
    vol_50d = vol.rolling(50).mean()
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()

    if len(df) < 50:
        return 0, 0, "Clean"

    score = 0
    reasons = []

    # ── 1. Breach of 20-day SMA (15 pts) ────────────────────────────
    for i in range(-5, 0):
        if not pd.isna(close.iloc[i]) and not pd.isna(sma_20.iloc[i]):
            if close.iloc[i] < sma_20.iloc[i]:
                score += 15
                reasons.append("below 20 SMA")
                break

    # ── 2. Breach of 50-day SMA on heavy volume (25 pts) ────────────
    for i in range(-5, 0):
        if (pd.isna(close.iloc[i]) or pd.isna(sma_50.iloc[i])
                or pd.isna(vol.iloc[i]) or pd.isna(vol_50d.iloc[i])):
            continue
        if close.iloc[i] < sma_50.iloc[i] and vol.iloc[i] > vol_50d.iloc[i] * 1.3:
            score += 25
            reasons.append("50 SMA + heavy vol")
            break

    # ── 3. Three or Four Lower Lows (20 pts) ────────────────────────
    consecutive = 0
    max_consecutive = 0
    for i in range(-9, 0):
        if pd.isna(low.iloc[i]) or pd.isna(low.iloc[i - 1]):
            continue
        if low.iloc[i] < low.iloc[i - 1]:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0
    if max_consecutive >= 4:
        score += 20
        reasons.append("4+ lower lows")
    elif max_consecutive >= 3:
        score += 15
        reasons.append("3 lower lows")

    # ── 4. Poor Close-to-Range Ratio (15 pts) ───────────────────────
    last_10 = df.iloc[-11:-1]
    good_closes = 0
    bad_closes = 0
    up_days = 0
    down_days = 0
    for j in range(1, len(last_10)):
        hi = last_10["High"].iloc[j]
        lo = last_10["Low"].iloc[j]
        c = last_10["Close"].iloc[j]
        rng = hi - lo
        if rng > 0:
            pos = (c - lo) / rng
            if pos >= 0.5:
                good_closes += 1
            else:
                bad_closes += 1
        if c > last_10["Close"].iloc[j - 1]:
            up_days += 1
        else:
            down_days += 1
    if bad_closes > good_closes and down_days > up_days:
        score += 15
        reasons.append("poor closes + more down days")
    elif bad_closes > good_closes:
        score += 8
        reasons.append("poor close ratio")
    elif down_days > up_days:
        score += 7
        reasons.append("more down days")

    # ── 5. Low Volume Out, High Volume In (20 pts) ──────────────────
    if len(df) >= 30:
        recent_high_idx = close.iloc[-20:].idxmax()
        recent_high_pos = close.index.get_loc(recent_high_idx)
        rel_pos = recent_high_pos - (len(df) - len(close))
        if rel_pos <= -5:
            bo_vol = vol.iloc[recent_high_pos]
            bo_avg = vol.iloc[recent_high_pos - 10:recent_high_pos].mean()
            if bo_avg > 0 and bo_vol < bo_avg:
                subsequent = close.iloc[recent_high_pos + 1:]
                if not subsequent.empty and subsequent.iloc[-1] < close.iloc[recent_high_pos]:
                    last_third = vol.iloc[-int(len(vol) * 0.15):]
                    high_vol_days = (last_third > vol_50d.iloc[-len(last_third):] * 1.5).sum()
                    if high_vol_days >= 2:
                        score += 20
                        reasons.append("low vol out, high vol in")
                    else:
                        score += 10
                        reasons.append("low vol breakout")
                else:
                    score += 8
                    reasons.append("light vol breakout")

    # ── 6. Lack of Follow-Through (15 pts) ──────────────────────────
    for i in range(-10, -4):
        if pd.isna(close.iloc[i]) or pd.isna(close.iloc[i - 1]):
            continue
        gain = _pct(close.iloc[i], close.iloc[i - 1])
        if gain > 2 and not pd.isna(vol.iloc[i]) and not pd.isna(vol_50d.iloc[i]):
            stalled = True
            for k in range(i + 1, 0):
                if pd.isna(close.iloc[k]):
                    continue
                if close.iloc[k] > close.iloc[k - 1]:
                    stalled = False
                    break
            if stalled:
                score += 15
                reasons.append("no follow-through")
                break

    # ── 7. Full Retracement of Gains (20 pts) ───────────────────────
    if entry_price is not None and entry_price > 0:
        current = close.iloc[-1]
        max_since_entry = close.iloc[-30:].max() if len(close) >= 30 else close.max()
        best_gain = _pct(max_since_entry, entry_price)
        current_gain = _pct(current, entry_price)
        if best_gain >= 10 and current_gain <= 1:
            score += 20
            reasons.append(f"full retrace (was +{best_gain:.0f}%)")

    # ── 8. Abnormal Volume Reversal (20 pts) ────────────────────────
    lookback = min(30, len(close))
    recent = df.iloc[-lookback:]
    max_vol_in_move = recent["Volume"].max()
    for i in range(-5, 0):
        if (pd.isna(high.iloc[i]) or pd.isna(high.iloc[i - 1])
                or pd.isna(close.iloc[i]) or pd.isna(close.iloc[i - 1])
                or pd.isna(vol.iloc[i]) or pd.isna(vol_50d.iloc[i])):
            continue
        attempted_up = high.iloc[i] > high.iloc[i - 1]
        reversed_down = close.iloc[i] < close.iloc[i - 1]
        heavy_vol = vol.iloc[i] > vol_50d.iloc[i] * 1.5
        heaviest = vol.iloc[i] >= max_vol_in_move * 0.95
        if attempted_up and reversed_down and heavy_vol and heaviest:
            score += 20
            reasons.append("abnormal vol reversal")
            break

    score = min(100, max(0, score))

    if score >= 60:
        status = "Multiple"
    elif score >= 35:
        status = "Warning"
    elif score >= 15:
        status = "Minor"
    else:
        status = "Clean"

    return len(reasons), score, status, "; ".join(reasons) if reasons else ""
