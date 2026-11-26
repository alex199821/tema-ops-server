# Tests never send traces to LangSmith. (.env turns tracing on for the real bot, and a traced
# fake model even breaks: LangSmith reads its list of prepared answers before the test can use it.)
import langsmith
import pytest


@pytest.fixture(autouse=True)
def no_langsmith_traces():
    with langsmith.tracing_context(enabled=False):
        yield
