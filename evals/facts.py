"""The right answers ("facts") for the eval questions, computed read-only from the database.

The questions are the 15 real owner questions of the LangSmith dataset `tema-ops-eval`, with every
relative date ("yesterday", "last 7 days", "up to now") replaced by a fixed one. 24 Nov 2026 plays
"yesterday": the last day both Wolt and the store were fully loaded when the questions were fixed.
So every question has one right answer forever, and runs at any hour are checked the same way.

Each question has:
- sql:      one row with every number a right answer may contain (named columns)
- table:    (optional) more rows, only for reading, e.g. one row per week
- required: groups of column names; from each group, at least one number must be in the answer
- optional: numbers that are good to see, but not needed
- wrong:    numbers that mean a mistake, e.g. Wolt orders + store receipts added into one number

The facts are real sales numbers, so they go to data/eval_facts.json (git-ignored: the repo is public).
evals/check_run.py compares a run's answers with them.

Usage:
  uv run python evals/facts.py            compute the facts (needs the DB tunnel on the Mac)
  uv run python evals/facts.py --upload   create the LangSmith dataset tema-ops-eval-fixed (once)
"""
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

FACTS_FILE = Path("data/eval_facts.json")
OLD_DATASET = "tema-ops-eval"
DATASET = "tema-ops-eval-fixed"

# Delivered Wolt orders with their branch name
WOLT = """wolt.orders o
JOIN wolt.venues v ON v.id = o.venue_id
JOIN branches b ON b.id = v.branch_id"""
# Store receipt lines with their product and group
STORE = """incopos.sales s
JOIN incopos.sale_lines l ON l.location_id = s.location_id AND l.sale_id = s.id
JOIN incopos.items i ON i.id = l.item_id
JOIN incopos.item_groups g ON g.id = i.group_id"""

# Sandwiches = all handheld food (agent/glossary.md). Wolt: the names in wolt/glossary.md.
WOLT_SANDWICHES = """('ქათმის როლი', 'სოკოს როლი სამარხვო', 'პიტა ცეზარი', 'ლეგო პიტა ცეზარი',
  'ქათმის სენდვიჩი', 'ქათმის სენდვიჩი ორმაგი შიგთავსით', 'ლორის და ყველის სენდვიჩი',
  'ლორის და ყველის სენდვიჩი ორმაგი შიგთავსით', 'წითელი ქაშაყის სენდვიჩი', 'ბურგერი')"""
# Store: every product of the food group except the salads and fries (incopos/glossary.md)
STORE_SANDWICH = "g.name = 'მზა პროდუქცია' AND i.name NOT IN ('ცეზარი', 'ბერძნული', 'ტუნა', 'ფრი')"
# In the store group ყავა but not coffee
NOT_COFFEE = "('ჩაი', 'ცხელი შოკოლადი', 'ორმაგი ცხელი შოკოლადი', 'ცივი მაჩა', 'პოდი')"


def day_sales(day):
    # Wolt per branch + the store, for one day
    return f"""
WITH w AS (SELECT b.name, o.total_gross FROM {WOLT}
           WHERE o.status = 'DELIVERED' AND o.received_at::date = '{day}'),
     st AS (SELECT SUM(l.quantity * l.price) AS gel, COUNT(DISTINCT s.id) AS receipts FROM {STORE}
            WHERE s.paid_at::date = '{day}')
SELECT SUM(total_gross) AS wolt_gel, COUNT(*) AS wolt_orders,
       SUM(total_gross) FILTER (WHERE name = 'ლისი') AS lisi_gel,
       SUM(total_gross) FILTER (WHERE name = 'დოლაბაური') AS dolabauri_gel,
       SUM(total_gross) FILTER (WHERE name = 'სანაპირო') AS sanapiro_gel,
       (SELECT gel FROM st) AS store_gel, (SELECT receipts FROM st) AS store_receipts,
       SUM(total_gross) + (SELECT gel FROM st) AS total_gel
FROM w"""


