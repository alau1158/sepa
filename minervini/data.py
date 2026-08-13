import os
import pickle
import time
from datetime import datetime
from io import StringIO

import urllib.request

# Force IPv4 to avoid Yahoo Finance IPv6 rate limiting
import socket
_original_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo



import pandas as pd
import requests
import yfinance as yf

CACHE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _wiki_tickers(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]
    tickers = df["Symbol"].tolist()
    return [t.replace(".", "-") for t in tickers]


def get_sp500_tickers():
    return _wiki_tickers("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")


def get_sp400_tickers():
    return _wiki_tickers("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies")


def get_sp600_tickers():
    return _wiki_tickers("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies")


def _ftp_tickers(url, etf_col, test_col):
    """Fetch common stocks from NASDAQ FTP listings."""
    resp = urllib.request.urlopen(url, timeout=15)
    text = resp.read().decode("utf-8")
    lines = text.strip().split("\n")
    tickers = []
    for line in lines[1:]:
        if line.strip().upper().startswith("FILE"):
            continue
        parts = line.split("|")
        if len(parts) <= max(etf_col, test_col):
            continue
        if parts[etf_col] == "Y":
            continue
        if parts[test_col] == "Y":
            continue
        name = parts[1].upper()
        if any(kw in name for kw in ["WARRANT", " RIGHT", " UNIT", "PREFERRED", "DEPOSITARY", "%",
                                      " FUND", "ETF", "TRUST", "NOTE", "DEBENTURE"]):
            continue
        tickers.append(parts[0].replace(".", "-"))
    return tickers


def get_nasdaq_tickers():
    return _ftp_tickers(
        "ftp://ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt", 6, 3
    )


def get_nyse_tickers():
    return _ftp_tickers(
        "ftp://ftp.nasdaqtrader.com/SymbolDirectory/otherlisted.txt", 4, 6
    )


TICKER_SOURCES = {
    "sp500": get_sp500_tickers,
    "sp400": get_sp400_tickers,
    "sp600": get_sp600_tickers,
    "nasdaq": get_nasdaq_tickers,
    "nyse": get_nyse_tickers,
}


def get_tickers(index):
    fn = TICKER_SOURCES.get(index)
    if not fn:
        raise ValueError(f"Unknown index: {index}")
    return fn()


def _download_batch(batch, period, min_price, all_data, filtered):
    """Download a single batch and return (new_data_dict, filtered_tickers).

    Returns the list of tickers excluded by the min_price filter separately
    from data, so the caller can distinguish price-filtered (expected) from
    genuinely failed (throttled/dead) tickers.
    """
    data = yf.download(
        batch,
        period=period,
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )

    new_data = {}
    filtered_tickers = []

    if isinstance(data.columns, pd.MultiIndex):
        for ticker in batch:
            try:
                td = data[ticker]
                if isinstance(td, pd.DataFrame) and not td.empty:
                    if min_price is not None:
                        last_close = td["Close"].iloc[-1]
                        if pd.isna(last_close) or last_close < min_price:
                            filtered_tickers.append(ticker)
                            continue
                    new_data[ticker] = td
            except (KeyError, Exception):
                pass
    else:
        if batch and not data.empty:
            if min_price is None or data["Close"].iloc[-1] >= min_price:
                new_data[batch[0]] = data
            else:
                filtered_tickers.append(batch[0])

    return new_data, filtered_tickers


