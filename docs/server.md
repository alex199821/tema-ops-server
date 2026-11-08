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

## Check the daily update (cron)

Run on the server.

```bash
crontab -l                                                  # what is scheduled
tail -20 ~/tema-ops-server/logs/daily_update.log            # last daily update output
tail -5 ~/tema-ops-server/logs/token.log                    # last Wolt token renewals
journalctl -u cron --since today | grep daily_update        # proof cron started it (and when)
ls -l --time-style=+%H:%M ~/tema-ops-server/data/wolt/*/$(date -d yesterday +%F).json   # when yesterday's files were written
```

A good daily run ends with 3 `loaded <venue_id> <date>` lines, one per branch.

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
