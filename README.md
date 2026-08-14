# SEPA Stage 2 Stock Screener

A stock screening toolkit implementing Mark Minervini's **SEPA** (Specific Entry Point Analysis) methodology to identify stocks in a **Stage 2 uptrend**. Screens the S&P 500, S&P 400, S&P 600, NASDAQ, and NYSE.

The repo is a suite, not one script:

| Tool | File | What it does |
|------|------|--------------|
| SEPA screener | `screen.py` | The 8-criteria Stage 2 screen + VCP/pullback/exhaustion/distribution enrichment |
| Momentum scanner | `momentum_accel.py` | Catches parabolic acceleration (MU-in-May style) the VCP screen misses |
| Market regime watcher | `market_regime.py` | Tells you when to switch between MOMENTUM and VCP modes |
| Sector heat monitor | `sector_heat.py` | Flags baskets ("AI getting hot") before individual scans do |
| Portfolio report | `portfolio_report.py` | P&L + position health report from your Google Sheet journal |
| News summarizer | `news_watchlist.py` | Summarizes the past week's news for open positions |
| Peer scanner | `peerscan.py` | Industry peer comparison for a given ticker |
| Steady climber | `steady_climber.py` | Streak-based steady-rise scanner (experimental, not scheduled) |

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

## Usage — SEPA Screener

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

# Save to CSV (auto mode writes to $CSV_OUTPUT_DIR, default ~/csv_output)
python screen.py -sp500 --output results.csv
python screen.py -sp500 --output          # auto-named sepa_results_YYYY-MM-DD.csv

