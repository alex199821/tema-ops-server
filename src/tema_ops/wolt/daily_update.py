import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from tema_ops.wolt.load_to_db import load_file

load_dotenv()


def daily_update(day):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        venue_ids = [row[0] for row in cur.execute("SELECT id FROM wolt.venues ORDER BY id")]

    # 1. Fetch the day for every branch (saves JSON files)
    for venue_id in venue_ids:
        subprocess.run([sys.executable, "src/tema_ops/wolt/fetch_wolt.py",
                        "--venue", venue_id, "--from", day, "--to", day], check=True)

    # 2. Load all of them into the database in one go
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        for venue_id in venue_ids:
            load_file(cur, Path(f"data/wolt/{venue_id}/{day}.json"))
            print("loaded", venue_id, day)


if __name__ == "__main__":
    # Default: yesterday. Or pass a date to redo one day: daily_update.py 2026-11-05
    day = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).isoformat()
    daily_update(day)