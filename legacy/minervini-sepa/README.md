# Minervini SEPA - Stock Screening & Portfolio Tracking

Weekly stock screening and portfolio tracking using Mark Minervini's SEPA (Specific Entry Point Analysis) method.

## Features

- **Mark Minervini Screening** - Identifies stocks passing all 9 trend template criteria
- **Portfolio Tracking** - Monitor your existing holdings against optimal conditions
- **Weekly Reports** - Automated HTML reports emailed every Sunday at 9 AM
- **Top 10 Opportunities** - Finds best stocks passing all criteria with RS rating ranking
- **Risk Management** - 22-day ATR% calculation for position sizing
- **VCP Pattern Detection** - Detects Volatility Contraction Patterns (Mark Minervini strategy)
- **Multiple Index Support** - S&P 500, S&P 400 (Mid-Cap), S&P 600 (Small-Cap)

## Installation

```bash
# After ensurepip, use full path to pip
python3 -m ensurepip --upgrade
~/.local/bin/pip3 install -r requirements.txt

# Or add to PATH
export PATH="$HOME/.local/bin:$PATH"
pip3 install -r requirements.txt
```

## Troubleshooting

**Error: `pip: command not found`**
```bash
# Install pip via ensurepip
python3 -m ensurepip --upgrade

# Or install via get-pip.py
curl -sS https://bootstrap.pypa.io/get-pip.py | python3
```

## Setup

1. **Edit holdings.csv** - Add your current stock holdings:
   ```csv
   symbol,shares,purchase_date,purchase_price
   AAPL,50,2024-01-15,185.00
   ```

2. **Configure email** - Already set in `.env`:
   - SMTP_USER: username@gmail.com
   - SMTP_PASSWORD: Gmail app password

## Usage

```bash
# Run once (S&P 500 by default)
python report.py

# Run for S&P 400 (Mid-Cap)
python report.py -sp400

# Run for S&P 600 (Small-Cap)
python report.py -sp600

# Screen S&P 500 stocks
python screener.py

# Screen S&P 400 stocks
python screener.py -sp400

# Screen S&P 600 stocks
python screener.py -sp600

# Audit a specific stock
python screener.py --audit AAPL

# Run scheduler (sends weekly - S&P 500)
python scheduler.py
```

## Minervini Trend Template (9 Criteria)

A stock passes when it meets ALL of:

1. Current price > 50-day moving average
2. Current price > 150-day moving average
3. Current price > 200-day moving average
4. 50-day MA > 150-day MA and 50-day MA > 200-day MA
5. 150-day MA > 200-day MA
6. 200-day MA trending up (2-month confirmed)
7. Price within 25% of 52-week high
8. Price ≥ 30% above 52-week low
9. RS Rating ≥ 80 (vs S&P 500/index)

## Risk Management - Position Sizing

The report includes **22-Day ATR%** for each stock to help with position sizing and stop loss placement.

**Position Sizing Formula:**
```
Shares to Buy = 0.02(T) / (E)(1.5)(A)
```

Where:
- **T** = Total portfolio size
- **E** = Entry price
- **A** = 22-Day ATR% (as decimal, e.g., 2.5% = 0.025)

**Example:** For a $100,000 portfolio, entry at $50, ATR% of 2.5%:
```
Shares = 0.02($100,000) / ($50)(1.5)(0.025)
       = 2,000 / 1.875
       = ~1,066 shares
```

## Report Status — What Each Signal Means

The **Status** column is the primary trading signal. Each stock gets exactly one status, chosen in priority order:

| Status | Meaning | Action Today |
|--------|---------|--------------|
| 🚀 **BREAKOUT** | VCP detected and price has just closed above the pivot on above-average volume | **Buy now** — as close to pivot as possible (≤5% above) |
| ✅ **SETUP** | Valid VCP forming, price hasn't broken pivot yet | **Wait** — place a buy stop at the pivot price |
| ✅ **NEAR 50-MA** | No active VCP, but price is within 5% of a rising 50-MA | **Watch for bounce** — classic Minervini pullback entry, but wait for a confirmation bar (green day off the 50-MA, ideally on rising volume) |
| ✅ **ACTIONABLE** | Template passes, 5–25% above 50-MA, no specific VCP or pullback trigger | **Nothing today** — add to watchlist; wait for a pullback or base to form |
| ⚠️ **EXTENDED** | Price is >25% above the 50-MA (climactic territory) | **Do not chase.** If already held: trim 1/3–1/2 into strength. Wait for a new 4–6+ week base before re-entry |
| ⚠️ **Watch only** | Template did not fully pass | **Nothing** — re-check next week |

