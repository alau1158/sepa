#!/usr/bin/env python3
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

_script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_script_dir, ".env"))

from portfolio_tracker import load_transactions, load_transactions_from_sheet, fifo_match, get_portfolio_summary
from minervini.sell_signals import compute_exhaustion_score, compute_distribution_score
from minervini.indicators import compute_sma, compute_ad_rating
from minervini.violations import compute_violations

PROFIT_THRESHOLD = 10.0  # percent — flag positions up this much for partial profit-taking


JOURNAL_PATH = os.path.join(_script_dir, "journal.csv")


def fetch_es_futures():
    """Fetch ES futures data for overnight sentiment."""
    try:
        # ES=F is the E-mini S&P 500 futures continuous contract
        es = yf.download("ES=F", period="5d", interval="1d", auto_adjust=True, progress=False)
        if es.empty:
            return None

        # Handle MultiIndex columns
        if isinstance(es.columns, pd.MultiIndex):
            if "Close" in es.columns.get_level_values(0):
                es = es.droplevel(1, axis=1)
            elif "Close" in es.columns.get_level_values(1):
                es = es.xs("Close", level=0, axis=1).to_frame("Close")

        current = float(es["Close"].iloc[-1])
        prev_close = float(es["Close"].iloc[-2]) if len(es) >= 2 else current
        change_pct = ((current - prev_close) / prev_close) * 100

        # Determine risk level
        if change_pct <= -2.0:
            risk_level = "HIGH"
            risk_color = "#dc3545"
            risk_icon = "🔴"
            risk_msg = "SEVERE DOWNGRADE — Market panic likely. Consider exiting weak positions."
        elif change_pct <= -1.0:
            risk_level = "ELEVATED"
            risk_color = "#fd7e14"
            risk_icon = "🟠"
            risk_msg = "Risk-off overnight. Tighten stops on high-beta positions. Don't add new longs."
        elif change_pct <= -0.5:
            risk_level = "CAUTION"
            risk_color = "#ffc107"
            risk_icon = "🟡"
            risk_msg = "Mild negative sentiment. Monitor open positions, no panic needed."
        elif change_pct >= 1.0:
            risk_level = "RISK-ON"
            risk_color = "#28a745"
            risk_icon = "🟢"
            risk_msg = "Strong overnight rally. Watch for gap-up fade — don't chase the open."
        elif change_pct >= 0.3:
            risk_level = "POSITIVE"
            risk_color = "#28a745"
            risk_icon = "🟢"
            risk_msg = "Mild positive sentiment. Markets supportive for open."
        else:
            risk_level = "NEUTRAL"
            risk_color = "#6c757d"
            risk_icon = "⚪"
            risk_msg = "Flat overnight. No directional signal."

        return {
            "price": current,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "risk_level": risk_level,
            "risk_color": risk_color,
            "risk_icon": risk_icon,
            "risk_msg": risk_msg,
        }
    except Exception as e:
        print(f"  ES futures fetch failed: {e}")
        return None


def load_portfolio(from_csv=False):
    if from_csv:
        transactions = load_transactions(JOURNAL_PATH)
    else:
        try:
            transactions = load_transactions_from_sheet()
        except Exception as e:
            print(f"Google Sheets unavailable ({e}), falling back to CSV...")
            transactions = load_transactions(JOURNAL_PATH)

    open_positions, closed_trades = fifo_match(transactions)
    summary = get_portfolio_summary(open_positions)

    tickers = []
    entry_prices = {}
    shares = {}
    brokers = {}
    purchase_dates = {}

    for key, data in summary.items():
        tickers.append(key)
        entry_prices[key] = data["avg_cost"]
        shares[key] = data["total_quantity"]
        brokers[key] = data["broker"]
        if data["lots"]:
            earliest_lot = min(data["lots"], key=lambda x: x["date"])
            purchase_dates[key] = earliest_lot["date"].date()

    return tickers, entry_prices, purchase_dates, shares, brokers, closed_trades


def fetch_stock_data(ticker, period="1y"):
    try:
        data = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            if ticker in data.columns.get_level_values(1).unique():
                data = data.xs(ticker, level=1, axis=1)
            elif ticker in data.columns.get_level_values(0).unique():
                data = data[ticker]
            else:
                return None
        if data.empty:
            return None
        data.name = ticker
        return data
    except Exception:
        return None


