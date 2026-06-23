import os
import pickle
import time
from datetime import datetime
from io import StringIO

import urllib.request

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
    """Download a single batch and return (new_data_dict, filtered_count)."""
    data = yf.download(
        batch,
        period=period,
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )

    new_data = {}
    new_filtered = 0

    if isinstance(data.columns, pd.MultiIndex):
        for ticker in batch:
            try:
                td = data[ticker]
                if isinstance(td, pd.DataFrame) and not td.empty:
                    if min_price is not None:
                        last_close = td["Close"].iloc[-1]
                        if pd.isna(last_close) or last_close < min_price:
                            new_filtered += 1
                            continue
                    new_data[ticker] = td
            except (KeyError, Exception):
                pass
    else:
        if batch and not data.empty:
            if min_price is None or data["Close"].iloc[-1] >= min_price:
                new_data[batch[0]] = data
            else:
                new_filtered += 1

    return new_data, new_filtered


def download_data(tickers, period="2y", batch_size=25, min_price=None):
    all_data = {}
    failed = []
    filtered = 0
    total_batches = (len(tickers) + batch_size - 1) // batch_size

    # Main pass: smaller batches with generous sleep
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        try:
            new_data, new_filtered = _download_batch(batch, period, min_price, all_data, filtered)
            all_data.update(new_data)
            filtered += new_filtered

            # Track failed tickers in this batch
            batch_set = set(batch)
            succeeded = set(new_data.keys())
            for t in batch:
                if t not in succeeded:
                    failed.append(t)

            if batch_num % 20 == 0 or batch_num == total_batches:
                print(f"  Progress: {batch_num}/{total_batches} batches ({len(all_data)} stocks loaded, {len(failed)} failed)", flush=True)
        except Exception:
            failed.extend(batch)

        time.sleep(5.0)

    # Retry pass: failed tickers one at a time with longer sleep
    if failed:
        print(f"\n  Retry pass: {len(failed)} failed tickers (one-at-a-time, 5s between)", flush=True)
        retry_failed = []
        for i, ticker in enumerate(failed):
            try:
                new_data, new_filtered = _download_batch([ticker], period, min_price, all_data, filtered)
                all_data.update(new_data)
                filtered += new_filtered
                if ticker not in all_data:
                    retry_failed.append(ticker)
            except Exception:
                retry_failed.append(ticker)

            if (i + 1) % 50 == 0:
                print(f"  Retry progress: {i+1}/{len(failed)} ({len(retry_failed)} still failed)", flush=True)
            time.sleep(5.0)

        failed = retry_failed
        if failed:
            print(f"  Final failed count: {len(failed)}", flush=True)

    if filtered:
        print(f"  Filtered {filtered} stocks below ${min_price}")
    return all_data, failed


SPY_CACHE_FILE = os.path.join(CACHE_DIR, "cache_spy.pkl")


def get_benchmark(period="2y", force_refresh=False):
    """Download SPY data (cached 6h)."""
    if not force_refresh:
        try:
            with open(SPY_CACHE_FILE, "rb") as f:
                cache = pickle.load(f)
            age = (datetime.now() - cache["timestamp"]).total_seconds() / 3600
            if age <= 6:
                print("  Using cached SPY data")
                return cache["data"]
            else:
                print(f"  SPY cache expired ({age:.1f}h), re-downloading...")
        except (FileNotFoundError, Exception):
            pass

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


def save_cache(index, tickers, data, failed=None):
    cache = {
        "tickers": tickers,
        "data": data,
        "failed": failed or [],
        "timestamp": datetime.now(),
        "index": index,
    }
    with open(CACHE_FILE.format(index), "wb") as f:
        pickle.dump(cache, f)


def load_cache(index, max_age_hours=6):
    try:
        with open(CACHE_FILE.format(index), "rb") as f:
            cache = pickle.load(f)
        age = (datetime.now() - cache["timestamp"]).total_seconds() / 3600
        if age > max_age_hours:
            print(f"  Cache expired ({age:.1f}h old), re-downloading...")
            return None
        print(f"  Loaded cached data from {cache['timestamp'].strftime('%Y-%m-%d %H:%M')}")
        return cache
    except (FileNotFoundError, Exception):
        return None
