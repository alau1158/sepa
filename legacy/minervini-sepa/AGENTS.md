# Long Term Investing - Mark Minervini Strategy

## Quick Start

```bash
pip install -r requirements.txt
python scheduler.py          # Run weekly reports (Sundays 9am)
python report.py              # Run single report (S&P 500 by default)
python screener.py -sp400     # Screen S&P 400 (Mid-Cap) stocks
python screener.py -sp600     # Screen S&P 600 (Small-Cap) stocks
```

## Project Structure

| File | Purpose |
|------|---------|
| `holdings.csv` | Your stock portfolio - edit with your IRA holdings |
| `screener.py` | Mark Minervini trend template screening |
| `portfolio.py` | Holdings management |
| `report.py` | Weekly HTML report generation |
| `notifier.py` | Gmail SMTP email sending |
| `scheduler.py` | Weekly cron job |

## Dependencies

- yfinance, pandas, numpy, python-dotenv, schedule
- System requires pip (not available in this environment - run locally)

## Key Files

- `.env` contains SMTP credentials (Gmail app password in SMTP_PASSWORD)
- `holdings.csv` format: `symbol,shares,purchase_date,purchase_price`

## Running

- `python report.py` - sends report for S&P 500 to email in SMTP_USER (.env)
- `python report.py -sp400` - sends report for S&P 400 (Mid-Cap)
- `python report.py -sp600` - sends report for S&P 600 (Small-Cap)
- `python screener.py` - run screener for S&P 500
- `python screener.py -sp400` - run screener for S&P 400
- `python screener.py -sp600` - run screener for S&P 600
- `python screener.py --audit SYMBOL` - audit a specific stock
- Edit `holdings.csv` with your actual stocks before first run

## Minervini Criteria Used

- Price > 50-day MA > 150-day MA > 200-day MA
- 200-day MA trending up (1+ month)
- Price within 25% of 52-week high
- RS rating > 80 vs S&P 500
- Positive EPS (25%+) and revenue growth (25%+)