import fcntl
import argparse
import datetime
import json
import os
import sys
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import httpx

from tema_ops.wolt.wolt_login import refresh

# ----- CONFIG & GLOBALS -----
BASE_URL = "https://merchant-gateway.wolt.com/merchant-analytics-api/v2"

# Shifts
# Day shift: 09:00 - 20:59
# Night shift: 21:00 - 08:59
def shift_of(iso_time_str: str) -> tuple[datetime.date, str]:
    """Returns the (shift_date, 'day'|'night') for a given local timestamp."""
    dt = datetime.datetime.fromisoformat(iso_time_str)
    shift_start = dt - datetime.timedelta(hours=9)
    shift_date = shift_start.date()
    shift_type = "day" if 9 <= dt.hour < 21 else "night"
    return shift_date, shift_type


def format_money(val: Decimal) -> str:
    """Formats a decimal value to a string with 2 decimal places."""
    return str(val.quantize(Decimal("0.00")))


def api_request(client: httpx.Client, url: str, params: dict = None) -> dict:
    """Makes an HTTP GET request with retries and specific error handling."""
    for attempt in range(12):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError:
            time.sleep(2 ** attempt)
            continue
        
        if response.status_code == 401:
            token = refresh()["access_token"]
            client.headers["Authorization"] = f"Bearer {token}"
            continue
            
        if response.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)  # Backoff: 1s, 2s, 4s...
            continue
            
        if response.status_code >= 400:
            # We must never print headers/auth details here
            print(f"Error {response.status_code} on {response.url}", file=sys.stderr)
            sys.exit(1)
            
        # Parse JSON using Decimal for floats
        return json.loads(response.text, parse_float=Decimal)
    
    print(f"Failed after retries: {url}", file=sys.stderr)
    sys.exit(1)


