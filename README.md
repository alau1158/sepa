# SEPA Stage 2 Stock Screener

A stock screener implementing Mark Minervini's **SEPA** (Specific Entry Point Analysis) methodology to identify stocks in a **Stage 2 uptrend**. Screens the S&P 500, S&P 400, and S&P 600 indices.

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

# Multiple indices
python screen.py -sp500 -sp600

# All three
python screen.py -all

# Console only (no email)
python screen.py -sp500 --no-email

# Save to CSV
python screen.py -sp500 --output results.csv

# Force re-download (ignore cache)
python screen.py -sp500 --refresh
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
- Computes average RS Rating per industry group
- Ranks groups by average RS (1 = strongest)
- Groups with fewer than 3 stocks are excluded

## Email Setup

Configure `.env` in the project root:

```env
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
RECIPIENTS=email1@example.com,email2@example.com
```

- Uses Gmail SMTP (`smtp.gmail.com:587`)
- App passwords recommended (enable 2FA → create app-specific password)
- Multiple recipients comma-separated (`#` comments supported)

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
  screener.py     — Filter + enrichment orchestration
  earnings.py     — Next earnings date from yfinance calendar
  fundamentals.py — Industry RS rank + EPS Rating (cached)
  emailer.py      — HTML table with TradingView links, Gmail SMTP
screen.py         — CLI entry point with argparse
```

## Requirements

- yfinance
- pandas
- requests
- lxml
- tqdm
- python-dotenv

Install: `pip install -r requirements.txt`

## Disclaimer

For educational purposes. Not financial advice.
