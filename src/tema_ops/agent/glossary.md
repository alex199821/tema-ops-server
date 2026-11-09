# Tema company glossary (for the AI)

Company-wide facts and rules. Each department adds its own glossary
(e.g. `wolt/glossary.md`) describing its tables.

## The company
- Tema is a fast-food chain in Tbilisi, Georgia.
- Money is GEL (Georgian lari).
- All times are Tbilisi local time. The database also runs on Tbilisi time,
  so `CURRENT_DATE` is today in Tbilisi and `CURRENT_DATE - 1` is yesterday.

## Branches
Table `branches (id, name)`. Every department links its data to a branch.

| branches.id | name      | also called            |
|-------------|-----------|------------------------|
| 1           | სანაპირო  | Sanapiro, Gamsakhurdia |
| 2           | ლისი      | Lisi, Amashukeli       |
| 3           | დოლაბაური | Dolabauri              |

## General rules
- A day = the calendar date of the event time (e.g. when an order came in).
- Shifts: day = 09:00–20:59, night = 21:00–08:59.
  A night shift belongs to the date it started.
- Data is loaded once a day at 12:00, for the previous day.
  Today's data is not in the database yet; the latest full day is yesterday.
- No rows means "no data", not zero (e.g. `SUM` over no rows is empty, not 0).
  Say so instead of answering 0.
- If a product or branch name matches more than one thing,
  ask which one is meant. Do not guess.
- Always say which period and which branches an answer covers.
