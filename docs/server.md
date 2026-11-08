# Server

## What it is

| | |
|---|---|
| Provider | Google Cloud |
| Project | `tema-ops-prod` (billing: free-trial account, credits until Feb 2027) |
| VM name | `tema-ops-server` |
| Zone | `europe-west3-a` (Frankfurt) |
| Machine | `e2-small` (2 vCPU, 2 GB RAM), Ubuntu 24.04, 30 GB disk |
| External IP | (see `gcloud compute instances list --project=tema-ops-prod`; not static yet, may change if the VM is stopped) |
| Timezone | `Asia/Tbilisi` |

## Connect

From this Mac:

```bash
gcloud compute ssh tema-ops-server --zone=europe-west3-a --project=tema-ops-prod
```

Type `exit` to leave the server.

## The SSH key

- Created automatically by `gcloud` the first time you connected.
- Private key: `~/.ssh/google_compute_engine` (on this Mac). **Never share it or put it in git.**
- Public key: `~/.ssh/google_compute_engine.pub`. Google copied it to the project, which is what lets this Mac in.
- Protected by the passphrase you set.

## Connect from another computer

You don't copy the key. On the new computer:

1. Install the Google Cloud CLI: https://cloud.google.com/sdk/docs/install
2. `gcloud auth login` (sign in with the Google account that owns the project)
3. Run the same `gcloud compute ssh ...` command. It creates a new key for that computer.

## Get the Wolt Excel report on your Desktop

Run on the Mac (not on the server). It builds the report on the server and copies it to `~/Desktop/wolt_report.xlsx`:

```bash
gcloud compute ssh tema-ops-server --zone=europe-west3-a --project=tema-ops-prod --command="cd ~/tema-ops-server && ~/.local/bin/uv run python src/tema_ops/wolt/excel_report.py" && gcloud compute scp tema-ops-server:~/tema-ops-server/reports/wolt_report.xlsx ~/Desktop/ --zone=europe-west3-a --project=tema-ops-prod
```

## Scheduled jobs (cron)

| When | What | Script | Log |
|---|---|---|---|
| Every day 12:00 | Fetch yesterday's Wolt orders for all branches → DB | `wolt/daily_update.py` | `logs/daily_update.log` |
| Every 4 h (+ random 0–60 min) | Renew the Wolt token so the chain stays alive | `wolt/wolt_login.py` | `logs/token.log` |
| 1st and 16th, 13:00 | Build the Excel report and email it to `WOLT_REPORT_TO` | `wolt/send_report.py` | `logs/send_report.log` |

Every job runs through `src/tema_ops/run_job.py` (the supervisor). It:

- puts a timestamp on every log line, plus `START`, `DONE` or `FAILED (exit N)` lines,
- emails `ALERT_TO` with the last 60 output lines if the job fails (non-zero exit code).

No alert email = everything worked. If the whole server is down, nothing runs and no email is sent.

## Email settings (server `.env`, not in git)

| Variable | What |
|---|---|
| `SMTP_USER` | bot Gmail that sends everything (`tema.opsai@gmail.com`) |
| `SMTP_PASSWORD` | that Gmail's app password |
| `ALERT_TO` | who gets "something broke" emails |
| `WOLT_REPORT_TO` | who gets the Wolt report (several emails: comma-separated) |

## Check the jobs

Run on the server.

```bash
crontab -l                                                  # what is scheduled
tail -20 ~/tema-ops-server/logs/daily_update.log            # last daily update output
tail -5 ~/tema-ops-server/logs/token.log                    # last Wolt token renewals
tail -5 ~/tema-ops-server/logs/send_report.log              # last report emails
journalctl -u cron --since today | grep run_job             # proof cron started the jobs (and when)
```

A good daily run ends with 3 `loaded <venue_id> <date>` lines (one per branch), then `DONE`.

Test the alert email (fails on purpose, no Wolt involved):

```bash
cd ~/tema-ops-server && uv run python src/tema_ops/run_job.py python -c "1/0"
```

Redo one day by hand (on the server):

```bash
cd ~/tema-ops-server && uv run python src/tema_ops/wolt/daily_update.py 2026-11-07
```

## Start / stop (to save credits)

```bash
gcloud compute instances stop tema-ops-server --zone=europe-west3-a --project=tema-ops-prod
gcloud compute instances start tema-ops-server --zone=europe-west3-a --project=tema-ops-prod
```

While stopped, the daily Wolt update does not run. If it stays stopped for long, the Wolt token chain can die.

## Lost access?

As long as you can log into the Google account, you can always get back in: run the `gcloud compute ssh` command again and it sets up a fresh key.
