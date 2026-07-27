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
    if len(df) < 20:
        return 0, "Quiet", {}

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]
    vol_50d = vol.rolling(50).mean()
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()

    components = {}
    score = 0

    # ── 1. Consecutive Up Days (35 pts) ──────────────────────────────
    daily_chg = close.pct_change(fill_method=None) * 100
    streak = 0
    streak_gains = []
    for i in range(-1, -21, -1):
        if pd.isna(daily_chg.iloc[i]):
            break
        if daily_chg.iloc[i] > 0:
            streak += 1
            streak_gains.append(daily_chg.iloc[i])
        else:
            break

    comp1 = 0
    if streak >= 4:
        comp1 = 35
    elif streak == 3:
        comp1 = 30
    elif streak == 2:
        comp1 = 20
    elif streak == 1:
        comp1 = 5
    score += comp1
    components["streak"] = comp1
    components["streak_days"] = streak
    components["streak_gains"] = streak_gains

    # ── 2. Gain Consistency (25 pts) ─────────────────────────────────
    comp2 = 0
    if streak >= 2 and streak_gains:
        avg_gain = sum(streak_gains) / len(streak_gains)
        max_gain = max(streak_gains)
        min_gain = min(streak_gains)

        # Ideal: avg gain 0.5-2.5%, no single day > 5%, no negative days
        if 0.3 <= avg_gain <= 3.0:
            comp2 += 10
        if max_gain <= 5.0:
            comp2 += 8
        elif max_gain <= 8.0:
            comp2 += 4
        if max_gain - min_gain <= 3.0:
            comp2 += 7
        elif max_gain - min_gain <= 5.0:
            comp2 += 3
    elif streak == 1:
        comp2 = 5
    comp2 = min(25, comp2)
    score += comp2
    components["consistency"] = comp2

    # ── 3. Above SMAs (20 pts) ───────────────────────────────────────
    comp3 = 0
    close_price = close.iloc[-1]
    vs_sma20 = (close_price / sma_20.iloc[-1] - 1) * 100 if not pd.isna(sma_20.iloc[-1]) else 0
    vs_sma50 = (close_price / sma_50.iloc[-1] - 1) * 100 if not pd.isna(sma_50.iloc[-1]) else 0

    if vs_sma20 > 0:
        comp3 += 6
    if vs_sma20 > 1:
        comp3 += 4
    if vs_sma50 > 0:
        comp3 += 6
    if vs_sma50 > 1:
        comp3 += 4

    # Penalty if too extended (could mean a spike is ending)
    if vs_sma20 > 15:
        comp3 = max(0, comp3 - 5)
    if vs_sma50 > 25:
        comp3 = max(0, comp3 - 5)

    score += comp3
    components["sma_position"] = comp3

    # ── 4. Volume Support (10 pts) ───────────────────────────────────
    comp4 = 0
    up_days_vol = 0
    down_days_vol = 0
    for i in range(-10, 0):
        if pd.isna(vol.iloc[i]) or pd.isna(close.iloc[i - 1]) or pd.isna(vol_50d.iloc[i]):
            continue
        vr = vol.iloc[i] / vol_50d.iloc[i] if vol_50d.iloc[i] > 0 else 0
        if close.iloc[i] > close.iloc[i - 1]:
            up_days_vol += vr
        else:
            down_days_vol += vr

    total_days = up_days_vol + down_days_vol
    if total_days > 0:
        up_ratio = up_days_vol / total_days
        if up_ratio > 0.7:
            comp4 = 10
        elif up_ratio > 0.6:
            comp4 = 7
        elif up_ratio > 0.5:
            comp4 = 4
        else:
            comp4 = 1
    score += comp4
    components["vol_support"] = comp4

    # ── 5. Trend Strength (10 pts) ───────────────────────────────────
    ret_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0
    comp5 = 0
    if 1 <= ret_5d <= 8:
        comp5 = 10
    elif 0 <= ret_5d < 1:
        comp5 = 5
    elif 8 < ret_5d <= 15:
        comp5 = 6
    elif ret_5d > 15:
        comp5 = 2
    score += comp5
    components["trend"] = comp5

    score = min(100, max(0, round(score)))

    if score >= 70:
        status = "Steady Climber"
    elif score >= 50:
        status = "Building"
    elif score >= 30:
        status = "Early"
    else:
        status = "Quiet"

    return score, status, components


