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
- [ ] **"No store data for დოლაბაური"** (#2, #4, #12) is true only while ახალი კაფე isn't linked to a
  branch. If ახალი კაფე turns out to be Wolt's დოლაბაური, set `incopos.locations.branch_id`
  and update the location table in `incopos/glossary.md`.
