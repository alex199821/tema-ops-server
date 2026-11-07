import fcntl
import json
import random
import time
from datetime import datetime
from pathlib import Path

import httpx

TOKEN_FILE = Path("auth/wolt.json")
TOKEN_URL = "https://authentication.wolt.com/v1/wauth2/access_token"


def refresh():
    with open("auth/refresh.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # if another script is renewing, wait here
        saved = json.loads(TOKEN_FILE.read_text())
        response = httpx.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": saved["refresh_token"]})
        with open("auth/refresh_log.csv", "a") as log:
            log.write(f"{datetime.now().isoformat(timespec='seconds')},{response.status_code}\n")
        response.raise_for_status()
        tokens = response.json()
        TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
        return tokens


if __name__ == "__main__":
    refresh()
    print(datetime.now().strftime("%H:%M"), "token renewed")