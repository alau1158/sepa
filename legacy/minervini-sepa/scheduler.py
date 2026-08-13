import schedule
import time
from datetime import datetime
import os
import sys


def run_weekly_report():
    print(f"\n=== Running weekly report at {datetime.now()} ===")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from report import ReportGenerator
        report = ReportGenerator()
        report.run_weekly()
    except Exception as e:
        print(f"Error running report: {e}")


def main():
    schedule.every().sunday.at("09:00").do(run_weekly_report)
    
    print("Scheduler started. Weekly reports will be sent every Sunday at 9:00 AM")
    print("Press Ctrl+C to stop")
    
    run_weekly_report()
    
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()