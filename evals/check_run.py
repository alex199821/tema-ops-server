"""Compares the answers of eval runs with the facts from evals/facts.py (read-only: it only reads LangSmith).

For every question it looks for the right numbers in the answer text:
  ok       every required number is there
  missing  a required number isn't there (shows the right value)
  wrong    a number that means a known mistake is there (e.g. orders + receipts added up)
  read     open-ended question: nothing is required, read the answer next to the facts
  FAILED   no answer at all (e.g. Google timed out)
Finding a number doesn't prove the whole answer is right, and a missing one can be a fair rounding:
it's a quick first check. Read the answers marked missing or wrong.

Usage: uv run python evals/check_run.py <run name> [<run name> ...]
  e.g. uv run python evals/check_run.py flash-3.8 flash-3.7 gemini-4-hydrogen
  -v   also print every answer that isn't ok
"""
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client

load_dotenv()

FACTS = {int(n): f for n, f in json.loads(Path("data/eval_facts.json").read_text(encoding="utf-8")).items()}
# In the original dataset these say "yesterday" / "last N days": their facts only fit runs made on
# 25 Nov 2026 (Tbilisi), when "yesterday" was 24 Nov
RELATIVE = {1, 2, 3, 6, 7, 8, 9}


def rounded(v, places):
    # Rounds like people do (923.05 → 923.1), not like floats sometimes do
    return str(Decimal(str(v)).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP))


def patterns(value):
    # The ways a number can appear in an answer: 2991.5 → "2991.5", "2991.50";
    # 982.02 → also "982.0" and "982"; 923.05 → also "923.1"
    v = abs(value)
    if v == int(v):
        return [rf"(?<![\d.]){int(v)}(?:\.0+)?(?!\d|\.\d)"]
    exact = f"{v:.2f}".rstrip("0")
    found = [rf"(?<![\d.]){re.escape(exact)}0*(?!\d)", rf"(?<![\d.]){re.escape(rounded(v, 1))}(?!\d)"]
    if v >= 100:  # big numbers are often rounded to whole numbers; small ones would match by chance
        found.append(rf"(?<![\d.]){rounded(v, 0)}(?!\d|\.\d)")
    return found


def has(answer, value):
    return value is not None and any(re.search(p, answer) for p in patterns(value))


def check(n, answer):
    facts = FACTS[n]
    values = facts["values"]
    if not answer:
        return "FAILED", []
    bad = [name for name in facts["wrong"] if has(answer, values[name])]
    if bad:
        return "wrong", [f"{name}={values[name]}" for name in bad]
    if not facts["required"]:
        return "read", []
    missing = [group for group in facts["required"] if not any(has(answer, values[name]) for name in group)]
    if missing:
        return "missing", [" or ".join(f"{name}={values[name]}" for name in group) for group in missing]
    return "ok", []


def normalize(text):
    # "2,991.50" / "2 991.50" → "2991.50"
    return re.sub(r"(?<=\d)[,\s ](?=\d{3}(?!\d))", "", text or "")


def load_run(client, name):
    # The newest experiment whose name starts with this run name
    projects = [p for p in client.list_projects(name_contains=name) if p.name.startswith(name)]
    if not projects:
        sys.exit(f"No run called {name}")
    project = max(projects, key=lambda p: p.start_time)
    dataset = client.read_dataset(dataset_id=project.reference_dataset_id)
    n_of = {e.id: e.metadata["n"] for e in client.list_examples(dataset_id=dataset.id)}
    runs = list(client.list_runs(project_id=project.id))
    calls = defaultdict(int)
    for r in runs:
        if r.run_type == "llm":
            calls[r.trace_id] += 1
    answers = {}
    for r in runs:
        if r.parent_run_id is None and r.reference_example_id in n_of:
            seconds = (r.end_time - r.start_time).total_seconds() if r.end_time else None
            answers[n_of[r.reference_example_id]] = {
                "answer": normalize((r.outputs or {}).get("answer")), "seconds": seconds, "calls": calls[r.trace_id],
                "tbilisi_day": (r.start_time + timedelta(hours=4)).date().isoformat()}
    return project.name, dataset.name, answers


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv
    if not names:
        sys.exit(__doc__)
    client = Client()
    table = {}
    for name in names:
        full, dataset, answers = load_run(client, name)
        print(f"\n=== {full}  (dataset {dataset})")
        results = {}
        for n in sorted(FACTS):
            a = answers.get(n)
            if a is None:
                results[n] = ("not run", [])
            elif dataset != "tema-ops-eval-fixed" and n in RELATIVE and a["tbilisi_day"] != "2026-11-25":
                results[n] = ("other date", [])  # "yesterday" wasn't 24 Nov for this run
            else:
                results[n] = check(n, a["answer"])
            status, detail = results[n]
            time = f"{a['seconds']:5.1f} s, {a['calls']} calls" if a and a["seconds"] is not None else ""
            print(f"  #{n:<2} {status:10} {time:20} {'; '.join(detail)}")
            if verbose and status in ("missing", "wrong") and a:
                print(f"        answer: {a['answer'][:600]}")
        done = [a for a in answers.values() if a["seconds"] is not None]
        ok = sum(1 for s, _ in results.values() if s == "ok")
        checked = sum(1 for s, _ in results.values() if s in ("ok", "missing", "wrong", "FAILED"))
        avg = statistics.mean(a["seconds"] for a in done) if done else 0
        med = statistics.median(a["seconds"] for a in done) if done else 0
        calls = statistics.mean(a["calls"] for a in done) if done else 0
        print(f"  → {ok}/{checked} ok · avg {avg:.1f} s · median {med:.1f} s · {calls:.1f} calls/question")
        table[full] = (ok, checked, avg, med, calls)
    if len(table) > 1:
        print("\nrun                              ok      avg     median  calls/q")
        for full, (ok, checked, avg, med, calls) in table.items():
            print(f"{full:32} {ok:>2}/{checked:<2}  {avg:6.1f} s {med:6.1f} s {calls:6.1f}")


if __name__ == "__main__":
    main()
