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
    # Corrected pivot: resistance_level excludes the last 25 days so a clean
    # base can form, but when a stock tagged its 52-week high inside those
    # excluded days and is now consolidating beneath it, resistance_level
    # sits below current_close and would yield a negative dist_to_pivot_pct
    # — mislabeling a pre-breakout name as above pivot. The true pivot is the
    # actual ceiling: the highest high across the prior 52-week window
    # (which includes the excluded base-formation days). Only override when
    # the base-window level is below current close; otherwise keep it as-is.
    # NOTE: today's bar is deliberately EXCLUDED from the 52-week high. Since
    # today's High >= today's Close, including it would force pivot_level >=
    # current_close, making dist_to_pivot_pct never negative and the "Already
    # Broken Out" status (close > pivot_level * 1.02) unreachable by
    # construction. Using the PRIOR 52-week high preserves the sign
    # semantics so genuine breakouts (close extended above the prior ceiling)
    # stay detectable while pre-breakout names (close beneath the prior
    # ceiling) still report a positive distance.
    high_52w_prev = float(high.iloc[-min(252, len(df)):-1].max())
    pivot_level = max(resistance_level, high_52w_prev) if resistance_level < current_close else resistance_level

    _meta = {"resistance_level": round(pivot_level, 2), "dist_to_pivot_pct": round(((pivot_level - current_close) / pivot_level) * 100, 2)}
    if current_close > pivot_level * 1.02:
        return "Already Broken Out", 0, _meta

    if current_close < resistance_level * 0.90:
        return "No VCP", 0, _meta

    first_depth = contractions[0]["depth"]
    if first_depth < 10 or first_depth > 50:
        return "No VCP", 0, _meta

    # ── Phase 4: Scoring (v4.0 — July 28 2026 refactor) ────────────────
    # Weights from 10-year backtest (341K obs) + v2 deep investigation
    #   v4.0 changes:
    #     - Base duration: REMOVED (zero correlation)
    #     - Halving rule: REPLACED by contraction ratio (15 pts)
    #     - Near resistance: NEW 10 pt component (3.6x multiplier)
    #     - Compression volatility: NEW 5 pt (coiled spring)
    #     - Price tier $200+: NEW 3 pt (institutional quality)
    #     - Score cap at 85 (returns turn negative at >=90)
    #     - Distance to pivot weight increased to 20 pts
    score = 0
    base_duration = len(seg) - 1 - resistance_idx  # kept for meta, not scored

    # ============================================================
    # 4a) Stage 2 MA Stacking Check (10 pts) — unchanged
    # ============================================================
    mav20 = close.rolling(20).mean()
    mav50 = close.rolling(50).mean()
    mav150 = close.rolling(150).mean()
    mav200 = close.rolling(200).mean()

    s2_score = 0
    if not pd.isna(mav150.iloc[-1]) and not pd.isna(mav200.iloc[-1]):
        if current_close > mav150.iloc[-1] and current_close > mav200.iloc[-1]:
            s2_score += 2
    if not pd.isna(mav150.iloc[-1]) and not pd.isna(mav200.iloc[-1]):
        if mav150.iloc[-1] > mav200.iloc[-1]:
            s2_score += 2
    if not pd.isna(mav200.iloc[-1]) and not pd.isna(mav200.iloc[-21]):
        if mav200.iloc[-1] > mav200.iloc[-21]:
            s2_score += 2
    if not pd.isna(mav50.iloc[-1]) and not pd.isna(mav150.iloc[-1]) and not pd.isna(mav200.iloc[-1]):
        if mav50.iloc[-1] > mav150.iloc[-1] and mav150.iloc[-1] > mav200.iloc[-1]:
            s2_score += 2
    if not pd.isna(mav50.iloc[-1]):
        if current_close > mav50.iloc[-1]:
            s2_score += 2
    score += min(10, s2_score)

    # ============================================================
    # 4b) Base Duration — REMOVED (v4.0, r=+0.001)
    # ============================================================

    # ============================================================
    # 4c) Contraction Count (5 pts, down from 10)
    # ============================================================
    if 2 <= T <= 3:
        score += 5
    elif T == 4:
        score += 3
    elif T >= 5:
        score += 1

    # ============================================================
    # 4d) Contraction Ratio (15 pts) — NEW v4.0, replaces halving
    # Backtest v2: first_depth/final_depth >=6x = 41% breakout
    # ============================================================
    final_depth = contractions[-1]["depth"]
    first_depth = contractions[0]["depth"]
    contraction_ratio = first_depth / final_depth if final_depth > 0 else 0

    if contraction_ratio >= 10:
        score += 15
    elif contraction_ratio >= 6:
        score += 12
    elif contraction_ratio >= 4:
        score += 9
    elif contraction_ratio >= 2:
        score += 4

    # ============================================================
    # 4e) Final Tightness (15 pts + 5 pts close = 20 pts total)
    # ============================================================
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
    close_std_pct = 0
    if recent_closes.mean() > 0:
        close_std_pct = recent_closes.std() / recent_closes.mean() * 100
        if close_std_pct <= 1.0:
            score += 5
        elif close_std_pct <= 2.0:
            score += 3
        elif close_std_pct <= 3.0:
            score += 1

    # ============================================================
    # 4f) Volume (5 pts — soft signal only)
    # ============================================================
    vol_avg = float(vol_50d.iloc[-1]) if not pd.isna(vol_50d.iloc[-1]) else 0
    recent_vol_5d = float(seg["Volume"].iloc[-5:].mean())
    if vol_avg > 0:
        vol_ratio = recent_vol_5d / vol_avg
        if 0.5 <= vol_ratio <= 1.5:
            score += 5
        elif vol_ratio < 0.5:
            score += 1
        else:
            score += 3

    # ============================================================
    # 4g) Price Position Near Pivot (20 pts — HARD GATE weight)
    # Backtest v2: cliff at 2%. 49% -> 25% breakout.
    # ============================================================
    price_pct_below = (pivot_level - current_close) / pivot_level * 100
    if price_pct_below <= 2:
        score += 20
    elif price_pct_below <= 5:
        score += 12
    elif price_pct_below <= 7:
        score += 6
    elif price_pct_below <= 10:
        score += 3

    # ============================================================
    # 4h) Near Resistance Flag (10 pts) — NEW v4.0
    # Backtest v2: 43.3% vs 12.1% breakout (3.6x multiplier).
    # ============================================================
    last_low = contractions[-1]["low_price"]
    above_last_low = current_close > last_low
    near_resistance = current_close >= resistance_level * 0.97
    if near_resistance:
        score += 10

    # ============================================================
    # 4i) 50MA Distance Check (10 pts) — unchanged
    # ============================================================
    if not pd.isna(mav50.iloc[-1]):
        vs_50ma = (current_close - mav50.iloc[-1]) / mav50.iloc[-1] * 100
        if 0 <= vs_50ma <= 5:
            score += 10
        elif -5 <= vs_50ma < 0:
            score += 6
        elif 5 < vs_50ma <= 10:
            score += 4
        elif vs_50ma > 10:
            score += 0
        else:
            score += 2

    # ============================================================
    # 4j) Run-up from 52w Low (5 pts) — unchanged
    # ============================================================
    lookback_full = min(252, len(df))
    low_52w = float(close.iloc[-lookback_full:].min())
    if low_52w > 0:
        runup_pct = (current_close - low_52w) / low_52w * 100
        if runup_pct >= 100:
            score += 5
        elif runup_pct >= 50:
            score += 3

    # ============================================================
    # 4k) Compression Volatility (5 pts) — NEW v4.0
    # Backtest v2: close_std >2% + depth <=5% = coiled spring.
    # ============================================================
    if close_std_pct > 2.0 and final_depth <= 5:
        score += 5
    elif close_std_pct > 1.0 and final_depth <= 3:
        score += 3

    # ============================================================
    # 4l) Price Tier Bonus (3 pts) — NEW v4.0
    # ============================================================
    if current_close >= 200:
        score += 3

    # ── Phase 5: Classification ───────────────────────────────────────
    # v4.0: Cap at 85 — returns turn negative at >=90
    score = int(min(85, max(0, score)))

    if score >= 60:
        status = "VCP Tight"
    elif score >= 50:
        status = "VCP Forming"
    else:
        status = "No VCP"

    _meta["contraction_ratio"] = round(contraction_ratio, 2)
    return status, score, _meta