QUESTIONS = [
    {"n": 1, "question": "how many orders were made on 24 November 2026?",
     "sql": f"""
SELECT *, wolt_orders + store_receipts AS orders_plus_receipts FROM (
  SELECT COUNT(*) AS wolt_orders,
         COUNT(*) FILTER (WHERE b.name = 'ლისი') AS lisi_orders,
         COUNT(*) FILTER (WHERE b.name = 'დოლაბაური') AS dolabauri_orders,
         COUNT(*) FILTER (WHERE b.name = 'სანაპირო') AS sanapiro_orders,
         (SELECT COUNT(*) FROM incopos.sales WHERE paid_at::date = '2026-11-24') AS store_receipts
  FROM {WOLT} WHERE o.status = 'DELIVERED' AND o.received_at::date = '2026-11-24') t""",
     "required": [["wolt_orders"]],
     "optional": ["store_receipts", "lisi_orders", "dolabauri_orders", "sanapiro_orders"],
     "wrong": ["orders_plus_receipts"]},

    {"n": 2, "question": "როგორი გაყიდვები იყო 2026 წლის 24 ნოემბერს?",
     "sql": day_sales("2026-11-24"),
     "required": [["wolt_gel"], ["store_gel"]],
     "optional": ["total_gel", "lisi_gel", "dolabauri_gel", "sanapiro_gel", "wolt_orders", "store_receipts"]},

    {"n": 3, "question": "2026 წლის 24 ნოემბრის ნავაჭრი ვოლტზე რა იყო?",
     "sql": day_sales("2026-11-24"),
     "required": [["wolt_gel"]],
     "optional": ["wolt_orders", "lisi_gel", "dolabauri_gel", "sanapiro_gel"]},

    {"n": 4, "question": "what about sales on 19 nov? br branch",
     "sql": day_sales("2026-11-19"),
     "required": [["lisi_gel"], ["dolabauri_gel"], ["sanapiro_gel"], ["store_gel"]],
     "optional": ["wolt_gel", "total_gel", "wolt_orders", "store_receipts"]},

    {"n": 5, "question": "21.11.2026 ში რამდენი დოზა ყავა გაიყიდა",
     "sql": f"""
SELECT SUM(l.quantity) FILTER (WHERE i.name NOT IN {NOT_COFFEE}) AS coffee_cups,
       SUM(l.quantity) FILTER (WHERE i.name IN {NOT_COFFEE}) AS other_drinks,
       SUM(l.quantity) AS whole_group
FROM {STORE} WHERE g.name = 'ყავა' AND s.paid_at::date = '2026-11-21'""",
     "required": [["coffee_cups"]],
     "optional": ["other_drinks", "whole_group"]},

    {"n": 6, "question": "2026 წლის 24 ნოემბერს რამდენი როლი გაიყიდა ვოლტზე სხვადასხვა ფილიალებში?",
     "sql": f"""
SELECT SUM(i.count) AS rolls,
       SUM(i.count) FILTER (WHERE i.name = 'ქათმის როლი') AS chicken_rolls,
       SUM(i.count) FILTER (WHERE i.name = 'სოკოს როლი სამარხვო') AS mushroom_rolls,
       SUM(i.count) FILTER (WHERE b.name = 'ლისი') AS lisi_rolls,
       SUM(i.count) FILTER (WHERE b.name = 'დოლაბაური') AS dolabauri_rolls,
       SUM(i.count) FILTER (WHERE b.name = 'სანაპირო') AS sanapiro_rolls
FROM {WOLT} JOIN wolt.order_items i USING (purchase_id)
WHERE o.status = 'DELIVERED' AND o.received_at::date = '2026-11-24'
  AND i.name IN ('ქათმის როლი', 'სოკოს როლი სამარხვო')""",
     "required": [["lisi_rolls"], ["dolabauri_rolls"], ["sanapiro_rolls"]],
     "optional": ["rolls", "chicken_rolls", "mushroom_rolls"]},

    {"n": 7, "question": "okay show me report for 11–24 November 2026 for chicken roll sales",
     "sql": f"""
WITH w AS (SELECT b.name, i.count, i.final_gross FROM {WOLT} JOIN wolt.order_items i USING (purchase_id)
           WHERE o.status = 'DELIVERED' AND o.received_at::date BETWEEN '2026-11-11' AND '2026-11-24'
             AND i.name = 'ქათმის როლი'),
     st AS (SELECT SUM(l.quantity) AS units, SUM(l.quantity * l.price) AS gel FROM {STORE}
            WHERE i.name = 'როლი' AND s.paid_at::date BETWEEN '2026-11-11' AND '2026-11-24')
SELECT SUM(count) AS wolt_units, SUM(final_gross) AS wolt_gel,
       SUM(count) FILTER (WHERE name = 'ლისი') AS lisi_units,
       SUM(count) FILTER (WHERE name = 'დოლაბაური') AS dolabauri_units,
       SUM(count) FILTER (WHERE name = 'სანაპირო') AS sanapiro_units,
       (SELECT units FROM st) AS store_units, (SELECT gel FROM st) AS store_gel,
       SUM(count) + (SELECT units FROM st) AS all_units, SUM(final_gross) + (SELECT gel FROM st) AS all_gel
FROM w""",
     # Store "როლი" as chicken roll isn't confirmed yet (evals/what_to_watch.md), so Wolt alone is enough
     "required": [["wolt_units", "all_units"]],
     "optional": ["wolt_gel", "lisi_units", "dolabauri_units", "sanapiro_units", "store_units", "all_gel"]},

    {"n": 8, "question": "okay show me report for 18–24 November 2026 for all sandwiches",
     "sql": f"""
WITH w AS (SELECT SUM(i.count) AS units, SUM(i.final_gross) AS gel FROM {WOLT} JOIN wolt.order_items i USING (purchase_id)
           WHERE o.status = 'DELIVERED' AND o.received_at::date BETWEEN '2026-11-18' AND '2026-11-24'
             AND i.name IN {WOLT_SANDWICHES}),
     st AS (SELECT SUM(l.quantity) AS units, SUM(l.quantity * l.price) AS gel FROM {STORE}
            WHERE {STORE_SANDWICH} AND s.paid_at::date BETWEEN '2026-11-18' AND '2026-11-24')
SELECT w.units AS wolt_units, w.gel AS wolt_gel, st.units AS store_units, st.gel AS store_gel,
       w.units + st.units AS all_units, w.gel + st.gel AS all_gel
FROM w, st""",
     "required": [["all_units", "all_gel"]],
     "optional": ["wolt_units", "wolt_gel", "store_units", "store_gel"]},

    {"n": 9, "question": "ლისი თემა ს გაყიდვების ტენდენცია მაჩვენე 2026 წლის 26 ოქტომბრიდან 24 ნოემბრამდე",
     "sql": f"""
SELECT SUM(o.total_gross) AS lisi_gel, COUNT(*) AS lisi_orders,
       ROUND(SUM(o.total_gross) / 30, 2) AS daily_avg, ROUND(SUM(o.total_gross) / COUNT(*), 2) AS avg_order
FROM {WOLT} WHERE b.name = 'ლისი' AND o.status = 'DELIVERED'
  AND o.received_at::date BETWEEN '2026-10-26' AND '2026-11-24'""",
     "table": f"""
SELECT date_trunc('week', o.received_at)::date AS week_from, SUM(o.total_gross) AS gel, COUNT(*) AS orders
FROM {WOLT} WHERE b.name = 'ლისი' AND o.status = 'DELIVERED'
  AND o.received_at::date BETWEEN '2026-10-26' AND '2026-11-24'
GROUP BY 1 ORDER BY 1""",
     "required": [["lisi_gel", "daily_avg"]],
     "optional": ["lisi_orders", "avg_order"]},

    {"n": 10, "question": "how are dynamics of sales in branches up to 24 November 2026? falling ? growing?",
     "sql": f"""
SELECT ROUND(SUM(o.total_gross) FILTER (WHERE b.name = 'ლისი' AND o.received_at::date BETWEEN '2026-10-01' AND '2026-10-31') / 31, 2) AS lisi_oct_daily,
       ROUND(SUM(o.total_gross) FILTER (WHERE b.name = 'ლისი' AND o.received_at::date BETWEEN '2026-11-01' AND '2026-11-24') / 24, 2) AS lisi_nov_daily,
       ROUND(SUM(o.total_gross) FILTER (WHERE b.name = 'დოლაბაური' AND o.received_at::date BETWEEN '2026-10-01' AND '2026-10-31') / 31, 2) AS dolabauri_oct_daily,
       ROUND(SUM(o.total_gross) FILTER (WHERE b.name = 'დოლაბაური' AND o.received_at::date BETWEEN '2026-11-01' AND '2026-11-24') / 24, 2) AS dolabauri_nov_daily,
       ROUND(SUM(o.total_gross) FILTER (WHERE b.name = 'სანაპირო' AND o.received_at::date BETWEEN '2026-10-01' AND '2026-10-31') / 31, 2) AS sanapiro_oct_daily,
       ROUND(SUM(o.total_gross) FILTER (WHERE b.name = 'სანაპირო' AND o.received_at::date BETWEEN '2026-11-01' AND '2026-11-24') / 24, 2) AS sanapiro_nov_daily
FROM {WOLT} WHERE o.status = 'DELIVERED'""",
     # Weekly totals of the last 4 full weeks (Monday to Sunday)
     "table": f"""
SELECT date_trunc('week', o.received_at)::date AS week_from,
       SUM(o.total_gross) FILTER (WHERE b.name = 'ლისი') AS lisi,
       SUM(o.total_gross) FILTER (WHERE b.name = 'დოლაბაური') AS dolabauri,
       SUM(o.total_gross) FILTER (WHERE b.name = 'სანაპირო') AS sanapiro
FROM {WOLT} WHERE o.status = 'DELIVERED' AND o.received_at::date BETWEEN '2026-10-26' AND '2026-11-22'
GROUP BY 1 ORDER BY 1""",
     # Open-ended: there are several fair ways to measure a trend, so nothing is required; read it
     "required": [],
     "optional": ["lisi_oct_daily", "lisi_nov_daily", "dolabauri_oct_daily", "dolabauri_nov_daily",
                  "sanapiro_oct_daily", "sanapiro_nov_daily"]},

    {"n": 11, "question": "how would you say overall multiple month dynamic of sanapiro up to 24 November 2026?",
     "sql": f"""
WITH m AS (SELECT o.total_gross, o.received_at::date AS d FROM {WOLT}
           WHERE b.name = 'სანაპირო' AND o.status = 'DELIVERED' AND o.received_at::date <= '2026-11-24')
SELECT SUM(total_gross) FILTER (WHERE d BETWEEN '2026-08-01' AND '2026-08-31') AS aug_gel,
       ROUND(SUM(total_gross) FILTER (WHERE d BETWEEN '2026-08-01' AND '2026-08-31') / 22, 2) AS aug_daily,
       SUM(total_gross) FILTER (WHERE d BETWEEN '2026-09-01' AND '2026-09-30') AS sep_gel,
       ROUND(SUM(total_gross) FILTER (WHERE d BETWEEN '2026-09-01' AND '2026-09-30') / 30, 2) AS sep_daily,
       SUM(total_gross) FILTER (WHERE d BETWEEN '2026-10-01' AND '2026-10-31') AS oct_gel,
       ROUND(SUM(total_gross) FILTER (WHERE d BETWEEN '2026-10-01' AND '2026-10-31') / 31, 2) AS oct_daily,
       SUM(total_gross) FILTER (WHERE d BETWEEN '2026-11-01' AND '2026-11-24') AS nov_gel,
       ROUND(SUM(total_gross) FILTER (WHERE d BETWEEN '2026-11-01' AND '2026-11-24') / 24, 2) AS nov_daily,
       MIN(d) AS first_day
FROM m""",
     # August has 22 days of data (Wolt starts on 10 Aug), November 24: compare per day, not per month
     "required": [["aug_gel", "aug_daily"], ["sep_gel", "sep_daily"], ["oct_gel", "oct_daily"], ["nov_gel", "nov_daily"]],
     "optional": []},

    {"n": 12, "question": "how much did sanapiro sales fall when dolabauri opened? can you make bit of analysis of this (data up to 24 November 2026)",
     "sql": f"""
WITH s AS (SELECT o.total_gross, o.received_at::date AS d FROM {WOLT}
           WHERE b.name = 'სანაპირო' AND o.status = 'DELIVERED')
SELECT (SELECT MIN(o.received_at::date) FROM {WOLT} WHERE b.name = 'დოლაბაური') AS dolabauri_first_day,
       ROUND(SUM(total_gross) FILTER (WHERE d BETWEEN '2026-08-10' AND '2026-09-06') / 28, 2) AS before_daily,
       ROUND(SUM(total_gross) FILTER (WHERE d BETWEEN '2026-09-07' AND '2026-10-04') / 28, 2) AS after_4_weeks_daily,
       ROUND(SUM(total_gross) FILTER (WHERE d BETWEEN '2026-09-07' AND '2026-11-24') / 79, 2) AS after_all_daily,
       ROUND(100 * (SUM(total_gross) FILTER (WHERE d BETWEEN '2026-09-07' AND '2026-10-04') /
                    SUM(total_gross) FILTER (WHERE d BETWEEN '2026-08-10' AND '2026-09-06') - 1), 1) AS change_4_weeks_pct,
       ROUND(100 * ((SUM(total_gross) FILTER (WHERE d BETWEEN '2026-09-07' AND '2026-11-24') / 79) /
                    (SUM(total_gross) FILTER (WHERE d BETWEEN '2026-08-10' AND '2026-09-06') / 28) - 1), 1) AS change_all_pct
FROM s""",
     "required": [["before_daily"], ["after_4_weeks_daily", "after_all_daily"]],
     "optional": ["change_4_weeks_pct", "change_all_pct"]},

    {"n": 13, "question": "შეადარე 2026 წლის 20 ნოემბრის პარასკევი წინა 4 პარასკევთან, როგორი მაჩვენბკები გვაქ",
     "sql": f"""
WITH f AS (SELECT d::date AS d FROM generate_series('2026-10-23'::date, '2026-11-20', '7 days') d),
     w AS (SELECT o.received_at::date AS d, SUM(o.total_gross) AS gel FROM {WOLT}
           WHERE o.status = 'DELIVERED' AND o.received_at::date IN (SELECT d FROM f) GROUP BY 1),
     st AS (SELECT s.paid_at::date AS d, SUM(l.quantity * l.price) AS gel FROM {STORE}
            WHERE s.paid_at::date IN (SELECT d FROM f) GROUP BY 1),
     t AS (SELECT f.d, w.gel AS wolt, st.gel AS store, w.gel + st.gel AS total
           FROM f JOIN w USING (d) JOIN st USING (d))
SELECT (SELECT wolt FROM t WHERE d = '2026-11-20') AS fri20_wolt,
       (SELECT store FROM t WHERE d = '2026-11-20') AS fri20_store,
       (SELECT total FROM t WHERE d = '2026-11-20') AS fri20_total,
       (SELECT ROUND(AVG(wolt), 2) FROM t WHERE d < '2026-11-20') AS prev4_avg_wolt,
       (SELECT ROUND(AVG(total), 2) FROM t WHERE d < '2026-11-20') AS prev4_avg_total""",
     "table": f"""
SELECT f.d AS friday, w.gel AS wolt, st.gel AS store, w.gel + st.gel AS total
FROM (SELECT d::date AS d FROM generate_series('2026-10-23'::date, '2026-11-20', '7 days') d) f
JOIN (SELECT o.received_at::date AS d, SUM(o.total_gross) AS gel FROM {WOLT}
      WHERE o.status = 'DELIVERED' GROUP BY 1) w USING (d)
JOIN (SELECT s.paid_at::date AS d, SUM(l.quantity * l.price) AS gel FROM {STORE} GROUP BY 1) st USING (d)
ORDER BY 1""",
     "required": [["fri20_wolt", "fri20_total"]],
     "optional": ["fri20_store", "prev4_avg_wolt", "prev4_avg_total"]},

    {"n": 14, "question": "რა, რა პროდუქტები იღებენ ყველაზე ცუდ შეფასებებს, ანუ აი რამე კონკრეტულ შეკვეთებს ხო არა ახასიათებთ და რამე კონკრეტულ პროდუქტებს ცუდი შეფასებები. თუნდაც სხვადასხვა ფილიალებში შეხედე და ისე ქენი ეგ. (2026 წლის 24 ნოემბრამდე)",
     "sql": """
SELECT COUNT(*) AS rated_orders, COUNT(*) FILTER (WHERE rating <= 3) AS low_rated,
       ROUND(100.0 * COUNT(*) FILTER (WHERE rating <= 3) / COUNT(*), 1) AS low_pct
FROM wolt.orders WHERE status = 'DELIVERED' AND rating IS NOT NULL AND received_at::date <= '2026-11-24'""",
     # Per product, with enough ratings to mean something
     "table": """
SELECT i.name, COUNT(*) AS rated, COUNT(*) FILTER (WHERE o.rating <= 3) AS low,
       ROUND(100.0 * COUNT(*) FILTER (WHERE o.rating <= 3) / COUNT(*), 1) AS low_pct
FROM wolt.orders o JOIN wolt.order_items i USING (purchase_id)
WHERE o.status = 'DELIVERED' AND o.rating IS NOT NULL AND o.received_at::date <= '2026-11-24'
GROUP BY 1 HAVING COUNT(*) >= 15 ORDER BY low_pct DESC""",
     "required": [["rated_orders", "low_rated"]],
     "optional": ["low_pct"]},

    {"n": 15, "question": "საბოლოო ჯამში შეაფასე შეფასებების აა ციკლი კვირიდან კვირამდე, დინამიკა როგორი არის. ანუ უფრო მეტი დადებითი შეფასება გვაქვს ბოლო პერიოდში, უფრო მეტი უარყოფითი, თავიდან დაიწყე და აი მიყევი. ხარისხი ობიექტებში მომსახურების ეცემა თუ იზრდება? (2026 წლის 24 ნოემბრამდე)",
     "sql": """
WITH r AS (SELECT rating, received_at::date AS d FROM wolt.orders
           WHERE status = 'DELIVERED' AND rating IS NOT NULL AND received_at::date <= '2026-11-24')
SELECT ROUND(AVG(rating) FILTER (WHERE d < '2026-09-01'), 2) AS aug_avg,
       ROUND(AVG(rating) FILTER (WHERE d BETWEEN '2026-09-01' AND '2026-09-30'), 2) AS sep_avg,
       ROUND(AVG(rating) FILTER (WHERE d BETWEEN '2026-10-01' AND '2026-10-31'), 2) AS oct_avg,
       ROUND(AVG(rating) FILTER (WHERE d >= '2026-11-01'), 2) AS nov_avg,
       ROUND(100.0 * COUNT(*) FILTER (WHERE d >= '2026-11-01' AND rating <= 3) / COUNT(*) FILTER (WHERE d >= '2026-11-01'), 1) AS nov_low_pct,
       ROUND(100.0 * COUNT(*) FILTER (WHERE d BETWEEN '2026-10-01' AND '2026-10-31' AND rating <= 3) /
             COUNT(*) FILTER (WHERE d BETWEEN '2026-10-01' AND '2026-10-31'), 1) AS oct_low_pct
FROM r""",
     "table": """
SELECT date_trunc('week', received_at)::date AS week_from, COUNT(*) AS rated, ROUND(AVG(rating), 2) AS avg,
       ROUND(100.0 * COUNT(*) FILTER (WHERE rating <= 3) / COUNT(*), 1) AS low_pct
FROM wolt.orders WHERE status = 'DELIVERED' AND rating IS NOT NULL AND received_at::date <= '2026-11-24'
GROUP BY 1 ORDER BY 1""",
     "required": [["nov_avg", "nov_low_pct"]],
     "optional": ["aug_avg", "sep_avg", "oct_avg", "oct_low_pct"]},
]


