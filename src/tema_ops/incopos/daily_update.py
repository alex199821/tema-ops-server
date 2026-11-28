"""Downloads yesterday's IncoPOS sales (every branch), loads them into the database,
then brings the sales tabs of the Google Sheet up to date.
Runs on the server every night at 01:00 (cron), one hour after the day has ended.
If one branch can't be downloaded, the others are still loaded and their tabs updated;
the job then ends with an error, so the alert email goes out.

Usage:
  uv run python src/tema_ops/incopos/daily_update.py              (yesterday)
  uv run python src/tema_ops/incopos/daily_update.py 2026-11-05   (redo one day)
"""
import subprocess
import sys
from datetime import date, timedelta


def daily_update(day):
    # 1. Download the day for every branch (one JSON file each, in data/incopos/<branch>/)
    fetched = subprocess.run([sys.executable, "src/tema_ops/incopos/fetch_incopos.py", "--from", day])
    # 2. Load those files into the database (safe to repeat: receipts are replaced, not doubled)
    subprocess.run([sys.executable, "src/tema_ops/incopos/load_incopos.py", "--from", day], check=True)
    # 3. Bring each branch's tab in the Google Sheet up to date (the newest month, and this day's month)
    subprocess.run([sys.executable, "src/tema_ops/incopos/sales_sheet.py", "--day", day], check=True)
    if fetched.returncode != 0:
        sys.exit("A branch could not be downloaded (see above); the others are up to date")


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).isoformat()
    daily_update(day)