The two highest-conviction signals are **BREAKOUT** and **SETUP** — both require a valid VCP.

### What "wait for pivot break / set buy stop at pivot" means

- The **pivot** is the high of the most recent tight consolidation on the right side of a VCP base — the resistance the stock must clear to confirm the breakout.
- A **buy stop** is an order that triggers a buy automatically when price rises *through* a specified level (the opposite of a sell stop). Set it slightly above the pivot (e.g., pivot + $0.05) so the trade executes mechanically the moment the breakout happens — no need to watch the screen.
- Most brokers support **buy stop limit** orders, which also cap the price you'll pay if the stock gaps up violently.

## VCP Pattern (Volatility Contraction Pattern)

A VCP is Minervini's preferred base — price consolidates in a series of progressively tighter pullbacks before breaking out.

- **Detection:** 2+ contraction legs, each shallower than the last (e.g., 18% → 9% → 4%)
- **Volume dry-up:** Ideally volume contracts on the final leg, signaling supply exhaustion
- **Pivot:** Most recent swing high — the breakout trigger / buy point
- **Stop:** Most recent swing low — your hard stop-loss level

## Minervini Trading Plan (in priority order)

1. **Only buy ACTIONABLE setups.** Skip anything marked EXTENDED — chasing >25% above the 50-MA is how Minervini-style traders give back gains.
2. **Wait for breakout.** For VCP setups, price must close above the pivot on volume ≥ 1.4× the 50-day average.
3. **Enter at pivot.** Buy as close to the pivot as possible — never chase more than 5% above.
4. **Set a hard stop.** Place stop-loss just below the recent swing low (or 50-MA for non-VCP setups). Max risk per trade = 1–2% of portfolio.
5. **Take profits on extended stocks.** When a held position becomes EXTENDED, trim 1/3–1/2 into strength. Re-enter on the next valid base.

## Worked Examples — Reading the Report in Practice

The status column is a **filter, not a decision.** Always cross-check the contraction sequence, the volume dry-up flag, and the risk math before placing an order. Below are two real examples that show how to interpret the report correctly.

### Example 1 — ATI: clean SETUP (this is what you want)

**Report values:**
| Field | Value |
|-------|-------|
| Price | $158.39 |
| % from 50-MA | +3.2% |
| Contractions | 16.6% → 10.9% → 10.4% |
| VCP | ✅ Vol dry-up |
| Pivot (Buy) | $165.28 |
| Stop (Recent Low) | $148.04 |

**Why this is a textbook SETUP:**
- **Contractions narrow:** 16.6 → 10.9 → 10.4. Each leg shallower than the last → supply being absorbed.
- **Volume dry-up confirmed:** Sellers exhausted on the final leg.
- **Sitting on 50-MA support:** +3.2% above a rising 50-MA — not extended, room to run.
- **Clean pivot and stop levels:** $165.28 resistance ceiling, $148.04 swing-low floor.

**Order plan:**
```
Buy Stop Limit (Good-Til-Cancelled)
  Stop trigger:  $165.38   (pivot + $0.10 cushion)
  Limit price:   $168.00   (~1.6% above pivot — never chase >5%)

After fill, place Sell Stop:
  Trigger:       $148.04   (recent swing low)
```

**Risk math:**
```
Entry:           $165.38
Stop:            $148.04
Risk per share:  $17.34  (10.5%)
```

10.5% per-share risk is wider than Minervini's preferred 5–8%, so **size the position smaller** to keep portfolio risk at 1–2%. For a $100k portfolio with 1.5% max risk = $1,500 ÷ $17.34 ≈ **86 shares max** (~$14k position). Use the ATR-based position-sizing formula above for a more precise number.

