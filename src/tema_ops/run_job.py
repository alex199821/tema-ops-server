"""Runs any command, puts a timestamp on every output line,
and emails an alert if it fails.
Usage: run_job.py <command...>
"""
import os
import subprocess
import sys
from collections import deque
from datetime import datetime

from tema_ops.notify import alert


def log(line):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {line}", flush=True)


cmd = sys.argv[1:]
last_lines = deque(maxlen=60)  # remember only the last 60 lines for the email

log(f"START {' '.join(cmd)}")
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                        env={**os.environ, "PYTHONUNBUFFERED": "1"})  # send lines right away
for line in proc.stdout:
    line = line.rstrip("\n")
    log(line)
    last_lines.append(line)

code = proc.wait()
if code == 0:
    log("DONE")
else:
    log(f"FAILED (exit {code})")
    alert(f"FAILED: {' '.join(cmd)} (exit {code})", "\n".join(last_lines))
sys.exit(code)