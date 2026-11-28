"""Totals IncoPOS sales between two times, from the day files fetch_incopos.py saved.

Rules (what we know so far):
- The API repeats some receipts, so we keep one copy per sale Id.
- A receipt's time is when it was paid (payment CreatedAt). The "Z" at the end
  is ignored: the times are already Tbilisi time.
- --from is included, --to is not: 21:00 -> 09:00 counts 21:00:00 but not 09:00:00.

Usage: uv run python src/tema_ops/incopos/shift_totals.py --branch lisi --from "2026-11-16 21:00" --to "2026-11-17 09:00"
"""
import argparse
import datetime
import json
from decimal import Decimal

from tema_ops.incopos.branches import BRANCHES, DATA_DIR


def load_receipts(branch: str, start: datetime.datetime, end: datetime.datetime) -> dict:
    """Reads every day file the time range touches. Returns {sale Id: sale}, repeats removed."""
    receipts = {}
    entries = 0
    day = start.date()
    while day <= end.date():
        path = DATA_DIR / branch / f"{day}.json"
        if not path.exists():
            raise SystemExit(f"Missing {path}: run fetch_incopos.py --from {day} --branch {branch} first")
        sales = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        entries += len(sales)
        for sale in sales:
            receipts.setdefault(sale["Id"], sale)  # a repeat of an Id we already have is skipped
        day += datetime.timedelta(days=1)
    print(f"Read {entries} entries = {len(receipts)} real receipts ({entries - len(receipts)} repeats removed)")
    return receipts


def paid_at(sale: dict) -> datetime.datetime:
    # removesuffix("Z"): with the Z, Python would treat the time as UTC
    return datetime.datetime.fromisoformat(sale["Payments"][0]["CreatedAt"].removesuffix("Z"))


def main():
    parser = argparse.ArgumentParser(description="Total IncoPOS sales between two times.")
    parser.add_argument("--branch", choices=BRANCHES, default="dolabauri", help="Default: dolabauri")
    parser.add_argument("--from", dest="start", required=True, help='e.g. "2026-11-16 21:00"')
    parser.add_argument("--to", dest="end", required=True, help='e.g. "2026-11-17 09:00"')
    args = parser.parse_args()
    start = datetime.datetime.fromisoformat(args.start)
    end = datetime.datetime.fromisoformat(args.end)

    receipts = load_receipts(args.branch, start, end)
    in_range = [sale for sale in receipts.values() if start <= paid_at(sale) < end]
    total = sum((p["Amount"] for sale in in_range for p in sale["Payments"]), Decimal("0"))
    print(f"{start} -> {end}: {len(in_range)} receipts, {total:.2f} GEL")


if __name__ == "__main__":
    main()