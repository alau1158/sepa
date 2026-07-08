import numpy as np
import pandas as pd


def _find_contractions_zigzag(seg, resistance_idx, resistance_level):
    """Find VCP contractions via alternating local peaks and troughs.

    After resistance is established:
    1. Find the deepest pullback (first contraction).
    2. Find the first local peak that reaches near resistance (>= 85%).
    3. Find the next local trough (shallower contraction).
    4. Repeat until no more contractions or pattern breaks.

    Returns list of dicts: {'idx', 'low_price', 'depth'}.
    """
    after_resistance = seg.iloc[resistance_idx + 1:]
    if len(after_resistance) < 10:
        return []

    first_low_rel = int(after_resistance["Low"].values.argmin())
    first_low_idx = resistance_idx + 1 + first_low_rel
    first_low_val = float(after_resistance["Low"].iloc[first_low_rel])
    first_depth = (resistance_level - first_low_val) / resistance_level * 100

    if first_depth < 3:
        return []

    contractions = [{
        "idx": first_low_idx,
        "low_price": first_low_val,
        "depth": first_depth,
    }]

    current_idx = first_low_idx

    for _ in range(5):
        # ── Find recovery peak: first LOCAL maximum near resistance ──
        after_low = seg.iloc[current_idx + 1:]
        if len(after_low) < 10:
            break

        window = 5
        recovery_idx = None
        recovery_val = None

        # Scan for first local peak that reaches >= 85% of resistance
        for i in range(window, len(after_low) - window):
            seg_high = after_low["High"].iloc[i - window:i + window + 1]
            if after_low["High"].iloc[i] == seg_high.max():
                hv = float(after_low["High"].iloc[i])
                if hv >= resistance_level * 0.85:
                    recovery_idx = current_idx + 1 + i
                    recovery_val = hv
                    break

        # Fallback: search for the highest point within the first
        # 40 trading days that reaches >= 85% of resistance
        if recovery_idx is None:
            search_len = min(40, len(after_low))
            head = after_low.iloc[:search_len]
            if len(head) > 0:
                best_rel = int(head["High"].values.argmax())
                best_val = float(head["High"].iloc[best_rel])
                if best_val >= resistance_level * 0.85:
                    recovery_idx = current_idx + 1 + best_rel
                    recovery_val = best_val

        if recovery_idx is None:
            break

        # ── Find next contraction low after recovery peak ──
        after_recovery = seg.iloc[recovery_idx + 1:]
        if len(after_recovery) < 5:
            break

        next_low = None

        # Find local minima with window=5
        for i in range(window, len(after_recovery) - window):
            seg_low = after_recovery["Low"].iloc[i - window:i + window + 1]
            if after_recovery["Low"].iloc[i] == seg_low.min():
                low_val = float(after_recovery["Low"].iloc[i])
                low_idx = recovery_idx + 1 + i
                low_depth = (resistance_level - low_val) / resistance_level * 100
                if low_depth >= 2:
                    if next_low is None or low_val < next_low["low_price"]:
                        next_low = {
                            "idx": low_idx,
                            "low_price": low_val,
                            "depth": low_depth,
                        }

        # Fallback: global minimum in the tail (skipping first 3 days)
        if next_low is None and len(after_recovery) >= 8:
            search_data = after_recovery.iloc[3:]
            if len(search_data) > 0:
                min_rel = int(search_data["Low"].values.argmin())
                min_val = float(search_data["Low"].iloc[min_rel])
                min_idx = recovery_idx + 1 + 3 + min_rel
                min_depth = (resistance_level - min_val) / resistance_level * 100
                if min_depth >= 2:
                    next_low = {
                        "idx": min_idx,
                        "low_price": min_val,
                        "depth": min_depth,
                    }

        if next_low is None:
            break

        # Next contraction must be shallower than previous
        if next_low["depth"] >= contractions[-1]["depth"]:
            break

        contractions.append(next_low)
        current_idx = next_low["idx"]

    return contractions


