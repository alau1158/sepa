import pandas as pd


def _sma(series, period):
    return series.rolling(window=period).mean()


def detect_pullback(df):
    """Minervini-style pullback-to-MA re-entry detection.

    Identifies stocks that have broken out/run up and are now pulling
    back toward a key moving average (20d or 50d SMA) on declining
    volume — a classic re-entry or add-to-position setup.

    Returns (status: str, score: int).
    Status: "Pullback to MA", "Pulling Back", "Extended", "No Pullback"
    """
    if len(df) < 200:
        return "No Pullback", 0

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]

    sma20 = _sma(close, 20)
    sma50 = _sma(close, 50)
    sma150 = _sma(close, 150)
    sma200 = _sma(close, 200)
    vol_50d = vol.rolling(50).mean()

    # ── Phase 1: Basic checks ─────────────────────────────────────
    if any(pd.isna(s.iloc[-1]) for s in [sma20, sma50, sma150, sma200]):
        return "No Pullback", 0

    # Must be in uptrend (above all key MAs)
    c = close.iloc[-1]
    if not (c >= sma20.iloc[-1] and c >= sma50.iloc[-1]
            and c >= sma150.iloc[-1] and c >= sma200.iloc[-1]):
        return "No Pullback", 0

    # Must have had a meaningful run-up (peak price >= 5% above SMA50)
    high_20d = high.iloc[-20:].max()
    pct_above_50 = (high_20d - sma50.iloc[-1]) / sma50.iloc[-1] * 100
    if pct_above_50 < 5:
        return "No Pullback", 0

    # ── Phase 2: Pullback measurement ─────────────────────────────
    dist_from_high = (high_20d - c) / high_20d * 100

    # Must be pulling back (3-12% off recent high)
    if dist_from_high < 3:
        return "No Pullback", 0

    # Pullback depth guard: peak-to-trough within last 20 days
    low_20d = low.iloc[-20:].min()
    pullback_depth = (high_20d - low_20d) / high_20d * 100
    if pullback_depth > 18:
        return "No Pullback", 0

    # ── Phase 3: Proximity to MA ──────────────────────────────────
    dist_to_sma20 = abs(c - sma20.iloc[-1]) / sma20.iloc[-1] * 100
    dist_to_sma50 = abs(c - sma50.iloc[-1]) / sma50.iloc[-1] * 100
    dist_to_nearest_ma = min(dist_to_sma20, dist_to_sma50)
    nearest_ma = "SMA20" if dist_to_sma20 <= dist_to_sma50 else "SMA50"

    # ── Phase 4: Volume dry-up ────────────────────────────────────
    recent_vol_5d = vol.iloc[-5:].mean()
    if not pd.isna(vol_50d.iloc[-1]) and vol_50d.iloc[-1] > 0:
        vol_ratio = recent_vol_5d / vol_50d.iloc[-1]
    else:
        vol_ratio = 1.0

    # ── Phase 5: Scoring ──────────────────────────────────────────
    score = 0

    # 5a) Proximity to nearest MA (35 pts)
    if nearest_ma == "SMA20":
        if dist_to_sma20 <= 1.0:
            score += 35
        elif dist_to_sma20 <= 2.0:
            score += 28
        elif dist_to_sma20 <= 3.0:
            score += 20
        elif dist_to_sma20 <= 5.0:
            score += 10
    else:  # SMA50
        if dist_to_sma50 <= 1.0:
            score += 35
        elif dist_to_sma50 <= 2.0:
            score += 30
        elif dist_to_sma50 <= 3.0:
            score += 25
        elif dist_to_sma50 <= 5.0:
            score += 15

    # 5b) Volume vacuum during pullback (25 pts)
    if vol_ratio <= 0.5:
        score += 25
    elif vol_ratio <= 0.7:
        score += 20
    elif vol_ratio <= 0.85:
        score += 14
    elif vol_ratio <= 1.0:
        score += 7

    # 5c) Pullback depth quality (20 pts) — ideal 5-10%
    if 5 <= dist_from_high <= 10:
        score += 20
    elif 3 <= dist_from_high <= 14:
        score += 12
    elif dist_from_high < 3 or dist_from_high <= 16:
        score += 5

    # 5d) Uptrend health (20 pts)
    # SMA20 slope (rising = healthy)
    if not pd.isna(sma20.iloc[-1]) and not pd.isna(sma20.iloc[-10]):
        sma20_slope = (sma20.iloc[-1] - sma20.iloc[-10]) / sma20.iloc[-10] * 100
        if sma20_slope > 1:
            score += 8
        elif sma20_slope > 0:
            score += 4

    # SMA50 slope
    if not pd.isna(sma50.iloc[-1]) and not pd.isna(sma50.iloc[-10]):
        sma50_slope = (sma50.iloc[-1] - sma50.iloc[-10]) / sma50.iloc[-10] * 100
        if sma50_slope > 2:
            score += 7
        elif sma50_slope > 1:
            score += 4
        elif sma50_slope > 0:
            score += 2

    # Price still above SMA20 (bouncing/pre-bounce)
    if c > sma20.iloc[-1]:
        score += 5
    elif c > sma20.iloc[-1] * 0.98:
        score += 2

    # ── Phase 6: Classification ───────────────────────────────────
    score = int(min(100, max(0, score)))

    if score >= 65:
        status = "Pullback to MA"
    elif score >= 40:
        status = "Pulling Back"
    elif score >= 20:
        status = "Extended"
    else:
        status = "No Pullback"

    return status, score
