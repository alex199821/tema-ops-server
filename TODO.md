# TODO

Open work, most important first. Remove a line when it's done; git keeps the history.

## Soon

- [ ] **Alert when the server is down.** Today, no email can mean "all good" or "server dead".
  Plan: a dead man's switch with [healthchecks.io](https://healthchecks.io) (free, open source).
  After `DONE`, `run_job.py` pings `https://hc-ping.com/<ping key>/<script name>`; healthchecks.io
  emails if a ping is late. One secret in `.env` (the ping key), no crontab changes.
  Checks: `wolt_login` (every ~4 h, the server's heartbeat), `daily_update` (12:00),
  `backup_db` (12:30), `send_report` (1st/16th 13:00).
- [ ] **Token recovery guide for managers.** If the Wolt token chain breaks (alert:
  `renew FAILED: 401`), only the developer can fix it today. Write a step-by-step guide:
  incognito window → log in to merchant.wolt.com → copy the refresh token → save it on the server.
- [ ] **Check the first report email** reached the manager (16 November, 13:00): `logs/send_report.log`.
- [ ] **Eval set for the AI.** About 15 real owner questions with hand-checked answers, saved as
  a LangSmith dataset. Needed before changing the model or any setting that affects answers.

## Security and cleanup

- [ ] Remove the `Editor` role from the old default compute service account. It isn't attached
  to any VM anymore, but it can still change everything in the project, backups included.
- [ ] Delete any Gemini API key in Google Cloud → APIs & Services → Credentials. We use Vertex AI
  through Google logins, so no key is needed.
- [ ] Delete the old personal Gmail app password (the bot Gmail account sends all email now).
- [ ] Make sure the local copy of the GitHub Actions deploy key is deleted. The private half
  should only exist in the GitHub secret `DEPLOY_SSH_KEY`.
- [ ] Before real users: decide whether order data and customer comments may go to LangSmith
  (US servers) with every trace.
- [ ] Optional: rename `wolt/daily_update.py` to something clearer (e.g. `sync_orders.py`).
  The crontab line on the server must change too.

## AI agent

- [ ] **Cost**, measured at ~0.9 cent per question, target ~0.1 cent. Levers, biggest first:
  `thinking_level="low"`, prompt caching (the 1,970-token instructions + glossaries are sent
  with every call), `MAX_ROWS` 200 → 100, a cheaper model (Flash-Lite) once the eval set
  proves it answers as well.
- [ ] Check that the Priority PayGo fallback really runs as priority: Google's raw response
  field `traffic_type` should be `ON_DEMAND_PRIORITY` (LangChain doesn't show it).
- [ ] `send_wolt_report` tool: "send me the Wolt report" builds and emails the Excel.
- [ ] Result checker (Reflection): a second look at the SQL and the answer before replying.
- [ ] Save questions and answers in our own DB table once the bot has real users
  (LangSmith keeps traces only 14 days on the free plan). Needs a DB user that may write
  only that table.
- [ ] Conversations that survive restarts: replace `InMemorySaver` with a Postgres checkpointer.

## Product

- [ ] FastAPI service with an `/ask` endpoint.
- [ ] WhatsApp bot (one conversation per phone number = `thread_id`).
- [ ] Wolt report: the missing columns AB–AG (deductions, refunds, positive/negative ratings,
  credit sent, complaints) and the shift sheet (day 09:00–20:59 / night 21:00–08:59).
  The source of deductions, refunds and credit isn't in the order data yet.
- [ ] New departments, each with its own folder, `glossary.md` and tools: store sales
  (cash register), expenses.
