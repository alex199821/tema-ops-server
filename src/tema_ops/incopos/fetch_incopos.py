import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# Where every IncoCloud account logs in. The answer says which server
# this account's data lives on (ServerBaseUrl), so we don't configure it.
LOGIN_URL = "https://h2.incocloud.com/connect/api/access_token"
OUT_DIR = Path("data/incopos")


def check(response: httpx.Response, name: str):
    """Stops on any error. Prints only the name: the URL contains the secret or the token."""
    if response.status_code != 200:
        print(f"Error {response.status_code} on {name}", file=sys.stderr)
        sys.exit(1)
    return response.json()


class IncoCloud:
    """Read-only IncoCloud client: logs in once, then sends every GET to the account's server."""

    def __init__(self, client: httpx.Client):
        self.client = client
        data = check(client.get(LOGIN_URL, params={
            "app_id": os.environ["INCOPOS_APP_ID"],
            "app_secret": os.environ["INCOPOS_APP_SECRET"],
        }), "access_token")
        self.server_url = data["ServerBaseUrl"].rstrip("/")
        self.token = data["Value"]

    def get(self, path: str, **params):
        """GET only: the other methods change live shop data."""
        response = self.client.get(f"{self.server_url}/{path}",
                                   params={"token": self.token, **params})
        return check(response, path)


def save_json(path: Path, data) -> None:
    """Saves the API answer exactly as it came."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Download one day of IncoPOS sales.")
    parser.add_argument("--date", required=True, help="Day to download (YYYY-MM-DD)")
    args = parser.parse_args()
    day = datetime.date.fromisoformat(args.date)  # stops right away on a typo like 2026-13-01

    with httpx.Client(timeout=120.0) as client:  # the sale call took ~40 s
        inco = IncoCloud(client)

        items = inco.get("item", include_availability=False)
        save_json(OUT_DIR / "items.json", items)
        print(f"Items: {len(items)}")

        for loc in inco.get("location"):
            print(f"Downloading {loc['Name']} {day} (takes ~40 s)...")
            sales = inco.get("sale", location_id=loc["Id"],
                             from_date=f"{day}T00:00:00", to_date=f"{day}T23:59:59",
                             load_payments=True)
            save_json(OUT_DIR / str(loc["Id"]) / f"{day}.json", sales)
            print(f"{loc['Name']}: {len(sales)} sales")


if __name__ == "__main__":
    main()