def download_data(tickers, period="2y", batch_size=25, min_price=None):
    all_data = {}
    failed = []
    filtered_tickers = []
    total_batches = (len(tickers) + batch_size - 1) // batch_size

    consecutive_failures = 0

    # Main pass: moderate batches, threads=True, modest pacing.
    # Yahoo's chart endpoint throttles at roughly ~2,000 req/hour/IP; a flat
    # 2s sleep between batches keeps the sustained rate sane, and we back off
    # harder when Yahoo actually refuses (HTTP 429 / empty result).
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        batch_num = (i // batch_size) + 1

        try:
            new_data, new_filtered = _download_batch(batch, period, min_price, all_data, filtered_tickers)
            all_data.update(new_data)
            filtered_tickers.extend(new_filtered)

            # Track genuinely-failed tickers: not in data AND not price-filtered.
            succeeded = set(new_data.keys()) | set(new_filtered)
            for t in batch:
                if t not in succeeded:
                    failed.append(t)

            if new_data:
                consecutive_failures = 0

            if batch_num % 20 == 0 or batch_num == total_batches:
                print(f"  Progress: {batch_num}/{total_batches} batches ({len(all_data)} stocks loaded, {len(failed)} failed, {len(filtered_tickers)} filtered)", flush=True)
        except Exception:
            failed.extend(batch)
            consecutive_failures += 1

        # Pacing: flat 2s between batches; 5s after a throttled batch;
        # 30s cooldown if Yahoo keeps refusing.
        if consecutive_failures > 2:
            time.sleep(30.0)
        elif consecutive_failures > 0:
            time.sleep(5.0)
        else:
            time.sleep(2.0)

    # Retry pass: only genuinely-failed tickers (throttled, not price-filtered).
    # Retry them in small batches with a pause. Verified Aug 2026: throttled
    # names load on retry once the burst window cools.
    if failed:
        print(f"  Retry pass: {len(failed)} failed tickers...", flush=True)
        retry_pending = failed[:]
        failed = []
        for i in range(0, len(retry_pending), 10):
            batch = retry_pending[i : i + 10]
            try:
                new_data, new_filtered = _download_batch(batch, period, min_price, all_data, filtered_tickers)
                all_data.update(new_data)
                filtered_tickers.extend(new_filtered)
                succeeded = set(new_data.keys()) | set(new_filtered)
                for t in batch:
                    if t not in succeeded:
                        failed.append(t)
            except Exception:
                failed.extend(batch)
            time.sleep(1.5)
        print(f"  Retry pass done: recovered {len(retry_pending) - len(failed)}, still failed {len(failed)}", flush=True)

    if filtered_tickers:
        print(f"  Filtered {len(filtered_tickers)} stocks below ${min_price}")
    return all_data, failed, filtered_tickers


SPY_CACHE_FILE = os.path.join(CACHE_DIR, "cache_spy.pkl")


def get_benchmark(period="2y", force_refresh=False):
    """SPY data. Without --refresh, only uses cache. With --refresh, downloads."""
    if not force_refresh:
        try:
            with open(SPY_CACHE_FILE, "rb") as f:
                cache = pickle.load(f)
            age = (datetime.now() - cache["timestamp"]).total_seconds() / 3600
            print(f"  Using cached SPY data from {cache['timestamp'].strftime('%Y-%m-%d %H:%M')} ({age:.1f}h old)")
            return cache["data"]
        except (FileNotFoundError, Exception):
            print("  No cached SPY data. Use --refresh to download.")
            return None

    print("  Downloading SPY...")
    data = yf.download("SPY", period=period, auto_adjust=True, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        has_ticker_level = "SPY" in data.columns.get_level_values(0)
        if has_ticker_level:
            data = data["SPY"]
        else:
            data.columns = data.columns.swaplevel()
            data = data["SPY"]
    cache = {"data": data, "timestamp": datetime.now()}
    with open(SPY_CACHE_FILE, "wb") as f:
        pickle.dump(cache, f)
    return data


CACHE_FILE = os.path.join(CACHE_DIR, "cache_{}.pkl")


def save_cache(index, tickers, data, failed=None, filtered=None):
    cache = {
        "tickers": tickers,
        "data": data,
        "failed": failed or [],
        "filtered": filtered or [],
        "timestamp": datetime.now(),
        "index": index,
    }
    with open(CACHE_FILE.format(index), "wb") as f:
        pickle.dump(cache, f)


def load_cache(index, max_age_hours=168):
    """Load the cache file. Freshness is managed by cron, not here.

    The max_age_hours check is now a sanity guard (default 7 days)
    — if the cache is genuinely ancient or missing, fall through to
    a fresh download. Otherwise trust whatever the cron last wrote.

    To force a refresh, pass --refresh on the CLI (screen.py handles
    that flag and bypasses the cache entirely).
    """
    try:
        with open(CACHE_FILE.format(index), "rb") as f:
            cache = pickle.load(f)
        age = (datetime.now() - cache["timestamp"]).total_seconds() / 3600
        if age > max_age_hours:
            print(f"  Cache very stale ({age:.1f}h old > {max_age_hours}h), re-downloading...")
            return None
        print(f"  Loaded cached data from {cache['timestamp'].strftime('%Y-%m-%d %H:%M')} ({age:.1f}h old)")
        return cache
    except (FileNotFoundError, Exception):
        return None


def incremental_refresh(index, tickers, period="1mo", batch_size=25, min_price=None):
    """Incremental cache refresh: keep the existing 2y history and only
    download a recent window (default 1mo) to append to it.

    Strategy:
    - Load the existing cache (2y history from previous full runs).
    - Split tickers: known (already in cache) vs new (missing).
    - Known tickers: download only `period` of fresh bars, merge with the
      cached history (concat + dedupe on the date index, keep newest).
    - New tickers: full 2y download (backfill for IPOs / new listings).
    - Price filter (min_price) applies to the MERGED last close, not the
      fresh window, so a stock that dropped under $15 since the last run
      is still caught.
    - Tickers that fail the incremental pull keep their cached history
      instead of vanishing (old behavior dropped them entirely).

    Returns (all_data, failed) where all_data has full OHLCV history.
    """
    cache = load_cache(index)
    old_data = cache["data"] if cache else {}
    old_failed = set(cache.get("failed", [])) if cache else set()
    old_filtered = set(cache.get("filtered", [])) if cache else set()

    # Known: already in cache with data → incremental pull.
    known = [t for t in tickers if t in old_data and not old_data[t].empty]
    # New: not in cache AND not previously price-filtered → full backfill.
    # Previously-filtered (sub-$15) names are skipped: re-downloading them
    # every run just to filter them again is wasted requests. A periodic
    # full refresh (--full-refresh) re-checks them for $15 crossings.
    new = [t for t in tickers if t not in old_data and t not in old_filtered]
    skipped_filtered = [t for t in tickers if t not in old_data and t in old_filtered]

    print(f"  Incremental refresh: {len(known)} known, {len(new)} new, {len(skipped_filtered)} previously-filtered (skipped)", flush=True)

    all_data = {}
    failed = []
    filtered_out = list(old_filtered)

    # ── 1. New tickers: full history backfill ──
    if new:
        print(f"  Backfilling {len(new)} new tickers (full history)...", flush=True)
        new_data, new_failed, new_filtered = download_data(new, period="2y", batch_size=batch_size, min_price=min_price)
        all_data.update(new_data)
        failed.extend(new_failed)
        filtered_out.extend(new_filtered)

    # ── 2. Known tickers: fresh window only, merge into cache ──
    if known:
        print(f"  Fetching recent data for {len(known)} known tickers ({period})...", flush=True)
        fresh_data, fresh_failed, fresh_filtered = download_data(known, period=period, batch_size=batch_size, min_price=None)
        # failed here means the incremental pull failed for that ticker —
        # keep its cached history instead of dropping it.
        failed.extend(fresh_failed)

        for t in known:
            cached = old_data.get(t)
            fresh = fresh_data.get(t)

            # No fresh bars (delisted/suspended): keep cached history.
            if fresh is None or fresh.empty:
                if cached is not None and not cached.empty:
                    all_data[t] = cached
                else:
                    failed.append(t)
                continue

            # Merge: cached history + fresh bars, dedupe on date, newest wins.
            merged = pd.concat([cached, fresh]) if cached is not None else fresh
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()

            # Apply the price filter on the merged last close.
            if min_price is not None:
                close_series = pd.Series(merged["Close"]).dropna()
                last_close = float(close_series.iloc[-1]) if len(close_series) else float("nan")
                if pd.isna(last_close) or last_close < min_price:
                    filtered_out.append(t)
                    continue  # dropped from cache, not counted as failed

            all_data[t] = merged

    # ── 3. Save ──
    save_cache(index, tickers, all_data, failed, filtered_out)
    print(f"  Incremental refresh done: {len(all_data)} stocks, {len(failed)} failed, {len(filtered_out)} filtered", flush=True)
    return all_data, failed
