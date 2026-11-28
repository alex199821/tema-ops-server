"""Downloads IncoPOS sales from IncoCloud: one file per branch per day, in data/incopos/<branch>/.

Every branch has its own key (see branches.py). For each branch it also saves its products
(items.json), product groups (item_groups.json) and shop (locations.json).
One branch failing doesn't stop the others; the script still ends with an error, so the
nightly job's alert email goes out.

Usage:
  uv run python src/tema_ops/incopos/fetch_incopos.py --from 2026-11-26                  (every branch)
  uv run python src/tema_ops/incopos/fetch_incopos.py --from 2026-11-26 --to 2026-11-27 --branch lisi
"""
import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from tema_ops.incopos.branches import BRANCHES, DATA_DIR

load_dotenv()

# Where every IncoCloud account logs in. The answer says which server
# this account's data lives on (ServerBaseUrl), so we don't configure it.
LOGIN_URL = "https://h2.incocloud.com/connect/api/access_token"
GAP_SECONDS = 20     # between two requests: IncoCloud blocks the IP after ~25 requests in ~3 minutes
MAX_WAIT = 15 * 60   # never wait more than 15 minutes for a block to end
last_request = 0.0


class FetchError(Exception):
    pass


def check(response: httpx.Response, name: str):
    """Any error stops this branch. Shows only the name: the URL contains the secret or the token."""
    if response.status_code != 200:
        raise FetchError(f"Error {response.status_code} on {name}")
    return response.json()


def send(client: httpx.Client, url: str, params: dict, name: str):
    """GET, at least GAP_SECONDS after the last one. On 429 (blocked) waits as long as IncoCloud asks."""
    global last_request
    for attempt in range(3):
        time.sleep(max(0.0, last_request + GAP_SECONDS - time.time()))
        last_request = time.time()
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
    raise FetchError(f"Error 429 on {name}: still blocked, try again later")


class IncoCloud:
    """Read-only client for one branch's account: logs in once, then sends every GET to its server."""

    def __init__(self, client: httpx.Client, branch: str):
        self.client = client
        data = send(client, LOGIN_URL, {
            "app_id": os.environ[f"INCOPOS_APP_ID_{branch.upper()}"],
            "app_secret": os.environ[f"INCOPOS_APP_SECRET_{branch.upper()}"],
        }, f"{branch} access_token")
        self.server_url = data["ServerBaseUrl"].rstrip("/")
        self.token = data["Value"]

    def get(self, path: str, **params):
        """GET only: the other methods change live shop data."""
        return send(self.client, f"{self.server_url}/{path}",
                    {"token": self.token, **params}, path)


def save_json(path: Path, data) -> None:
    """Saves the API answer exactly as it came. Writes a .tmp first, so a stop never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def fetch_branch(client: httpx.Client, branch: str, days: list, skip_existing: bool) -> None:
    folder = DATA_DIR / branch
    inco = IncoCloud(client, branch)
    locations = inco.get("location")
    if len(locations) != 1:  # the loader counts on one shop per account
        raise FetchError(f"{branch}: expected 1 shop in its IncoCloud account, got {len(locations)}")
    shop = locations[0]
    save_json(folder / "locations.json", locations)
    items = inco.get("item", include_availability=False)
    save_json(folder / "items.json", items)
    save_json(folder / "item_groups.json", inco.get("item_group"))
    print(f"{branch}: {len(items)} products")

    for day in days:
        path = folder / f"{day}.json"
        if skip_existing and path.exists():
            continue
        print(f"Downloading {branch} {day} (takes ~40-90 s)...")
        sales = inco.get("sale", location_id=shop["Id"],
                         from_date=f"{day}T00:00:00", to_date=f"{day}T23:59:59",
                         load_payments=True)
        save_json(path, sales)
        print(f"  {len(sales)} sales")


def main():
    parser = argparse.ArgumentParser(description="Download IncoPOS sales: one file per branch per day.")
    parser.add_argument("--from", dest="start", required=True, help="First day (YYYY-MM-DD)")
    parser.add_argument("--to", dest="end", help="Last day (YYYY-MM-DD). Default: same as --from")
    parser.add_argument("--branch", choices=BRANCHES, help="Only this branch. Default: every branch with a key")
    parser.add_argument("--skip-existing", action="store_true", help="Skip days that are already saved")
    args = parser.parse_args()
    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end) if args.end else start
    days = [start + datetime.timedelta(days=i) for i in range((end - start).days + 1)]

    failed = []
    with httpx.Client(timeout=300.0) as client:  # a busy day takes 40-90 s
        for branch in [args.branch] if args.branch else BRANCHES:
            if f"INCOPOS_APP_ID_{branch.upper()}" not in os.environ:
                print(f"{branch}: no key in .env, skipped")
                continue
            try:
                fetch_branch(client, branch, days, args.skip_existing)
            except (FetchError, httpx.HTTPError) as e:  # an httpx error's text can hold the URL with the secret
                print(f"{branch} FAILED: {e if isinstance(e, FetchError) else type(e).__name__}", file=sys.stderr)
                failed.append(branch)
    if failed:
        sys.exit(f"Not downloaded: {', '.join(failed)}")


if __name__ == "__main__":
    main()