def plain(value):
    # Numbers as JSON: Decimal → float, dates → text
    if isinstance(value, Decimal):
        return float(value)
    return value if isinstance(value, (int, float, str)) or value is None else str(value)


def compute():
    facts = {}
    with psycopg.connect(os.environ["AI_DATABASE_URL"]) as conn:  # ai_reader: read-only
        for q in QUESTIONS:
            cur = conn.execute(q["sql"])
            row = dict(zip([c.name for c in cur.description], map(plain, cur.fetchone())))
            table = []
            if "table" in q:
                cur = conn.execute(q["table"])
                cols = [c.name for c in cur.description]
                table = [dict(zip(cols, map(plain, r))) for r in cur.fetchall()]
            facts[q["n"]] = {"question": q["question"], "values": row, "table": table,
                             "required": q["required"], "optional": q["optional"], "wrong": q.get("wrong", [])}
            print(f"#{q['n']}: {row}")
    FACTS_FILE.parent.mkdir(exist_ok=True)
    FACTS_FILE.write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nSaved to {FACTS_FILE}")


def upload():
    # Creates the fixed-date dataset once. The old dataset stays as it is.
    from langsmith import Client
    client = Client()
    if client.has_dataset(dataset_name=DATASET):
        sys.exit(f"{DATASET} already exists; nothing changed")
    old = {e.metadata["n"]: e.inputs["question"] for e in client.list_examples(dataset_name=OLD_DATASET)}
    examples = [{"inputs": {"question": q["question"]},
                 "metadata": {"n": q["n"], "original_question": old[q["n"]]}} for q in QUESTIONS]
    dataset = client.create_dataset(DATASET, description=(
        "The 15 questions of tema-ops-eval with fixed dates (24 Nov 2026 = yesterday). "
        "Right answers: evals/facts.py."))
    client.create_examples(dataset_id=dataset.id, examples=examples)
    print(f"Created {DATASET} with {len(QUESTIONS)} questions")


if __name__ == "__main__":
    upload() if "--upload" in sys.argv else compute()
