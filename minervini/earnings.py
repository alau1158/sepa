import yfinance as yf


def get_next_earnings(ticker):
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal and "Earnings Date" in cal:
            dates = cal["Earnings Date"]
            if isinstance(dates, list):
                if len(dates) == 2 and dates[0] != dates[1]:
                    d = dates[0]
                    if hasattr(d, "strftime"):
                        return f"Week of {d.strftime('%Y-%m-%d')}"
                    return f"Week of {d}"
                d = dates[0]
                if hasattr(d, "strftime"):
                    return d.strftime("%Y-%m-%d")
                return str(d)
            if hasattr(dates, "strftime"):
                return dates.strftime("%Y-%m-%d")
            return str(dates)
        return "N/A"
    except Exception:
        return "N/A"