# Refresh price data
python screen.py -sp500 --refresh         # INCREMENTAL: ~1 month pull, merged into cached 2y history
python screen.py -sp500 --full-refresh    # FULL: re-download 2y history, replaces cache (weekly re-sync / splits)
```

Cache-first by default: without a refresh flag the screener reads the pickle cache and never hits Yahoo. See [Caching](#caching).

## Sample Output

Real output from the NASDAQ screen (2026-08-12) is included as [`sample_output.csv`](sample_output.csv) — see what a typical run produces before you install anything.

## Output Columns

Quick reference: **higher is better** for VCP Score, EPS, RS Rating. **Lower is better** for Ind Rk. **A is better than E** for A/D.

| Column | Direction | Description |
|--------|-----------|-------------|
| Ticker | — | Stock symbol (clickable TradingView link in email/CSV) |
| Price | — | Current closing price |
| vs 50 SMA% | — | % distance from 50-day SMA (positive = above) |
| ATR% | — | 22-day Average True Range as % of price |
| Vol vs 50d Low% | Low preferred | Current volume vs the 50-day low-volume mark |
| Vol Low Flag | Yes preferred | Volume trading near 50-day lows (dry-up) |
| VCP Status | — | Volatility Contraction Pattern: `VCP Tight` / `VCP Forming` / `No VCP` / `Already Broken Out` |
| VCP Score | Higher better | 0–85 contraction confidence (capped; ≥60 Tight, ≥50 Forming) |
| Dist to Pivot% | Near 0 preferred | % below the pivot ceiling (negative = already above pivot). CSV only — not in email |
| Pullback Status | — | `Pullback to MA` / `Pulling Back` / `Extended` / `No Pullback` |
| Pullback Score | Higher better | 0–100 pullback-to-MA re-entry confidence |
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

### VCP Scoring Breakdown (v4.0 — July 2026 backtest-driven refactor)

Weights are derived from a 10-year backtest (2016–2026, 341K observations). Key findings that changed the model:
- Final tightness and price position near the pivot are the strongest signals
- Volume dry-up is **not** predictive (inverted in practice) — downgraded to a soft signal
- Base duration had zero correlation — **removed** from scoring
- The halving rule was replaced by the **contraction ratio** (first depth / final depth)
- 2–3 contractions are ideal; 4+ gets stale
- High run-up from the 52w low is NOT exhaustion (leaders keep leading)

| Component | Max Pts | Method |
|-----------|---------|--------|
| Stage 2 MA Stacking | 10 | Close / 50 / 150 / 200 SMA alignment in uptrend order |
| Contraction Count (T) | 5 | 2–3 contractions = full points; 4 = 3; 5+ = 1 |
| Contraction Ratio | 15 | first pullback depth ÷ final depth; ≥10× = 15, ≥6× = 12, ≥4× = 9, ≥2× = 4 |
| Final Tightness | 15 | Last pullback depth ≤3% = 15, ≤5% = 12, ≤10% = 8, ≤15% = 3 |
| Close Compression | 5 | 10-day close std ≤1% = 5, ≤2% = 3, ≤3% = 1 |
| Volume | 5 | Last 5d avg vol 0.5–1.5× the 50d avg = 5 (soft signal) |
| Price Position Near Pivot | 20 | ≤2% below pivot = 20 (cliff at 2%: breakout odds drop from 49% to 25%) |
| Near Resistance Flag | 10 | Close within 3% of resistance (3.6× breakout multiplier) |
| 50MA Distance | 10 | 0–5% above 50 SMA = 10; extended (>10% above) = 0 |
| Run-up from 52w Low | 5 | ≥100% off the low = 5, ≥50% = 3 |
| Compression Volatility | 5 | Coiled spring: tight close std + shallow final depth |
| Price Tier | 3 | Close ≥ $200 (institutional quality) |

- **Score is capped at 85** — backtest showed returns turn negative at ≥90.
- **VCP Tight** = score ≥ 60, **VCP Forming** = 50–59, **No VCP** = < 50.
- **Already Broken Out** = close > pivot level × 1.02 — flagged separately instead of scored.
- `Dist to Pivot%` comes from the same detection: positive = below the pivot, negative = already above it. The pivot is the **prior** 52-week high (today's bar deliberately excluded) so pre-breakout names keep a positive distance.

### Backtest Validation (July 2026)

The VCP engine was validated with a 10-year walk-forward backtest before the scoring weights were trusted: **1,000 tickers, 341K+ observations (2017–2025)**, running `detect_vcp()` weekly and measuring forward returns and breakout rates.

What it showed:

- VCP Tight stocks broke out (above pivot +2%) at **3–4× the rate** of the general universe — 21.6% vs 4.7% in 5 days; 46.9% vs 14.4% in 21 days
- VCP Tight had **3.5× lower volatility** than the broad market with a better Sharpe (0.15 vs 0.13) and better tail-risk (VaR95 −14% vs −24%)
- The v4.0 scoring weights in `minervini/vcp.py` are derived directly from these findings — components with zero or inverted predictive power (base duration, binary halving rule, volume dry-up as a hard gate) were removed or reweighted
- Best combo found: **within 2% of pivot + 2–3 contractions → 50.9% 10-day breakout rate**, stable across 7 of 9 years

Honest caveat: this is a **timing tool, not a return predictor** — breakout timing was stable, but forward returns were negative in bear years (2018, 2020, 2022).

### Pullback to MA (Re-Entry / Add Setup)

`pullback.py` detects stocks that broke out / ran up and are now pulling back toward the 20d or 50d SMA on declining volume — a classic re-entry or add-to-position setup.

| Component | Max Pts | Method |
|-----------|---------|--------|
| Proximity to nearest MA | 35 | Close within 1% of SMA20/50 = 35, tapering to 10–15 at 5% |
| Volume vacuum | 25 | 5d avg volume ≤50% of 50d avg = 25, tapering to 7 at 100% |
| Pullback depth quality | 20 | 5–10% off the recent high is ideal (20); 3–14% = 12 |
| Uptrend health | 20 | SMA20/SMA50 slopes rising + close still above SMA20 |

- **Pullback to MA** = score ≥ 65, **Pulling Back** = 40–64, **Extended** = 20–39, **No Pullback** = < 20.

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

## Market Regime Watcher

`market_regime.py` answers one question: **should you be trading momentum or VCP right now?**

It reads the NASDAQ/NYSE price caches (refreshed by the daily cron) plus a live QQQ chop index, computes market breadth across the liquid universe, and classifies the tape:

| Regime | Meaning | Trigger |
|--------|---------|---------|
| 🚀 MOMENTUM | Full speed — momentum setups | Breadth + coil healthy |
| ⚠️ CAREFUL | Momentum, but pickier | % above 50MA < 50 |
| 🔁 SWITCH-TO-VCP | Go back to VCP/coil setups | QQQ chop ≥ 55 **or** coil density ≥ 15% **or** % above 50MA < 40 |

It's a **watchdog**: it prints nothing when the regime is unchanged, and only alerts when the label **flips** (state tracked in `~/.hermes/scripts/.market_regime_state.json`). Empty output when silent makes it a drop-in for a `no_agent` cron with WhatsApp delivery.

```bash
python market_regime.py
```

(As of Aug 2026 it is not yet wired into cron — it's designed to be.)

## Sector / Basket Heat Monitor

`sector_heat.py` catches "AI is getting hot" moments that the VCP and momentum scans structurally miss. It watches curated baskets of names (Alan's actual May/June winners + core holdings):

- AI/Compute, AI/Software, Semis Equip, Biotech, Energy, Financials, Industrials, Consumer

A basket is **HOT** when:
- median 20-day return ≥ +8%, **or**
- median 20d ≥ 1.5× the market median **and** ≥50% of the basket within 5% of its 52w high

Also a watchdog: prints only when a basket flips to/from HOT (state in `~/.hermes/scripts/.sector_heat_state.json`).

```bash
python sector_heat.py
```

HOT basket → dig into the names with the momentum scanner.

## Watchlist News Summarizer

`news_watchlist.py` reads your **open positions from the Google Sheet journal** (not a watchlist file), fetches the past week of news for each ticker via yfinance, summarizes each stock's news into 1–2 paragraphs using the OpenCode Go LLM API, and emails the result to `REPORT_RECIPIENTS`.

```bash
python news_watchlist.py                      # full run (news → AI summary → email)
python news_watchlist.py --no-email           # print summaries to console only
```

- Requires `OPENCODE_GO_API_KEY` in `.env` (OpenAI-compatible endpoint at `opencode.ai/zen/go/v1`, model `mimo-v2.5`)
- Requires the Google Sheet journal setup below (it derives the ticker list from open positions via FIFO matching)
- Sorted by ticker; each stock gets its own summary paragraph + raw article links

## Portfolio Report

Generates a combined HTML report of your open positions (with A/D rating +
violations + exhaustion/distribution signals from the screener) and closed trades
(P&L grouped by broker).

Reads from a **Google Sheet** by default (no more hand-editing CSV). Falls back to
`journal.csv` if the sheet is unreachable.

```bash
python portfolio_report.py                  # reads from Google Sheets
python portfolio_report.py --from-csv       # reads journal.csv instead
python portfolio_report.py --no-email       # print to console only
```

### Google Sheets Setup (once)

1. Go to https://console.cloud.google.com → create a project → enable **Google Sheets API**
2. **Credentials** → **Create Credentials** → **Service Account**
3. Name it (e.g. `journal-reader`), skip optional fields, click **Done**
4. Click the service account → **Keys** tab → **Add Key** → **Create New Key** → **JSON**
5. A `.json` file downloads — save it to the project root as `service-account-key.json`
6. Open your Google Sheet, click **Share**, paste the service account email from the JSON (looks like `journal-reader@your-project.iam.gserviceaccount.com`), grant **Editor** access
7. Set these in `.env`:

```env
GOOGLE_CREDENTIALS=service-account-key.json
SHEET_ID=your_sheet_id_here    # from the URL: /d/THIS_IS_THE_ID/edit
```

**Sheet format** — first row must be the headers, data rows follow:

| broker | action | ticket | quantity | date | price |
|--------|--------|--------|----------|------|-------|
| e      | buy    | AAPL   | 20       | 20260318 | 252.62 |
| e      | sell   | AAPL   | 20       | 20260401 | 255.43 |

- **broker**: `e` (Etrade), `f` (Fidelity), `r` (Robinhood), `i` (Interactive Broker)
- **action**: `buy` or `sell`
- **date**: `YYYYMMDD` format (e.g. `20260527`)
- **ticket/quantity/price**: plain numbers

## Momentum Acceleration Scanner

Detects stocks in a parabolic acceleration phase — rapid price expansion on heavy
volume, similar to what MU showed in early May 2026. Complements VCP (quiet setups)
by finding explosive moves. This is the **primary intraday scanner** in the cron
schedule (see [Caching](#caching)).

Scoring (0–100): Price Acceleration (25) + Power Days (20) + SMA Expansion (20)
+ Volume Ratio (15) + RS Slope (20). The acceleration component now credits small
moves too — a 3%+ 5-day return scores points, not just >5% ones.

```bash
python momentum_accel.py -nasdaq --top 20                # top 20 NASDAQ
python momentum_accel.py -sp500 -sp400 --top 30           # top 30 S&P
python momentum_accel.py --all-us --min-score 60          # all US, ≥60 only
python momentum_accel.py --watchlist watchlist.txt        # watchlist only
python momentum_accel.py -nasdaq --no-email               # console only
python momentum_accel.py --all-us --full-refresh          # full 2y cache rebuild
```

## Steady Climber Scanner

`steady_climber.py` — streak-based scanner for stocks grinding steadily higher
(consecutive up days, controlled pullbacks) rather than exploding or coiling.
Same CLI shape as the momentum scanner (`--all-us`, `--top`, `--min-score`,
`--no-email`, `--output`, `--refresh`, plus `--no-ai` to skip catalyst analysis).
Experimental — currently commented out of the cron schedule.

## Peer Comparison Scanner

Find stocks in the same industry as a given ticker and compare their momentum,
exhaustion, and distribution scores (`peerscan.py`). Uses cached data from all
available indices.

```bash
python peerscan.py PANW                           # top 30 peers, email
python peerscan.py PANW --top 10                   # top 10 only
python peerscan.py PANW --min-score 60             # only accelerating+
python peerscan.py PANW --no-email                 # console only
python peerscan.py -i                              # interactive mode
```

## Email Setup

Copy `.env.template` to `.env` and fill in your credentials:

```env
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
RECIPIENTS=email1@example.com,email2@example.com
REPORT_RECIPIENTS=you@example.com
OPENCODE_GO_API_KEY=your_opencode_go_api_key
CSV_OUTPUT_DIR=~/csv_output
GOOGLE_CREDENTIALS=your-service-account-key.json
SHEET_ID=your_sheet_id_here
```

- Uses Gmail SMTP (`smtp.gmail.com:587`)
- App passwords recommended (enable 2FA → create app-specific password)
- Multiple recipients comma-separated (`#` comments supported)
- `RECIPIENTS` receives screener results; `REPORT_RECIPIENTS` receives news summaries
- `OPENCODE_GO_API_KEY` is required only for the watchlist news summarizer (OpenCode Go API)
- `CSV_OUTPUT_DIR` is where `--output` auto mode saves CSV files (default `~/csv_output`)
- `GOOGLE_CREDENTIALS` / `SHEET_ID` — required for portfolio report + news summarizer (both read the journal sheet)

