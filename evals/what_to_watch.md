# What to watch

Weak spots in the agent's answers, found while reading eval runs. Not urgent: fix them later.
Remove an item when it's fixed. Question numbers are the `n` in the `tema-ops-eval` dataset.

## From the 1b runs (2026-11-25, `fix-1b-incopos-glossary`)

- [ ] **"დოზა ყავა" headline counts tea and hot chocolate** (#5). Both runs led with "132 doses",
  and only below said 116 of them were coffee. 116 is the right number.
  Fix: in `incopos/glossary.md`, count only the coffee drinks and give tea and hot chocolate separately.
- [ ] **Wolt orders + store receipts added into one number** (#1, "how many orders yesterday?":
  "101 Wolt orders and 260 store receipts, 361 total"). An order and a receipt aren't the same thing.
  Fix: give them side by side, without a sum.
- [ ] **Open-ended conclusions change from run to run** (#10, "dynamics of sales in branches").
  Lisi was "stable" in one run and "slightly falling" in the other, and Sanapiro "volatile" vs "growing".
  This happened before 1b too. Fix idea: a fixed method in the glossary (e.g. compare the last 4 full
  weeks with the 4 before them, and give the % change).
- [ ] **The agent added up a long list itself and got it wrong** (#8, 1c run `fix-1c-query-rules-eac1e04e`).
  It summed ~23 store product rows in its head: 46,322 GEL instead of 46,612.50 (290 GEL off).
  Its own daily query in the same answer adds up to 46,612.50. Adding 2 numbers was right every time
  (#2, #7). It happened again without 1c (`fixed-3.8`: 28,661 instead of 29,051.00), so it's the model,
  not 1c: 2 wrong out of 7 Flash runs. Trying now (2026-11-26): one sentence in INSTRUCTIONS, "get a total
  of many rows from the query (SUM or ROLLUP), never by adding rows yourself; two or three numbers are fine".
  If #8 still goes wrong, the sturdier fix: `run_sql` adds a sums line under long results (computed by code).
- [ ] **Store "როლი" counted as chicken roll** (#7, 1c run `fix-1c-query-rules-eac1e04e`). The answer
  added store როლი (1,325) to Wolt ქათმის როლი (883) = 2,208 chicken rolls. Probably right (the store
  also has სოკოს როლი), but nobody confirmed it. If it's right, say so in `incopos/glossary.md`.
- [ ] **#11's very first Gemini call keeps hanging** ("how would you say overall multiple month dynamic
  of sanapiro?"). In the last 4 runs (25 Nov 18:32–19:45 UTC), its first call returned nothing within
  30 s, twice in a row (504), every time; it failed the whole question in 2 of those runs. Earlier it took
  3–7 s. The other questions' first calls in the same runs were fine. They're hangs, not long thinking:
  without the timeout the same call once took 285 s for 143 tokens. Unknown why; check whether it also
  happens on the server after the deploy.
- [ ] **The glossaries' product lists are written by hand and can go stale.** Today the store list
  matches all 103 sold products. A new or renamed product, or the other 4 branches' IncoPOS data, makes
  it incomplete, and the agent trusts the lists. (Under 1c, which said "the glossaries are complete",
  name checks fell from ~3 per run to ~0.8; 1c is reverted, so they're back.) Fix idea: a pytest that
  fails when a sold product (store or Wolt) is missing from the glossary lists.
- [ ] **Old answers reused from the chat memory** (live WhatsApp, 25 Nov 23:32). "როგორი შეფასებები გვაქ
  მიღებული ბოლო დღეებში?" was answered with zero queries, by translating an earlier "last 3 days (18–20 Nov)"
  answer from a few days before; 21–24 Nov (4 one-star ratings, 21 Nov the worst day) were missed. Fix
  (2026-11-26): each earlier question in the memory now carries "[asked Sat 21 Nov 2026, 22:45]". Watch
  whether repeated questions are now answered with fresh queries.
- [ ] **"What was the bad rating about?" skips ratings without a comment** (same chat): it named #495 (with a
  comment) but not the three 1★ ratings with no comment (#321, #512, #374). Fix idea: say how many low
  ratings had no comment at all.
- [x] **"No store data for დოლაბაური"** (#2, #4, #12): ახალი კაფე IS დოლაბაური (the new one). Migration 010
  gives every IncoPOS row a `branch_id`, and `incopos/glossary.md` lists all 4 branches. Once the other
  branches are loaded, the store facts (#2, #4, #8, #12) cover all 4 branches, so they change.