def get_results(data_dict, min_score=0):
    results = []
    for ticker, df in data_dict.items():
        if ticker == "SPY":
            continue
        if len(df) < 20:
            continue

        score, status, comps = compute_score(df)

        if score < min_score:
            continue

        close = df["Close"].iloc[-1]
        ret_5d = (close / df["Close"].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
        ret_3d = (close / df["Close"].iloc[-4] - 1) * 100 if len(df) >= 4 else 0
        ret_10d = (close / df["Close"].iloc[-11] - 1) * 100 if len(df) >= 11 else 0
        ret_20d = (close / df["Close"].iloc[-21] - 1) * 100 if len(df) >= 21 else 0

        streak_days = comps.get("streak_days", 0)
        streak_gains = comps.get("streak_gains", [])
        avg_streak_gain = round(sum(streak_gains) / len(streak_gains), 2) if streak_gains else 0.0

        if streak_days >= 10:
            stage = "Extended+"
        elif streak_days >= 5:
            stage = "Extended"
        elif streak_days == 3:
            stage = "3-Up"
        elif streak_days == 2:
            stage = "2-Up"
        elif streak_days == 1:
            stage = "Fresh"
        else:
            stage = "Quiet"

        results.append({
            "Ticker": ticker,
            "Price": round(close, 2),
            "Score": score,
            "Status": status,
            "Stage": stage,
            "Days Up": streak_days,
            "Avg Gain": avg_streak_gain,
            "3d%": round(ret_3d, 1),
            "5d%": round(ret_5d, 1),
            "10d%": round(ret_10d, 1),
            "20d%": round(ret_20d, 1),
            "Streak": comps.get("streak", 0),
            "Consist": comps.get("consistency", 0),
            "SMAs": comps.get("sma_position", 0),
            "Vol": comps.get("vol_support", 0),
            "Trend": comps.get("trend", 0),
        })

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

Based on this news, determine if there is a fundamental catalyst driving the stock's steady rise. Reply with 1-2 sentences identifying the catalyst (e.g., strong earnings, product launch, sector tailwind). If no clear catalyst is found, say "No clear catalyst identified from recent news." Do not include any preamble."""
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
        if r.get("Stage") == "2-Up": stage_style = ' style="background:#d4edda;font-weight:bold;"'
        elif r.get("Stage") == "3-Up": stage_style = ' style="background:#fff3cd;font-weight:bold;"'
        elif r.get("Stage") == "Extended": stage_style = ' style="background:#f8d7da;font-weight:bold;"'
        catalyst = r.get("Catalyst", "")
        tradingview_link = f"https://www.tradingview.com/chart/?symbol={r['Ticker']}"
        rows += f"""<tr>
<td><a href="{tradingview_link}">{r['Ticker']}</a></td>
<td>${r['Price']}</td>
<td style="font-weight:bold;">{r['Score']}</td>
<td>{r['Status']}</td>
<td{stage_style}>{r.get('Stage', '')}</td>
<td>{r.get('Days Up', '')}</td>
<td>{r.get('Avg Gain', '')}%</td>
<td>{r['3d%']:+.1f}%</td>
<td>{r['5d%']:+.1f}%</td>
<td>{r['10d%']:+.1f}%</td>
<td>{r['20d%']:+.1f}%</td>
<td>{r['Streak']}</td>
<td>{r['Consist']}</td>
<td>{r['SMAs']}</td>
<td>{r['Vol']}</td>
<td>{r['Trend']}</td>
<td style="font-size:12px;max-width:300px;">{catalyst}</td>
</tr>"""

    html = f"""<html><body style="font-family:Arial,sans-serif;">
<h2>Steady Climber Scan</h2>
<p>{date_str} | Universe: {index_str} | Passing: {len(results)} stocks</p>
<p style="color:#888;font-size:12px;">Stocks with 2+ consecutive up days — consistent climbers, not spike-and-dump.</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px;">
<tr style="background:#2c3e50;color:white;">
<th>Ticker</th><th>Price</th><th>Score</th><th>Status</th><th>Stage</th><th>Days Up</th><th>Avg Gain</th><th>3d%</th><th>5d%</th><th>10d%</th><th>20d%</th><th>Streak</th><th>Consist</th><th>SMAs</th><th>Vol</th><th>Trend</th><th>Catalyst</th>
</tr>
{rows}
</table>
<p style="color:#888;font-size:12px;">Experimental — not financial advice. Stage: 2-Up=2 days, 3-Up=3 days, Extended=5+ days.</p>
</body></html>"""

    csv_out = io.StringIO()
    writer = csv.writer(csv_out)
    cols = ["Ticker", "Price", "Score", "Status", "Stage", "Days Up", "Avg Gain",
            "3d%", "5d%", "10d%", "20d%", "Streak", "Consist", "SMAs",
            "Vol", "Trend", "Catalyst", "TradingView_Link"]
    writer.writerow(cols)
    for r in results[:top_n]:
        vals = [r.get(c, "") for c in cols[:-1]]
        vals.append(f"https://www.tradingview.com/chart/?symbol={r['Ticker']}")
        writer.writerow(vals)
    csv_data = csv_out.getvalue()

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Steady Climber Scan - {date_str}"
    msg["From"] = smtp_config["user"]
    msg["To"] = ", ".join(recipients)

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(html, "html"))
    msg.attach(body)

    csv_part = MIMEBase("text", "csv")
    csv_part.set_payload(csv_data)
    encoders.encode_base64(csv_part)
    csv_part.add_header("Content-Disposition", "attachment",
                        filename=f"steady_climber_{date_str[:10]}.csv")
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
    parser = argparse.ArgumentParser(description="Steady climber scanner — stocks up 2-3 days straight")
    parser.add_argument("-sp500", action="store_true")
    parser.add_argument("-sp400", action="store_true")
    parser.add_argument("-sp600", action="store_true")
    parser.add_argument("-nasdaq", action="store_true")
    parser.add_argument("-nyse", action="store_true")
    parser.add_argument("-all", action="store_true")
    parser.add_argument("--all-us", action="store_true")
    parser.add_argument("--watchlist", type=str, help="Scan a watchlist file instead of an index")
    parser.add_argument("--min-score", type=int, default=30, help="Minimum score threshold (default: 30)")
    parser.add_argument("--top", type=int, default=0, help="Show only top N results")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--no-ai", action="store_true", help="Skip AI catalyst analysis")
    parser.add_argument("--output", nargs="?", const="__auto__", help="Save results to CSV (default: steady_climber_YYYY-MM-DD.csv)")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    indices = []
    if args.watchlist:
        pass
    elif args.all_us:
        indices = ["nasdaq", "nyse"]
    else:
        if args.all or args.sp500: indices.append("sp500")
        if args.all or args.sp400: indices.append("sp400")
        if args.all or args.sp600: indices.append("sp600")
        if args.nasdaq: indices.append("nasdaq")
        if args.nyse: indices.append("nyse")

    all_results = []

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

    if not args.no_ai:
        fresh_running = [r for r in all_results if r.get("Stage") in ("2-Up", "3-Up")]
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
    print(f"Steady Climber Results — {len(all_results)} stocks")
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
        output_path = args.output if args.output != "__auto__" else os.path.expanduser(f"{os.getenv('CSV_OUTPUT_DIR', '~/csv_output')}/steady_climber_{datetime.now().strftime('%Y-%m-%d')}.csv")
        out = df.copy()
        out["TradingView_Link"] = "https://www.tradingview.com/chart/?symbol=" + out["Ticker"]
        out.to_csv(output_path, index=False)
        print(f"\nResults saved to {output_path}")

    if not args.no_email:
        raw_rcpt = os.getenv("REPORT_RECIPIENTS", "")
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