**Pre-trade checklist:**
- ☐ No earnings within ~2 weeks (binary event = not a technical setup)
- ☐ Broad market (S&P 500 / NASDAQ) above its own 50-MA and not whipsawing
- ☐ Breakout day volume ≥ 1.4× the 50-day average (if not, exit on weakness — low-quality breakout)

---

### Example 2 — FN: misleading NEAR 50-MA (skip this)

**Report values:**
| Field | Value |
|-------|-------|
| Price | $612.28 |
| % from 50-MA | +3.6% |
| Contractions | **8.6% → 17.3%** |
| Status | ✅ NEAR 50-MA |

**Why this is NOT actionable despite the green check:**

The screener flags NEAR 50-MA based purely on distance from a rising 50-MA. It does **not** cross-check that the base is healthy. FN looks fine on the surface but the contraction sequence is **backwards**:

- Valid VCP: each leg **shallower** than the last (volatility contracting)
- FN: leg 2 (17.3%) is **2× deeper** than leg 1 (8.6%) → volatility **expanding**

Expanding contractions = sellers gaining strength, not losing it. In Minervini's framework this is a **failed base** or early Stage 3 → Stage 4 distribution. A pivot break here would likely be a false breakout because supply has *not* been exhausted.

**Risk math is also poor:**
```
Hypothetical entry:   $612
Stop (recent low):    ~$506  (612 × (1 − 0.173))
Risk per share:       ~17%  (well above Minervini's 5–8% max)
```

**Action: PASS. Watch only.**

**Triggers to revisit FN:**

| Scenario | Signal | Action |
|----------|--------|--------|
| **A — Base re-forms tighter** | New leg ≤ ~8% over 2–3 weeks on declining volume | Watch for VCP to re-form → SETUP status |
| **B — Reversal at 50-MA** | Green reversal bar on volume ≥ 1.5× avg, close in upper third of range | Tactical entry with stop just below the reversal day's low (~3–5% risk) |
| **C — 50-MA breaks** | Close below 50-MA on above-avg volume | **Abandon.** Reset clock — need a full new base (4–6+ weeks) before re-evaluating |

---

### The takeaway

Both stocks show **+~3% from 50-MA** and a green status, but they are **opposite trades**:

| | ATI | FN |
|---|-----|-----|
| Contractions | 16.6 → 10.9 → 10.4 ✅ narrowing | 8.6 → 17.3 ❌ widening |
| Vol dry-up | ✅ Confirmed | Not present |
| Base quality | Healthy | Broken |
| Risk/reward | ~10% stop, defined pivot | ~17% stop, no clean trigger |
| **Verdict** | **Place buy stop at pivot** | **Skip — watch only** |

**Rule of thumb:** Before acting on any NEAR 50-MA or SETUP signal, look at the **Contractions** column. If the numbers don't get smaller from left to right, the base is broken — no matter what the status says.

## Report Columns

| Column | Description |
|--------|-------------|
| **Status** | Primary trading signal (see table above) |
| **% from 50-MA** | Distance from 50-day MA. Buy zone: 0–15%; stretched: 15–25%; climactic: >25% |
| **RS** | Relative strength rating, 0–100 (template requires ≥80) |
| **Trend** | Minervini template criteria passed, X/9 |
| **22-Day ATR%** | Volatility measure for position sizing |
| **Next Earnings** | Upcoming earnings date |
| **VCP** | ✅ = valid VCP, 🚀 = breakout above pivot, "Vol dry-up" = volume contracting on final leg |
| **Pivot (Buy)** | Most recent swing high — set your buy stop here |
| **Stop (Recent Low)** | Most recent swing low — set your stop-loss just below this |
| **Contractions** | Sequence of pullback depths, oldest → newest |
| **AI** | LLM sentiment from recent news & earnings: 🟢 Positive / 🟡 Neutral / 🔴 Negative |

## Files

| File | Description |
|------|-------------|
| `holdings.csv` | Your stock portfolio |
| `screener.py` | Stock screening logic with Minervini trend template |
| `portfolio.py` | Holdings management |
| `report.py` | HTML report generator with ATR% and position sizing |
| `notifier.py` | Gmail SMTP email sender |
| `scheduler.py` | Weekly cron job scheduler |
| `api_clients.py` | External API clients (Finnhub, etc.) |

## Disclaimer

This is for informational purposes only. Always do your own research before investing.
