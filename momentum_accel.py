#!/usr/bin/env python3
import argparse
import os
import sys
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minervini.data import get_tickers, download_data, save_cache, load_cache


def compute_score(df):
    """Momentum acceleration score 0–100."""
    if len(df) < 20:
        return 0, "Quiet", {}

    close = df["Close"]
    high = df["High"]
    vol = df["Volume"]
    vol_50d = vol.rolling(50).mean()
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()

    components = {}
    score = 0

    # ── 1. Price Acceleration (25 pts) ──────────────────────────────
    ret_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0
    daily_chg = close.pct_change(fill_method=None) * 100
    avg_move_10d = daily_chg.iloc[-11:-1].abs().mean() if len(daily_chg) >= 11 else 1
    
    # Track old score for logging (before 3% threshold)
    old_comp1 = 0
    if ret_5d > 10:
        old_comp1 += 15
        if ret_5d > avg_move_10d * 2:
            old_comp1 += 10
    elif ret_5d > 5:
        old_comp1 += 8
        if ret_5d > avg_move_10d * 1.5:
            old_comp1 += 5
    
    comp1 = 0
    if ret_5d > 10:
        comp1 += 15
        if ret_5d > avg_move_10d * 2:
            comp1 += 10
    elif ret_5d > 5:
        comp1 += 8
        if ret_5d > avg_move_10d * 1.5:
            comp1 += 5
    elif ret_5d > 3:
        comp1 += 3
    comp1 = min(25, comp1)
    score += comp1
    components["accel"] = comp1
    components["accel_old"] = old_comp1  # Track for logging
    components["ret_5d"] = ret_5d  # Track 5d return for logging

    # ── 2. Power Days (20 pts) ─────────────────────────────────────
    power = 0
    for i in range(-10, 0):
        if (pd.isna(close.iloc[i]) or pd.isna(high.iloc[i])
                or pd.isna(vol.iloc[i]) or pd.isna(vol_50d.iloc[i])):
            continue
        close_above_prior = close.iloc[i] > max(close.iloc[i - 1], high.iloc[i - 1]) if i > -10 else False
        heavy_vol = vol.iloc[i] > vol_50d.iloc[i] * 1.2
        if close_above_prior and heavy_vol:
            power += 1
    comp2 = min(20, power * 7)
    score += comp2
    components["power"] = comp2

    # ── 3. SMA Expansion (20 pts) ──────────────────────────────────
    vs_sma20_today = (close.iloc[-1] / sma_20.iloc[-1] - 1) * 100 if not pd.isna(sma_20.iloc[-1]) else 0
    vs_sma20_before = (close.iloc[-11] / sma_20.iloc[-11] - 1) * 100 if (len(close) >= 11 and not pd.isna(sma_20.iloc[-11])) else 0
    expansion = vs_sma20_today - vs_sma20_before
    comp3 = 0
    if expansion > 15:
        comp3 = 20
    elif expansion > 10:
        comp3 = 15
    elif expansion > 5:
        comp3 = 10
    elif expansion > 2:
        comp3 = 5
    score += comp3
    components["sma_exp"] = comp3

    # ── 4. Volume Ratio (15 pts) ───────────────────────────────────
    up_vol = 0.0
    down_vol = 0.0
    for i in range(-10, 0):
        if pd.isna(vol.iloc[i]) or pd.isna(close.iloc[i - 1]):
            continue
        vr = vol.iloc[i] / vol_50d.iloc[i] if vol_50d.iloc[i] > 0 else 0
        if close.iloc[i] > close.iloc[i - 1]:
            up_vol += vr
        else:
            down_vol += vr
    vol_ratio = up_vol / down_vol if down_vol > 0 else up_vol / 0.5
    comp4 = 0
    if vol_ratio > 3:
        comp4 = 15
    elif vol_ratio > 2:
        comp4 = 12
    elif vol_ratio > 1.5:
        comp4 = 8
    elif vol_ratio > 1:
        comp4 = 4
    score += comp4
    components["vol_ratio"] = comp4

    # ── 5. RS Slope (20 pts) ───────────────────────────────────────
    rs_today = close.iloc[-1] / sma_50.iloc[-1] if not pd.isna(sma_50.iloc[-1]) else 1
    rs_before = close.iloc[-11] / sma_50.iloc[-11] if (len(close) >= 11 and not pd.isna(sma_50.iloc[-11])) else 1
    rs_slope = (rs_today / rs_before - 1) * 100
    comp5 = 0
    if rs_slope > 10:
        comp5 = 20
    elif rs_slope > 5:
        comp5 = 15
    elif rs_slope > 3:
        comp5 = 10
    elif rs_slope > 1:
        comp5 = 5
    score += comp5
    components["rs_slope"] = comp5

    score = min(100, max(0, round(score)))

    if score >= 80:
        status = "Explosive"
    elif score >= 60:
        status = "Accelerating"
    elif score >= 40:
        status = "Building"
    else:
        status = "Quiet"

    return score, status, components


