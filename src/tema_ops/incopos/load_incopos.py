"""Loads the IncoPOS files saved by fetch_incopos.py into the database.

Safe to run again and again: a receipt already in the database is replaced by
the copy from the file, and receipts the API repeats end up stored once.

Usage:
  uv run python src/tema_ops/incopos/load_incopos.py                                 (every saved day)
  uv run python src/tema_ops/incopos/load_incopos.py --from 2026-11-16 --to 2026-11-17
"""
import argparse
import datetime
import json
import os
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

load_dotenv()

DATA_DIR = Path("data/incopos")

# branch_id is not here on purpose: we set it by hand once Nino confirms the branch,
# so loading must never overwrite it.
UPSERT_LOCATION = """
INSERT INTO incopos.locations (id, name) VALUES (%s, %s)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
"""

UPSERT_ITEM = """
INSERT INTO incopos.items (id, name, group_id, measure_unit, retail_price, deleted, raw)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name, group_id = EXCLUDED.group_id, measure_unit = EXCLUDED.measure_unit,
    retail_price = EXCLUDED.retail_price, deleted = EXCLUDED.deleted, raw = EXCLUDED.raw
"""

INSERT_SALE = """
INSERT INTO incopos.sales (location_id, id, paid_at, raw) VALUES (%s, %s, %s, %s)
"""

INSERT_LINE = """
INSERT INTO incopos.sale_lines (location_id, sale_id, id, item_id, quantity, price, cost, discount)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

INSERT_PAYMENT = """
INSERT INTO incopos.payments (location_id, sale_id, id, type_id, amount, created_at)
VALUES (%s, %s, %s, %s, %s, %s)
"""


def number(value) -> Decimal:
    """The API sends numbers like 2.5 as floats. Money must be exact, so we go through the text."""
    return Decimal(str(value))


def to_time(value: str) -> datetime.datetime:
    # removesuffix("Z"): the times are already Tbilisi time, the Z is wrong
    return datetime.datetime.fromisoformat(value.removesuffix("Z"))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_reference(cur):
    """Branches (locations) and products. Always replaced with the latest download."""
    for loc in read_json(DATA_DIR / "locations.json"):
        cur.execute(UPSERT_LOCATION, (loc["Id"], loc["Name"]))
    for item in read_json(DATA_DIR / "items.json"):
        cur.execute(UPSERT_ITEM, (item["Id"], item["Name"], item["GroupId"], item["MeasureUnit"],
                                  number(item["RetailPrice"]), item["Deleted"], Jsonb(item)))


def load_day(cur, path: Path) -> int:
    """Loads one day file. Returns how many real receipts it had."""
    receipts = {}
    for sale in read_json(path):
        receipts[sale["Id"]] = sale  # a repeated receipt just replaces its identical copy

    for sale in receipts.values():
        loc = sale["LocationId"]
        # Remove the old copy first (its lines and payments go with it: ON DELETE CASCADE),
        # so a receipt that was corrected in IncoPOS doesn't keep old lines.
        cur.execute("DELETE FROM incopos.sales WHERE location_id = %s AND id = %s", (loc, sale["Id"]))
        # Every receipt so far has exactly 1 payment: its time is when the receipt was paid
        cur.execute(INSERT_SALE, (loc, sale["Id"], to_time(sale["Payments"][0]["CreatedAt"]), Jsonb(sale)))
        for line in sale["Details"]:
            cur.execute(INSERT_LINE, (loc, sale["Id"], line["DetailId"], line["ItemId"],
                                      number(line["Quantity"]), number(line["Price"]),
                                      number(line["PriceIn"]), number(line["Discount"])))
        for pay in sale["Payments"]:
            cur.execute(INSERT_PAYMENT, (loc, sale["Id"], pay["Id"], pay["TypeId"],
                                         number(pay["Amount"]), to_time(pay["CreatedAt"])))
    return len(receipts)


def main():
    parser = argparse.ArgumentParser(description="Load saved IncoPOS files into the database.")
    parser.add_argument("--from", dest="start", help="First day (YYYY-MM-DD). Default: every saved day")
    parser.add_argument("--to", dest="end", help="Last day (YYYY-MM-DD). Default: same as --from")
    args = parser.parse_args()

    paths = sorted(DATA_DIR.glob("*/*.json"))  # data/incopos/<location Id>/<day>.json
    if args.start:
        end = args.end or args.start
        paths = [p for p in paths if args.start <= p.stem <= end]  # "2026-11-16" dates compare like text

    with psycopg.connect(os.environ["INCOPOS_DATABASE_URL"]) as conn, conn.cursor() as cur:
        load_reference(cur)
        total = 0
        for path in paths:
            count = load_day(cur, path)
            total += count
            print(f"loaded {path}: {count} receipts")
    print(f"Done: {len(paths)} files, {total} receipts")


if __name__ == "__main__":
    main()