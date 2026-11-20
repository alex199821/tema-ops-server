import asyncio
import hashlib
import hmac
import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from tema_ops.agent.agent import build_agent
from tema_ops.agent.voice import transcribe

load_dotenv()

app = FastAPI()
agent = build_agent()  # one agent; each phone number is its own conversation
ALLOWED_NUMBERS = set(os.environ["WHATSAPP_ALLOWED_NUMBERS"].split(","))
APP_SECRET = os.environ["WHATSAPP_APP_SECRET"].encode() 
SEND_URL = f"https://graph.facebook.com/v25.0/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
MEDIA_URL = SEND_URL.replace("/messages", "/media")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
seen_ids = set()  # Meta sometimes delivers the same message twice

# People often send one question as several quick messages ("hi", "how are you?",
# "report for yesterday"). Instead of answering each one, the bot waits until the person
# has been quiet for WAIT_SECONDS, then answers everything they sent at once.
WAIT_SECONDS = 5
waiting = {}   # phone -> messages not answered yet: ("text", body) or ("audio", media id)
timers = {}    # phone -> the pending "answer after the wait" task
locks = {}     # phone -> lock, so one person never gets two answers being made at once
tasks = set()  # keeps running tasks alive until they finish


def send_text(to, text):
    text = text.replace("**", "") 
    response = httpx.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"},
        json={"messaging_product": "whatsapp", "to": to, "type": "text",
              "text": {"body": text[:4096]}},  # WhatsApp's limit per message
    )
    response.raise_for_status()

def send_document(to, path):
    headers = {"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"}
    filename = os.path.basename(path)
    # 1. upload the file to Meta, which gives back a media id
    with open(path, "rb") as f:
        upload = httpx.post(MEDIA_URL, headers=headers,
                            data={"messaging_product": "whatsapp", "type": XLSX},
                            files={"file": (filename, f, XLSX)})
    upload.raise_for_status()
    # 2. send a message that points to that file
    response = httpx.post(SEND_URL, headers=headers, json={
        "messaging_product": "whatsapp", "to": to, "type": "document",
        "document": {"id": upload.json()["id"], "filename": filename}})
    response.raise_for_status()

def download_media(media_id):
    headers = {"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"}
    # 1. ask Meta where the file is
    info = httpx.get(f"https://graph.facebook.com/v25.0/{media_id}", headers=headers)
    info.raise_for_status()
    # 2. download it from there (that link needs the token too)
    file = httpx.get(info.json()["url"], headers=headers)
    file.raise_for_status()
    return file.content, info.json()["mime_type"]

def answer_all(phone, items):
    # Turn the collected messages into one question (voice messages become text first)
    texts, heard = [], []
    for kind, value in items:
        if kind == "text":
            texts.append(value)
            continue
        try:
            audio, mime_type = download_media(value)
            # WhatsApp says "audio/ogg; codecs=opus"; Gemini wants just "audio/ogg"
            said = transcribe(audio, mime_type.split(";")[0])
        except Exception as e:
            print("Failed to transcribe", phone, ":", e)
            send_text(phone, "ბოდიში, ხმოვანი შეტყობინება ვერ გავიგე. სცადეთ ხელახლა ან დაწერეთ.")
            continue
        texts.append(said)
        heard.append(said)
    if texts:
        answer(phone, "\n".join(texts), heard="\n".join(heard) or None)

async def answer_after_wait(phone):
    # A new message from the same person cancels this wait and starts a fresh one
    await asyncio.sleep(WAIT_SECONDS)
    # The person has been quiet long enough: take everything they sent so far
    items = waiting.pop(phone)
    del timers[phone]
    async with locks.setdefault(phone, asyncio.Lock()):
        # The agent is slow and not async, so it runs in a separate thread
        await asyncio.to_thread(answer_all, phone, items)

def answer(phone, question, heard=None):
    # Runs after Meta already got its "ok", because the agent can take 10+ seconds
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": question}]},
                              config={"configurable": {"thread_id": phone}})
        messages = result["messages"]
        reply = messages[-1].text
        if heard:  # voice message: show what we heard, so a mishearing is easy to spot
            reply = f"🎤 გავიგე: {heard}\n\n{reply}"
        send_text(phone, reply)
        # Files made for THIS question only (the memory also holds older questions' files)
        last_question = max(i for i, m in enumerate(messages) if m.type == "human")
        for message in messages[last_question:]:
            if getattr(message, "artifact", None):
                send_document(phone, message.artifact)
    except Exception as e:
        print("Failed to answer", phone, ":", e)
        send_text(phone, "ბოდიში, პასუხი ვერ მოვამზადე. სცადეთ ხელახლა.")

def is_from_meta(body, signature):
    # Meta signs every webhook call with our app secret. Without the secret,
    # nobody can produce a matching signature, so fake messages are rejected.
    expected = "sha256=" + hmac.new(APP_SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")  # safe comparison


# Meta checks the URL once, when you click "Verify and save":
# it sends our verify token and expects its "challenge" number back.
@app.get("/webhook")
def verify(request: Request):
    params = request.query_params
    if (params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == os.environ["WHATSAPP_VERIFY_TOKEN"]):
        return PlainTextResponse(params.get("hub.challenge"))
    raise HTTPException(status_code=403)


# Meta sends every incoming WhatsApp message here (a POST with JSON)
@app.post("/webhook")
async def receive(request: Request):
    body = await request.body()  # the raw bytes, exactly as Meta signed them
    if not is_from_meta(body, request.headers.get("X-Hub-Signature-256")):
        print("Rejected a webhook call without a valid Meta signature")
        raise HTTPException(status_code=403)
    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            for message in change["value"].get("messages", []):
                if message["id"] in seen_ids:
                    continue
                seen_ids.add(message["id"])
                phone = message["from"]
                if phone not in ALLOWED_NUMBERS:
                    print("Ignored a message from an unknown number:", phone)
                    continue
                if message["type"] == "text":
                    waiting.setdefault(phone, []).append(("text", message["text"]["body"]))
                elif message["type"] == "audio":
                    waiting.setdefault(phone, []).append(("audio", message["audio"]["id"]))
                else:
                    continue
                # (Re)start the wait: answer only after WAIT_SECONDS without a new message
                if phone in timers:
                    timers[phone].cancel()
                task = asyncio.create_task(answer_after_wait(phone))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
                timers[phone] = task
    return {"ok": True}
