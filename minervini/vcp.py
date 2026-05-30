import pandas as pd


def _find_swing_points(series, window=5):
    """Find swing high (H) and swing low (L) indices in a price Series.
    Returns list of (index, type, value).
    """
    points = []
    for i in range(window, len(series) - window):
        seg = series.iloc[i - window : i + window + 1]
        if series.iloc[i] == seg.max():
            points.append((i, "H", series.iloc[i]))
        if series.iloc[i] == seg.min():
            points.append((i, "L", series.iloc[i]))
    if not points:
        return []
    cleaned = [points[0]]
    for p in points[1:]:
        if p[1] == cleaned[-1][1]:
            if p[1] == "H" and p[2] > cleaned[-1][2]:
                cleaned[-1] = p
            elif p[1] == "L" and p[2] < cleaned[-1][2]:
                cleaned[-1] = p
        else:
            cleaned.append(p)
    return cleaned


def detect_vcp(df):
    """Minervini Volatility Contraction Pattern detection.
    Uses swing-based pullback identification with halving rule, final
    tightness, and volume dry-up confirmation.
    """
    if len(df) < 30:
        return "No VCP", 0

    close = df["Close"]
    high = df["High"]
    vol = df["Volume"]
    vol_50d = vol.rolling(50).mean()

    lookback = min(225, len(df))
    segment = df.iloc[-lookback:]

    swings = _find_swing_points(segment["Close"])
    if len(swings) < 2:
        return "No VCP", 0

    highs = [(i, v) for i, t, v in swings if t == "H"]
    if not highs:
        return "No VCP", 0

    base_top_idx, _ = max(highs, key=lambda x: x[1])

    post_top = [s for s in swings if s[0] >= base_top_idx]

    pullbacks = []
    for i in range(len(post_top) - 1):
        if post_top[i][1] == "H" and post_top[i + 1][1] == "L":
            depth = (post_top[i][2] - post_top[i + 1][2]) / post_top[i][2] * 100
            if depth >= 3:
                pullbacks.append({
                    "depth": depth,
                    "high_price": post_top[i][2],
                    "low_price": post_top[i + 1][2],
                })

    T = len(pullbacks)
    if T < 2:
        return "No VCP", 0

    score = 0

    # 1) Base Duration (10 pts) — 2 to 45 weeks
    base_dur = len(segment) - base_top_idx
    if 14 <= base_dur <= 225:
        score += 10

    # 2) Pullback Count (10 pts)
    score += min(10, T * 5)

    # 3) Halving Rule (25 pts)
    halving_ok = True
    for i in range(1, T):
        if pullbacks[i]["depth"] > pullbacks[i - 1]["depth"] * 0.65:
            halving_ok = False
            break
    if halving_ok:
        score += 25
    elif T >= 2:
        ok = sum(1 for i in range(1, T)
                 if pullbacks[i]["depth"] <= pullbacks[i - 1]["depth"] * 0.65)
        score += int(25 * ok / (T - 1))

    # 4) Final Tightness (25 pts)
    final_depth = pullbacks[-1]["depth"]
    if final_depth <= 7:
        score += 25
    elif final_depth <= 10:
        score += 20
    elif final_depth <= 15:
        score += 10

    # 5) Volume Dry-Up (15 pts) — last 5d vs 50d avg
    recent_vol = vol.iloc[-5:].mean()
    vol_avg = vol_50d.iloc[-1] if not pd.isna(vol_50d.iloc[-1]) else 0
    if vol_avg > 0:
        vol_ratio = recent_vol / vol_avg
        if vol_ratio < 0.7:
            score += 15
        elif vol_ratio < 0.9:
            score += 10
        elif vol_ratio < 1.1:
            score += 5

    # 6) Selling Vacuum (10 pts) — 1+ day at base-lowest volume
    base_vol = segment["Volume"]
    if len(base_vol) > 0:
        min_vol = base_vol.min()
        recent_min = vol.iloc[-10:].min()
        if recent_min == min_vol:
            score += 10
        elif not pd.isna(vol_avg) and vol.iloc[-1] < vol_avg * 0.5:
            score += 5

    # 7) Breakout Trigger (5 pts)
    tight_high = high.iloc[-5:].max()
    latest_close = close.iloc[-1]
    latest_vol = vol.iloc[-1]
    if latest_close > tight_high and not pd.isna(vol_avg) and vol_avg > 0:
        if latest_vol > vol_avg * 1.25:
            score += 5

    score = int(min(100, max(0, score)))

    if score >= 60:
        status = "VCP Tight"
    elif score >= 45:
        status = "VCP Forming"
    else:
        status = "No VCP"

    return status, score