def detect_vcp(df):
    """Minervini Volatility Contraction Pattern detection.

    Identifies VCP by finding a resistance ceiling, then walking an
    alternating zigzag of recovery peaks and decreasing pullback lows.
    Validates the halving rule, final tightness, volume vacuum, and
    hard-filters stocks that have already broken out.

    Returns (status: str, score: int).
    Status: "VCP Tight", "VCP Forming", "No VCP", "Already Broken Out"
    """
    if len(df) < 130:
        return "No VCP", 0

    close = df["Close"]
    vol = df["Volume"]
    vol_50d = vol.rolling(50, min_periods=20).mean()

    lookback = min(250, len(df))
    seg = df.iloc[-lookback:].copy().reset_index(drop=True)

    # ── Phase 1: Resistance level ─────────────────────────────────────
    # Find the resistance ceiling in the first portion of the segment,
    # leaving at least 25 trading days for base formation after it.
    min_base_days = 25
    cutoff = len(seg) - min_base_days
    if cutoff < 20:
        return "No VCP", 0

    # Find the highest high in the first portion — this defines resistance.
    # Then find the FIRST time price reached near that level — this marks
    # when resistance was established and where the base begins.
    resistance_level = float(seg["High"].iloc[:cutoff].max())

    # Walk forward from the start to find the first time price
    # reached within 2% of resistance, so resistance_idx points to the
    # BEGINNING of the base rather than a later re-test.
    argmax_idx = int(seg["High"].iloc[:cutoff].values.argmax())
    threshold = resistance_level * 0.98
    resistance_idx = argmax_idx
    for i in range(argmax_idx):
        if seg["High"].iloc[i] >= threshold:
            resistance_idx = i
            break

    current_close = float(close.iloc[-1])

    # ── Phase 2: Contraction sequence (zigzag) ─────────────────────────
    contractions = _find_contractions_zigzag(seg, resistance_idx, resistance_level)

    T = len(contractions)
    if T < 2:
        return "No VCP", 0

    # ── Phase 3: Hard Filters ──────────────────────────────────────────
    if current_close > resistance_level * 1.02:
        return "Already Broken Out", 0

    if current_close < resistance_level * 0.90:
        return "No VCP", 0

    first_depth = contractions[0]["depth"]
    if first_depth < 10 or first_depth > 50:
        return "No VCP", 0

    # ── Phase 4: Scoring ───────────────────────────────────────────────
    score = 0
    base_duration = len(seg) - 1 - resistance_idx

    # 4a) Base Duration (10 pts) — ideal 7-30 weeks, acceptable 5-50 weeks
    if 35 <= base_duration <= 150:    # 7-30 weeks
        score += 10
    elif 25 <= base_duration <= 250:  # 5-50 weeks
        score += 5

    # 4b) Contraction Count (10 pts) — 2-6 is ideal
    if 2 <= T <= 6:
        score += 10
    else:
        score += 3

    # 4c) Halving Rule (25 pts) — each contraction <=60% of previous
    halving_passes = 0
    halving_total = 0
    for i in range(1, T):
        halving_total += 1
        if contractions[i]["depth"] <= contractions[i - 1]["depth"] * 0.60:
            halving_passes += 1

    if halving_total > 0:
        score += int(25 * halving_passes / halving_total)

    # 4d) Final Tightness (25 pts)
    final_depth = contractions[-1]["depth"]

    if final_depth <= 3:
        score += 15
    elif final_depth <= 5:
        score += 12
    elif final_depth <= 10:
        score += 8
    elif final_depth <= 15:
        score += 3

    last_n = min(10, len(seg))
    recent_closes = seg["Close"].iloc[-last_n:]
    if recent_closes.mean() > 0:
        close_std_pct = recent_closes.std() / recent_closes.mean() * 100
        if close_std_pct <= 1.0:
            score += 10
        elif close_std_pct <= 2.0:
            score += 7
        elif close_std_pct <= 3.0:
            score += 3

    # 4e) Volume Vacuum (15 pts)
    vol_avg = float(vol_50d.iloc[-1]) if not pd.isna(vol_50d.iloc[-1]) else 0

    recent_vol_5d = float(seg["Volume"].iloc[-5:].mean())
    if vol_avg > 0:
        vol_ratio = recent_vol_5d / vol_avg
        if vol_ratio < 0.5:
            score += 8
        elif vol_ratio < 0.7:
            score += 6
        elif vol_ratio < 0.9:
            score += 3

    base_vols = seg["Volume"].values
    if len(base_vols) > 0:
        base_vol_p10 = np.percentile(base_vols, 10)
        recent_10d_min = float(seg["Volume"].iloc[-10:].min())
        if recent_10d_min <= base_vol_p10:
            score += 5
        elif recent_10d_min <= np.percentile(base_vols, 20):
            score += 3

    down_vol_days = 0
    for i in range(-5, 0):
        if seg["Close"].iloc[i] < seg["Open"].iloc[i]:
            day_vol = float(seg["Volume"].iloc[i])
            if vol_avg > 0 and day_vol > vol_avg * 1.5:
                down_vol_days += 1
    if down_vol_days == 0:
        score += 2

    # 4f) Price Position Near Pivot (10 pts)
    price_pct_below = (resistance_level - current_close) / resistance_level * 100
    if price_pct_below <= 2:
        score += 10
    elif price_pct_below <= 5:
        score += 7
    elif price_pct_below <= 7:
        score += 4
    elif price_pct_below <= 10:
        score += 2

    # 4g) Pivot Proximity Bonus (5 pts)
    last_low = contractions[-1]["low_price"]
    above_last_low = current_close > last_low
    near_resistance = current_close >= resistance_level * 0.97
    if above_last_low and near_resistance:
        score += 5

    # ── Phase 5: Classification ───────────────────────────────────────
    score = int(min(100, max(0, score)))

    if score >= 60:
        status = "VCP Tight"
    elif score >= 50:
        status = "VCP Forming"
    else:
        status = "No VCP"

    return status, score