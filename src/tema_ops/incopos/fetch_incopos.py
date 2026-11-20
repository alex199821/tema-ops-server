import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# Where every IncoCloud account logs in. The answer says which server
# this account's data lives on (ServerBaseUrl), so we don't configure it.
LOGIN_URL = "https://h2.incocloud.com/connect/api/access_token"
OUT_DIR = Path("data/incopos")
PAUSE_SECONDS = 30   # between days, so a long download doesn't get us blocked
MAX_WAIT = 15 * 60   # never wait more than 15 minutes for a block to end


def check(response: httpx.Response, name: str):
    """Stops on any error. Prints only the name: the URL contains the secret or the token."""
    if response.status_code != 200:
        print(f"Error {response.status_code} on {name}", file=sys.stderr)
        sys.exit(1)
    return response.json()


def send(client: httpx.Client, url: str, params: dict, name: str):
    """GET with a polite retry: on 429 (too many requests) waits as long as IncoCloud asks."""
    for attempt in range(3):
        response = client.get(url, params=params)
        if response.status_code != 429:
            return check(response, name)
        try:
            wait = int(response.headers.get("retry-after", "60"))
        except ValueError:
            wait = 60
        if wait > MAX_WAIT:
            break
        print(f"IncoCloud: too many requests, waiting {wait} s before trying {name} again", file=sys.stderr)
        time.sleep(wait + 5)
    print(f"Error 429 on {name}: still blocked, try again later", file=sys.stderr)
    sys.exit(1)


class IncoCloud:
    """Read-only IncoCloud client: logs in once, then sends every GET to the account's server."""

    def __init__(self, client: httpx.Client):
        self.client = client
        data = send(client, LOGIN_URL, {
            "app_id": os.environ["INCOPOS_APP_ID"],
            "app_secret": os.environ["INCOPOS_APP_SECRET"],
        }, "access_token")
        self.server_url = data["ServerBaseUrl"].rstrip("/")
        self.token = data["Value"]

    def get(self, path: str, **params):
        """GET only: the other methods change live shop data."""
        return send(self.client, f"{self.server_url}/{path}",
                    {"token": self.token, **params}, path)


def save_json(path: Path, data) -> None:
    """Saves the API answer exactly as it came."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Download IncoPOS sales: one file per branch per day.")
    parser.add_argument("--from", dest="start", required=True, help="First day (YYYY-MM-DD)")
    parser.add_argument("--to", dest="end", help="Last day (YYYY-MM-DD). Default: same as --from")
    parser.add_argument("--skip-existing", action="store_true", help="Skip days that are already saved")
    args = parser.parse_args()
    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end) if args.end else start

    with httpx.Client(timeout=120.0) as client:  # the sale call takes ~40 s
        inco = IncoCloud(client)

        items = inco.get("item", include_availability=False)
        save_json(OUT_DIR / "items.json", items)
        print(f"Items: {len(items)}")
        locations = inco.get("location")
        save_json(OUT_DIR / "locations.json", locations)
    
        day = start
        while day <= end:
            for loc in locations:
                path = OUT_DIR / str(loc["Id"]) / f"{day}.json"
                if args.skip_existing and path.exists():
                    continue
                print(f"Downloading {loc['Name']} {day} (takes ~40 s)...")
                sales = inco.get("sale", location_id=loc["Id"],
                                 from_date=f"{day}T00:00:00", to_date=f"{day}T23:59:59",
                                 load_payments=True)
                save_json(path, sales)
                print(f"  {len(sales)} sales")
                time.sleep(PAUSE_SECONDS)
            day += datetime.timedelta(days=1)


if __name__ == "__main__":
    main()