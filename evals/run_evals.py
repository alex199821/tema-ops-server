"""Asks the eval questions one by one to the WhatsApp agent and times every answer.

Usage: uv run python evals/run_evals.py <run name> [dataset]
  dataset: tema-ops-eval-fixed (default: fixed dates, right answers in evals/facts.py)
           or tema-ops-eval (the owner's original wording, with "yesterday" etc.)
Afterwards: uv run python evals/check_run.py <run name> compares the answers with the facts.
"""
import sys

from langsmith import evaluate

from tema_ops.whatsapp.app import agent  # the same agent the WhatsApp bot uses


def ask(inputs):
    # LangSmith calls this once per question and times it
    result = agent.invoke({"messages": [{"role": "user", "content": inputs["question"]}]})
    return {"answer": result["messages"][-1].text}


if __name__ == "__main__":
    results = evaluate(
        ask,                          # the function above
        data=sys.argv[2] if len(sys.argv) > 2 else "tema-ops-eval-fixed",  # the 15 questions in LangSmith
        # name of this run in LangSmith, e.g. "fix-1a-…" (from the command line; default "baseline")
        experiment_prefix=sys.argv[1] if len(sys.argv) > 1 else "baseline",
        max_concurrency=0,            # one question at a time, like a real person
    )

    # How long each answer took: when it ended minus when it started
    times = [(row["run"].end_time - row["run"].start_time).total_seconds() for row in results]
    print(f"Average reply time: {sum(times) / len(times):.1f} s over {len(times)} questions")