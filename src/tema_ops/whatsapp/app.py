import asyncio
import hashlib
import hmac
import os
import time

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from tema_ops.agent.agent import build_agent
from tema_ops.agent.voice import transcribe

load_dotenv()

WHATSAPP_RULES = """Your reply is read in WhatsApp on a phone.
- WhatsApp shows *bold*, _italic_ and lists ("- " or "1. "). It does not show tables,
  # headings or **double stars**, so never use them.
- Start with the answer itself (the key number), then the details.
- Rows of data (per day, per branch, ...): one short line per row, for example:
  *13 Nov*: 101 (Sanapiro 31 · Lisi 43 · Dolabauri 27)"""

app = FastAPI()
agent = build_agent(WHATSAPP_RULES)  # one agent; each phone number is its own conversation
ALLOWED_NUMBERS = set(os.environ["WHATSAPP_ALLOWED_NUMBERS"].split(","))
APP_SECRET = os.environ["WHATSAPP_APP_SECRET"].encode() 
SEND_URL = f"https://graph.facebook.com/v25.0/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
MEDIA_URL = SEND_URL.replace("/messages", "/media")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
seen_ids = set()  # Meta sometimes delivers the same message twice

# People often send one question as several quick messages ("hi", "how are you?",
# "report for yesterday"). The bot answers only after the person has been quiet for
# WAIT_SECONDS. If more messages arrive while it is still thinking, it throws that answer
# away (and out of its memory) and answers everything together.
WAIT_SECONDS = 5
waiting = {}       # phone -> messages not taken yet: ("text", body) or ("audio", media id)
last_message = {}  # phone -> when the person's latest message arrived
workers = {}       # phone -> the task answering this person (at most one per person)


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

def to_text(phone, items):
    # Voice messages become text. Returns all texts, and separately what we heard in voice
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
    return texts, heard

def memory_point(phone):
    # Where this person's conversation stands right now (None = no conversation yet)
    state = agent.get_state({"configurable": {"thread_id": phone}})
    return state.config["configurable"].get("checkpoint_id")

def think(phone, question, start):
    # Runs the agent from memory point `start`, so an answer we threw away is never remembered
    config = {"configurable": {"thread_id": phone}}
    if start:
        config["configurable"]["checkpoint_id"] = start
    else:
        agent.checkpointer.delete_thread(phone)  # there was no conversation before: start empty
    result = agent.invoke({"messages": [{"role": "user", "content": question}]}, config=config)
    messages = result["messages"]
    # Files made for THIS question only (the memory also holds older questions' files)
    last_question = max(i for i, m in enumerate(messages) if m.type == "human")
    files = [m.artifact for m in messages[last_question:] if getattr(m, "artifact", None)]
    return messages[-1].text, files

def send_answer(phone, reply, files, heard):
    if heard:  # voice message: show what we heard, so a mishearing is easy to spot
        heard_text = "\n".join(heard)
        reply = f"🎤 გავიგე: {heard_text}\n\n{reply}"
    send_text(phone, reply)
    for path in files:
        send_document(phone, path)

async def wait_until_quiet(phone):
    # Sleep until the person has sent nothing for WAIT_SECONDS
    while (quiet := time.monotonic() - last_message[phone]) < WAIT_SECONDS:
        await asyncio.sleep(WAIT_SECONDS - quiet)

async def answer_person(phone):
    # Slow work (voice, the agent, sending) runs in a separate thread, so the bot keeps
    # receiving messages meanwhile
    try:
        start = await asyncio.to_thread(memory_point, phone)
        texts, heard = [], []
        while True:
            await wait_until_quiet(phone)
            new_texts, new_heard = await asyncio.to_thread(to_text, phone, waiting.pop(phone, []))
            texts += new_texts
            heard += new_heard
            if not texts:
                return
            try:
                reply, files = await asyncio.to_thread(think, phone, "\n".join(texts), start)
            except Exception as e:
                print("Failed to answer", phone, ":", e)
                await asyncio.to_thread(send_text, phone, "ბოდიში, პასუხი ვერ მოვამზადე. სცადეთ ხელახლა.")
                return
            # Last check before sending: did the person write more while the bot was thinking?
            if waiting.get(phone):
                print("New message while answering, answering everything together:", phone)
                continue  # the next run starts from `start` again, so this answer is forgotten
            await asyncio.to_thread(send_answer, phone, reply, files, heard)
            return
    except Exception as e:
        print("Failed to answer", phone, ":", e)
    finally:
        del workers[phone]
        if waiting.get(phone):  # a message came in while the answer was being sent
            start_worker(phone)

def start_worker(phone):
    workers[phone] = asyncio.create_task(answer_person(phone))

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
                last_message[phone] = time.monotonic()
                if phone not in workers:  # otherwise the running one picks the message up
                    start_worker(phone)
    return {"ok": True}
