import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

load_dotenv()

UPSERT_ORDER = """
INSERT INTO wolt.orders (purchase_id, venue_id, order_number, status, received_at, delivered_at,
                         total_gross, total_net, is_cash, rating, review_comment, raw)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (purchase_id) DO UPDATE SET
    status = EXCLUDED.status, delivered_at = EXCLUDED.delivered_at,
    total_gross = EXCLUDED.total_gross, total_net = EXCLUDED.total_net,
    rating = EXCLUDED.rating, review_comment = EXCLUDED.review_comment, raw = EXCLUDED.raw
"""


def to_time(value):
    return datetime.fromisoformat(value) if value else None


def load_file(cur, path):
    for o in json.loads(path.read_text()):
        cur.execute(UPSERT_ORDER, (
            o["purchase_id"], o["venue_id"], o["order_number"], o["status"],
            to_time(o["time_received_local"]), to_time(o["time_delivered_local"]),
            Decimal(o["total_gross"]), Decimal(o["total_net"]),
            o["is_cash"], o["rating"], o["review_comment"], Jsonb(o),
        ))
        cur.execute("DELETE FROM wolt.order_items WHERE purchase_id = %s", (o["purchase_id"],))
        for item in o["items"]:
            cur.execute("INSERT INTO wolt.order_items VALUES (%s, %s, %s, %s, %s, %s)", (
                o["purchase_id"], item["row"], item["name"], item["count"],
                Decimal(item["final_gross"]), Decimal(item["final_net"]),
            ))


if __name__ == "__main__":
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            for path in sorted(Path("data/wolt").glob("*/*.json")):
                load_file(cur, path)
                print("loaded", path)