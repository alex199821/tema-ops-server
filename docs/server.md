# Server

## What it is

| | |
|---|---|
| Provider | Google Cloud |
| Project | `tema-ops-prod` (billing: free-trial account, credits until Feb 2027) |
| VM name | `tema-ops-server` |
| Zone | `europe-west3-a` (Frankfurt) |
| Machine | `e2-small` (2 vCPU, 2 GB RAM), Ubuntu 24.04, 30 GB disk |
| External IP | static, reserved as `tema-ops-ip` (region `europe-west3`). See it with `gcloud compute addresses list --project=tema-ops-prod`. Kept out of git while the repo is public. |
| Timezone | `Asia/Tbilisi` |
| Google account the VM runs as | `tema-ops-vm` (service account). It may only use Vertex AI (Gemini). See "The AI on the server". |

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
| Every day 12:30 | Back up the whole database to Cloud Storage (see "Backups") | `scripts/backup_db.sh` | `logs/backup_db.log` |
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

## Database users

Created by `db/migrations/003_roles.sql`. Passwords are **not** in git; they are set by hand.

| User | Can do | Used by | `.env` variable |
|---|---|---|---|
| `ops` | everything (owner) | migrations only (`docker compose exec ... psql -U ops`) | none |
| `wolt_writer` | read/write rows in `wolt.*`, read `branches` | all current scripts (daily update, report) | `DATABASE_URL` |
| `ai_reader` | read only, queries stopped after 10 s | the AI sandbox | `AI_DATABASE_URL` |

Tables added later get the same rights automatically, so `ai_reader` can read every new table too. For sensitive tables (salaries etc.), revoke it: `REVOKE SELECT ON <table> FROM ai_reader;`

**On a new server (or new Mac DB), in this order:**

1. Run the migrations (`./scripts/setup_server.sh` does it). This creates the users without passwords.
2. Make two passwords: `openssl rand -hex 16; openssl rand -hex 16` (hex, so they are safe inside a URL).
3. Set them in the DB:

   ```bash
   sudo docker compose exec db psql -U ops -d ops
   ```

   then type `\password wolt_writer` (paste the 1st password twice), `\password ai_reader` (paste the 2nd twice), and `\q`. Nothing shows while you paste; that's normal.
4. Only now put them into `.env`:

   ```
   DATABASE_URL=postgresql://wolt_writer:<1st password>@localhost:5432/ops
   AI_DATABASE_URL=postgresql://ai_reader:<2nd password>@localhost:5432/ops
   ```

If a script says `password authentication failed for user "wolt_writer"`, step 3 was skipped or the password in the DB doesn't match `.env`. Redo step 3 with the password from `.env` (`grep DATABASE_URL .env`).

Check that `ai_reader` really is read-only (prints the order count, then must fail with `read-only transaction`):

```bash
uv run python -c "import os, psycopg, dotenv; dotenv.load_dotenv(); c = psycopg.connect(os.environ['AI_DATABASE_URL']); print(c.execute('SELECT count(*) FROM wolt.orders').fetchone()); c.execute('DELETE FROM wolt.orders')"
```

## Backups

Every day at 12:30, right after the Wolt load, `scripts/backup_db.sh` saves a full copy of the
database (`pg_dump`, compressed, about 1 MB) to the Google Cloud Storage bucket
`gs://tema-ops-prod-db-backups` (Frankfurt). Each file is a complete copy, e.g.
`ops_2026-11-10_1230.dump`, not just that day's changes.

