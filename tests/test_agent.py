# Checks how the agent runs its tools, with a fake model instead of Gemini (no cost, no network).
# run_sql still runs for real, so like test_tools.py this needs AI_DATABASE_URL (on the Mac, the tunnel).
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from tema_ops.agent import agent as agent_module


class FakeModel(GenericFakeChatModel):
    # Answers with the prepared messages, one per call, and remembers what it was sent.
    seen: list = []

    def bind_tools(self, tools, **kwargs):
        return self  # the fake model doesn't need the tool list

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


def test_two_queries_in_one_step(monkeypatch):
    # The model asks for 2 queries at once (Gemini can do this, so the agent must handle it).
    # Both must run before the model is called again: 2 model calls in total, not 3.
    fake = FakeModel(messages=iter([
        AIMessage(content="", tool_calls=[
            {"name": "run_sql", "args": {"query": "SELECT 1 AS wolt"}, "id": "1"},
            {"name": "run_sql", "args": {"query": "SELECT 2 AS store"}, "id": "2"},
        ]),
        AIMessage(content="done"),
    ]))
    monkeypatch.setattr(agent_module, "get_model", lambda **kwargs: fake)
    monkeypatch.setattr(agent_module, "today_facts", lambda: "Today is Wednesday, 2026-11-25.")

    result = agent_module.build_agent(remember=False).invoke(
        {"messages": [{"role": "user", "content": "how were sales yesterday?"}]})

    assert [m.type for m in result["messages"]] == ["human", "ai", "tool", "tool", "ai"]
    assert "wolt" in result["messages"][2].content and "store" in result["messages"][3].content
    assert len(fake.seen) == 2

    # The instructions and today's facts reach the model in its system prompt, the facts at the end
    system_prompt = fake.seen[0][0].content
    assert system_prompt.startswith(agent_module.INSTRUCTIONS)
    assert system_prompt.endswith("Today is Wednesday, 2026-11-25.")
