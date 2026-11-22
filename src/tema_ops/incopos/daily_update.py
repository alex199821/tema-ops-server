"""Downloads yesterday's IncoPOS sales (every location) and loads them into the database.
Runs on the server every night at 01:00 (cron), one hour after the day has ended.

Usage:
  uv run python src/tema_ops/incopos/daily_update.py              (yesterday)
  uv run python src/tema_ops/incopos/daily_update.py 2026-11-05   (redo one day)
"""
import subprocess
import sys
from datetime import date, timedelta


def daily_update(day):
    # 1. Download the day for every location (one JSON file each, in data/incopos/)
    subprocess.run([sys.executable, "src/tema_ops/incopos/fetch_incopos.py", "--from", day], check=True)
    # 2. Load those files into the database (safe to repeat: receipts are replaced, not doubled)
    subprocess.run([sys.executable, "src/tema_ops/incopos/load_incopos.py", "--from", day], check=True)


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).isoformat()
    daily_update(day)
