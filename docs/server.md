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

## The Wolt Google Sheet

"თემა - ვოლტის რეპორტი" (`WOLT_SHEET_ID` in `.env`; the robot `tema-ops-vm` is Editor on it) is a copy
of the Wolt Excel report: `wolt/wolt_sheet.py` builds the Excel in memory and copies every tab into
it (values, formulas, colours, merged cells). Nobody types into it, so every run rebuilds it from
scratch. It runs at the end of the 12:00 Wolt job. By hand, or to only see the sizes:

```bash
cd ~/tema-ops-server && ~/.local/bin/uv run python src/tema_ops/wolt/wolt_sheet.py
cd ~/tema-ops-server && ~/.local/bin/uv run python src/tema_ops/wolt/wolt_sheet.py --dry-run   # sends nothing
```

## Scheduled jobs (cron)

| When | What | Script | Log |
|---|---|---|---|
| Every day 01:00 | Fetch yesterday's IncoPOS store sales for every location → DB, then update the sales tabs in the Google Sheet | `incopos/daily_update.py` | `logs/incopos_daily.log` |
| Every day 12:00 | Fetch yesterday's Wolt orders for all branches → DB, then rebuild the Wolt Google Sheet | `wolt/daily_update.py` | `logs/daily_update.log` |
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
| `bot_writer` | add and read rows in `whatsapp.questions` only (`007_whatsapp.sql`) | the WhatsApp bot's memory | `BOT_DATABASE_URL` |

Tables added later get the same rights automatically, so `ai_reader` can read every new table too. For sensitive tables (salaries etc.), revoke it: `REVOKE SELECT ON <table> FROM ai_reader;`
The bot's questions and answers are in their own schema `whatsapp` on purpose: `ai_reader` can't read them, so one person's questions never show up in someone else's answer.

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

## The WhatsApp bot

Employees chat with the AI agent in WhatsApp. The bot (`src/tema_ops/whatsapp/app.py`) runs
all the time on the server, unlike the cron jobs.

**How a message reaches the bot:**

```
phone → WhatsApp (Meta) → https://<BOT_DOMAIN>/webhook → Caddy (HTTPS, ports 80/443)
      → the bot on 127.0.0.1:8000 → AI agent → reply through Meta's API → phone
```

- **Caddy** (`Caddyfile`, a Docker container in `docker-compose.yml`) is the HTTPS front door.
  It gets a free Let's Encrypt certificate for `BOT_DOMAIN` by itself, renews it by itself, and
  passes only `/webhook` to the bot. Every other address gets `404` from Caddy itself: those
  are robots that scan the whole internet for `/.env`, `/wp-login.php` and so on, and they never
  reach the bot. The certificate is kept in the `caddy_data` volume.
- **The bot** listens only on `127.0.0.1`, so the internet can reach it only through Caddy.
- **The domain** was bought at Cloudflare Registrar and renews once a year. Its DNS has an `A`
  record pointing to the static IP, set to **DNS only** (grey cloud, not proxied). The name is in
  the server `.env` as `BOT_DOMAIN` and kept out of git.
- **Firewall:** the GCP rule `allow-web` opens tcp 80 and 443 (80 is needed for the certificate).

**What the bot does with a message:**

- Ignores numbers that are not in `WHATSAPP_ALLOWED_NUMBERS`, and requests that are not signed by
  Meta (checked with `WHATSAPP_APP_SECRET`).
- Waits until the person has been quiet for 5 seconds, then answers all their messages at once.
  If a new message arrives while it is thinking, it throws that answer away and answers
  everything together.
- Voice messages are written down by Gemini first. The reply starts with what it heard.
- Each phone number is its own conversation, kept in the database (table `whatsapp.questions`),
  so restarts and deploys don't wipe it. One row per answer that was sent: several quick
  messages are one question, a voice message is saved as the text it heard, and the answer is
  saved without the "🎤 heard" line. Before answering, the AI gets the person's last 4 questions
  and answers, plus the new question.

**Read a person's conversation** (`sudo docker compose exec db psql -U ops -d ops`, then):

```sql
SELECT asked_at, question, answer FROM whatsapp.questions WHERE phone = '995XXXXXXXXX' ORDER BY id;
SELECT phone, count(*) AS questions, max(answered_at) AS last_used FROM whatsapp.questions GROUP BY phone;
```

**Bot settings (server `.env`, not in git).** The bot reads `.env` only when it starts, so
**restart it after every change** (`sudo systemctl restart tema-bot`):

