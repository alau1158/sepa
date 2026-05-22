import yfinance as yf

from . import fundamentals as fund


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
    stored = fund._load_fund_cache().get("earnings", {})
    cache = dict(stored)
    missing = [t for t in tickers if t not in stored]
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