def analyze_open_positions(tickers, entry_prices, shares, brokers, purchase_dates):
    today = datetime.now().date()
    results = []

    for key in tickers:
        ticker = key.split("-", 1)[1] if "-" in key else key
        df = fetch_stock_data(ticker)
        if df is None:
            continue

        close = df["Close"].iloc[-1]
        entry = entry_prices.get(key, close)
        share_count = shares.get(key, 0)
        pnl_pct = ((close - entry) / entry) * 100
        pnl_dollar = (close - entry) * share_count
        purchase_date = purchase_dates.get(key)
        days_held = (today - purchase_date).days if purchase_date else None

        sma_50 = compute_sma(df["Close"], 50)
        vs_sma50 = ((close / sma_50.iloc[-1]) - 1) * 100 if not pd.isna(sma_50.iloc[-1]) else None

        ad_letter, ad_score = compute_ad_rating(df)

        viol_count, viol_score, viol_status, viol_reasons = compute_violations(df, entry)

        exh_score, exh_status = compute_exhaustion_score(df)
        dist_score, dist_status = compute_distribution_score(df)

        profit_alert = pnl_pct >= PROFIT_THRESHOLD
        sell_half_shares = int(share_count / 2) if profit_alert and share_count >= 2 else 0

        results.append({
            "broker": brokers.get(key, "").upper(),
            "ticker": ticker,
            "shares": share_count,
            "entry": entry,
            "current_price": close,
            "pnl_pct": pnl_pct,
            "pnl_dollar": pnl_dollar,
            "days_held": days_held,
            "vs_sma50": vs_sma50,
            "ad_letter": ad_letter,
            "ad_score": ad_score,
            "viol_status": viol_status,
            "viol_score": viol_score,
            "viol_reasons": viol_reasons,
            "exh_status": exh_status,
            "exh_score": exh_score,
            "dist_status": dist_status,
            "dist_score": dist_score,
            "profit_alert": profit_alert,
            "sell_half_shares": sell_half_shares,
        })

    return results


