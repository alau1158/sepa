import os
import pickle
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

CACHE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUND_CACHE = os.path.join(CACHE_DIR, "cache_fundamentals.pkl")


def _load_fund_cache():
    try:
        with open(FUND_CACHE, "rb") as f:
            return pickle.load(f)
    except (FileNotFoundError, Exception):
        return {}


def _save_fund_cache(cache):
    cache["_timestamp"] = datetime.now()
    with open(FUND_CACHE, "wb") as f:
        pickle.dump(cache, f)


def _cache_section_valid(cache, section, max_hours):
    ts = cache.get(f"_{section}_ts")
    if ts is None:
        return False
    age = (datetime.now() - ts).total_seconds() / 3600
    return age <= max_hours


def get_industries(tickers, force_refresh=False):
    cache = _load_fund_cache()
    valid = _cache_section_valid(cache, "industries", 168) and not force_refresh
    if valid and "industries" in cache:
        cached_tickers = set(cache["industries"].keys())
        missing = [t for t in tickers if t not in cached_tickers]
        if missing:
            new_inds = _fetch_industries(missing)
            if new_inds:
                cache["industries"].update(new_inds)
                _save_fund_cache(cache)
        return cache["industries"]

    industries = _fetch_industries(tickers)
    if industries:
        cache["industries"] = industries
        cache["_industries_ts"] = datetime.now()
        _save_fund_cache(cache)
    return industries or cache.get("industries", {})


def _fetch_industries(tickers):
    import time
    result = {}
    batch_size = 100
    with ThreadPoolExecutor(max_workers=5) as ex:
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            fut_map = {ex.submit(_get_industry, t): t for t in batch}
            for f in as_completed(fut_map):
                t = fut_map[f]
                try:
                    ind = f.result()
                    if ind:
                        result[t] = ind
                except Exception:
                    pass
            if i + batch_size < len(tickers):
                time.sleep(2)
    return result


def _get_industry(ticker):
    import time
    for attempt in range(3):
        try:
            t = yf.Ticker(ticker)
            info = t.info
            return info.get("industry") or info.get("sector") or "Unknown"
        except Exception as e:
            msg = str(e).lower()
            if "rate" in msg or "429" in msg or "400" in msg or "bad request" in msg:
                wait = 2 ** attempt
                time.sleep(wait)
            else:
                return None
    return None


def compute_industry_ranks(passing_tickers, rs_ratings, industries):
    """Rank industries by the max RS of PASSING tickers (Minervini bottom-up).

    Only industries with ≥1 passing ticker are ranked.
    Returns dict[ticker] -> (rank, total_industries).
    """
    ind_max_rs = {}
    for t in passing_tickers:
        ind = industries.get(t)
        if not ind:
            continue
        rs = rs_ratings.get(t)
        if rs is None:
            continue
        prev = ind_max_rs.get(ind, 0)
        if rs > prev:
            ind_max_rs[ind] = rs

    sorted_inds = sorted(ind_max_rs, key=ind_max_rs.get, reverse=True)
    rank_map = {ind: i + 1 for i, ind in enumerate(sorted_inds)}
    total = len(sorted_inds)

    ticker_ranks = {}
    for t in passing_tickers:
        ind = industries.get(t)
        if ind and ind in rank_map:
            ticker_ranks[t] = (rank_map[ind], total)
        else:
            ticker_ranks[t] = (None, None)
    return ticker_ranks


def compute_breakout_order(passing_tickers, data_dict, industries):
    """Within each industry, rank passing stocks by breakout timing.

    Breakout date = earliest day in the last 4 weeks where price crossed
    above its 20-day high on >1.2× average volume.  First to break out = 1.
    Returns dict[ticker] -> (order, total_in_industry).
    """
    groups = {}
    for t in passing_tickers:
        ind = industries.get(t)
        if not ind:
            continue
        df = data_dict.get(t)
        if df is None or len(df) < 30:
            continue
        close = df["Close"]
        high_20 = df["High"].rolling(20).max().shift()
        avg_vol = df["Volume"].rolling(50).mean().shift()
        breakout_day = None
        for i in range(-29, 0):
            if (close.iloc[i] > high_20.iloc[i]
                    and df["Volume"].iloc[i] > avg_vol.iloc[i] * 1.2
                    and not pd.isna(high_20.iloc[i])
                    and not pd.isna(avg_vol.iloc[i])):
                breakout_day = df.index[i]
                break
        groups.setdefault(ind, []).append((t, breakout_day))

    order_map = {}
    for ind, members in groups.items():
        valid = [(t, d) for t, d in members if d is not None]
        valid.sort(key=lambda x: x[1])
        total = len(valid)
        for i, (t, _) in enumerate(valid, 1):
            order_map[t] = (i, total)
        for t, d in members:
            if d is None:
                order_map[t] = ("N/A", total)

    result = {}
    for t in passing_tickers:
        result[t] = order_map.get(t, ("N/A", 0))
    return result


def get_eps_data(tickers, force_refresh=False):
    cache = _load_fund_cache()
    valid = _cache_section_valid(cache, "eps", 24) and not force_refresh
    if valid and "eps" in cache:
        cached_tickers = set(cache["eps"].keys())
        missing = [t for t in tickers if t not in cached_tickers]
        if missing:
            new_eps = _fetch_eps(missing)
            if new_eps:
                cache["eps"].update(new_eps)
                _save_fund_cache(cache)
        return cache["eps"]

    eps_data = _fetch_eps(tickers)
    existing = dict(cache.get("eps", {}))
    existing.update(eps_data)
    if eps_data:
        cache["eps"] = existing
        cache["_eps_ts"] = datetime.now()
        _save_fund_cache(cache)
    return existing


def _fetch_eps(tickers):
    result = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        fut_map = {ex.submit(_get_eps, t): t for t in tickers}
        for f in as_completed(fut_map):
            t = fut_map[f]
            try:
                eps = f.result()
                if eps is not None and len(eps) >= 5:
                    result[t] = eps
            except Exception:
                pass
    return result


def _get_eps(ticker):
    try:
        t = yf.Ticker(ticker)
        qis = t.quarterly_income_stmt
        if qis is None or "Diluted EPS" not in qis.index:
            return None
        eps = qis.loc["Diluted EPS"].dropna()
        if len(eps) < 5:
            return None
        return eps
    except Exception:
        return None


def compute_eps_ratings(tickers, eps_data):
    growth_rates = {}
    for t in tickers:
        eps = eps_data.get(t)
        if eps is None or len(eps) < 5:
            continue
        vals = eps.values
        q0, q4 = vals[0], vals[4]
        if q4 > 0:
            growth = (q0 - q4) / q4 * 100
        elif q4 < 0 and q0 > 0:
            growth = 999
        else:
            continue
        growth_rates[t] = growth

    if not growth_rates:
        return {t: None for t in tickers}

    sorted_tickers = sorted(growth_rates, key=growth_rates.get)
    n = len(sorted_tickers)
    ratings = {}
    for i, t in enumerate(sorted_tickers):
        pct = (i + 1) / (n + 1) * 100
        ratings[t] = max(1, min(99, round(pct)))
    return ratings
