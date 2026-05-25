# SEPA Stage 2 Stock Screener

A stock screener implementing Mark Minervini's **SEPA** (Specific Entry Point Analysis) methodology to identify stocks in a **Stage 2 uptrend**. Screens the S&P 500, S&P 400, S&P 600, NASDAQ, and NYSE. Also includes a separate watchlist news summarizer that fetches recent news and summarizes it via Gemini AI.

## The 8 Trend Template Criteria

All 8 must pass simultaneously for a stock to qualify:

| # | Criterion | Condition |
|---|-----------|-----------|
| 1 | Price > 150 & 200 SMA | Close above both 150-day and 200-day SMAs |
| 2 | 150 SMA > 200 SMA | Medium-term MA above long-term MA |
| 3 | 200 SMA trending up | Higher than it was 22 trading days ago |
| 4 | 50 SMA > 150 & 200 SMA | Short-term MA above both longer MAs |
| 5 | Price > 50 SMA | Close above 50-day SMA |
| 6 | ≥ 30% above 52w low | Price at least 30% above 52-week low |
| 7 | Within 25% of 52w high | Price within 25% of 52-week high |
| 8 | RS Rating ≥ 80 | IBD-style relative strength percentile rank |

## Usage

```bash
# Screen individual indices
python screen.py -sp500
python screen.py -sp400
python screen.py -sp600
python screen.py -nasdaq
python screen.py -nyse

# Multiple indices
python screen.py -sp500 -sp600 -nasdaq

# All S&P indices
python screen.py -all

# All US stocks (S&P + NASDAQ + NYSE)
python screen.py --all-us

# Console only (no email)
python screen.py -sp500 --no-email

# Save to CSV
python screen.py -sp500 --output results.csv

# Force re-download (ignore cache)
python screen.py -sp500 --refresh

# ── Watchlist News Summarizer ──────────────────────
python news_watchlist.py                            # full run (news → Gemini → email)
python news_watchlist.py --no-email                 # print summaries to console
python news_watchlist.py --watchlist my_list.txt    # use a different watchlist file
```

## Output Columns

Quick reference: **higher is better** for VCP Score, EPS, RS Rating. **Lower is better** for Ind Rk. **A is better than E** for A/D.

| Column | Direction | Description |
|--------|-----------|-------------|
| Ticker | — | Stock symbol (clickable TradingView link in email) |
| Price | — | Current closing price |
| vs 50 SMA% | — | % distance from 50-day SMA (positive = above) |
| ATR% | — | 22-day Average True Range as % of price |
| VCP | Higher better | Volatility Contraction Pattern: VCP Tight / Forming / None |
| VCP Score | Higher better | 0–100 contraction confidence (≥60 Tight, ≥45 Forming, <45 None) |
| A/D | A > E | Accumulation/Distribution (A=strong buying, E=strong selling) |
| EPS | Higher better | Earnings Per Share growth percentile (1–99) |
| Ind Rk | Lower better | Industry group RS rank (e.g. `3/70` = 3rd out of 70 groups) |
| Next Earnings | — | Upcoming earnings report date |
| RS Rating | Higher better | Relative Strength percentile (1–99) |
| RS Trend | Up preferred | RS line (stock/SPY ratio) 65-day direction |
| RS Div | Yes preferred | RS line made a new 13d high before price did (bullish divergence) |
| Corr Div | Strong preferred | Stock held up better than market during SPY corrections ≥5% |
| Brk Order | 1 or 2 preferred | Breakout timing rank within industry (e.g. `1/3` = first to break out) |
| Exh | Normal preferred | Exhaustion status: Normal / Late Stage / Exhausted (climax top) |
| Exh Sc | Lower better | Exhaustion score (0–100), ≥60 = climax top likely |
| Dist | Normal preferred | Distribution status: Normal / Weakening / Distribution (breaking down) |
| Dist Sc | Lower better | Distribution score (0–100), ≥60 = institutional selling |
| Viol | Clean preferred | Post-purchase violation status: Clean / Minor / Warning / Multiple |
| V Sc | Lower better | Violation score (0–100), ≥60 = multiple violations active |

### Minervini Context for New Columns

For a stock showing strong relative and institutional characteristics, look for:
- **RS Trend**: `Up`
- **RS Div**: `Yes` or `Partial` — stock strengthening versus market before price confirms
- **Corr Div**: `Strong` or `Moderate` — stock holds up better than SPY during corrections
- **Brk Order**: `1` or `2` — first to break out in its industry group (industry leadership)

