import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()


class AlphaVantageClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
        self.base_url = "https://www.alphavantage.co/query"

    def get_earnings_calendar(self, symbols: List[str]) -> Dict[str, Optional[str]]:
        result = {}
        for symbol in symbols:
            try:
                url = f"{self.base_url}?function=EARNINGS&symbol={symbol}&apikey={self.api_key}"
                resp = requests.get(url, timeout=10)
                data = resp.json()

                quarterly = data.get("quarterlyEarnings", [])
                if quarterly:
                    next_earnings = quarterly[0].get("reportedDate")
                    if next_earnings:
                        result[symbol] = next_earnings
                else:
                    result[symbol] = None
            except Exception:
                result[symbol] = None
        return result


class FinnhubClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY")
        self.base_url = "https://finnhub.io/api/v1"

    def get_company_news(self, symbol: str, from_date: str = None, to_date: str = None) -> List[Dict]:
        if not from_date:
            from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")

        try:
            url = f"{self.base_url}/company-news?symbol={symbol}&from={from_date}&to={to_date}&token={self.api_key}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                news = resp.json()
                return [
                    {
                        "headline": n.get("headline", "")[:100],
                        "source": n.get("source", ""),
                        "datetime": n.get("datetime", ""),
                    }
                    for n in news[:5]
                ]
        except Exception:
            pass
        return []

    def get_earnings_calendar(self, symbol: str) -> Optional[Dict]:
        try:
            url = f"{self.base_url}/calendar/earnings?symbol={symbol}&token={self.api_key}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                earnings = data.get("earningsCalendar")
                if earnings and len(earnings) > 0:
                    return earnings[0]
        except Exception:
            pass
        return None


def fetch_stock_data(symbols: List[str], use_finnhub: bool = True) -> Dict[str, Dict]:
    result = {}
    fh_client = FinnhubClient()

    for symbol in symbols:
        entry = {
            "next_earnings": None,
            "recent_news": [],
            "catalyst": None,
        }

        if use_finnhub:
            news = fh_client.get_company_news(symbol)
            entry["recent_news"] = [n["headline"] for n in news[:3]]

            earnings_cal = fh_client.get_earnings_calendar(symbol)
            if earnings_cal:
                entry["next_earnings"] = earnings_cal.get("date")
                entry["catalyst"] = earnings_cal.get("estimate")

        if entry["next_earnings"]:
            try:
                e_date = datetime.strptime(entry["next_earnings"], "%Y-%m-%d")
                days_until = (e_date - datetime.now()).days
                if days_until >= 0 and days_until <= 30:
                    entry["catalyst"] = f"Earnings in {days_until} days"
                elif days_until < 0:
                    entry["catalyst"] = f"Earnings reported"
            except Exception:
                pass

        result[symbol] = entry

    return result