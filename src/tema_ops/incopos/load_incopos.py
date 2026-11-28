"""Loads the IncoPOS files saved by fetch_incopos.py into the database, branch by branch.

Each branch's files are in data/incopos/<branch>/ (see branches.py), and every row gets the
branch's id: the receipt and product numbers of different branches clash.
Safe to run again and again: a receipt already in the database is replaced by the copy from the
file, and receipts the API repeats end up stored once.
A receipt with no payment is skipped: it has no time. (5 in the history, all 0 GEL.)
deleted_items.json (if there): products the branch has deleted in IncoPOS but sold before. IncoCloud's
product list leaves them out, so they were looked up one by one (item?id=…); without them their sales
would have no name. (ლისი: 21 products, saved 2026-11-28.)
Every product is also linked to the shared product list (`products`, see products.py), so the
same product can be added up over branches that name it differently.

Usage:
  uv run python src/tema_ops/incopos/load_incopos.py                                 (every saved day)
  uv run python src/tema_ops/incopos/load_incopos.py --from 2026-11-16 --to 2026-11-17
  uv run python src/tema_ops/incopos/load_incopos.py --branch lisi
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

from tema_ops.incopos.branches import BRANCHES, DATA_DIR
from tema_ops.incopos.products import product_name

load_dotenv()

UPSERT_LOCATION = """
INSERT INTO incopos.locations (branch_id, id, name) VALUES (%s, %s, %s)
ON CONFLICT (branch_id) DO UPDATE SET id = EXCLUDED.id, name = EXCLUDED.name
"""

UPSERT_ITEM = """
INSERT INTO incopos.items (branch_id, id, name, group_id, measure_unit, retail_price, deleted, raw)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (branch_id, id) DO UPDATE SET
    name = EXCLUDED.name, group_id = EXCLUDED.group_id, measure_unit = EXCLUDED.measure_unit,
    retail_price = EXCLUDED.retail_price, deleted = EXCLUDED.deleted, raw = EXCLUDED.raw
"""

UPSERT_GROUP = """
INSERT INTO incopos.item_groups (branch_id, id, name, code) VALUES (%s, %s, %s, %s)
ON CONFLICT (branch_id, id) DO UPDATE SET name = EXCLUDED.name, code = EXCLUDED.code
"""

# A shared product is added only if its name is new (so the id counter doesn't run on every night)
ADD_PRODUCT = """
INSERT INTO products (name) SELECT %(name)s WHERE NOT EXISTS (SELECT 1 FROM products WHERE name = %(name)s)
ON CONFLICT (name) DO NOTHING
"""

LINK_PRODUCT = """
UPDATE incopos.items SET product_id = (SELECT id FROM products WHERE name = %s)
WHERE branch_id = %s AND id = %s
"""

INSERT_SALE = """
INSERT INTO incopos.sales (branch_id, id, paid_at, raw) VALUES (%s, %s, %s, %s)
"""

INSERT_LINE = """
INSERT INTO incopos.sale_lines (branch_id, sale_id, id, item_id, quantity, price, cost, discount)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

INSERT_PAYMENT = """
INSERT INTO incopos.payments (branch_id, sale_id, id, type_id, amount, created_at)
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


def load_reference(cur, branch_id: int, folder: Path) -> int:
    """The branch's shop, product groups and products. Always replaced with the latest download.
    Returns the shop's IncoPOS location Id."""
    locations = read_json(folder / "locations.json")
    if len(locations) != 1:
        raise SystemExit(f"{folder}/locations.json: expected 1 shop, got {len(locations)}")
    shop = locations[0]
    cur.execute(UPSERT_LOCATION, (branch_id, shop["Id"], shop["Name"]))
    cur.executemany(UPSERT_GROUP, [(branch_id, g["Id"], g["Name"], g["Code"])
                                   for g in read_json(folder / "item_groups.json")])
    deleted = folder / "deleted_items.json"
    # The deleted ones first: if one is ever back in the product list, the current list wins
    items = (read_json(deleted) if deleted.exists() else []) + read_json(folder / "items.json")
    cur.executemany(UPSERT_ITEM, [(branch_id, i["Id"], i["Name"], i["GroupId"], i["MeasureUnit"],
                                   number(i["RetailPrice"]), i["Deleted"], Jsonb(i))
                                  for i in items])
    link_products(cur, branch_id, folder.name)
    return shop["Id"]