### VCP Scoring Breakdown (max 100 pts)

| Component | Max Pts | Method |
|-----------|---------|--------|
| Range contraction | 50 | 5-window ~10d splits, progressive tightening checks |
| Volume dry-up | 25 | 5-window volume decline check |
| Breakout | 25 | Price above base high + volume confirmation + extension |

### A/D Rating Thresholds

| Rating | Net 65-day Score | S&P 500 Distribution | Meaning |
|--------|-----------------|---------------------|---------|
| A | ≥ +7 | ~5% | Strong accumulation (institutional buying) |
| B | +3 to +6 | ~18% | Moderate accumulation |
| C | -3 to +2 | ~52% | Neutral |
| D | -7 to -4 | ~17% | Moderate distribution |
| E | ≤ -8 | ~8% | Strong distribution (institutional selling) |

### EPS Rating

- YoY growth of latest quarterly Diluted EPS vs same quarter one year ago
- Negative-to-positive turnarounds scored as 999% growth
- Ranked 1–99 among all tickers in the screened universe
- Stocks with 2+ consecutive negative quarters or missing data are skipped

### Industry RS Rank

- Groups all stocks in the screened universe by yfinance `industry`
- Ranks groups by the **top RS Rating among passing tickers** in that industry (Minervini bottom-up approach)
- Only industries with at least 1 passing stock are ranked
- Higher rank (1 = strongest) = the industry contains at least one very strong relative performer

### Breakout Order

- Within each industry, passing stocks are ordered by when they broke out above their 20-day high on >1.2× average volume
- The stock that breaks out earliest gets rank `1`
- First movers in an industry tend to be the leaders

### Exhaustion Score (Taking Profits Into Strength)

Detects climax-run / blow-off top signals. Higher score = more overextended.

| Component | Max Pts | Method |
|-----------|---------|--------|
| Climax Run | 25 | 25–50%+ gain in any rolling 3-week window (last 30 days) |
| Concentrated Up Days | 20 | ≥70% up days in trailing 15 days |
| Extreme Price Spread | 20 | Widest daily range (% price) in 65 days, occurring in last 15 |
| Exhaustion Gap | 15 | Gap up above prior day's high, close held, price >20% above 50 SMA |
| Churning | 10 | Volume >1.5× avg with <0.5% price move (2+ days in last 10) |
| P/E Expansion | 10 | Trailing P/E doubled vs ~6 months ago |

- ≥60 = **Exhausted** (climax top likely near)
- 35–59 = **Late Stage** (extended but not yet climaxing)
- <35 = **Normal**

### Distribution Score (Selling Into Weakness)

Detects technical breakdown / institutional distribution signals.

| Component | Max Pts | Method |
|-----------|---------|--------|
| Major Price Break | 30 | Largest 1-day % decline in 65 days, >2× avg daily move |
| High-Volume Reversal | 25 | Close below open AND prior close on >1.5× avg volume |
| MA Violation | 25 | Close below 50 SMA on >1.3× avg volume (within last 5 days) |
| Full Retracement | 20 | Price within 5% of 50-day low (whipsaw) |

- ≥60 = **Distribution** (institutional selling)
- 35–59 = **Weakening** (early signs of breakdown)
- <35 = **Normal**

### RS Line & Market Divergence

- **RS Line** = stock close / SPY close, measuring relative strength versus the broad market
- **RS Trend** checks whether the RS line's 65-day slope is positive (Up) or negative (Down)
- **RS Divergence** detects when the RS line makes a new 13-day high while price does not — a bullish signal that institutional money is quietly accumulating
- **Market Correction Divergence** looks at SPY 5%+ corrections and checks if the stock made higher lows during those declines, indicating the stock is under accumulation relative to the market

### Post-Purchase Violations (Portfolio Report)

Minervini watches for specific abnormal price/volume activity after entering a trade.
If multiple violations pile up, the trade is likely failing and should be cut early.

The violations score (0–100) is computed from 8 checks:

