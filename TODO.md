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

## AI agent

- [ ] Result checker (Reflection): a second look at the SQL and the answer before replying.
- [ ] Save questions and answers in our own DB table once the bot has real users
  (LangSmith keeps traces only 14 days on the free plan). Needs a DB user that may write
  only that table.
- [ ] Conversations that survive restarts: replace `InMemorySaver` with a Postgres checkpointer.

## Product

- [ ] FastAPI service with an `/ask` endpoint.
- [ ] WhatsApp bot (one conversation per phone number = `thread_id`).
- [ ] Shift sheet: ask the manager whether orders are counted by the time they came in (now)
  or the delivery time. Changing it is one word in `SHIFTS_SQL`.
- [ ] New departments, each with its own folder, `glossary.md` and tools: store sales
  (cash register), expenses.
