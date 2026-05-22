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

| Column | Description |
|--------|-------------|
| Ticker | Stock symbol (clickable TradingView link in email) |
| Price | Current closing price |
| vs 50 SMA% | % distance from 50-day SMA (positive = above) |
| SMA50 | 50-day simple moving average |
| SMA150 | 150-day simple moving average |
| SMA200 | 200-day simple moving average |
| ATR(22) | 22-day Average True Range |
| VCP | Volatility Contraction Pattern status (VCP Tight / VCP Forming / No VCP) |
| VCP Score | 0–100 contraction confidence score |
| Next Earnings | Upcoming earnings report date |
| RS Rating | Relative Strength percentile (1–99) |

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

- Downloaded data is cached to `cache_sp500.pkl`, `cache_sp400.pkl`, `cache_sp600.pkl`
- Cache expires after 24 hours
- Use `--refresh` to force re-download

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