def build_html_report(open_results, closed_trades, es_data=None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def row_color(pnl):
        if pnl > 0: return "#d4edda"
        if pnl < 0: return "#f8d7da"
        return "#fff3cd"

    def text_color(pnl):
        if pnl > 0: return "#155724"
        if pnl < 0: return "#721c24"
        return "#856404"

    # ── ES Futures Section ──
    es_section = ""
    if es_data:
        change_color = "#28a745" if es_data["change_pct"] >= 0 else "#dc3545"
        es_section = f"""
<div style="margin:15px 0;padding:15px;border:2px solid {es_data['risk_color']};border-radius:8px;background:#f8f9fa;">
  <h3 style="margin:0 0 8px 0;">{es_data['risk_icon']} Overnight Market Sentiment — ES Futures</h3>
  <div style="font-size:14px;margin-bottom:8px;">
    <strong>ES Price:</strong> ${es_data['price']:,.2f} |
    <strong>Prev Close:</strong> ${es_data['prev_close']:,.2f} |
    <strong>Change:</strong> <span style="color:{change_color};font-weight:bold;">{es_data['change_pct']:+.2f}%</span>
  </div>
  <div style="padding:8px 12px;background:{es_data['risk_color']}20;border-left:4px solid {es_data['risk_color']};border-radius:4px;">
    <strong style="color:{es_data['risk_color']};">Risk Level: {es_data['risk_level']}</strong><br>
    <span style="font-size:13px;">{es_data['risk_msg']}</span>
  </div>
  <div style="font-size:11px;color:#888;margin-top:8px;">
    ⚠️ ES futures reflect overnight sentiment, not a guarantee. High-beta stocks (semis, tech) move 2-4x the index.
    A 1% ES drop can mean 3-5% down on individual stocks.
  </div>
</div>"""

    # ── Open Positions Table ──
    open_rows = ""
    total_pnl_pct = 0
    total_pnl_dollar = 0

    profit_alert_tickers = []

    for r in open_results:
        tcolor = text_color(r["pnl_pct"])
        days = f"{r['days_held']}d" if r["days_held"] is not None else "N/A"
        vs50 = f"{r['vs_sma50']:+.1f}%" if r["vs_sma50"] is not None else "N/A"
        ad = f"{r['ad_letter']} ({r['ad_score']})"
        viol = f"{r['viol_status']} ({r['viol_score']})"

        if r.get("profit_alert"):
            row_bg = "#fff3cd"
            action_cell = f'<td style="background:#ffc107;color:#000;font-weight:bold;text-align:center;">SELL HALF<br>({r["sell_half_shares"]} shares)</td>'
            profit_alert_tickers.append(r)
        else:
            row_bg = row_color(r["pnl_pct"])
            action_cell = '<td style="color:#888;text-align:center;">—</td>'

        open_rows += f"""<tr style="background-color:{row_bg};">
<td>{r["broker"]}</td>
<td><a href="https://www.tradingview.com/chart/?symbol={r["ticker"]}" style="color:{tcolor};text-decoration:none;font-weight:bold;">{r["ticker"]}</a></td>
<td style="color:{tcolor};font-weight:bold;">{r["pnl_pct"]:+.2f}%<br>${r["pnl_dollar"]:+.2f}</td>
<td>{r["shares"]}</td>
<td>${r["current_price"]:.2f}</td>
<td>${r["entry"]:.2f}</td>
<td>{days}</td>
<td>{vs50}</td>
<td>{ad}</td>
<td style="font-weight:bold;">{r["viol_status"]}</td>
<td>{r["viol_score"]}</td>
<td style="font-weight:bold;">{r["exh_status"]}</td>
<td>{r["exh_score"]}</td>
<td style="font-weight:bold;">{r["dist_status"]}</td>
<td>{r["dist_score"]}</td>
{action_cell}
</tr>"""
        total_pnl_pct += r["pnl_pct"]
        total_pnl_dollar += r["pnl_dollar"]

    # Build profit alert banner
    if profit_alert_tickers:
        banner_items = "".join(
            f'<li><strong>{t["ticker"]}</strong> ({t["broker"]}): '
            f'{t["pnl_pct"]:+.1f}% — sell {t["sell_half_shares"]} of {t["shares"]} shares '
            f'(${t["pnl_dollar"]:+,.2f})</li>'
            for t in profit_alert_tickers
        )
        profit_banner = f"""<div style="margin:15px 0;padding:15px;border:2px solid #ffc107;border-radius:8px;background:#fff8e1;">
  <h3 style="margin:0 0 8px 0;">💰 Profit Alert — {len(profit_alert_tickers)} position(s) up 10%+</h3>
  <p style="margin:0 0 8px 0;font-size:14px;">Consider selling half to lock in gains. Let the rest ride with your trailing stop.</p>
  <ul style="margin:0;padding-left:20px;font-size:14px;">
    {banner_items}
  </ul>
</div>"""
    else:
        profit_banner = ""

    avg_pnl = total_pnl_pct / len(open_results) if open_results else 0
    total_color = text_color(total_pnl_dollar)

    # ── Closed Trades Table ──
    retirement = [t for t in closed_trades if t.get("broker", "").strip().lower() == "f"]
    daytrade = [t for t in closed_trades if t.get("broker", "").strip().lower() in ("e", "r")]

    def closed_rows(trades):
        rows = ""
        for t in trades:
            pl = t["profit_loss"]
            c = row_color(pl)
            tc = text_color(pl)
            pl_str = f"${pl:,.2f}" if pl >= 0 else f"-${abs(pl):,.2f}"
            days = (t["sell_date"] - t["buy_date"]).days if t["buy_date"] and t["sell_date"] else "N/A"
            rows += f"""<tr style="background-color:{c};">
<td>{t["ticket"]}</td>
<td>{t["quantity"]}</td>
<td>${t["buy_price"]:.2f}</td>
<td>${t["sell_price"]:.2f}</td>
<td>{t["sell_date"].strftime("%Y%m%d")}</td>
<td>{days}d</td>
<td style="color:{tc};font-weight:bold;">{pl_str}</td>
</tr>"""
        return rows

    def total_row(trades):
        total = sum(t["profit_loss"] for t in trades)
        tc = text_color(total)
        total_str = f"${total:,.2f}" if total >= 0 else f"-${abs(total):,.2f}"
        return f'<td colspan="5"><strong>Total</strong></td><td style="color:{tc};font-weight:bold;">{total_str}</td>'

    ret_rows = closed_rows(retirement)
    day_rows = closed_rows(daytrade)

    grand_total = sum(t["profit_loss"] for t in closed_trades)
    grand_tc = text_color(grand_total)
    grand_str = f"${grand_total:,.2f}" if grand_total >= 0 else f"-${abs(grand_total):,.2f}"

    html = f"""<html>
<head><style>
body {{ font-family:Arial,sans-serif; padding:20px; }}
h2 {{ color:#333; }}
table {{ border-collapse:collapse; width:100%; margin:15px 0; }}
th {{ background-color:#4a90d9; color:white; padding:10px; text-align:left; border:1px solid #ddd; }}
td {{ padding:8px; border:1px solid #ddd; }}
.summary {{ margin:15px 0; padding:12px; background:#f8f9fa; border-radius:5px; }}
</style></head>
<body>
<h2>Portfolio Report — {now}</h2>

{es_section}

<div class="summary">
<strong>Open Positions:</strong> {len(open_results)} stocks |
<strong>Avg P&amp;L:</strong> <span style="color:{total_color}">{avg_pnl:+.2f}%</span> |
<strong>Total P&amp;L:</strong> <span style="color:{total_color}">${total_pnl_dollar:+.2f}</span>
</div>

<h3>Open Positions</h3>
<table>
<tr>
<th>Broker</th><th>Ticker</th><th>P&amp;L</th><th>Shares</th><th>Price</th><th>Entry</th>
<th>Held</th><th>vs 50 SMA</th><th>A/D</th><th>Viol</th><th>V Sc</th><th>Exh</th><th>Exh Sc</th><th>Dist</th><th>Dist Sc</th><th>💰 Action</th>
</tr>
{open_rows}
</table>

<h3>Closed Trades — Retirement (Fidelity)</h3>
<table>
<tr><th>Ticker</th><th>Qty</th><th>Buy</th><th>Sell</th><th>Sold</th><th>Held</th><th>P&amp;L</th></tr>
{ret_rows if ret_rows else "<tr><td colspan='7'>No closed trades</td></tr>"}
{"<tr>" + total_row(retirement) + "</tr>" if retirement else ""}
</table>

<h3>Closed Trades — Day Trading (Etrade/Robinhood)</h3>
<table>
<tr><th>Ticker</th><th>Qty</th><th>Buy</th><th>Sell</th><th>Sold</th><th>Held</th><th>P&amp;L</th></tr>
{day_rows if day_rows else "<tr><td colspan='7'>No closed trades</td></tr>"}
{"<tr>" + total_row(daytrade) + "</tr>" if daytrade else ""}
</table>

<h3>Grand Total (Closed)</h3>
<table><tr><td colspan="5"><strong>All Accounts</strong></td><td style="color:{grand_tc};font-weight:bold;">{grand_str}</td></tr></table>

<p style="color:#888;font-size:12px;margin-top:20px;">
Green = Profit | Red = Loss | Exh: Normal / Late Stage / Exhausted | Dist: Normal / Weakening / Distribution
</p>
</body></html>"""

    return html


def send_report(html, recipients):
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    if not smtp_user or not smtp_pass:
        print("SMTP not configured.")
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"Portfolio Report — {datetime.now().strftime('%Y-%m-%d')}"
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, recipients, msg.as_string())


