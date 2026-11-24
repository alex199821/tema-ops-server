# TODO

Open work, most important first. Remove a line when it's done; git keeps the history.

## Main goal: daily insights for the CEO

The CEO uses the reports to know what is happening in the branches (e.g. "burger sales are
down at one branch: is it only there, or everywhere?"). Goal: the bot tells her every day,
and a weekly report finds deeper patterns. Code finds the changes; the AI only writes them up.

- [ ] **IncoPOS for the other 4 branches.** Ask the vendor for an app ID + secret per branch (or
  one key for all locations), and how far back their cloud has each branch. Test one old day
  per branch, then download the whole history on the server in the background (~40 s per
  day: about 2–3 days for 2 years × 4 branches), and map each IncoPOS location to its branch.
  The daily job (`incopos/daily_update.py`, 01:00) already fetches every location the key can
  see; if each branch gets its own key, the scripts need a list of keys instead of one.
  (Location "ახალი კაფე" opened 2026-09-03; that's why the API has nothing for it before that date.)
- [ ] **Company context for the agents**, in the DB (not in git: the repo is public):
  - branch facts: name in each system (Wolt, IncoPOS, shift SMS), opening date, coordinates,
    kind of place, which branches are close and share customers
  - an events timeline (date, branch, what happened): price changes, new menu items, closed
    days, renovations, new branches or competitors nearby, influencer videos
- [ ] **Daily "what changed" message** to the CEO in WhatsApp:
  - code compares yesterday with the same weekday of the last 4 weeks (store + Wolt) and flags
    only changes that are big **and** have enough volume (Wolt alone is too small per product:
    0–5 burgers a day per branch)
  - for each flag, code checks the other branches: only here (local cause) or everywhere
    (outside cause), plus what else changed (rejected orders, a product stopped selling at
    16:00, reviews, weather, events). Shown as "possible reasons", never as the cause.
  - Flash writes 2–4 Georgian lines from the flagged rows only. Every day, also when nothing
    happened ("all stable"), so silence never means "broken".
  - 👍/👎 per line to tune the thresholds (and to measure how useful it is)
  - a bot-started message needs a Meta-approved utility template. This replaces the planned
    fixed daily report with a "Show report" button.
- [ ] **Google Sheets**: the store sales tab is live and updated every night (`incopos/sales_sheet.py`).
  Next: a tab for each other branch once its IncoPOS key arrives (one `SALES_SHEET_TAB_<id>` line
  each), the costs still missing in `თვითღირებულებები`, and the profit for the bot to read.
- [ ] **TikTok videos.** Tema doesn't advertise, but influencers post about it. No clean API
  (TikTok's research API is for academics only; scraping breaks TikTok's terms), so: whoever sees
  a video forwards the link to the bot, and it is saved as an event (the post time comes from
  the video ID; creator, branch, views). A spike that nothing explains → the bot asks "was there
  a TikTok?".
- [ ] **Start recording who works which shift** (if it's only on paper today, it's lost every day).
- [ ] **Weekly deep research** (after IncoPOS history, the daily message and the eval set):
  researcher agents in parallel (products, shifts, branches, reviews, weather) write ideas →
  an independent checker agent re-runs the numbers and tests each idea on other weeks/years
  → 3–5 findings a week, each with a number, how sure, an action and an experiment that would
  prove the cause (e.g. a promo in one branch only). Built backwards from the CEO's real
  decisions (menu, prices, promos, staff per shift, how much to prepare). Pro model.
  Sources in order: IncoPOS, shifts, Google reviews, weather; social media needs full control of
  the Facebook Page; road traffic skipped (no history to download).

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

- [ ] The 5 employees' numbers in `WHATSAPP_ALLOWED_NUMBERS` (3 set so far).
- [ ] Privacy policy on the domain (e.g. `https://<BOT_DOMAIN>/privacy`); then fill Meta's
  "Data deletion instructions URL" (Meta rejected the GitHub link there).

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
- [ ] **LangSmith: deprecated API endpoint, stops working 31 Jan 2027** (banner seen 2026-11-22:
  the `tema-ops` key called 1 deprecated endpoint in 7 days). Probably fixed by updating the
  `langsmith` library (`uv lock --upgrade-package langsmith`); check with LangSmith's "How to migrate".

## AI agent

- [ ] **Faster answers.** Measured 2026-11-20 (LangSmith, 18 answers): ~100% of the time is
  Gemini calls, SQL ~0%. Worst cases are single calls hanging 24–94 s at Google. Fix first:
  a ~20 s timeout on the normal model so the existing priority fallback takes over. Then:
  glossary examples for common questions (fewer SQL rounds; avg 3.2, max 9 AI calls per
  answer), and a lower thinking level (needs the eval set first).
- [ ] Result checker (Reflection): a second look at the SQL and the answer before replying.

## Product

- [ ] New departments, each with its own folder, `glossary.md` and tools: expenses.
  (Store sales: see "IncoPOS for the other 4 branches".)
