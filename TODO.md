# TODO

Open work, most important first. Remove a line when it's done; git keeps the history.

## Next: tests and evals

- [ ] **CI: tests before every deploy.** GitHub Actions runs `pytest` (and a linter, `ruff`)
  on every push; the deploy to the server only happens if they pass. Tests that need the
  database run against a throwaway Postgres in CI, never the live one.
- [ ] **More tests**, beyond the 4 tool tests: shift rules (`shift_value`: a 20:59 order is
  day, an 08:59 order belongs to the previous night, half-loaded nights are empty), the
  WhatsApp webhook (unknown numbers ignored, duplicate messages answered once, voice
  messages routed to transcription), report building.
- [ ] **Eval set for the AI.** About 15 real owner questions with hand-checked answers, saved as
  a LangSmith dataset, run on every prompt/model change. Needed before changing the model,
  the thinking level, or anything else that affects answers.
- [ ] **No live write access from the Mac.** Point the Mac's `DATABASE_URL` back to the local
  database; only `AI_DATABASE_URL` (read-only) goes through the tunnel.

## WhatsApp bot: rollout

- [ ] Revoke the extra access token the Meta dashboard ("Send message" step) generated; it was
  shown in a screenshot. The server uses its own System User token.
- [ ] **One answer for a burst of messages.** "hi" / "how are you?" / "report for yesterday"
  sent within seconds now get 3 separate answers. Wait a few seconds after each message
  (reset the wait when another one comes in), then answer all of them together once.
- [ ] The 5 employees' numbers in `WHATSAPP_ALLOWED_NUMBERS`; daily-report template with a
  "Show report" button.
- [ ] Caddy: pass only `/webhook` to the bot, answer everything else itself (scanners hit the
  bot every few seconds). Remove the unused GCP firewall rule `default-allow-rdp`.
- [ ] Privacy policy on the domain (e.g. `https://<BOT_DOMAIN>/privacy`); then fill Meta's
  "Data deletion instructions URL" (Meta rejected the GitHub link there).
- [ ] Document Caddy + the bot service in `docs/server.md` (`BOT_DOMAIN`, install commands).

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

## AI agent

- [ ] Result checker (Reflection): a second look at the SQL and the answer before replying.
- [ ] Save questions and answers in our own DB table once the bot has real users
  (LangSmith keeps traces only 14 days on the free plan). Needs a DB user that may write
  only that table.
- [ ] Conversations that survive restarts: replace `InMemorySaver` with a Postgres checkpointer.

## Product

- [ ] Shift sheet: ask the manager whether orders are counted by the time they came in (now)
  or the delivery time. Changing it is one word in `SHIFTS_SQL`.
- [ ] New departments, each with its own folder, `glossary.md` and tools: store sales
  (cash register), expenses.
