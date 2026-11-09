# tema-ops

The operations backend for **Tema**, a fast-food chain with 3 branches in Tbilisi, Georgia.
It runs on one small server and handles the restaurant's data work by itself: collecting
Wolt orders, building reports, emailing them, and alerting when something breaks.
In progress: an AI that answers the owner's questions about the data in plain language.

This is a real system used by a real business, not a demo.

## What it does today

| When | What |
|---|---|
| Every day, 12:00 | Pulls yesterday's Wolt delivery orders for all 3 branches into PostgreSQL |
| Every day, 12:30 | Backs up the whole database to Google Cloud Storage (kept 30 days; the server can add backups but not delete them) |
| 1st and 16th of the month, 13:00 | Builds the Wolt sales report (Excel, one sheet per branch, units per product per day) and emails it to the manager |
| Every ~4 hours | Renews the Wolt login token so the daily pull keeps working |
| Any job fails | Emails an alert with the last 60 lines of that job's output |
| Push to `main` | Deploys the new code to the server (GitHub Actions) |

## Ask the data a question

The owner asks something like *"Which products get bad ratings most often?"* The AI writes
the SQL, runs it on the database and answers with the numbers, saying which period and
branches the answer covers. It works today in the terminal, on the server and on a laptop.

- **Model:** Gemini 3.8 Flash on Vertex AI, through LangChain. The model is a setting
  (`AI_MODEL`), so different models can be compared.
- **Business rules:** glossaries (`glossary.md`) tell the AI what the data means, for example:
  revenue counts delivered orders only; a rating average must say how many orders were rated;
  if a product name matches more than one product, ask instead of guessing.
- **Follow-up questions:** it remembers the last 5 questions of a conversation, so
  *"How many pitas did Lisi sell yesterday?"* followed by *"And Dolabauri?"* works.
- **When Vertex AI is busy** (error 429), the call is retried on Priority PayGo, which costs 1.8×
  but only for the calls that need it.
- **Tracing:** every question, SQL query and answer is recorded in LangSmith.
- **Cost, measured:** about 0.9 cent per question.

Safety comes from the database, not from the prompt. The AI connects as `ai_reader`:

- can only read (every transaction is read-only, and it has no write rights)
- any query is stopped after 10 seconds
- only one SQL statement per query, so it can't switch its own time limit off
- at most 200 rows are returned to the model

On the server, the AI logs in to Google as its own account (`tema-ops-vm`), which can call
Vertex AI and nothing else.

**Next:** an eval set of real owner questions with known answers, then a comparison of models
and settings on accuracy and cost (target: about 0.1 cent per question). After that comes a
FastAPI service and a WhatsApp bot. The full list of open work is in [TODO.md](TODO.md).

## How it fits together

```
cron on the server (Tbilisi time)
 └─ run_job.py: timestamps every log line, emails an alert if the job fails
     ├─ wolt/daily_update.py → fetch_wolt.py (Wolt API) → load_to_db.py → PostgreSQL
     ├─ wolt/wolt_login.py   (renews the Wolt token)
     └─ wolt/send_report.py  → excel_report.py → email with the .xlsx attached

agent/ (the AI): reads all glossaries, queries PostgreSQL as the read-only user
```

## Folders

| Path | What's in it |
|---|---|
| `src/tema_ops/wolt/` | Wolt: fetch orders, load them into the DB, Excel report, glossary for the AI |
| `src/tema_ops/agent/` | The AI: model setup, tools, company-wide glossary |
| `src/tema_ops/notify.py` | Sends email (alerts and reports) |
| `src/tema_ops/run_job.py` | Wraps every scheduled job (logs and alerts) |
| `db/migrations/` | Database schema as numbered SQL files; each one runs once |
| `scripts/` | Server setup, deploy, migrations |
| `.github/workflows/deploy.yml` | Auto-deploy on push to `main` |
| `docs/server.md` | How to run, check and fix the server |

Each department has its own folder with its data code, its `glossary.md` and its AI tools.
Wolt is the only department so far; store sales and expenses come later. There is one AI
agent, and it reads every department's folder.

## Design decisions

- **One database user per job.** `ops` owns the schema and is used only for migrations,
  `wolt_writer` can change only Wolt tables, and `ai_reader` can only read. A bad AI query
  can't change or delete anything.
- **Read-only towards Wolt.** The code only reads the restaurant's own order data and
  renews its login token. It never changes anything in the Wolt merchant account.
- **Only one machine renews the Wolt token.** Every renewal replaces the token, so if two
  machines renewed it, one would end up holding a dead token. Only the server renews it,
  and a file lock stops two scripts on the server renewing at the same time.
- **One supervisor instead of error handling in every script.** `run_job.py` wraps every cron
  job, so timestamps and failure alerts work for current and future jobs without changing
  them.
- **The database runs on Tbilisi time.** `CURRENT_DATE - 1` in SQL is yesterday in Tbilisi,
  so neither the AI nor the reports need to convert time zones.
- **One AI agent with one glossary per department.** Questions often cross departments
  (e.g. Wolt sales against expenses), so one agent that knows every department works better
  than one agent per department.

## Stack

Python 3.11 · uv · PostgreSQL 17 (Docker) · httpx · psycopg 3 · openpyxl ·
LangChain · Gemini on Vertex AI · LangSmith · GitHub Actions · Google Cloud VM (Ubuntu 24.04)

## Running it

Server setup, scheduled jobs, database users, deploys and troubleshooting are all in
[docs/server.md](docs/server.md).

Locally:

```bash
uv sync
docker compose up -d db
scripts/migrate.sh
```

Settings go in a `.env` file (never committed):

| Variable | What |
|---|---|
| `DATABASE_URL` | DB connection as `wolt_writer` (used by the Wolt scripts and the report) |
| `AI_DATABASE_URL` | DB connection as `ai_reader` (used by the AI) |
| `SMTP_USER`, `SMTP_PASSWORD` | Gmail account and app password that send all email |
| `ALERT_TO` | Who gets failure alerts |
| `WOLT_REPORT_TO` | Who gets the Wolt report (comma-separated) |
| `AI_MODEL`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | Which model to use and where (Vertex AI) |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | Tracing |

Fetching from Wolt needs Tema's own merchant login. This repo contains no credentials and
no order data.