## Caching

Price data freshness is managed by **cron**, not by the on-demand screener. The
screener reads whatever cache file exists; it does NOT trigger a refresh if
the data is "old." This avoids hammering Yahoo Finance when you just want a
quick read.

### Refresh semantics

- `--refresh` → **incremental**: downloads the recent window (~1 month), merges it
  into the cached 2-year history (dedupe on date, newest wins), and saves. Tickers
  that fail the pull keep their cached history instead of vanishing. Previously
  price-filtered (sub-$15) names are skipped until a full refresh.
- `--full-refresh` → **full**: re-downloads all 2 years, replaces the cache
  entirely. Use weekly (or after splits) to re-sync and re-check $15 crossings.

### Cron schedule (Pacific time, weekdays unless noted)

| Time | Job |
|------|-----|
| 7:30am M–F | `momentum_accel.py --all-us --no-email --refresh` |
| 8:45am M–F | `momentum_accel.py --all-us --refresh --output` |
| 10:00am M–F | `momentum_accel.py --all-us --no-email --refresh` |
| 11:30am M–F | `portfolio_report.py` |
| 1:15pm M–F | `screen.py --all-us --refresh --output` |
| 5:30pm M–F | `news_watchlist.py` |
| 8:00am Sat | `momentum_accel.py --all-us --no-email --full-refresh` |

