#!/usr/bin/env python3
import argparse
import os
import sys
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

from minervini.data import get_tickers, download_data, save_cache, load_cache, get_benchmark
from minervini.screener import screen_stocks
from minervini.emailer import send_email

load_dotenv()


def parse_recipients(raw):
    recipients = []
    for part in raw.split(","):
        part = part.split("#")[0].strip()
        if part:
            recipients.append(part)
    return recipients


def main():
    parser = argparse.ArgumentParser(description="SEPA Stage 2 Stock Screener (Minervini)")
    parser.add_argument("-sp500", action="store_true", help="Screen S&P 500")
    parser.add_argument("-sp400", action="store_true", help="Screen S&P 400")
    parser.add_argument("-sp600", action="store_true", help="Screen S&P 600")
    parser.add_argument("-nasdaq", action="store_true", help="Screen NASDAQ common stocks")
    parser.add_argument("-nyse", action="store_true", help="Screen NYSE common stocks")
    parser.add_argument("-all", action="store_true", help="Screen all S&P indices")
    parser.add_argument("--all-us", action="store_true", help="Screen NASDAQ + NYSE (incl. S&P components)")
    parser.add_argument("--no-email", action="store_true", help="Print results to console only")
    parser.add_argument("--output", nargs="?", const="__auto__", help="Save results to CSV (default: sepa_results_YYYY-MM-DD.csv)")
    parser.add_argument("--refresh", action="store_true", help="Force re-download data")
    args = parser.parse_args()

    indices = []
    if args.all_us:
        indices = ["nasdaq", "nyse"]
    if args.all or args.sp500:
        indices.append("sp500")
    if args.all or args.sp400:
        indices.append("sp400")
    if args.all or args.sp600:
        indices.append("sp600")
    if args.nasdaq:
        indices.append("nasdaq")
    if args.nyse:
        indices.append("nyse")

    if not indices:
        parser.print_help()
        sys.exit(1)

    spy_data = get_benchmark(force_refresh=args.refresh)
    all_results = []

    for index in indices:
        print(f"\n=== Screening {index.upper()} ===")

        cache = None if args.refresh else load_cache(index)

        if cache:
            data_dict = cache["data"]
        elif args.refresh:
            print("  Fetching ticker list...", flush=True)
            try:
                tickers = get_tickers(index)
            except Exception as e:
                print(f"  Error fetching {index} tickers: {e}")
                continue

            if not tickers:
                print(f"  No tickers found for {index}, skipping.")
                continue

            min_price = 15 if index in ("nasdaq", "nyse") else None
            print(f"  Found {len(tickers)} stocks. Downloading data (this may take a while)...", flush=True)
            data_dict, failed = download_data(tickers, min_price=min_price)
            print(f"  Downloaded {len(data_dict)} stocks ({len(failed)} failed)", flush=True)
            save_cache(index, tickers, data_dict, failed)
        else:
            print(f"  No cached data for {index}. Use --refresh to download.")
            continue

        if spy_data is not None:
            data_dict["SPY"] = spy_data
        print("  Running screener...", flush=True)
        results = screen_stocks(data_dict)

        if not results.empty:
            print(f"  {len(results)} stocks passed all 8 criteria:")
            print(results.to_string(index=False))
            all_results.append(results)
        else:
            print("  No stocks passed.")

    if not all_results:
        print("\nNo stocks passed the screen.")
        return

    combined = pd.concat(all_results, ignore_index=True)
    combined = combined.drop_duplicates(subset="Ticker").reset_index(drop=True)
    if len(all_results) > 1:
        print(f"\n  Combined: {len(combined)} unique stocks")

    if args.output is not None:
        output_path = args.output if args.output != "__auto__" else f"sepa_results_{datetime.now().strftime('%Y-%m-%d')}.csv"
        combined.to_csv(output_path, index=False)
        print(f"\nResults saved to {output_path}")

    if not args.no_email:
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASSWORD")
        raw_rcpt = os.getenv("RECIPIENTS", "")

        if smtp_user and smtp_pass and raw_rcpt:
            recipients = parse_recipients(raw_rcpt)
            if recipients:
                smtp_config = {"user": smtp_user, "password": smtp_pass}
                print(f"\nSending email to {len(recipients)} recipient(s)...")
                try:
                    send_email(combined, indices, smtp_config, recipients)
                    print("Email sent!")
                except Exception as e:
                    print(f"Failed to send email: {e}")
                    print("\n=== Results ===")
                    print(combined.to_string(index=False))
            else:
                print("\nNo valid recipients found in .env. Printing results:")
                print(combined.to_string(index=False))
        else:
            print("\nSMTP not configured (check .env). Printing results:")
            print(combined.to_string(index=False))
    else:
        print("\n=== Final Results ===")
        print(combined.to_string(index=False))


if __name__ == "__main__":
    main()