def get_run_stage(df):
    """Count consecutive days in current acceleration run.
    Fresh = 1d, Running = 2d, Extended = 3+ days.
    """
    close = df["Close"]
    high = df["High"]
    vol = df["Volume"]
    vol_50d = vol.rolling(50).mean()
    count = 0
    for i in range(-1, -21, -1):
        if (pd.isna(close.iloc[i]) or pd.isna(high.iloc[i])
                or pd.isna(vol.iloc[i]) or pd.isna(vol_50d.iloc[i])):
            break
        close_above_prior = close.iloc[i] > max(close.iloc[i - 1], high.iloc[i - 1])
        heavy_vol = vol.iloc[i] > vol_50d.iloc[i] * 1.2
        if close_above_prior and heavy_vol:
            count += 1
        else:
            break
    if count == 0:
        stage = "Quiet"
    elif count == 1:
        stage = "Fresh"
    elif count == 2:
        stage = "Running"
    else:
        stage = "Extended"
    return count, stage


def get_results(data_dict, min_score=0):
    results = []
    for ticker, df in data_dict.items():
        if ticker == "SPY":
            continue
        if len(df) < 20:
            continue
        close = df["Close"].iloc[-1]

        score, status, comps = compute_score(df)

        if score < min_score:
            continue

        run_days, stage = get_run_stage(df)

        close = df["Close"].iloc[-1]
        ret_5d = (close / df["Close"].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
        ret_10d = (close / df["Close"].iloc[-11] - 1) * 100 if len(df) >= 11 else 0
        ret_20d = (close / df["Close"].iloc[-21] - 1) * 100 if len(df) >= 21 else 0

        results.append({
            "Ticker": ticker,
            "Price": round(close, 2),
            "Score": score,
            "Status": status,
            "Stage": stage,
            "Days": run_days,
            "5d%": round(ret_5d, 1),
            "10d%": round(ret_10d, 1),
            "20d%": round(ret_20d, 1),
            "Accel": comps.get("accel", 0),
            "Power": comps.get("power", 0),
            "SMA_Exp": comps.get("sma_exp", 0),
            "Vol_Ratio": comps.get("vol_ratio", 0),
            "RS_Slope": comps.get("rs_slope", 0),
        })
        
        # Log stocks that benefited from the new 3% threshold
        accel_new = comps.get("accel", 0)
        accel_old = comps.get("accel_old", 0)
        if accel_new > accel_old:
            print(f"  ⚡ {ticker}: benefited from new threshold (accel: {accel_old} → {accel_new}, 5d%: {ret_5d:.1f}%)")

    results.sort(key=lambda r: r["Score"], reverse=True)
    return results


def fetch_news(ticker, max_days=7):
    try:
        t = yf.Ticker(ticker)
        raw = t.get_news() or []
    except Exception:
        return []
    from datetime import timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
    filtered = []
    for item in raw:
        content = item.get("content", {})
        pub_date = content.get("pubDate", "")
        try:
            pub_time = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if pub_time < cutoff:
            continue
        filtered.append({
            "title": content.get("title", ""),
            "publisher": content.get("provider", {}).get("displayName", ""),
            "link": content.get("canonicalUrl", {}).get("url", ""),
            "summary": content.get("summary", ""),
        })
    return filtered


def get_catalyst(ticker, news_items, api_key):
    from openai import OpenAI
    if not news_items:
        return "No recent news found."
    client = OpenAI(api_key=api_key, base_url="https://opencode.ai/zen/go/v1")
    lines = []
    for item in news_items:
        lines.append(f"  - {item['title']} ({item['publisher']})")
        if item.get("summary"):
            lines.append(f"    {item['summary']}")
    news_text = "\n".join(lines)
    prompt = f"""You are a financial analyst. Below is recent news for {ticker}.

{news_text}

Based on this news, determine if there is a fundamental catalyst driving the stock's recent momentum. Reply with 1-2 sentences identifying the catalyst (e.g., strong earnings, product launch, sector tailwind). If no clear catalyst is found, say "No clear catalyst identified from recent news." Do not include any preamble."""
    try:
        response = client.chat.completions.create(
            model="mimo-v2.5",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return "AI analysis unavailable."


def send_email(results, indices, smtp_config, recipients, top_n=999):
    import csv
    import io
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email import encoders

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    index_str = ", ".join(i.upper() for i in indices)

    rows = ""
    for r in results[:top_n]:
        stage_style = ""
        if r.get("Stage") == "Fresh": stage_style = ' style="background:#d4edda;font-weight:bold;"'
        elif r.get("Stage") == "Running": stage_style = ' style="background:#fff3cd;font-weight:bold;"'
        catalyst = r.get("Catalyst", "")
        tradingview_link = f"https://www.tradingview.com/chart/?symbol={r['Ticker']}"
        rows += f"""<tr>
<td><a href="{tradingview_link}">{r['Ticker']}</a></td>
<td>${r['Price']}</td>
<td style="font-weight:bold;">{r['Score']}</td>
<td>{r['Status']}</td>
<td{stage_style}>{r.get('Stage', '')}</td>
<td>{r.get('Days', '')}</td>
<td>{r['5d%']:+.1f}%</td>
<td>{r['10d%']:+.1f}%</td>
<td>{r['20d%']:+.1f}%</td>
<td>{r['Accel']}</td>
<td>{r['Power']}</td>
<td>{r['SMA_Exp']}</td>
<td>{r['Vol_Ratio']}</td>
<td>{r['RS_Slope']}</td>
<td style="font-size:12px;max-width:300px;">{catalyst}</td>
</tr>"""

    html = f"""<html><body style="font-family:Arial,sans-serif;">
<div style="background:#fff3cd;border:1px solid #ffc107;padding:12px;margin-bottom:15px;border-radius:4px;">
<strong>⚠️ Disclaimer:</strong> This scan only flags stocks with recent price spikes.
It does not check <em>why</em> they are moving — do your own research before trading.
</div>
<h2>Momentum Acceleration Scan</h2>
<p>{date_str} | Universe: {index_str} | Passing: {len(results)} stocks</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px;">
<tr style="background:#2c3e50;color:white;">
<th>Ticker</th><th>Price</th><th>Score</th><th>Status</th><th>Stage</th><th>Days</th><th>5d%</th><th>10d%</th><th>20d%</th><th>Accel</th><th>Power</th><th>SMA Exp</th><th>Vol Ratio</th><th>RS Slope</th><th>Catalyst</th>
</tr>
{rows}
</table>
<p style="color:#888;font-size:12px;">Experimental — not financial advice. Stage: Fresh=1d, Running=2d, Extended=3+ days in this run.</p>
</body></html>"""

    # ── Build CSV attachment ──
    csv_out = io.StringIO()
    writer = csv.writer(csv_out)
    cols = ["Ticker", "Price", "Score", "Status", "Stage", "Days",
            "5d%", "10d%", "20d%", "Accel", "Power", "SMA_Exp",
            "Vol_Ratio", "RS_Slope", "Catalyst", "TradingView_Link"]
    writer.writerow(cols)
    for r in results[:top_n]:
        vals = [r.get(c, "") for c in cols[:-1]]
        vals.append(f"https://www.tradingview.com/chart/?symbol={r['Ticker']}")
        writer.writerow(vals)
    csv_data = csv_out.getvalue()

    # ── Build message ──
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Momentum Acceleration Scan - {date_str}"
    msg["From"] = smtp_config["user"]
    msg["To"] = ", ".join(recipients)

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(html, "html"))
    msg.attach(body)

    csv_part = MIMEBase("text", "csv")
    csv_part.set_payload(csv_data)
    encoders.encode_base64(csv_part)
    csv_part.add_header("Content-Disposition", "attachment",
                        filename=f"momentum_scan_{date_str[:10]}.csv")
    msg.attach(csv_part)

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


def read_watchlist(path):
    tickers = []
    with open(path) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if line:
                tickers.append(line.upper())
    return tickers


def main():
    parser = argparse.ArgumentParser(description="Momentum acceleration scanner (experimental)")
    parser.add_argument("-sp500", action="store_true")
    parser.add_argument("-sp400", action="store_true")
    parser.add_argument("-sp600", action="store_true")
    parser.add_argument("-nasdaq", action="store_true")
    parser.add_argument("-nyse", action="store_true")
    parser.add_argument("-all", action="store_true")
    parser.add_argument("--all-us", action="store_true")
    parser.add_argument("--watchlist", type=str, help="Scan a watchlist file instead of an index")
    parser.add_argument("--min-score", type=int, default=40, help="Minimum score threshold (default: 40)")
    parser.add_argument("--top", type=int, default=0, help="Show only top N results")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--no-ai", action="store_true", help="Skip AI catalyst analysis")
    parser.add_argument("--output", nargs="?", const="__auto__", help="Save results to CSV (default: momentum_scan_YYYY-MM-DD.csv)")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    # Collect indices
    indices = []
    if args.watchlist:
        pass  # handled separately
    elif args.all_us:
        indices = ["nasdaq", "nyse"]
    else:
        if args.all or args.sp500: indices.append("sp500")
        if args.all or args.sp400: indices.append("sp400")
        if args.all or args.sp600: indices.append("sp600")
        if args.nasdaq: indices.append("nasdaq")
        if args.nyse: indices.append("nyse")

    all_results = []

    # ── Watchlist mode ──
    if args.watchlist:
        path = args.watchlist
        if not os.path.exists(path):
            print(f"Watchlist not found: {path}")
            sys.exit(1)
        tickers = read_watchlist(path)
        if not tickers:
            print("No tickers in watchlist.")
            return
        print(f"Scanning watchlist: {', '.join(tickers)}")
        data_dict, failed = download_data(tickers, min_price=None)
        print(f"  Got data for {len(data_dict)} stocks ({len(failed)} failed)")
        results = get_results(data_dict, min_score=args.min_score)
        all_results = results

    # ── Index mode ──
    elif indices:
        for index in indices:
            print(f"\n=== {index.upper()} ===")
            cache = None if args.refresh else load_cache(index)
            if cache:
                data_dict = cache["data"]
            elif args.refresh:
                print("  Downloading...", flush=True)
                tickers = get_tickers(index)
                if not tickers:
                    continue
                min_price = 15 if index in ("nasdaq", "nyse") else None
                data_dict, failed = download_data(tickers, min_price=min_price)
                print(f"  Downloaded {len(data_dict)} stocks", flush=True)
                save_cache(index, tickers, data_dict, failed)
            else:
                print(f"  No cached data for {index}. Use --refresh to download.")
                continue

            results = get_results(data_dict, min_score=args.min_score)
            if results:
                print(f"  {len(results)} stocks above min-score {args.min_score}", flush=True)
                all_results.extend(results)

        if len(indices) > 1:
            seen = set()
            deduped = []
            for r in all_results:
                if r["Ticker"] not in seen:
                    seen.add(r["Ticker"])
                    deduped.append(r)
            all_results = deduped
            all_results.sort(key=lambda r: r["Score"], reverse=True)

    else:
        parser.print_help()
        sys.exit(1)

    if not all_results:
        print("\nNo stocks above threshold.")
        return

    # ── AI catalyst analysis (Fresh & Running only) ──
    if not args.no_ai:
        fresh_running = [r for r in all_results if r.get("Stage") in ("Fresh", "Running")]
        api_key = os.getenv("OPENCODE_GO_API_KEY")
        if api_key and fresh_running:
            print(f"\nAnalyzing catalysts for {len(fresh_running)} stocks...")
            for i, r in enumerate(fresh_running):
                ticker = r["Ticker"]
                print(f"  [{i+1}/{len(fresh_running)}] {ticker}...", end=" ", flush=True)
                news = fetch_news(ticker)
                if news:
                    catalyst = get_catalyst(ticker, news, api_key)
                else:
                    catalyst = "No recent news found."
                r["Catalyst"] = catalyst
                print(catalyst[:80])
        elif not api_key:
            print("\nOPENCODE_GO_API_KEY not set. Skipping AI catalyst analysis.")

    display = all_results[:args.top] if args.top > 0 else all_results
    df = pd.DataFrame(display)
    print(f"\n{'='*60}")
    print(f"Momentum Acceleration Results — {len(all_results)} stocks")
    print(f"{'='*60}")
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 200)
    cols = [c for c in df.columns if c != "Catalyst"]
    print(df[cols].to_string(index=False))

    if "Catalyst" in df.columns:
        print(f"\n{'='*60}")
        print("Catalyst Analysis")
        print(f"{'='*60}")
        for r in display:
            cat = r.get("Catalyst", "")
            tv = f"https://www.tradingview.com/chart/?symbol={r['Ticker']}"
            print(f"{r['Ticker']} (Score: {r['Score']}, Stage: {r['Stage']})")
            print(f"  Catalyst: {cat}")
            print(f"  TradingView: {tv}")
            print()

    if args.output is not None:
        output_path = args.output if args.output != "__auto__" else os.path.expanduser(f"{os.getenv('CSV_OUTPUT_DIR', '~/csv_output')}/momentum_scan_{datetime.now().strftime('%Y-%m-%d')}.csv")
        out = df.copy()
        out["TradingView_Link"] = "https://www.tradingview.com/chart/?symbol=" + out["Ticker"]
        out.to_csv(output_path, index=False)
        print(f"\nResults saved to {output_path}")

    if not args.no_email:
        raw_rcpt = os.getenv("RECIPIENTS", "")
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASSWORD")
        if smtp_user and smtp_pass and raw_rcpt:
            recipients = parse_recipients(raw_rcpt)
            if recipients:
                print(f"\nSending email to {len(recipients)} recipient(s)...")
                send_email(all_results, indices, {"user": smtp_user, "password": smtp_pass}, recipients)
                print("Email sent!")


if __name__ == "__main__":
    main()
