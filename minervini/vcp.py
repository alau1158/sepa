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
    Scores the pattern with weights derived from 10-year backtest (2016-2026).

    Backtest-validated findings incorporated (Jul 2026):
      - Final tightness & price near pivot are strongest signals
      - Volume dry-up is NOT predictive (inverted in practice)
      - Halving rule contributes minimally
      - 2-3 contractions are ideal; 4+ gets stale
      - Stage 2 MA alignment improves outcomes significantly
      - >10% above 50MA = extended (win rate drops below 50%)
      - High run-up from 52w low is NOT exhaustion (leaders keep leading)

    Returns (status: str, score: int, meta: dict).
    Status: "VCP Tight", "VCP Forming", "No VCP", "Already Broken Out"
    Meta: {"resistance_level": float|None, "dist_to_pivot_pct": float|None}
        - resistance_level: the pivot ceiling price (None if undetermined)
        - dist_to_pivot_pct: how far current price is from resistance
          (negative = above pivot, positive = below, None if undetermined)
    """
    _no_meta = {"resistance_level": None, "dist_to_pivot_pct": None}

    if len(df) < 130:
        return "No VCP", 0, _no_meta

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
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
        return "No VCP", 0, _no_meta

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
        return "No VCP", 0, _no_meta

    # ── Phase 3: Hard Filters ──────────────────────────────────────────
    _meta = {"resistance_level": round(resistance_level, 2), "dist_to_pivot_pct": round(((resistance_level - current_close) / resistance_level) * 100, 2)}
    if current_close > resistance_level * 1.02:
        return "Already Broken Out", 0, _meta

    if current_close < resistance_level * 0.90:
        return "No VCP", 0, _meta

    first_depth = contractions[0]["depth"]
    if first_depth < 10 or first_depth > 50:
        return "No VCP", 0, _meta

    # ── Phase 4: Scoring (100 pts) ─────────────────────────────────────
    # Weights derived from 10-year backtest (341K observations, Jul 2026)
    score = 0
    base_duration = len(seg) - 1 - resistance_idx

    # ============================================================
    # 4a) Stage 2 MA Stacking Check (10 pts) — NEW
    # ------------------------------------------------------------
    # Backtest: VCP + full Stage 2 tends to outperform VCP alone.
    # Checks the core MA alignment criteria from OHLCV data alone.
    # ============================================================
    mav20 = close.rolling(20).mean()
    mav50 = close.rolling(50).mean()
    mav150 = close.rolling(150).mean()
    mav200 = close.rolling(200).mean()

    s2_score = 0
    # C1: Price > 150MA AND > 200MA
    if not pd.isna(mav150.iloc[-1]) and not pd.isna(mav200.iloc[-1]):
        if current_close > mav150.iloc[-1] and current_close > mav200.iloc[-1]:
            s2_score += 2
    # C2: 150MA > 200MA
    if not pd.isna(mav150.iloc[-1]) and not pd.isna(mav200.iloc[-1]):
        if mav150.iloc[-1] > mav200.iloc[-1]:
            s2_score += 2
    # C3: 200MA trending up (today > 20 days ago)
    if not pd.isna(mav200.iloc[-1]) and not pd.isna(mav200.iloc[-21]):
        if mav200.iloc[-1] > mav200.iloc[-21]:
            s2_score += 2
    # C4: 50MA > 150MA > 200MA
    if not pd.isna(mav50.iloc[-1]) and not pd.isna(mav150.iloc[-1]) and not pd.isna(mav200.iloc[-1]):
        if mav50.iloc[-1] > mav150.iloc[-1] and mav150.iloc[-1] > mav200.iloc[-1]:
            s2_score += 2
    # C5: Price > 50MA
    if not pd.isna(mav50.iloc[-1]):
        if current_close > mav50.iloc[-1]:
            s2_score += 2
    # Cap at 10
    score += min(10, s2_score)

    # ============================================================
    # 4b) Base Duration (5 pts, down from 10)
    # ------------------------------------------------------------
    # Backtest: near-zero correlation with forward returns.
    # Keep for structural completeness, minimal weight.
    # ============================================================
    if 35 <= base_duration <= 150:    # 7-30 weeks (sweet spot)
        score += 5
    elif 25 <= base_duration <= 250:  # 5-50 weeks (acceptable)
        score += 2

    # ============================================================
    # 4c) Contraction Count (10 pts — cap reward at 3)
    # ------------------------------------------------------------
    # Backtest: 2-3 contractions have best breakout rates.
    # 4+ gets stale. Don't reward 5+.
    # ============================================================
    if 2 <= T <= 3:
        score += 10
    elif T == 4:
        score += 5
    elif T >= 5:
        score += 2

    # ============================================================
    # 4d) Halving Rule (5 pts, down from 25)
    # ------------------------------------------------------------
    # Backtest: essentially no predictive power. Stocks with zero
    # halving break out MORE than perfectly-halving ones.
    # Kept as a minor check for pattern aesthetics, not signal.
    # ============================================================
    halving_passes = 0
    halving_total = 0
    for i in range(1, T):
        halving_total += 1
        if contractions[i]["depth"] <= contractions[i - 1]["depth"] * 0.60:
            halving_passes += 1

    if halving_total > 0:
        score += int(5 * halving_passes / halving_total)

    # ============================================================
    # 4e) Final Tightness (25 pts — BEST SIGNAL, keep as-is)
    # ------------------------------------------------------------
    # Backtest: final depth <=3% gives 80.3% breakout rate. 
    # Strongest single predictor. Unchanged from original.
    # ============================================================
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

    # ============================================================
    # 4f) Volume (10 pts, down from 15 — gate removed)
    # ------------------------------------------------------------
    # Backtest: volume dry-up is INVERTED — higher vol ratio 
    # correlates with HIGHER breakout rates. Very low volume 
    # (<0.5x avg) = dead stock, not coiled spring.
    # Removed the "vol at p10" bonus and down-vol check entirely.
    # Now just uses vol ratio as a soft signal favoring normal
    # or slightly elevated volume.
    # ============================================================
    vol_avg = float(vol_50d.iloc[-1]) if not pd.isna(vol_50d.iloc[-1]) else 0
    recent_vol_5d = float(seg["Volume"].iloc[-5:].mean())
    if vol_avg > 0:
        vol_ratio = recent_vol_5d / vol_avg
        # Sweet spot: 0.5-1.5x average volume. Dead (<0.5) gets no pts.
        # Very high (>1.5) might already be breaking out.
        if 0.5 <= vol_ratio <= 1.5:
            score += 8
        elif vol_ratio < 0.5:
            score += 2   # Dead volume — minimal pts
        else:  # > 1.5
            score += 5   # Loud — possible breakout in progress, partial credit

    # ============================================================
    # 4g) Price Position Near Pivot (15 pts, up from 10)
    # ------------------------------------------------------------
    # Backtest: stocks within 2% of pivot have 38.3% 10d breakout 
    # vs 8.6% for 5-10% away. Strongest timing signal.
    # ============================================================
    price_pct_below = (resistance_level - current_close) / resistance_level * 100
    if price_pct_below <= 2:
        score += 15
    elif price_pct_below <= 5:
        score += 10
    elif price_pct_below <= 7:
        score += 6
    elif price_pct_below <= 10:
        score += 3

    # Pivot Proximity Bonus (5 pts) — keep
    last_low = contractions[-1]["low_price"]
    above_last_low = current_close > last_low
    near_resistance = current_close >= resistance_level * 0.97
    if above_last_low and near_resistance:
        score += 5

    # ============================================================
    # 4h) 50MA Distance Check — Extended Penalty (10 pts) — NEW
    # ------------------------------------------------------------
    # Backtest: win rate drops below 50% at >10% above 50MA.
    # For VCP stocks specifically, >+5% above 50MA hurts returns.
    # Penalty scales: bonus at 0-5%, neutral at 5-10%, penalize >10%.
    # ============================================================
    if not pd.isna(mav50.iloc[-1]):
        vs_50ma = (current_close - mav50.iloc[-1]) / mav50.iloc[-1] * 100
        if 0 <= vs_50ma <= 5:
            score += 10    # Sweet spot — near 50MA but above it
        elif -5 <= vs_50ma < 0:
            score += 6     # Slightly below — still OK
        elif 5 < vs_50ma <= 10:
            score += 4     # Getting extended, reduced points
        elif vs_50ma > 10:
            score += 0     # Extended — no points (could be negative, but score is capped at 0)
            # Note: for analysis, flag vs_50ma in meta
        else:  # vs_50ma < -5
            score += 2     # Deep below 50MA — not ideal for VCP

    # ============================================================
    # 4i) Run-up from 52w Low — Late Stage Awareness (5 pts) — NEW
    # ------------------------------------------------------------
    # Backtest: stocks with 200-400% run-up from 52w low have BEST 
    # forward returns. "Late stage = dangerous" is backwards.
    # Reward strong run-up, penalize very low run-up (weak stock).
    # ============================================================
    lookback_full = min(252, len(df))
    low_52w = float(close.iloc[-lookback_full:].min())
    if low_52w > 0:
        runup_pct = (current_close - low_52w) / low_52w * 100
        if runup_pct >= 100:
            score += 5     # Strong prior run — leader
        elif runup_pct >= 50:
            score += 3     # Moderate run
        # <50% = weak run-up, no points (stock hasn't proven itself)

    # ── Phase 5: Classification ───────────────────────────────────────
    score = int(min(100, max(0, score)))

    if score >= 60:
        status = "VCP Tight"
    elif score >= 50:
        status = "VCP Forming"
    else:
        status = "No VCP"

    return status, score, _meta
