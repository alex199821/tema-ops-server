"""Downloads the whole IncoPOS sales history of the branches that have their own key.

Raw files only, one per branch per day: data/incopos_backfill/<branch>/<day>.json.
They are kept apart from data/incopos/ on purpose: the nightly job loads everything in there
as location 2, and every branch's account has its own receipt numbers starting at 1.
The files go into the database once the tables know about branches.

Runs on the server in the background (you can log out; it keeps going):
  nohup ~/.local/bin/uv run python src/tema_ops/incopos/backfill.py >> logs/incopos_backfill.log 2>&1 &
Watch it:  tail -f logs/incopos_backfill.log
Safe to stop and start again: days that are already saved are skipped.
"""
import datetime
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

LOGIN_URL = "https://h2.incocloud.com/connect/api/access_token"
OUT_DIR = Path("data/incopos_backfill")

# Branch (= the end of its INCOPOS_APP_ID_<BRANCH> name in .env) → day of its receipt 1
BRANCHES = {
    "lisi": datetime.date(2024, 8, 25),
    "sanapiro": datetime.date(2025, 3, 13),
    "ivertubani": datetime.date(2026, 11, 2),
}
DAYS_AT_ONCE = 3          # per branch
GAP_SECONDS = 8           # at least this long between two requests, over all branches
PAUSE_ON_ERROR = 15 * 60  # after a timeout or server error (a block waits as long as IncoCloud says)
MAX_TRIES = 5             # per day, then skip it (a later run picks it up again)
TIMEOUT = 300             # a busy day takes 40-90 s

lock = threading.Lock()
paused_until = 0.0        # shared by all branches: the block is per IP address, not per key
next_start = 0.0


def log(message: str) -> None:
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def pause_everyone(reason: str, seconds: float = PAUSE_ON_ERROR) -> None:
    """Nobody sends anything until the pause is over. The block is per IP, so all branches stop."""
    global paused_until
    with lock:
        paused_until = max(paused_until, time.time() + seconds)
    log(f"{reason} → everyone waits {seconds / 60:.0f} min")


def blocked_for(response: httpx.Response) -> float:
    """How long IncoCloud says we are blocked (the retry-after header, in seconds), plus 1 minute."""
    try:
        return int(response.headers["retry-after"]) + 60
    except (KeyError, ValueError):
        return PAUSE_ON_ERROR


def wait_turn() -> None:
    """Waits while everyone is paused, then keeps requests GAP_SECONDS apart."""
    global next_start
    while True:
        with lock:
            now = time.time()
            if now >= paused_until and now >= next_start:
                next_start = now + GAP_SECONDS
                return
            wait = max(paused_until, next_start) - now
        time.sleep(min(wait, 30))


def save_json(path: Path, data) -> None:
    """Saves the API answer exactly as it came. Writes a .tmp first, so a stop never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


class Branch:
    """One branch's IncoCloud account. GET only: the other methods change live shop data."""

    def __init__(self, name: str, client: httpx.Client):
        self.name = name
        self.client = client
        self.login_lock = threading.Lock()
        self.server = self.token = None
        self.done = 0
        self.login()

    def login(self) -> None:
        with self.login_lock:
            data = self.get(LOGIN_URL, {
                "app_id": os.environ[f"INCOPOS_APP_ID_{self.name.upper()}"],
                "app_secret": os.environ[f"INCOPOS_APP_SECRET_{self.name.upper()}"],
            }, "login")
            if data is None:
                raise RuntimeError(f"[{self.name}] login failed, check its key in .env")
            self.server = data["ServerBaseUrl"].rstrip("/")
            self.token = data["Value"]

    def api(self, path: str, what: str, **params):
        return self.get(f"{self.server}/{path}", params, what, with_token=True)

    def get(self, url: str, params: dict, what: str, with_token: bool = False):
        """Returns the answer, or None after MAX_TRIES errors.
        Logs never show the URL: it holds the secret or the token."""
        tries = 0
        while tries < MAX_TRIES:
            wait_turn()
            send = {**params, "token": self.token} if with_token else params
            try:
                response = self.client.get(url, params=send)
            except httpx.HTTPError as e:  # timeout, dropped connection
                tries += 1
                pause_everyone(f"[{self.name}] {what}: {type(e).__name__}")
                continue
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:  # "Your IP address is temporarily blocked"
                pause_everyone(f"[{self.name}] {what}: blocked (429)", blocked_for(response))
                continue  # being blocked doesn't use up a try
            if response.status_code >= 500:
                pause_everyone(f"[{self.name}] {what}: error {response.status_code}")
                continue
            tries += 1
            log(f"[{self.name}] {what}: error {response.status_code} {response.text[:200]}")
            if response.status_code == 401 and with_token:
                self.login()  # the token ran out
        return None


def download_day(branch: Branch, day: datetime.date, total: int) -> None:
    path = OUT_DIR / branch.name / f"{day}.json"
    if path.exists():
        return
    start = time.time()
    sales = branch.api("sale", str(day), from_date=f"{day}T00:00:00", to_date=f"{day}T23:59:59",
                       load_payments=True)
    if sales is None:
        log(f"[{branch.name}] {day}: SKIPPED after {MAX_TRIES} errors (run again later)")
        return
    save_json(path, sales)
    with lock:
        branch.done += 1
        done = branch.done
    log(f"[{branch.name}] {day}: {len(sales)} sales, {time.time() - start:.0f} s ({done}/{total})")


def run_branch(name: str, first_day: datetime.date, client: httpx.Client) -> None:
    branch = Branch(name, client)
    # Products, groups and shops of this account (its numbers are its own)
    for path, what, params in (("item", "items", {"include_availability": False}),
                               ("item_group", "item_groups", {}),
                               ("location", "locations", {})):
        data = branch.api(path, what, **params)
        if data is not None:
            save_json(OUT_DIR / name / f"{what}.json", data)

    newest = datetime.date.today() - datetime.timedelta(days=1)
    days = [newest - datetime.timedelta(days=i) for i in range((newest - first_day).days + 1)]  # newest first
    missing = [d for d in days if not (OUT_DIR / name / f"{d}.json").exists()]
    log(f"[{name}] {len(missing)} of {len(days)} days to download ({first_day} → {newest})")
    with ThreadPoolExecutor(DAYS_AT_ONCE) as pool:
        list(pool.map(lambda d: download_day(branch, d, len(missing)), missing))
    log(f"[{name}] FINISHED")


def main():
    log("Backfill started")
    with httpx.Client(timeout=TIMEOUT) as client, ThreadPoolExecutor(len(BRANCHES)) as pool:
        jobs = [pool.submit(run_branch, name, first, client) for name, first in BRANCHES.items()]
        for job in jobs:
            job.result()  # shows the error if a branch stopped
    log("Backfill done")


if __name__ == "__main__":
    main()