| Component | Max Pts | Method |
|-----------|---------|--------|
| Breach of 20-day SMA | 15 | Close below 20-day SMA (recent 5 days) |
| Breach of 50-day SMA + heavy vol | 25 | Close below 50-day SMA on >1.3× avg volume |
| Three+ Lower Lows | 20 | 3–4 consecutive days of declining lows |
| Poor Close-to-Range Ratio | 15 | More bad closes (lower half of range) than good closes + more down days |
| Low Volume Out, High Vol In | 20 | Breakout on below-avg volume, then reversal on heavy volume |
| Lack of Follow-Through | 15 | Strong up day followed by stalling |
| Full Retracement of Gains | 20 | Price retraces all gains back to entry after being up ≥10% |
| Abnormal Volume Reversal | 20 | Attempts to rally, reverses to close lower on heaviest volume of the move |

- ≥60 = **Multiple** (strongly suggests trade will fail)
- 35–59 = **Warning**
- 15–34 = **Minor**
- <15 = **Clean**

## Watchlist News Summarizer

A standalone script (`news_watchlist.py`) that reads a watchlist file, fetches the past week of news for each ticker via yfinance, summarizes each stock's news into 1–2 paragraphs using Gemini 3.5 Flash, and emails the result.

### Watchlist File Format

One ticker per line, `#` for comments:

```
# My watchlist
AAPL
NVDA
AMD
DELL
```

Default path: `watchlist.txt` (override with `--watchlist`). This file is gitignored — create your own, one ticker per line.

### Per-Ticker Summaries

Each stock gets its own Gemini AI summary paragraph in the email, followed by the raw article links. This keeps the signal per-stock rather than mixing everything into one blob.

```bash
python news_watchlist.py                      # full run
python news_watchlist.py --no-email           # console only
python news_watchlist.py --watchlist my.txt   # custom watchlist file
```

## Portfolio Report

Generates a combined HTML report of your open positions (with A/D rating +
violations + exhaustion/distribution signals from the screener) and closed trades
(P&L grouped by broker). Reads `journal.csv` from the project root.

```bash
python portfolio_report.py              # sends email to REPORT_RECIPIENTS
python portfolio_report.py --no-email   # print to console only
```

## Email Setup

Copy `.env.template` to `.env` and fill in your credentials:

```env
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
RECIPIENTS=email1@example.com,email2@example.com
REPORT_RECIPIENTS=you@example.com
GEMINI_API_KEY=your_gemini_api_key
```

- Uses Gmail SMTP (`smtp.gmail.com:587`)
- App passwords recommended (enable 2FA → create app-specific password)
- Multiple recipients comma-separated (`#` comments supported)
- `RECIPIENTS` receives screener results; `REPORT_RECIPIENTS` receives news summaries
- `GEMINI_API_KEY` is required only for the watchlist news summarizer (get one at [aistudio.google.com](https://aistudio.google.com/))

## Caching

| Cache | File | Expiry |
|-------|------|--------|
| Price data | `cache_{index}.pkl` | 6 hours |
| Fundamentals (industries, EPS, earnings) | `cache_fundamentals.pkl` | Industries: 7 days, EPS: 24h, Earnings: 24h |

Use `--refresh` to force re-download price data. Delete `cache_fundamentals.pkl` manually to reset fundamental data.

## Project Structure

```
minervini/
  data.py         — Ticker sources, yfinance download, pickle cache
  indicators.py   — SMAs, ATR, 52w metrics, A/D Rating
  rs_rating.py    — IBD-style RS percentile (40/20/20/20 weighting)
  vcp.py          — VCP detection (5-window swing-based)
  sell_signals.py — Exhaustion climax + distribution breakdown scores
  violations.py   — Post-purchase violation detection (8 Minervini criteria)
  screener.py     — Filter + enrichment orchestration
  earnings.py     — Next earnings date from yfinance calendar
  fundamentals.py — Industry RS rank + EPS Rating (cached)
  emailer.py      — HTML table with TradingView links, Gmail SMTP
screen.py           — SEPA screener CLI
news_watchlist.py   — Watchlist news summarizer CLI
portfolio_report.py — Portfolio report with A/D, exhaustion, distribution signals
.env.template           — Environment variable template
journal.example.csv     — Journal format reference
watchlist.example.txt   — Watchlist format reference
watchlist.txt           — (gitignored) Your watchlist, one ticker per line
```

## Requirements

- yfinance
- pandas
- requests
- lxml
- tqdm
- python-dotenv
- google-genai (watchlist news only)

Install: `pip install -r requirements.txt`

## Disclaimer

For educational purposes. Not financial advice.
