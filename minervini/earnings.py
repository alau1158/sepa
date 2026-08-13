import yfinance as yf
from datetime import datetime

from . import fundamentals as fund


def _is_stale_date(value, today):
    """True if a cached Next_Earnings date is in the past (already reported).

    The cache freezes dates at first fetch; yfinance moves on after each
    report. A cached date older than today is stale by definition and must
    be refetched — otherwise EAT can show '2026-04-29' in August.
    """
    s = str(value)
    if s.startswith("Week of "):
        s = s[len("Week of "):]
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return False
    return d < today


def get_next_earnings(ticker):
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal and "Earnings Date" in cal:
            dates = cal["Earnings Date"]
            if isinstance(dates, list):
                d = dates[0]
                if len(dates) == 2 and dates[0] != dates[1]:
                    if hasattr(d, "strftime"):
                        return f"Week of {d.strftime('%Y-%m-%d')}"
                    return f"Week of {d}"
                if hasattr(d, "strftime"):
                    return d.strftime("%Y-%m-%d")
                return str(d)
            if hasattr(dates, "strftime"):
                return dates.strftime("%Y-%m-%d")
            return str(dates)
        return "N/A"
    except Exception:
        return "N/A"


def get_earnings_cache(tickers):
    from datetime import date as _date
    stored = fund._load_fund_cache().get("earnings", {})
    cache = dict(stored)
    today = _date.today()
    # Refetch any cached date that is in the past — the cache freezes dates
    # at first fetch, so a stale entry (e.g. EAT '2026-04-29' in August) would
    # otherwise poison Next_Earnings forever.
    missing = [
        t for t in tickers
        if t not in stored or _is_stale_date(stored.get(t), today)
    ]
    for t in missing:
        result = get_next_earnings(t)
        if result and result != "N/A":
            cache[t] = result
    if missing:
        fc = fund._load_fund_cache()
        fc["earnings"] = cache
        fc["_earnings_ts"] = __import__("datetime").datetime.now()
        fund._save_fund_cache(fc)
    return cache
