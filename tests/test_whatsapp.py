import asyncio
import os
import time
from datetime import datetime

import httpx
import pytest

# Fake WhatsApp settings, so no test can ever use the real token or phone number
os.environ["WHATSAPP_TOKEN"] = "test-token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "test-number"
os.environ["WHATSAPP_APP_SECRET"] = "test-secret"
os.environ["WHATSAPP_ALLOWED_NUMBERS"] = "995500000000"

from tema_ops.whatsapp import app  # noqa: E402  (must come after the fake settings)

PHONE = "995500000000"


@pytest.fixture
def meta(monkeypatch):
    # Replaces Meta: each call takes the next planned answer (a status code or an error)
    # and is recorded, so a test can check what was sent and how often.
    planned, calls = [], []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        answer = planned.pop(0) if planned else 200
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer, json={"id": "media-1"}, request=httpx.Request(method, url))

    monkeypatch.setattr(app.httpx, "request", fake_request)
    monkeypatch.setattr(app.time, "sleep", lambda seconds: None)  # no real waiting
    return planned, calls


def sent_texts(calls):
    return [c["json"]["text"]["body"] for c in calls if c.get("json", {}).get("type") == "text"]


def test_meta_fails_for_a_moment_and_the_retry_delivers(meta):
    planned, calls = meta
    planned += [500]
    app.send_text(PHONE, "hello")
    assert sent_texts(calls) == ["hello", "hello"]


def test_meta_keeps_failing_and_we_stop_after_three_tries(meta):
    planned, calls = meta
    planned += [500, 500, 500]
    with pytest.raises(RuntimeError):
        app.send_text(PHONE, "hello")
    assert len(calls) == 3


def test_meta_refuses_the_message_and_we_do_not_retry(meta):
    planned, calls = meta
    planned += [400]
    with pytest.raises(httpx.HTTPStatusError):
        app.send_text(PHONE, "hello")
    assert len(calls) == 1


def test_lost_connection_and_too_many_requests_are_retried(meta):
    planned, calls = meta
    planned += [httpx.ConnectError("no internet"), 429]
    app.send_text(PHONE, "hello")
    assert len(calls) == 3


def test_file_upload_retried_with_the_same_file(meta, tmp_path):
    planned, calls = meta
    report = tmp_path / "report.xlsx"
    report.write_bytes(b"excel bytes")
    planned += [500]  # the first upload fails
    app.send_document(PHONE, report)
    uploads = [c for c in calls if c["url"] == app.MEDIA_URL]
    assert [u["files"]["file"][1] for u in uploads] == [b"excel bytes", b"excel bytes"]
    assert calls[-1]["json"]["document"]["id"] == "media-1"


def run_answer(monkeypatch, think):
    # Runs the bot's answering for one text question; returns the alerts and saved answers
    alerts, saved = [], []
    monkeypatch.setattr(app, "think", think)
    monkeypatch.setattr(app, "alert", lambda subject, body: alerts.append(body))
    monkeypatch.setattr(app, "save_answer", lambda *args: saved.append(args))
    app.waiting[PHONE] = [("text", "question")]
    app.last_message[PHONE] = time.monotonic() - 60  # the person stopped typing long ago
    app.asked_at[PHONE] = datetime.now()
    app.workers[PHONE] = None
    asyncio.run(app.answer_person(PHONE))
    return alerts, saved


def test_answer_cannot_be_sent_so_the_person_gets_an_apology(meta, monkeypatch):
    # What happened on 25 Nov: the answer was ready, but Meta kept returning 500
    planned, calls = meta
    planned += [500, 500, 500]  # all 3 tries of the answer fail, the apology goes through
    alerts, saved = run_answer(monkeypatch, lambda phone, question: ("the answer", []))
    assert sent_texts(calls) == ["the answer"] * 3 + [app.SORRY]
    assert len(alerts) == 1      # the developer hears about it at once
    assert saved == []           # not saved: the person never saw it
    assert PHONE not in app.workers


def test_answer_cannot_be_prepared_so_the_person_gets_an_apology(meta, monkeypatch):
    planned, calls = meta

    def broken_think(phone, question):
        raise RuntimeError("Gemini is down")

    alerts, saved = run_answer(monkeypatch, broken_think)
    assert sent_texts(calls) == [app.SORRY]
    assert len(alerts) == 1
    assert saved == []


def test_normal_answer_is_sent_once_and_saved(meta, monkeypatch):
    planned, calls = meta
    alerts, saved = run_answer(monkeypatch, lambda phone, question: ("the answer", []))
    assert sent_texts(calls) == ["the answer"]
    assert alerts == []
    assert len(saved) == 1


def test_earlier_questions_carry_when_they_were_asked(monkeypatch):
    # The AI must see how old an earlier answer is, so it doesn't reuse an out-of-date one
    # (it once answered "recent days" with a 4-day-old "last 3 days" answer, without querying).
    from langchain_core.messages import AIMessage

    monkeypatch.setattr(app, "last_questions", lambda phone, count: [
        (datetime(2026, 11, 21, 22, 45), "any ratings in the last 3 days?", "18–20 Nov: 32 ratings")])
    seen = []

    class FakeAgent:
        def invoke(self, state):
            seen.extend(state["messages"])
            return {"messages": [AIMessage(content="fresh answer")]}

    monkeypatch.setattr(app, "agent", FakeAgent())
    reply, files = app.think(PHONE, "როგორი შეფასებები გვაქ ბოლო დღეებში?")

    assert seen[0] == {"role": "user", "content": "[asked Sat 21 Nov 2026, 22:45] any ratings in the last 3 days?"}
    assert seen[1] == {"role": "assistant", "content": "18–20 Nov: 32 ratings"}
    assert seen[2] == {"role": "user", "content": "როგორი შეფასებები გვაქ ბოლო დღეებში?"}  # the new one: no label
    assert (reply, files) == ("fresh answer", [])


# The error Google gave on 26 Nov 05:12, on every try of the question
BUSY_ERROR = RuntimeError("504 DEADLINE_EXCEEDED. {'error': {'code': 504, 'message': "
                          "'Deadline expired before operation could complete.'}}")


def test_google_busy_gets_one_notice_and_retries(meta, monkeypatch):
    # 26 Nov 05:12: Google failed every try; the same question asked 3 minutes later worked.
    # Here it fails twice, then the second retry works.
    planned, calls = meta
    monkeypatch.setattr(app, "RETRY_AFTER", 0)  # no real 2-minute wait in the test
    results = [BUSY_ERROR, BUSY_ERROR, ("the answer", [])]

    def think(phone, question):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    alerts, saved = run_answer(monkeypatch, think)
    assert sent_texts(calls) == [app.BUSY, "the answer"]  # the notice only once
    assert alerts == []      # it worked in the end: nothing to alert about
    assert len(saved) == 1


def test_google_still_busy_after_the_retries_gets_the_apology(meta, monkeypatch):
    planned, calls = meta
    monkeypatch.setattr(app, "RETRY_AFTER", 0)
    tries = []

    def think(phone, question):
        tries.append(question)
        raise BUSY_ERROR

    alerts, saved = run_answer(monkeypatch, think)
    assert len(tries) == 3   # the first try and 2 retries, no more
    assert sent_texts(calls) == [app.BUSY, app.SORRY]
    assert len(alerts) == 1  # now the developer hears about it
    assert saved == []