- **Kept 30 days.** The bucket deletes older files by itself (lifecycle rule). A deleted file
  can still be recovered for 7 more days (Google's "soft delete").
- **The server can add and read backups, but not delete or overwrite them** (roles
  `storage.objectCreator` + `storage.objectViewer` for `tema-ops-vm`). Someone who broke into
  the server couldn't destroy the backups.
- **A failed backup sends an alert email**, because it runs through `run_job.py` like every job.
- Code, `.env`, `auth/wolt.json` and the crontab are **not** in the backup. Code is in git; the
  rest is listed in "Moving to a new server".

**See the backups** (on the server or the Mac):

```bash
gcloud storage ls -l gs://tema-ops-prod-db-backups/
```

**Run a backup by hand** (on the server):

```bash
cd ~/tema-ops-server && uv run python src/tema_ops/run_job.py scripts/backup_db.sh
```

**Restore** (on the server, e.g. after a broken disk or bad data). This **replaces** the
database's contents with the backup, so stop and think first:

1. Pick a file from the list above and download it:

   ```bash
   gcloud storage cp gs://tema-ops-prod-db-backups/<file>.dump /tmp/
   ```

2. Load it. `--clean --if-exists` drops each table first, then recreates it from the backup:

   ```bash
   cd ~/tema-ops-server && sudo docker compose exec -T db pg_restore -U ops -d ops --clean --if-exists < /tmp/<file>.dump
   ```

3. Check, then delete the downloaded file:

   ```bash
   sudo docker compose exec -T db psql -U ops -d ops -c "SELECT count(*), max(received_at) FROM wolt.orders"
   rm /tmp/<file>.dump
   ```

The DB users (`wolt_writer`, `ai_reader`) must already exist; on a new server, run the
migrations first (see "Database users"). The backup brings back their table rights, not their
passwords.

Tested 2026-11-10 on the Mac, into a separate test database: all 7,893 orders came back, both
into an empty database and over an existing one (`--clean`), with the users' rights intact.

## The AI on the server

The agent (`src/tema_ops/agent/agent.py`) answers questions about the data using Gemini on Vertex AI.

**How the server logs in to Gemini:** with no key and no password. The VM runs as its own Google
service account, `tema-ops-vm@tema-ops-prod.iam.gserviceaccount.com`, which has exactly one role:
`roles/aiplatform.user` (may call Vertex AI models). Someone who broke into the server could use
Gemini with it, and nothing else in the Google Cloud project.

The VM's access scope is `cloud-platform` (all Google services). That's Google's recommended
setup: the scope stays wide, and the account's role decides what is actually allowed.

How it was set up (on the Mac). Changing the account needs the VM stopped for about a minute:

```bash
gcloud iam service-accounts create tema-ops-vm --display-name="tema-ops server" --project=tema-ops-prod
gcloud projects add-iam-policy-binding tema-ops-prod --member="serviceAccount:tema-ops-vm@tema-ops-prod.iam.gserviceaccount.com" --role="roles/aiplatform.user" --condition=None
gcloud compute instances stop tema-ops-server --zone=europe-west3-a --project=tema-ops-prod
gcloud compute instances set-service-account tema-ops-server --zone=europe-west3-a --project=tema-ops-prod --service-account=tema-ops-vm@tema-ops-prod.iam.gserviceaccount.com --scopes=cloud-platform
gcloud compute instances start tema-ops-server --zone=europe-west3-a --project=tema-ops-prod
```

After the start, check that the database came back (see "Start / stop").

**AI settings (server `.env`, not in git):**

| Variable | What |
|---|---|
| `AI_DATABASE_URL` | DB login as `ai_reader` (read-only, see "Database users") |
| `AI_MODEL` | which model, e.g. `google_genai:gemini-3.8-flash` |
| `GOOGLE_CLOUD_PROJECT` | `tema-ops-prod` |
| `GOOGLE_CLOUD_LOCATION` | `global`. Gemini models only work there; EU regions return 404. |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | tracing: every question, SQL query and answer is recorded in LangSmith |

**Ask a question on the server:**

```bash
cd ~/tema-ops-server && uv run python src/tema_ops/agent/agent.py
```

An empty line quits. It remembers the last 5 questions of the conversation until it quits.

**Run the agent on the Mac, with the server's data.** The Mac's own database isn't updated
daily, so connect to the server's database through an SSH tunnel:

1. In a separate terminal tab, start the tunnel and leave it running:

   ```bash
   gcloud compute ssh tema-ops-server --zone=europe-west3-a --project=tema-ops-prod -- -N -L 5433:localhost:5432
   ```

2. In the Mac `.env`, `AI_DATABASE_URL` uses port `5433` (the tunnel) instead of `5432` (the Mac's own database).

On the Mac, Gemini uses your own Google login: `gcloud auth application-default login`.

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

## Auto-deploy (GitHub Actions)

Every push to `main` updates the server on its own. Nobody has to `git pull` on the server.

**To deploy**, on the Mac, after committing on `develop`:

```bash
git checkout main && git merge develop && git push && git checkout develop
```

**What happens after the push:**

1. GitHub sees the push to `main` and runs `.github/workflows/deploy.yml` on one of its own machines.
2. That machine connects to the server over SSH using the deploy key (see below).
3. The server runs `scripts/deploy.sh`, which does three things:
   - `git pull --ff-only`: downloads the new code
   - `uv sync`: installs new or changed libraries
   - `scripts/migrate.sh`: runs any new file in `db/migrations/`. Each file runs only once; the database records which ones ran (table `schema_migrations`).

Nothing needs restarting. Cron starts the scripts from scratch each time, so the next run uses the new code.

**Not deployed automatically.** Do these by hand on the server:

- changes to `.env`
- changes to the crontab (`crontab -e`)
- DB user passwords

**Check a deploy** (on the Mac), or open GitHub → repo → **Actions** tab:

```bash
gh run list --workflow=deploy.yml --limit 5     # ✓ = worked, X = failed
gh run view <run id> --log-failed               # why it failed (run id comes from the list)
```

GitHub emails you by default when a run fails.

**Deploy again without a new push** (e.g. after fixing something on the server):

```bash
gh workflow run deploy.yml
```

or Actions tab → **Deploy** → **Run workflow**. You can also run `./scripts/deploy.sh` by hand on the server.

**If it fails at `git pull`**, someone changed code files directly on the server. Run `git status` on the server and undo those changes. Code changes should only arrive through `main`.

**The deploy key:**

| Part | Where |
|---|---|
| Private half | only in the GitHub secret `DEPLOY_SSH_KEY` |
| Public half | on the server in `~/.ssh/authorized_keys`, on a line starting with `command="/home/macbook/tema-ops-server/scripts/deploy.sh",restrict` |

That `command=…,restrict` prefix means this key can only run `deploy.sh`. A stolen copy of the key can't open a shell or run any other command.

The other two GitHub secrets are `DEPLOY_HOST` (the server's IP) and `DEPLOY_KNOWN_HOSTS` (the server's fingerprint, so GitHub only ever connects to the real server). All three are in GitHub → repo **Settings → Secrets and variables → Actions**. When the server moves, update them (steps 7–8 in "Moving to a new server" below).

## Start / stop (to save credits)

```bash
gcloud compute instances stop tema-ops-server --zone=europe-west3-a --project=tema-ops-prod
gcloud compute instances start tema-ops-server --zone=europe-west3-a --project=tema-ops-prod
```

While stopped, the daily Wolt update does not run. If it stays stopped for long, the Wolt token chain can die.

After every start (by you, or by Google for maintenance), check that the database is running:

```bash
cd ~/tema-ops-server && sudo docker compose ps     # the db line must say "Up" or "running"
```

It should start by itself (`restart: unless-stopped` in `docker-compose.yml`). If the list is empty, start it:

```bash
sudo docker compose up -d db
```

## Moving to a new server (e.g. Hetzner)

Everything below is tied to *this* machine and has to be redone on the new one.

1. **New machine**: Ubuntu, timezone `Asia/Tbilisi`, clone the repo, run `./scripts/setup_server.sh`.
2. **GitHub read-only deploy key** (lets the server `git pull`): make a new one on the new server and add it in GitHub → repo Settings → Deploy keys. Delete the old one.
3. **Secrets, copied by hand**: `.env`, then the DB user passwords (see "Database users").
4. **Data**: run a backup by hand on the old server, then restore it on the new one (see "Backups"). The new server reads the bucket with the `tema-ops-vm` key from step 9. Stop the old server's cron first, so no new orders arrive after the backup.
5. **Wolt token**: move `auth/wolt.json` and **stop the old server's cron first**. Only one machine may ever renew the token, otherwise the chain dies.
6. **Cron**: copy the lines from `crontab -l`.
7. **Auto-deploy key** (lets GitHub Actions run `deploy.sh`): add the same `command="…/scripts/deploy.sh",restrict ssh-ed25519 …` line to `~/.ssh/authorized_keys` on the new server.
8. **GitHub Actions secrets**: update the server IP and its host key (known_hosts) to the new server's.
9. **Gemini login**: a server outside Google Cloud has no service account attached. Create a key file for `tema-ops-vm`:

   ```bash
   gcloud iam service-accounts keys create tema-ops-vm-key.json --iam-account=tema-ops-vm@tema-ops-prod.iam.gserviceaccount.com
   ```

   Copy it to the new server (never into git, and delete it from the Mac afterwards), then add `GOOGLE_APPLICATION_CREDENTIALS=/home/<user>/tema-ops-vm-key.json` to `.env`. Keep the `tema-ops-vm` account in Google Cloud; the key belongs to it.
10. **Google Cloud cleanup**, so it stops costing money:
   ```bash
   gcloud compute instances delete tema-ops-server --zone=europe-west3-a --project=tema-ops-prod
   gcloud compute addresses delete tema-ops-ip --region=europe-west3 --project=tema-ops-prod
   ```

## Lost access?

As long as you can log into the Google account, you can always get back in: run the `gcloud compute ssh` command again and it sets up a fresh key.
