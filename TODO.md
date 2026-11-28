# TODO

Open work, most important first. Remove a line when it's done; git keeps the history.

## Main goal: daily insights for the CEO

The CEO uses the reports to know what is happening in the branches (e.g. "burger sales are
down at one branch: is it only there, or everywhere?"). Goal: the bot tells her every day,
and a weekly report finds deeper patterns. Code finds the changes; the AI only writes them up.

- [ ] **IncoPOS for the other 4 branches** (in progress). Keys for სანაპირო, ლისი, ივერთუბანი are
  in the Mac `.env`; the first key (POS name ახალი კაფე) is ახალი დოლაბაური, the same branch as
  Wolt "Tema Dolabauri". Still missing: the OLD დოლაბაური's key. Each key is a separate IncoCloud account that
  counts shops, receipts and products from 1, so the numbers clash. Decided: a `branch_id`
  column on every IncoPOS row and one data folder per branch (option A). Then a download on
  the server: one worker per branch, 3 days at a time, newest first, wait 15 min after an error
  (the API allows max 30 days per request and blocks the IP ~10 min after too many requests).
  First receipts: ლისი 2024-08-25, სანაპირო 2025-03-13, ივერთუბანი 2026-11-02, ახალი კაფე
  2026-09-03. Ask the vendor / CEO where the older years are (expected 7–8 years for one branch).
- [ ] **URGENT, right after the branches are loaded: one product list for all branches.** A
  mapping table (branch, IncoPOS product number) → one shared product (e.g. სანაპირო 6 = ლისი 59
  = ბურგერი): matched by name automatically, checked by a person. Without it "is it down
  everywhere?" only works by fragile name matching.
- [ ] **URGENT, right after the branches are loaded: clean summary tables** that the bot and the
  Sheets read instead of the raw receipts, e.g. one row per day × branch × product with
  quantity, revenue and cost. Simple, documented tables make the AI's queries far more
  accurate. Plus checks after every load (totals vs IncoPOS's own report, no duplicate
  receipts, no missing days).
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
- [ ] **Eval set for the AI.** LangSmith datasets `tema-ops-eval` (15 real owner questions) and
  `tema-ops-eval-fixed` (the same with fixed dates, the default). `evals/run_evals.py <name> [dataset]`
  times every answer (needs the DB tunnel); `evals/facts.py` computes the right numbers (read-only SQL,
  saved to the git-ignored `data/`); `evals/check_run.py <run> [<run> ...]` scores answers against them.
  - **More detailed checks of the facts by hand.** Done so far against the Wolt portal: ლისი 11–24 Nov
    (totals, orders, rejected, chicken rolls) and #8's Wolt sandwiches per product in all 3 branches:
    exact matches. (The portal's Items tab also counts items of rejected orders; we don't.)
    Still to check: the store numbers against IncoPOS's own report (#2, #4, #5, #8's store half),
    ratings (#14, #15), and the definitions in #10, #12, #13 with Nino.
  - Still to do: more questions (only 15 today, a few per kind), and running it in CI.
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

- [ ] **Faster answers.** Measured 2026-11-25 with the eval set: ~100% of the time is Gemini calls.
  Baseline 6.5 Gemini calls per question, median ~48 s, single calls hanging 1–5 min at Google
  (standard and priority alike; priority as the main model was no faster).
  - Done: 1a, today's date + newest Wolt/IncoPOS day at the end of the prompt
    (agent.py `add_today`, glossary rule fixed) → 5.6 calls/question; timeout fix (model.py,
    agent.py): 30 s + 1 re-send, then the priority backup with 60 s → worst question 274–559 s → 97–169 s.
  - Done: 1b, `incopos/glossary.md` → 4.4–5.3 calls/question (was 5.6–6.3), table-list lookups
    9–11 → 0 per run, median 28–44 s (was 48–60 s). Weak spots seen in the answers: `evals/what_to_watch.md`.
  - Tried and reverted (2026-11-26): 1c, query rules in `INSTRUCTIONS` (no schema/name lookups, fewest
    queries, let the query do the adding, independent queries in one step) → ~4 calls/question, typical
    answer only ~3 s faster, #7/#8/#12 10–26 s faster. Reverted to keep the risk low: bigger, harder-to-check
    SQL, one hand-added wrong total (#8), and "the glossaries are complete" stops being true when products
    or branches change. Gemini ran 2 queries in one step only once in ~50 steps.
  - **Honest result over all the runs:** the typical answer went only from ~37.5 s to ~34 s (Google hangs
    taken out). Calls fell, but each call writes more, and a call costs ~3.5 s fixed + ~0.6 s per 100
    written tokens, about half of them thinking (the final answer alone: ~11.5 s, ~740 thinking tokens).
    The longer prompt cost ~nothing. The real win is the worst cases (timeout): worst question
    274–559 s → 67–185 s; the price is a rare failed question when both Google models time out.
  - Next, the only noticeable lever left: a lower thinking level, after hand-checked answers for #4, #5, #12.
    Voice: a timeout + minimal thinking (`voice.py`). A backup on another provider for Google bursts.
    Maybe: run the eval once on the server (hangs are rarer there).
- [ ] Result checker (Reflection): a second look at the SQL and the answer before replying.

## Product

- [ ] New departments, each with its own folder, `glossary.md` and tools: expenses.
  (Store sales: see "IncoPOS for the other 4 branches".)