def parse_recipients(raw):
    recipients = []
    for part in raw.split(","):
        part = part.split("#")[0].strip()
        if part:
            recipients.append(part)
    return recipients


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Portfolio report with screener signals")
    parser.add_argument("--no-email", action="store_true", help="Print to console only")
    parser.add_argument("--from-csv", action="store_true", help="Read journal.csv instead of Google Sheets")
    args = parser.parse_args()

    print("Loading portfolio...")
    tickers, entry_prices, purchase_dates, shares, brokers, closed_trades = load_portfolio(from_csv=args.from_csv)

    print(f"  Open positions: {len(tickers)} tickers")
    print(f"  Closed trades: {len(closed_trades)}")

    if not tickers:
        print("No open positions to analyze.")
        return

    print("Fetching ES futures data...")
    es_data = fetch_es_futures()
    if es_data:
        print(f"  ES: ${es_data['price']:,.2f} ({es_data['change_pct']:+.2f}%) — Risk: {es_data['risk_level']}")
    else:
        print("  ES futures data unavailable")

    print("Downloading data and computing signals...")
    open_results = analyze_open_positions(tickers, entry_prices, shares, brokers, purchase_dates)

    for r in open_results:
        viol_extra = f" [{r['viol_reasons']}]" if r["viol_reasons"] else ""
        print(f"  {r['broker']}-{r['ticker']}: ${r['current_price']:.2f} | "
              f"P&L: {r['pnl_pct']:+.2f}% | A/D: {r['ad_letter']} ({r['ad_score']}) | "
              f"Viol: {r['viol_status']} ({r['viol_score']}){viol_extra} | "
              f"Exh: {r['exh_status']} ({r['exh_score']}) | "
              f"Dist: {r['dist_status']} ({r['dist_score']})")

    html = build_html_report(open_results, closed_trades, es_data=es_data)

    if args.no_email:
        print("\n" + "=" * 60)
        print("PORTFOLIO REPORT")
        print("=" * 60)
        if es_data:
            print(f"ES Futures: ${es_data['price']:,.2f} ({es_data['change_pct']:+.2f}%) — {es_data['risk_level']}")
            print(f"  {es_data['risk_msg']}")
            print("-" * 60)
        for r in open_results:
            print(f"{r['broker']}-{r['ticker']}: ${r['current_price']:.2f} "
                  f"(entry ${r['entry']:.2f}, P&L {r['pnl_pct']:+.2f}% / ${r['pnl_dollar']:+.2f})")
    else:
        raw_rcpt = os.getenv("REPORT_RECIPIENTS", "")
        recipients = parse_recipients(raw_rcpt)
        if recipients:
            print(f"Sending email to {len(recipients)} recipient(s)...")
            send_report(html, recipients)
            print("Email sent!")
        else:
            print("REPORT_RECIPIENTS not set in .env")


if __name__ == "__main__":
    main()