### Cache files

| Cache | File | Expiry |
|-------|------|--------|
| Price data | `cache_{index}.pkl` | 7 days (sanity guard; cron refreshes intraday) |
| SPY benchmark | `cache_spy.pkl` | Re-downloaded on `--refresh` |
| Fundamentals (industries, EPS, earnings) | `cache_fundamentals.pkl` | Industries: 7 days, EPS: 24h, Earnings: 24h + stale-date refetch |

Next_Earnings dates in the fundamentals cache are auto-refetched when a cached
date lands in the past (the cache freezes dates at first fetch; yfinance moves
on after each report).

### Download pipeline details

- Batch size 25 (retry pass: 10), `threads=True`
- Pacing: 2s between batches, 5s after a throttled batch, 30s cooldown after 3 consecutive failures
- Failed tickers are retried once; price-filtered (sub-$15) are tracked separately from genuine failures
- Socket resolution forced to IPv4 to dodge Yahoo Finance IPv6 rate limiting

## Project Structure

```
minervini/
  data.py         — Ticker sources, yfinance download (batched/paced), pickle cache, incremental refresh
  indicators.py   — SMAs, ATR, 52w metrics, A/D Rating, volume-near-50d-low
  rs_rating.py    — IBD-style RS percentile (40/20/20/20 weighting)
  vcp.py          — VCP detection v4.0 (backtest-derived scoring, dist-to-pivot meta)
  pullback.py     — Pullback-to-MA re-entry detection
  sell_signals.py — Exhaustion climax + distribution breakdown scores
  violations.py   — Post-purchase violation detection (8 Minervini criteria)
  screener.py     — Filter + enrichment orchestration
  earnings.py     — Next earnings date (yfinance calendar, stale-date refetch)
  fundamentals.py — Industry RS rank + EPS Rating (cached)
  emailer.py      — HTML table with TradingView links, Gmail SMTP
screen.py           — SEPA screener CLI
momentum_accel.py   — Momentum acceleration scanner (primary cron driver)
market_regime.py    — MOMENTUM vs VCP regime watchdog
sector_heat.py      — Basket heat monitor (watchdog)
steady_climber.py   — Steady-rise scanner (experimental, not scheduled)
portfolio_report.py — Portfolio report with A/D, exhaustion, distribution signals
news_watchlist.py   — Open-position news summarizer (OpenCode Go AI)
peerscan.py         — Peer comparison scanner by industry
sample_output.csv   — Real sample run output
legacy/             — Archived predecessor code (minervini-sepa, May 2026)
.env.template       — Environment variable template
journal.example.csv — Journal format reference
LICENSE             — MIT
```

## Requirements

- yfinance
- pandas
- numpy
- requests
- lxml
- python-dotenv
- openai (watchlist news summarizer only)
- gspread (portfolio journal / news ticker source)

Install: `pip install -r requirements.txt`

## Disclaimer

For educational purposes. Not financial advice.
