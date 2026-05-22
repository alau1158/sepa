import os
import pickle
from datetime import datetime
from io import StringIO

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


TICKER_SOURCES = {
    "sp500": get_sp500_tickers,
    "sp400": get_sp400_tickers,
    "sp600": get_sp600_tickers,
}


def get_tickers(index):
    fn = TICKER_SOURCES.get(index)
    if not fn:
        raise ValueError(f"Unknown index: {index}")
    return fn()


def download_data(tickers, period="2y", batch_size=100):
    all_data = {}
    failed = []

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        try:
            data = yf.download(
                batch,
                period=period,
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )

            if isinstance(data.columns, pd.MultiIndex):
                for ticker in batch:
                    try:
                        td = data[ticker]
                        if isinstance(td, pd.DataFrame) and not td.empty:
                            all_data[ticker] = td
                        else:
                            failed.append(ticker)
                    except (KeyError, Exception):
                        failed.append(ticker)
            else:
                if batch and not data.empty:
                    all_data[batch[0]] = data
                else:
                    failed.extend(batch)
        except Exception:
            failed.extend(batch)

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
