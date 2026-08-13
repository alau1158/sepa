#!/usr/bin/env python3
"""
Market Regime Watcher — tells Alan when to switch between MOMENTUM and VCP.

Reads the NYSE/NASDAQ caches (refreshed by the daily screener) + QQQ chop index,
classifies the tape into TREND / WARNING / CHOP, and only prints (alerts) when
the regime LABEL changes. Silent otherwise — designed for a no_agent cron with
WhatsApp delivery (empty stdout = no ping).

Classification (thresholds from cache analysis Aug 2026):
  CHOP   (switch to VCP):  QQQ chop >= 55  OR  coil density >= 15%  OR  %above50MA < 40
  WARNING (momentum, cautious): %above50MA < 50
  TREND  (momentum): otherwise

State file: ~/.hermes/scripts/.market_regime_state.json
"""
import json, math, os, pickle, sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

SEPA_DIR = "/home/alau/sepa_screener"
STATE_FILE = os.path.expanduser("~/.hermes/scripts/.market_regime_state.json")
CACHES = ["cache_nasdaq.pkl", "cache_nyse.pkl"]

# ---- indicators ----
def rsi_wilder(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / period, adjust=False).mean()
    al = loss.ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))

def chop_index(df, n=14):
    """Ehlers Choppiness Index: >61.8 choppy, <38.2 trending."""
    h = df["High"].values
    l = df["Low"].values
    c = df["Close"].values
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out = np.full(len(c), np.nan)
    for i in range(n - 1, len(c)):
        tr_sum = tr[i - n + 1:i + 1].sum()
        rng = h[i - n + 1:i + 1].max() - l[i - n + 1:i + 1].min()
        if rng > 0:
            out[i] = 100 * math.log10(tr_sum / rng) / math.log10(n)
    return out

# ---- data ----
def load_universe():
    frames = {}
    for cf in CACHES:
        path = os.path.join(SEPA_DIR, cf)
        if not os.path.exists(path):
            print(f"ERROR: missing {path}", file=sys.stderr)
            continue
        with open(path, "rb") as fh:
            cache = pickle.load(fh)
        for t, df in cache.get("data", {}).items():
            if isinstance(df.columns, pd.MultiIndex):
                df = df.copy()
                df.columns = df.columns.get_level_values(0)
            frames[t] = df
    return frames

def last_full_close_index(df, now):
    """Index of the most recent COMPLETE close. Skips NaN closes and today's
    partial bar when the market is still open."""
    closes = df["Close"].dropna()
    if closes.empty:
        return None
    idx = closes.index[-1]
    pos = df.index.get_loc(idx)
    partial = False
    if idx.date() == now.date():
        minutes = now.hour * 60 + now.minute
        if minutes < 13 * 60 + 30:  # before 1:30 PM PT -> bar is partial
            partial = True
    if partial and pos > 250:
        pos -= 1
    return pos

def compute_breadth(frames, ends, liquid_only=True):
    above20 = above50 = above200 = stage2 = near_high = coil = valid = 0
    rsis = []
    for t, df in frames.items():
        if len(df) < 255:
            continue
        idx = ends[t]
        if idx < 250:
            continue
        c = df["Close"].iloc[:idx + 1]
        h = df["High"].iloc[:idx + 1]
        l = df["Low"].iloc[:idx + 1]
        v = df["Volume"].iloc[:idx + 1]
        last = float(c.iloc[-1])
        if last <= 0 or np.isnan(last):
            continue
        if liquid_only:
            avgvol = float(v.tail(60).mean())
            if last < 10 or avgvol < 300000:
                continue
        ma20 = float(c.rolling(20).mean().iloc[-1])
        ma50 = float(c.rolling(50).mean().iloc[-1])
        ma150 = float(c.rolling(150).mean().iloc[-1])
        ma200 = float(c.rolling(200).mean().iloc[-1])
        rsi = float(rsi_wilder(c).iloc[-1])
        if np.isnan(rsi):
            continue
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr_pct = float(tr.rolling(14).mean().iloc[-1] / last * 100)
        hi52 = float(h.tail(252).max())
        std10 = float(c.tail(10).std() / last * 100)
        valid += 1
        if last > ma20:
            above20 += 1
        if last > ma50:
            above50 += 1
        if last > ma200:
            above200 += 1
        if ma20 > ma50 > ma150 > ma200 and last > ma200:
            stage2 += 1
        if hi52 > 0 and last >= hi52 * 0.95:
            near_high += 1
        if rsi < 47 and last < ma50 and std10 < 4.5 and atr_pct < 8:
            coil += 1
        rsis.append(rsi)
    if valid == 0:
        return None
    return {
        "n": valid,
        "above20": above20 / valid * 100,
        "above50": above50 / valid * 100,
        "above200": above200 / valid * 100,
        "stage2": stage2 / valid * 100,
        "near_high": near_high / valid * 100,
        "coil": coil / valid * 100,
        "med_rsi": float(np.nanmedian(rsis)),
    }

