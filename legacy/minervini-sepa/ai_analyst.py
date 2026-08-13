import os
import json
import requests
from typing import List, Dict, Optional
from dotenv import load_dotenv
from dataclasses import dataclass

load_dotenv()


@dataclass
class AIAnalysis:
    symbol: str
    summary: str
    setup_quality: str
    risk_level: str
    key_catalysts: List[str]
    recommendation: str
    estimated_entry_price: Optional[float] = None
    sentiment: str = "-"  # positive/negative/neutral


class BaseAnalyst:
    """Base class for AI analysts with shared logic."""

    def __init__(self):
        self.api_key = None
        self.mock_mode = os.getenv("MOCK_AI", "false").lower() in ("true", "1", "yes")

    def _get_mock_response(self, symbol: str) -> str:
        """Return mock AI response in JSON format for testing."""
        return f'{{"SE": "positive", "CA": ["Mock catalyst 1 for {symbol}", "Mock catalyst 2 for {symbol}"], "SM": "Mock sentiment for {symbol}: positive earnings and news outlook."}}'

    def _build_prompt(self, symbol: str, stock_data: Dict) -> str:
        price = stock_data.get('price', 'N/A')
        news_articles = stock_data.get('recent_news', [])

        news_text = ""
        if news_articles and len(news_articles) > 0:
            news_lines = []
            for article in news_articles[:3]:
                title = article.get('title', 'N/A')
                summary = article.get('summary', 'No summary available')
                link = article.get('link', '')
                news_lines.append(f"- {title}: {summary[:200]} [Link: {link}]")
            news_text = "\n".join(news_lines)
        else:
            news_text = "No recent news available"

        earnings_date = stock_data.get('next_earnings', 'N/A')

        return f"""Analyze recent earnings and news for {symbol} to determine the sentiment (positive, negative, or neutral).

Data:
- Current Price: ${price}
- Next Earnings Date: {earnings_date}
- Recent News:
{news_text}

TASK: Based on the earnings outlook and recent news, determine if the sentiment is POSITIVE (earnings beat/raise guidance, positive catalysts), NEGATIVE (earnings miss/lower guidance, negative news), or NEUTRAL (no clear direction, mixed news).

OUTPUT ONLY VALID JSON. NO markdown, NO code blocks, NO explanation:
{{"SE": "positive/negative/neutral", "CA": ["key catalyst or news event 1", "key catalyst or news event 2"], "SM": "one sentence sentiment summary"}}"""

    def _call_llm(self, prompt: str) -> Optional[str]:
        raise NotImplementedError("Subclasses must implement _call_llm")

    def analyze_stock(self, symbol: str, stock_data: Dict) -> Optional[AIAnalysis]:
        if not self.api_key and not self.mock_mode:
            return None

        try:
            if self.mock_mode:
                text = self._get_mock_response(symbol)
                print(f"MOCK AI response for {symbol}:\n{text}\n")
            else:
                prompt = self._build_prompt(symbol, stock_data)
                text = self._call_llm(prompt)

            if not text:
                print(f"AI returned empty response for {symbol}")
                return None

            print(f"AI raw response for {symbol}:\n{text}\n")

            # Try to extract JSON from response (may be wrapped in markdown)
            json_text = text.strip()
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0].strip()
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0].strip()

            try:
                data = json.loads(json_text)
                sentiment = data.get("SE", "neutral")
                catalysts = data.get("CA", [])
                if not isinstance(catalysts, list):
                    catalysts = [catalysts] if catalysts else []
                summary = data.get("SM")
            except json.JSONDecodeError:
                # Fallback to line parsing if JSON fails
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                sentiment = "neutral"
                catalysts = []
                summary = None
                for line in lines:
                    if line.startswith("- SE:"):
                        sentiment = line.split("SE:")[1].strip()
                    elif line.startswith("- CA:"):
                        catalysts.append(line.split("CA:")[1].strip())
                    elif line.startswith("- SM:"):
                        summary = line.split("SM:")[1].strip()

            print(f"Parsed for {symbol}: sentiment={sentiment}, catalysts={catalysts}, summary={summary}")

            return AIAnalysis(
                symbol=symbol,
                summary=summary or "Analysis unavailable",
                setup_quality="N/A",
                risk_level="N/A",
                key_catalysts=catalysts or [],
                recommendation="N/A",
                estimated_entry_price=None,
                sentiment=sentiment,
            )
        except Exception as e:
            print(f"AI analysis failed for {symbol}: {e}")
            return None

    def analyze_opportunities(self, stocks: List) -> Dict[str, AIAnalysis]:
        results = {}
        if not self.api_key and not self.mock_mode:
            print(f"No API key configured for {self.__class__.__name__} - skipping AI analysis")
            return results

        # Cap is set by the caller (report.py passes the desired limit).
        # No hard cap here — analyze every stock in the list.
        for stock in stocks:
            stock_data = {
                "price": getattr(stock, "price", None),
                "entry_zone": getattr(stock, "entry_zone", None),
                "rs_rating": getattr(stock, "rs_rating", None),
                "trend_score": getattr(stock, "trend_score", None),
                "next_earnings": getattr(stock, "next_earnings_date", None),
                "catalyst": getattr(stock, "catalyst", None),
                "recent_news": getattr(stock, "news_articles", []) or [],
            }
            analysis = self.analyze_stock(stock.symbol, stock_data)
            if analysis:
                results[stock.symbol] = analysis

        return results


class GeminiAnalyst(BaseAnalyst):
    def __init__(self, api_key: str = None):
        super().__init__()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        # Use Flash for cost-efficient sentiment analysis across many stocks.
        # Pro is overkill for short classification + 2-bullet catalyst extraction.
        self.model = "gemini-3.1-flash-lite-preview"

    def _call_llm(self, prompt: str) -> Optional[str]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2048,
            }
            }

            response = requests.post(url, json=payload, timeout=30)
            if response.status_code != 200:
                print(f"Gemini API error: {response.status_code}")
                return None

            result = response.json()
            return result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        except Exception as e:
            print(f"Gemini API call failed: {e}")
            return None


class ClaudeAnalyst(BaseAnalyst):
    def __init__(self, api_key: str = None):
        super().__init__()
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        # Sonnet is ~5x cheaper than Opus with comparable quality for short
        # sentiment-classification tasks. Switch to claude-haiku-4-5 for the
        # cheapest option if running across very large universes.
        self.model = "claude-haiku-4-5"

    def _call_llm(self, prompt: str) -> Optional[str]:
        try:
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}]
            }

            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code != 200:
                print(f"Claude API error: {response.status_code} - {response.text}")
                return None

            result = response.json()
            return result.get("content", [{}])[0].get("text", "")
        except Exception as e:
            print(f"Claude API call failed: {e}")
            return None


def get_ai_analysis(stocks: List) -> Dict[str, AIAnalysis]:
    claude_key = os.getenv("ANTHROPIC_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    if claude_key:
        analyst = ClaudeAnalyst()
        print("Using Claude for AI analysis")
    elif gemini_key:
        analyst = GeminiAnalyst()
        print("Using Gemini for AI analysis")
    else:
        print("No AI API keys configured - skipping AI analysis")
        return {}

    return analyst.analyze_opportunities(stocks)