def clean_order(api1_order: dict, api2_order: dict) -> dict:
    """
    Cleans the order merging API 1 and API 2 data.
    Removes personal data completely and structures to requirements.
    """
    purchase_id = api2_order["purchaseId"]
    
    # Validation checks (Warnings only)
    api1_gross = api1_order["pricing"]["finalPrice"]["gross"]
    api2_gross = api2_order["pricing"]["finalPrice"]["gross"]
    if api1_gross != api2_gross:
        print(f"Warning: Gross mismatch for {purchase_id} -> API1: {api1_gross}, API2: {api2_gross}", file=sys.stderr)

    status = api2_order["status"]
    if status not in ("DELIVERED", "REJECTED"):
        print(f"Warning: Unknown status '{status}' for {purchase_id}", file=sys.stderr)

    basket_gross = api2_order["pricing"]["breakdown"]["basket"]["finalPrice"]["gross"]
    items_gross_sum = sum(
        (item["pricing"]["finalPrice"]["gross"] for item in api2_order["basket"]["items"]), 
        Decimal("0.00")
    )
    if items_gross_sum != basket_gross:
        print(f"Warning: Item sum {items_gross_sum} != Basket gross {basket_gross} for {purchase_id}", file=sys.stderr)

    # Clean Items
    cleaned_items = []
    for item in api2_order["basket"]["items"]:
        names = item["product"]["names"]
        # ka entry or first available
        name_val = next((n["value"] for n in names if n["lang"] == "ka"), names[0]["value"] if names else "")
        
        cleaned_items.append({
            "item_id": item["itemId"],
            "row": item["rowNumber"],
            "name": name_val,
            "sku": item["product"].get("merchantSku"),
            "count": item["count"],
            "final_gross": format_money(item["pricing"]["finalPrice"]["gross"]),
            "final_net": format_money(item["pricing"]["finalPrice"]["net"]),
            "options": item.get("options", [])
        })

    # Optional nested keys
    review_data = api2_order.get("review") or {}
    delivery_data = api2_order.get("delivery") or {}

    return {
        "purchase_id": purchase_id,
        "venue_id": api2_order["venueId"],
        "order_number": api2_order["orderNumber"],
        "order_type": api2_order["orderType"],
        "status": status,
        "time_received_local": api2_order["timeReceived"],
        "time_delivered_local": api2_order.get("timeDelivered"),
        "time_preorder_local": api2_order.get("timePreorder"),
        "rejection": api2_order.get("rejection"),
        "currency": api2_order["currency"],
        "total_gross": format_money(api2_order["pricing"]["finalPrice"]["gross"]),
        "total_net": format_money(api2_order["pricing"]["finalPrice"]["net"]),
        "is_cash": api2_order.get("paymentMethod", {}).get("isCashPayment", False),
        "delivery_method": delivery_data.get("method"),
        "delivery_provider": delivery_data.get("providerType"),
        "rating": review_data.get("rating"),
        "review_attributions": review_data.get("attributions", []),
        "review_comment": review_data.get("comment"),
        "items": cleaned_items,
        "missing_items": api2_order.get("basket", {}).get("missingItems", []),
        "substitutions": api2_order.get("basket", {}).get("substitutions", {})
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch Wolt venue orders.")
    parser.add_argument("--venue", required=True, help="Venue ID")
    parser.add_argument("--from", dest="from_date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip days that are already saved")
    args = parser.parse_args()

    token = refresh()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    start_dt = datetime.date.fromisoformat(args.from_date)
    end_dt = datetime.date.fromisoformat(args.to_date)

    out_dir = Path(f"data/wolt/{args.venue}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Shift Tracking structure
    # {(date, type): {'revenue': Decimal, 'statuses': dict, 'ratings': list}}
    shift_stats = defaultdict(lambda: {
        "revenue": Decimal("0.00"), 
        "statuses": defaultdict(int),
        "ratings": []
    })

    with httpx.Client(headers=headers, timeout=20.0) as client:
        current_dt = start_dt
        while current_dt <= end_dt:
            day_str = current_dt.isoformat()
            next_day_str = (current_dt + datetime.timedelta(days=1)).isoformat()
            if args.skip_existing and (out_dir / f"{day_str}.json").exists():
                print(f"Skipping {day_str} (already saved)")
                current_dt += datetime.timedelta(days=1)
                continue
            print(f"Fetching {args.venue} {day_str}...")
            
            # 1. Fetch API 1 paginated list
            api1_orders_map = {}
            cursor = None
            limit = 40
            
            while True:
                params = {
                    "start_date": day_str,
                    "end_date": next_day_str,
                    "limit": limit,
                }
                if cursor:
                    params["cursor"] = cursor

                url = f"{BASE_URL}/venues/{args.venue}/purchases"
                resp_data = api_request(client, url, params)
                
                purchases = resp_data.get("data", {}).get("purchases", [])
                
                # Cursor progress guard
                new_count = 0
                for p in purchases:
                    pid = p["purchaseId"]
                    if pid not in api1_orders_map:
                        api1_orders_map[pid] = p
                        new_count += 1
                        
                if cursor and new_count == 0 and purchases:
                    print("Cursor parameter not accepted (stuck in loop). Stopping.", file=sys.stderr)
                    sys.exit(1)

                cursor = resp_data.get("metadata", {}).get("pagination", {}).get("next")
                if not cursor:
                    break
                    
                time.sleep(1)

            # 2. Fetch API 2 for each purchaseId and clean
            daily_results = []
            
            for pid, api1_order in api1_orders_map.items():
                time.sleep(1) # Gentle fetching
                url2 = f"{BASE_URL}/venues/{args.venue}/purchases/{pid}"
                api2_order = api_request(client, url2)
                
                cleaned = clean_order(api1_order, api2_order)
                daily_results.append(cleaned)
                
                # 3. Calculate Shift Stats
                s_date, s_type = shift_of(cleaned["time_received_local"])
                shift_key = (s_date, s_type)
                
                if cleaned["status"] == "DELIVERED":
                    shift_stats[shift_key]["revenue"] += Decimal(cleaned["total_gross"])
                else:
                    shift_stats[shift_key]["statuses"][cleaned["status"]] += 1
                
                if cleaned["rating"] is not None:
                    shift_stats[shift_key]["ratings"].append(cleaned["rating"])

            # Save the JSON for the day
            day_file = out_dir / f"{day_str}.json"
            with open(day_file, "w", encoding="utf-8") as f:
                json.dump(daily_results, f, ensure_ascii=False, indent=2, default=str)

            current_dt += datetime.timedelta(days=1)

    # 4. Print Shift Totals
    print("\n--- Shift Totals ---")
    print(f"Note: The night before {args.from_date} and the night of {args.to_date} are incomplete.\n")
    
    for (s_date, s_type) in sorted(shift_stats.keys()):
        stats = shift_stats[(s_date, s_type)]
        statuses_str = ", ".join(f"{count} {st}" for st, count in stats["statuses"].items())
        statuses_display = f" (Excluded: {statuses_str})" if statuses_str else ""
        ratings_display = f" Ratings: {sorted(stats['ratings'])}" if stats['ratings'] else " Ratings: None"
        
        print(f"{s_date} {s_type.title()}: {format_money(stats['revenue'])} GEL{statuses_display} |{ratings_display}")


if __name__ == "__main__":
    main()