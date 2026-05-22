import os
import pickle
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
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
    result = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        fut_map = {ex.submit(_get_industry, t): t for t in tickers}
        for f in as_completed(fut_map):
            t = fut_map[f]
            try:
                ind = f.result()
                if ind:
                    result[t] = ind
            except Exception:
                pass
    return result


def _get_industry(ticker):
    try:
        t = yf.Ticker(ticker)
        info = t.info
        return info.get("industry") or info.get("sector") or "Unknown"
    except Exception:
        return None


def compute_industry_ranks(tickers, rs_ratings, industries):
    groups = {}
    for t in tickers:
        ind = industries.get(t)
        if not ind:
            continue
        rs = rs_ratings.get(t)
        if rs is None:
            continue
        groups.setdefault(ind, []).append(rs)

    avg_rs = {ind: np.mean(vals) for ind, vals in groups.items() if len(vals) >= 3}
    sorted_inds = sorted(avg_rs, key=avg_rs.get, reverse=True)
    rank_map = {ind: i + 1 for i, ind in enumerate(sorted_inds)}
    total = len(sorted_inds)

    ticker_ranks = {}
    for t in tickers:
        ind = industries.get(t)
        if ind and ind in rank_map:
            ticker_ranks[t] = (rank_map[ind], total)
        else:
            ticker_ranks[t] = (None, None)
    return ticker_ranks


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
