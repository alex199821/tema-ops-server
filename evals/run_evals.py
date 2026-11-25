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
        data="tema-ops-eval",         # the 15 questions in LangSmith
        # name of this run in LangSmith, e.g. "fix-1a-…" (from the command line; default "baseline")
        experiment_prefix=sys.argv[1] if len(sys.argv) > 1 else "baseline",
        max_concurrency=0,            # one question at a time, like a real person
    )

    # How long each answer took: when it ended minus when it started
    times = [(row["run"].end_time - row["run"].start_time).total_seconds() for row in results]
    print(f"Average reply time: {sum(times) / len(times):.1f} s over {len(times)} questions")