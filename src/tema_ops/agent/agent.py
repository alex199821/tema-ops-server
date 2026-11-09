from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware

from tema_ops.agent.model import get_model
from tema_ops.agent.tools import run_sql

SRC = Path(__file__).parent.parent  # src/tema_ops/

INSTRUCTIONS = """You answer questions about Tema's business data.
To get data, write a PostgreSQL query and run it with the run_sql tool.
The glossaries below describe the tables, columns and business rules.
Use only the tables and columns they describe, and follow their rules.
If the glossaries don't cover what a question needs, say so instead of guessing.
Every number in your answer must come from a query result. Never guess numbers.
Answer in the language of the question. Keep answers short."""


def load_glossaries():
    # Every department folder has a glossary.md. agent/ comes first (company-wide rules).
    files = sorted(SRC.glob("*/glossary.md"))
    return "\n\n".join(f.read_text(encoding="utf-8") for f in files)


def build_agent():
    return create_agent(
        get_model(),
        tools=[run_sql],
        system_prompt=INSTRUCTIONS + "\n\n" + load_glossaries(),
        middleware=[ModelFallbackMiddleware(get_model(priority=True))],
    )


if __name__ == "__main__":
    agent = build_agent()
    while True:
        question = input("\nQuestion (empty to quit): ").strip()
        if not question:
            break
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": question}]})
        except Exception as e:
            print("Failed, try again:", e)
            continue
        # Show the SQL the AI ran, so we can check it
        for message in result["messages"]:
            for call in getattr(message, "tool_calls", []):
                print("SQL:", call["args"]["query"])
        print(result["messages"][-1].text)