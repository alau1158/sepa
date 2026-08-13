#!/usr/bin/env python3
"""
Sector/Basket Heat Monitor — catches "AI getting hot" moments the VCP and
momentum scans structurally miss.

Reads the NYSE/NASDAQ caches, computes per-basket momentum + breakout breadth,
flags HOT baskets, and (in watchdog mode) only prints when a basket flips to/from
HOT — silent otherwise. Designed for a no_agent cron with WhatsApp delivery.

Basket = curated lists (Alan's actual May/June winners + core names).
HOT rule (v1, fit to May/Jun 2026): median 20d return >= 8% OR
  (median 20d >= 1.5x market median AND >= 50% of basket within 5% of 52w high).

State file: ~/.hermes/scripts/.sector_heat_state.json
"""
import json, os, pickle, sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

SEPA_DIR = "/home/alau/sepa_screener"
STATE_FILE = os.path.expanduser("~/.hermes/scripts/.sector_heat_state.json")
CACHES = ["cache_nasdaq.pkl", "cache_nyse.pkl"]

BASKETS = {
    "AI/Compute": ["NVDA","AMD","AVGO","TSM","MU","SNDK","WDC","INTC","QCOM","ARM","MRVL",
                   "LSCC","TTMI","LITE","ANET","DELL","SMCI","VRT","CRDO","ALAB","RMBS","ON","UCTT","VICR"],
    "AI/Software": ["CRWD","PANW","SNOW","MSFT","GOOG","AMZN","ORCL","PLTR","NOW","MDB","NET","DDOG"],
    "Semis Equip": ["AMAT","LRCX","KLAC","ASML","ENTG","COHR","AMKR","AEIS"],
    "Biotech": ["ILMN","TXG","ELV","BMY","ABBV","BIIB","ALKS","MRNA","REGN","VRTX"],
    "Energy": ["XOM","CVX","OXY","SLB","COP","VLO","MPC","PSX","LPG","NEM"],
    "Financials": ["C","GS","JPM","BAC","MS","WFC","SCHW","AXP"],
    "Industrials": ["GE","HON","CAT","RTX","LMT","NOC","ARCB","PWR"],
    "Consumer": ["HD","PM","T","CMCSA","LULU","SBUX","COST","MCD"],
}

def load_universe():
    frames = {}
    for cf in CACHES:
        path = os.path.join(SEPA_DIR, cf)
        if not os.path.exists(path):
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
    closes = df["Close"].dropna()
    if closes.empty:
        return None
    idx = closes.index[-1]
    pos = df.index.get_loc(idx)
    if idx.date() == now.date():
        minutes = now.hour * 60 + now.minute
        if minutes < 13 * 60 + 30:
            if pos > 250:
                pos -= 1
    return pos

def basket_stats(frames, tickers, ends):
    """Median momentum + breadth for a basket at per-ticker end indices."""
    rets5, rets20, rets60, above20, above50, near_high = [], [], [], 0, 0, 0
    nh_count = 0; valid = 0
    for t in tickers:
        if t not in frames:
            continue
        df = frames[t]
        idx = ends.get(t)
        if idx is None or idx < 60:
            continue
        c = df["Close"].iloc[:idx + 1]
        h = df["High"].iloc[:idx + 1]
        last = float(c.iloc[-1])
        if last <= 0 or np.isnan(last):
            continue
        valid += 1
        r5 = float(c.iloc[-1] / c.iloc[-6] - 1) * 100 if len(c) > 5 else np.nan
        r20 = float(c.iloc[-1] / c.iloc[-21] - 1) * 100 if len(c) > 20 else np.nan
        r60 = float(c.iloc[-1] / c.iloc[-61] - 1) * 100 if len(c) > 60 else np.nan
        rets5.append(r5); rets20.append(r20); rets60.append(r60)
        ma20 = float(c.rolling(20).mean().iloc[-1])
        ma50 = float(c.rolling(50).mean().iloc[-1])
        if last > ma20: above20 += 1
        if last > ma50: above50 += 1
        hi52 = float(h.tail(252).max())
        if hi52 > 0 and last >= hi52 * 0.95:
            near_high += 1
        if hi52 > 0 and last >= hi52:
            nh_count += 1
    if valid == 0:
        return None
    return {
        "n": valid,
        "med5": float(np.nanmedian(rets5)),
        "med20": float(np.nanmedian(rets20)),
        "med60": float(np.nanmedian(rets60)),
        "above20": above20 / valid * 100,
        "above50": above50 / valid * 100,
        "near_high": near_high / valid * 100,
        "at_high": nh_count,
    }

def market_median_20d(frames, ends):
    rets = []
    for t, df in frames.items():
        idx = ends.get(t)
        if idx is None or idx < 60:
            continue
        c = df["Close"].iloc[:idx + 1]
        last = float(c.iloc[-1])
        if last <= 0 or np.isnan(last) or len(c) < 21:
            continue
        rets.append(float(c.iloc[-1] / c.iloc[-21] - 1) * 100)
    return float(np.nanmedian(rets)) if rets else None

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
        if idx is not None and idx >= 250:
            ends[t] = idx
            if asof is None:
                asof = df.index[idx]

    mkt = market_median_20d(frames, ends)
    results = {}
    for name, tickers in BASKETS.items():
        s = basket_stats(frames, tickers, ends)
        if s is None:
            continue
        hot = s["med20"] >= 8 or (s["med20"] >= 1.5 * mkt and s["near_high"] >= 50) if mkt else s["med20"] >= 8
        results[name] = {**s, "hot": bool(hot)}

    # Load state
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            state = json.load(open(STATE_FILE))
        except Exception:
            state = {}

    prev_hot = set(state.get("hot", []))
    cur_hot = {n for n, r in results.items() if r["hot"]}
    newly = cur_hot - prev_hot
    cooled = prev_hot - cur_hot

    state["hot"] = sorted(cur_hot)
    state["date"] = str(now.date())
    state["asof"] = str(asof.date()) if asof is not None else ""
    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh)

    # Build ranked lines
    lines = []
    for name, r in sorted(results.items(), key=lambda kv: -kv[1]["med20"]):
        flag = "🔥" if r["hot"] else "  "
        lines.append(f"{flag} {name:14} 20d={r['med20']:+.1f}% 5d={r['med5']:+.1f}% "
                     f"above50MA={r['above50']:.0f}% near52wH={r['near_high']:.0f}%")

    if newly or cooled:
        print(f"🔥 SECTOR HEAT UPDATE (as of {state['asof']}, market 20d median {mkt:+.1f}%)")
        if newly:
            print("NOW HOT: " + ", ".join(sorted(newly)))
        if cooled:
            print("COOLED: " + ", ".join(sorted(cooled)))
        print("--- all baskets ---")
        print("\n".join(lines))
        print("HOT = median 20d >= +8% OR (>=1.5x market AND >=50% near 52w highs). Dig into HOT baskets with the momentum scanner.")
    else:
        pass  # silent

if __name__ == "__main__":
    main()
