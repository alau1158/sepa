#!/usr/bin/env python3
import argparse
import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minervini.data import load_cache
from minervini.fundamentals import get_industries
from momentum_accel import compute_score
from minervini.sell_signals import compute_exhaustion_score, compute_distribution_score
from minervini.indicators import compute_ad_rating


def get_ticker_industry(ticker):
    try:
        t = yf.Ticker(ticker)
        info = t.info
        ind = info.get("industry") or info.get("sector") or "Unknown"
        sector = info.get("sector", "Unknown")
        name = info.get("shortName") or info.get("longName") or ticker
        return ind, sector, name
    except Exception as e:
        print(f"  Error fetching {ticker} info: {e}")
        return None, None, None


def load_universe():
    indices = ["sp500", "sp400", "sp600", "nasdaq", "nyse"]
    all_tickers = {}
    for idx in indices:
        cache = load_cache(idx)
        if cache:
            for t, df in cache["data"].items():
                if t not in all_tickers and t != "SPY":
                    all_tickers[t] = df
    return all_tickers


def _send_email(results, ticker, industry, smtp_config, recipients, top_n=30):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    rows = ""
    for r in results[:top_n]:
        highlight = ' style="background:#ffeeba;font-weight:bold;"' if r["Ticker"] == ticker else ""
        rows += f"""<tr{highlight}>
<td>{r['Ticker']}</td>
<td>${r['Price']}</td>
<td style="font-weight:bold;">{r['Score']}</td>
<td>{r['Status']}</td>
<td>{r['5d%']:+.1f}%</td>
<td>{r['10d%']:+.1f}%</td>
<td>{r['20d%']:+.1f}%</td>
<td>{r['vs50']:+.1f}%</td>
<td>{r['Exh']}</td>
<td>{r['ExSt']}</td>
<td>{r['Dist']}</td>
<td>{r['AD']}</td>
</tr>"""

    html = f"""<html><body style="font-family:Arial,sans-serif;">
<h2>Peer Comparison: {ticker} — {industry}</h2>
<p>{date_str} | {len(results)} peer stocks | Highlighted = input ticker</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px;">
<tr style="background:#2c3e50;color:white;">
<th>Ticker</th><th>Price</th><th>Score</th><th>Status</th><th>5d%</th><th>10d%</th><th>20d%</th><th>vs50</th><th>Exh</th><th>ExSt</th><th>Dist</th><th>A/D</th>
</tr>
{rows}
</table>
<p style="color:#888;font-size:12px;">Experimental — not financial advice.</p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Peer Scan: {ticker} ({industry}) - {date_str}"
    msg["From"] = smtp_config["user"]
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_config["user"], smtp_config["password"])
        server.sendmail(smtp_config["user"], recipients, msg.as_string())


def parse_recipients(raw):
    recipients = []
    for part in raw.split(","):
        part = part.split("#")[0].strip()
        if part:
            recipients.append(part)
    return recipients


def main():
    parser = argparse.ArgumentParser(description="Peer comparison scanner")
    parser.add_argument("ticker", nargs="?", help="Stock ticker to find peers for")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive ticker input")
    parser.add_argument("--top", type=int, default=30, help="Show top N peers (default: 30)")
    parser.add_argument("--min-score", type=int, default=0, help="Minimum momentum score")
    parser.add_argument("--no-email", action="store_true", help="Print to console only")
    args = parser.parse_args()

    ticker = args.ticker
    if not ticker and args.interactive:
        ticker = input("Ticker: ").strip().upper()
    if not ticker:
        parser.print_help()
        sys.exit(1)

    ticker = ticker.upper()

    print(f"Looking up {ticker}...")
    industry, sector, name = get_ticker_industry(ticker)
    if not industry:
        print(f"  Could not determine industry for {ticker}.")
        sys.exit(1)

    print(f"  {name} ({ticker})")
    print(f"  Sector: {sector}")
    print(f"  Industry: {industry}")

    print("\nLoading cached universe...")
    universe = load_universe()
    print(f"  {len(universe)} stocks in cache")

    universe_tickers = list(universe.keys())
    print("  Fetching industry data for cached stocks...")
    ind_map = get_industries(universe_tickers)

    peers = {t: universe[t] for t, ind in ind_map.items() if ind == industry}
    if not peers:
        peers = {t: universe[t] for t, ind in ind_map.items() if ind == sector}
        label = "Sector"
    else:
        label = "Industry"

    if ticker in peers:
        pass
    else:
        df_t = yf.download(ticker, period="6mo", auto_adjust=True, progress=False)
        if isinstance(df_t.columns, pd.MultiIndex):
            if ticker in df_t.columns.get_level_values(0).unique():
                df_t = df_t[ticker]
            elif ticker in df_t.columns.get_level_values(1).unique():
                df_t = df_t.xs(ticker, level=1, axis=1)
        if not df_t.empty:
            peers[ticker] = df_t

    if not peers:
        print(f"  No peers found in {label}: {industry}")
        sys.exit(1)

    print(f"  {label}: {industry}")
    print(f"  Found {len(peers)} peer stocks")

    print("\nScoring peers...")
    results = []
    for t, df in peers.items():
        if len(df) < 20:
            continue
        close = df["Close"].iloc[-1]
        sma50 = df["Close"].rolling(50).mean().iloc[-1]
        vs50 = ((close / sma50) - 1) * 100 if not pd.isna(sma50) else 0

        mom_score, mom_status, _ = compute_score(df)
        if mom_score < args.min_score:
            continue

        exh_s, exh_st = compute_exhaustion_score(df)
        dist_s, dist_st = compute_distribution_score(df)
        ad_l, ad_s = compute_ad_rating(df)

        ret_5d = (df["Close"].iloc[-1] / df["Close"].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
        ret_10d = (df["Close"].iloc[-1] / df["Close"].iloc[-11] - 1) * 100 if len(df) >= 11 else 0
        ret_20d = (df["Close"].iloc[-1] / df["Close"].iloc[-21] - 1) * 100 if len(df) >= 21 else 0

        results.append({
            "Ticker": t,
            "Price": round(close, 2),
            "Score": mom_score,
            "Status": mom_status,
            "5d%": round(ret_5d, 1),
            "10d%": round(ret_10d, 1),
            "20d%": round(ret_20d, 1),
            "vs50": round(vs50, 1),
            "Exh": exh_s,
            "ExSt": exh_st,
            "Dist": dist_s,
            "AD": f"{ad_l}{ad_s}",
        })

    results.sort(key=lambda r: r["Score"], reverse=True)
    is_input = [r for r in results if r["Ticker"] == ticker]
    others = [r for r in results if r["Ticker"] != ticker]
    ranked = is_input + others[:args.top]

    df_out = pd.DataFrame(ranked)
    print(f"\n{'='*70}")
    print(f"Peers: {ticker} ({industry}) — {len(results)} stocks")
    print(f"Top peers: {args.top}")
    print(f"{'='*70}")
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 200)
    print(df_out.to_string(index=False))

    if not args.no_email:
        raw_rcpt = os.getenv("REPORT_RECIPIENTS", "")
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASSWORD")
        if smtp_user and smtp_pass and raw_rcpt:
            recipients = parse_recipients(raw_rcpt)
            if recipients:
                html_results = [dict(r) for r in ranked]
                print(f"\nSending email to {len(recipients)} recipient(s)...")
                _send_email(html_results, ticker, industry, {"user": smtp_user, "password": smtp_pass}, recipients)
                print("Email sent!")


if __name__ == "__main__":
    main()