| Variable | What |
|---|---|
| `BOT_DOMAIN` | the bot's domain name, used by Caddy |
| `WHATSAPP_TOKEN` | token of the Meta system user `tema-ops`; never expires |
| `WHATSAPP_PHONE_NUMBER_ID` | the bot number's ID in Meta (not the phone number itself) |
| `WHATSAPP_APP_SECRET` | Meta app → App settings → Basic → App secret; checks that requests come from Meta |
| `WHATSAPP_VERIFY_TOKEN` | any random text (`openssl rand -hex 16`); Meta must send the same one when the webhook is set up |
| `WHATSAPP_ALLOWED_NUMBERS` | who may use the bot: country code + number, no `+`, comma-separated, **no spaces**, e.g. `995555123456,995577654321` |
| `BOT_DATABASE_URL` | `postgresql://bot_writer:<password>@localhost:5432/ops`; the password is set with `\password bot_writer` (see "Database users") |

**Add a person:** add their number to `WHATSAPP_ALLOWED_NUMBERS` (`nano .env`), then
`sudo systemctl restart tema-bot`. They message the bot's number first; until then the bot can't
write to them (WhatsApp only allows free replies within 24 hours of the person's last message).

**On Meta's side** (developers.facebook.com, app **Tema**, in the business portfolio **Tema**):

- WhatsApp → Configuration → Webhook: callback URL `https://<BOT_DOMAIN>/webhook`, verify token =
  `WHATSAPP_VERIFY_TOKEN`, webhook field `messages` subscribed.
- The app must stay **published** (Live). An unpublished app gets no real messages.
- **New token:** business.facebook.com → Settings → Users → System users → `tema-ops` →
  Generate token → app Tema, expiration Never, permissions `whatsapp_business_messaging` and
  `whatsapp_business_management`. Put it in `WHATSAPP_TOKEN` and restart the bot.
  "Revoke tokens" there cancels **all** of `tema-ops`' tokens, including the bot's.

**Check that it works** (on the Mac or anywhere):

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://<BOT_DOMAIN>/webhook
```

`403` = all good (Caddy and the bot are up; the bot refuses because there is no verify token).
`502` = Caddy is up but the bot is down. No answer at all = Caddy, the firewall or DNS.

**Logs** (on the server):

```bash
journalctl -u tema-bot -f                                    # the bot, live (Ctrl+C to stop)
journalctl -u tema-bot --since "1 hour ago" --no-pager       # the last hour
cd ~/tema-ops-server && sudo docker compose logs caddy --tail 30   # Caddy, e.g. certificate problems
```

- `Ignored a message from an unknown number` = someone not in `WHATSAPP_ALLOWED_NUMBERS`.
- `GET /webhook … 403` from an unknown address = a robot trying the one open address. Harmless:
  without Meta's verify token or signature the bot refuses.
- `status=143` after a restart is normal (the old process was told to stop).

**Who keeps it running:** `systemd`, Linux's service manager. `scripts/tema-bot.service` tells it
to start the bot at boot and restart it 5 seconds after a crash. Caddy restarts by itself too
(`restart: unless-stopped`).

```bash
sudo systemctl status tema-bot      # running? since when?
sudo systemctl restart tema-bot     # after a .env change
```

**Install on a new server** (once):

```bash
cd ~/tema-ops-server
sudo cp scripts/tema-bot.service /etc/systemd/system/
sudo systemctl enable --now tema-bot                 # start now and at every boot
sudo docker compose --profile server up -d caddy     # needs BOT_DOMAIN in .env and DNS pointing here
gcloud compute firewall-rules create allow-web --project=tema-ops-prod --allow=tcp:80,tcp:443 --source-ranges=0.0.0.0/0   # once per project (on Google Cloud)
```

The `server` profile keeps Caddy from starting on the Mac.

## Check the jobs

Run on the server.

```bash
crontab -l                                                  # what is scheduled
tail -20 ~/tema-ops-server/logs/incopos_daily.log           # last IncoPOS daily update
tail -20 ~/tema-ops-server/logs/daily_update.log            # last Wolt daily update output
tail -5 ~/tema-ops-server/logs/token.log                    # last Wolt token renewals
tail -5 ~/tema-ops-server/logs/backup_db.log                # last database backups
tail -5 ~/tema-ops-server/logs/send_report.log              # last report emails
journalctl -u cron --since today | grep run_job             # proof cron started the jobs (and when)
```

A good Wolt daily run ends with 3 `loaded <venue_id> <date>` lines (one per branch), then `DONE`.
A good IncoPOS daily run has `Downloading <branch> <date>` and `N sales` for each branch,
then `loaded data/incopos/<branch>/<date>.json: N receipts` and `<branch> done: …` for each, a line per branch tab
of the Google Sheet (`<tab>: … updated <month>`), and `DONE`. There are fewer receipts than
sales: the API repeats some receipts, and each is stored once.

The Google Sheet (`SALES_SHEET_ID` in `.env`, one tab per branch named in `SALES_SHEET_TAB_<BRANCH>`,
e.g. `SALES_SHEET_TAB_LISI`; the branch keys are in `incopos/branches.py`) is kept up to date by `incopos/sales_sheet.py` as the robot (`tema-ops-vm`, Editor on
the sheet). It never clears a tab: it inserts a section for a new month and a row for a new product,
and writes only the newest month's IncoPOS cells (price, sold per day, and the cost from the sheet's
`თვითღირებულებები` tab), so edits in past months stay. To update the tabs by hand, without fetching:

```bash
cd ~/tema-ops-server && uv run python src/tema_ops/incopos/sales_sheet.py
cd ~/tema-ops-server && uv run python src/tema_ops/incopos/sales_sheet.py --day 2026-11-07   # also that day's month
```

Test the alert email (fails on purpose, no Wolt involved):

```bash
cd ~/tema-ops-server && uv run python src/tema_ops/run_job.py python -c "1/0"
```

Redo one day by hand (on the server):

```bash
cd ~/tema-ops-server && uv run python src/tema_ops/wolt/daily_update.py 2026-11-07
cd ~/tema-ops-server && uv run python src/tema_ops/incopos/daily_update.py 2026-11-07   # IncoPOS (~1.5 min)
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
3. The server runs `scripts/deploy.sh`, which does five things:
   - `git pull --ff-only`: downloads the new code
   - `uv sync`: installs new or changed libraries
   - `scripts/migrate.sh`: runs any new file in `db/migrations/`. Each file runs only once; the database records which ones ran (table `schema_migrations`).
   - restarts Caddy, so `Caddyfile` changes apply (the certificate is kept)
   - restarts the WhatsApp bot, so it runs the new code. Conversations are kept (they are in the database). A question that is being answered at that moment is lost; the person has to ask again.

The cron jobs need no restart: cron starts the scripts from scratch each time, so the next run uses the new code.

A change to `scripts/deploy.sh` itself takes effect one deploy later: the server has already
started the old version of the script before `git pull` downloads the new one.

**Not deployed automatically.** Do these by hand on the server:

- changes to `.env` (then `sudo systemctl restart tema-bot`, see "The WhatsApp bot")
- changes to the crontab (`crontab -e`)
- DB user passwords
- changes to `scripts/tema-bot.service`: copy it again, then
  `sudo systemctl daemon-reload && sudo systemctl restart tema-bot`

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
4. **Data**: run a backup by hand on the old server, then restore it on the new one (see "Backups"). The new server reads the bucket with the `tema-ops-vm` key from step 10. Stop the old server's cron first, so no new orders arrive after the backup.
5. **Wolt token**: move `auth/wolt.json` and **stop the old server's cron first**. Only one machine may ever renew the token, otherwise the chain dies.
6. **Cron**: copy the lines from `crontab -l`.
7. **Auto-deploy key** (lets GitHub Actions run `deploy.sh`): add the same `command="…/scripts/deploy.sh",restrict ssh-ed25519 …` line to `~/.ssh/authorized_keys` on the new server.
8. **GitHub Actions secrets**: update the server IP and its host key (known_hosts) to the new server's.
9. **WhatsApp bot**: point the domain's DNS `A` record to the new IP, open ports 80/443 in the
   new provider's firewall, then follow "Install on a new server" in "The WhatsApp bot". The
   webhook URL in Meta stays the same, because the domain stays the same.
10. **Gemini login**: a server outside Google Cloud has no service account attached. Create a key file for `tema-ops-vm`:

   ```bash
   gcloud iam service-accounts keys create tema-ops-vm-key.json --iam-account=tema-ops-vm@tema-ops-prod.iam.gserviceaccount.com
   ```

   Copy it to the new server (never into git, and delete it from the Mac afterwards), then add `GOOGLE_APPLICATION_CREDENTIALS=/home/<user>/tema-ops-vm-key.json` to `.env`. Keep the `tema-ops-vm` account in Google Cloud; the key belongs to it.
11. **Google Cloud cleanup**, so it stops costing money:
   ```bash
   gcloud compute instances delete tema-ops-server --zone=europe-west3-a --project=tema-ops-prod
   gcloud compute addresses delete tema-ops-ip --region=europe-west3 --project=tema-ops-prod
   ```

## Lost access?

As long as you can log into the Google account, you can always get back in: run the `gcloud compute ssh` command again and it sets up a fresh key.