def get_qqq_chop():
    try:
        import yfinance as yf
        df = yf.Ticker("QQQ").history(period="1y", interval="1d", timeout=15)
        if df is None or df.empty or len(df) < 30:
            return None
        ch = chop_index(df)
        return float(ch[-1])
    except Exception:
        return None

# ---- classification ----
def classify(b, chop):
    if b is None:
        return "UNKNOWN", {}
    if chop is not None and chop >= 55:
        return "SWITCH-TO-VCP", {"driver": f"QQQ chop {chop:.0f} >= 55"}
    if b["coil"] >= 15:
        return "SWITCH-TO-VCP", {"driver": f"coil density {b['coil']:.1f}% >= 15%"}
    if b["above50"] < 40:
        return "SWITCH-TO-VCP", {"driver": f"breadth {b['above50']:.0f}% < 40%"}
    if b["above50"] < 50:
        return "CAREFUL", {"driver": f"breadth {b['above50']:.0f}% < 50%"}
    return "MOMENTUM", {"driver": "breadth + coil healthy"}

# ---- main ----
def main():
    now = datetime.now(timezone.utc).astimezone()
    frames = load_universe()
    if not frames:
        print("ERROR: no cache data", file=sys.stderr)
        sys.exit(1)

    ends = {}
    asof = None
    for t, df in frames.items():
        if len(df) < 255:
            continue
        idx = last_full_close_index(df, now)
        if idx is None or idx < 250:
            continue
        ends[t] = idx
        if asof is None:
            asof = df.index[idx]

    b = compute_breadth(frames, ends, liquid_only=True)
    chop = get_qqq_chop()
    label, info = classify(b, chop)

    # Build message
    if b is None:
        print("ERROR: breadth compute failed", file=sys.stderr)
        sys.exit(1)
    metrics = (
        f"breadth(50MA)={b['above50']:.0f}% stage2={b['stage2']:.0f}% "
        f"coil={b['coil']:.1f}% RSI={b['med_rsi']:.1f} "
        f"chop={'n/a' if chop is None else f'{chop:.0f}'}"
    )

    # Load state
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            state = json.load(open(STATE_FILE))
        except Exception:
            state = {}

    prev = state.get("label")
    changed = prev != label
    state.update({"label": label, "date": str(now.date()), "metrics": metrics,
                  "driver": info.get("driver", ""), "asof": str(asof.date()) if asof is not None else ""})
    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh)

    # Silent unless the regime changed (or first run)
    if changed:
        emoji = {"SWITCH-TO-VCP": "🔁", "CAREFUL": "⚠️", "MOMENTUM": "🚀", "UNKNOWN": "❓"}.get(label, "")
        direction = "first read" if prev is None else f"from {prev}"
        print(f"{emoji} REGIME FLIP {direction} -> {label} (as of {state['asof']})")
        print(f"{metrics} | trigger: {info.get('driver','')}")
        print("SWITCH-TO-VCP = go back to VCP/coil setups | CAREFUL = momentum but pickier | MOMENTUM = full speed")
    else:
        # still update state, print nothing (silent watchdog)
        pass

if __name__ == "__main__":
    main()