def link_products(cur, branch_id: int, branch: str) -> None:
    """Points every product of the branch (also older ones that are no longer in its files) to its
    shared product, adding the shared product if it's new."""
    items = cur.execute("SELECT id, name FROM incopos.items WHERE branch_id = %s", (branch_id,)).fetchall()
    shared = {item_id: product_name(branch, name) for item_id, name in items}
    cur.executemany(ADD_PRODUCT, [{"name": n} for n in sorted(set(shared.values()))])
    cur.executemany(LINK_PRODUCT, [(n, branch_id, item_id) for item_id, n in shared.items()])


def load_day(cur, branch_id: int, shop_id: int, path: Path) -> tuple[int, int]:
    """Loads one day file. Returns (receipts loaded, receipts skipped because they have no payment)."""
    receipts = {}
    for sale in read_json(path):
        if sale["LocationId"] != shop_id:  # one shop per account: anything else would mix shops up
            raise SystemExit(f"{path}: receipt {sale['Id']} is from shop {sale['LocationId']}, expected {shop_id}")
        receipts[sale["Id"]] = sale  # a repeated receipt just replaces its identical copy
    paid = [sale for sale in receipts.values() if sale.get("Payments")]

    # Remove the old copies first (their lines and payments go with them: ON DELETE CASCADE),
    # so a receipt that was corrected in IncoPOS doesn't keep old lines.
    cur.execute("DELETE FROM incopos.sales WHERE branch_id = %s AND id = ANY(%s)", (branch_id, list(receipts)))
    # A receipt's time = its first payment (2 payments = a split bill, paid at the same moment)
    cur.executemany(INSERT_SALE, [(branch_id, s["Id"], to_time(s["Payments"][0]["CreatedAt"]), Jsonb(s))
                                  for s in paid])
    cur.executemany(INSERT_LINE, [(branch_id, s["Id"], line["DetailId"], line["ItemId"],
                                   number(line["Quantity"]), number(line["Price"]),
                                   number(line["PriceIn"]), number(line["Discount"]))
                                  for s in paid for line in s["Details"]])
    cur.executemany(INSERT_PAYMENT, [(branch_id, s["Id"], pay["Id"], pay["TypeId"],
                                      number(pay["Amount"]), to_time(pay["CreatedAt"]))
                                     for s in paid for pay in s["Payments"]])
    return len(paid), len(receipts) - len(paid)


def main():
    parser = argparse.ArgumentParser(description="Load saved IncoPOS files into the database.")
    parser.add_argument("--from", dest="start", help="First day (YYYY-MM-DD). Default: every saved day")
    parser.add_argument("--to", dest="end", help="Last day (YYYY-MM-DD). Default: same as --from")
    parser.add_argument("--branch", choices=BRANCHES, help="Only this branch. Default: every branch")
    args = parser.parse_args()

    with psycopg.connect(os.environ["INCOPOS_DATABASE_URL"]) as conn, conn.cursor() as cur:
        for branch in [args.branch] if args.branch else BRANCHES:
            folder = DATA_DIR / branch
            if not (folder / "locations.json").exists():
                print(f"{branch}: nothing downloaded yet, skipped")
                continue
            row = cur.execute("SELECT id FROM branches WHERE name = %s", (BRANCHES[branch],)).fetchone()
            if row is None:
                raise SystemExit(f"Branch {BRANCHES[branch]} is not in the branches table")
            branch_id = row[0]

            paths = sorted(folder.glob("20*.json"))  # data/incopos/<branch>/<day>.json
            if args.start:
                end = args.end or args.start
                paths = [p for p in paths if args.start <= p.stem <= end]  # "2026-11-16" dates compare like text

            shop_id = load_reference(cur, branch_id, folder)
            total = skipped = 0
            for path in paths:
                count, no_payment = load_day(cur, branch_id, shop_id, path)
                total += count
                skipped += no_payment
                print(f"loaded {path}: {count} receipts" + (f" ({no_payment} with no payment skipped)" if no_payment else ""))
            conn.commit()  # one branch at a time
            print(f"{branch} done: {len(paths)} files, {total} receipts, {skipped} skipped (no payment)")


if __name__ == "__main__":
    main()
