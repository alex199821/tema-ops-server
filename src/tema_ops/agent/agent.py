from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware, wrap_model_call
from langgraph.checkpoint.memory import InMemorySaver

from tema_ops.agent.model import get_model
from tema_ops.agent.tools import get_wolt_report, run_sql
from tema_ops.agent.tools import run_sql

SRC = Path(__file__).parent.parent  # src/tema_ops/

INSTRUCTIONS = """You answer questions about Tema's business data.
To get data, write a PostgreSQL query and run it with the run_sql tool.
The glossaries below describe the tables, columns and business rules.
Use only the tables and columns they describe, and follow their rules.
If the glossaries don't cover what a question needs, say so instead of guessing.
Every number in your answer must come from a query result. Never guess numbers.
Answer in the language of the question. Keep answers short."""

MAX_QUESTIONS = 5

def what_ai_reads(messages):
    # The last MAX_QUESTIONS questions with their final answers, plus every step of the
    # current question. Older SQL steps and result tables are left out: they made the
    # AI's input about 40% bigger (slower, costlier) and follow-ups query fresh data anyway.
    # (The full conversation stays stored; this only decides what the AI is shown.)
    questions = [i for i, m in enumerate(messages) if m.type == "human"]
    if not questions:
        return messages
    start = questions[-MAX_QUESTIONS] if len(questions) > MAX_QUESTIONS else 0
    current = questions[-1]
    older = [m for m in messages[start:current]
             if m.type == "human" or (m.type == "ai" and not m.tool_calls)]
    return older + messages[current:]

@wrap_model_call
def keep_last_questions(request, handler):
    return handler(request.override(messages=what_ai_reads(request.messages)))


def load_glossaries():
    # Every department folder has a glossary.md. agent/ comes first (company-wide rules).
    files = sorted(SRC.glob("*/glossary.md"))
    return "\n\n".join(f.read_text(encoding="utf-8") for f in files)


def build_agent(channel_rules="", remember=True):
    # channel_rules: how answers must look where they are read (e.g. WhatsApp on a phone)
    # remember=True: the agent itself remembers earlier questions, in RAM only (lost when the
    #   program stops). For the terminal chat at the bottom of this file.
    # remember=False: the agent remembers nothing between questions. The WhatsApp bot uses
    #   this: it saves every answer to the database right after sending it, and hands the
    #   agent the earlier questions and answers itself (app.py, think).
    parts = [INSTRUCTIONS, channel_rules, load_glossaries()]
    return create_agent(
        get_model(),
        tools=[run_sql, get_wolt_report],
        system_prompt="\n\n".join(part for part in parts if part),
        middleware=[keep_last_questions, ModelFallbackMiddleware(get_model(priority=True))],
        checkpointer=InMemorySaver() if remember else None,
    )


if __name__ == "__main__":
    agent = build_agent()
    config = {"configurable": {"thread_id": "terminal"}}  # which conversation
    seen = 0  # how many messages we already printed
    while True:
        question = input("\nQuestion (empty to quit): ").strip()
        if not question:
            break
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": question}]}, config=config)
        except Exception as e:
            print("Failed, try again:", e)
            continue
        new_messages = result["messages"][seen:]
        seen = len(result["messages"])
        for message in new_messages:
            for call in getattr(message, "tool_calls", []):
                if call["name"] == "run_sql":
                    print("SQL:", call["args"]["query"])
            if getattr(message, "artifact", None):
                print("File:", message.artifact)
        print(result["messages"][-1].text)