import asyncio
import hashlib
import hmac
import os
import time
from datetime import datetime

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from tema_ops.agent.agent import MAX_QUESTIONS, build_agent
from tema_ops.agent.voice import transcribe
from tema_ops.notify import alert
from tema_ops.whatsapp.history import last_questions, save_answer

load_dotenv()

WHATSAPP_RULES = """Your reply is read in WhatsApp on a phone.
- WhatsApp shows *bold*, _italic_ and lists ("- " or "1. "). It does not show tables,
  # headings or **double stars**, so never use them.
- Start with the answer itself (the key number), then the details.
- Rows of data (per day, per branch, ...): one short line per row, for example:
  *13 Nov*: 101 (Sanapiro 31 · Lisi 43 · Dolabauri 27)"""

app = FastAPI()
agent = build_agent(WHATSAPP_RULES, remember=False)  # memory is in the database (history.py)
ALLOWED_NUMBERS = set(os.environ["WHATSAPP_ALLOWED_NUMBERS"].split(","))
APP_SECRET = os.environ["WHATSAPP_APP_SECRET"].encode() 
SEND_URL = f"https://graph.facebook.com/v25.0/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
MEDIA_URL = SEND_URL.replace("/messages", "/media")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TRIES = 3  # Meta's servers sometimes fail for a moment, so every call to Meta gets 3 tries
seen_ids = set()  # Meta sometimes delivers the same message twice
SORRY = "ბოდიში, რაღაც შეფერხდა და პასუხი ვერ მოგწერეთ. სცადეთ ხელახლა."
VOICE_SORRY = "ბოდიში, ხმოვანი შეტყობინება ვერ გავიგე. სცადეთ ხელახლა ან დაწერეთ."
BUSY = ("⏳ Google-ის სერვერები ახლა გადატვირთულია, ამიტომ პასუხს ცოტა მეტი დრო სჭირდება. "
        "რამდენიმე წუთში მოგწერთ, ხელახლა გაგზავნა საჭირო არ არის.")

# Google sometimes gets overloaded for a few minutes: then every try of a question fails
# (26 Nov: 4 tries, 170 s, all "504 DEADLINE_EXCEEDED"; the same question 3 min later took 23 s).
# For these errors the bot says so (once), waits RETRY_AFTER seconds and tries again, up to BUSY_RETRIES times.
GOOGLE_BUSY = ("DEADLINE_EXCEEDED", "RESOURCE_EXHAUSTED", "UNAVAILABLE")  # Google's 504, 429, 503
RETRY_AFTER = 120
BUSY_RETRIES = 2


def google_busy(error):
    return any(word in str(error) for word in GOOGLE_BUSY)

# People often send one question as several quick messages ("hi", "how are you?",
# "report for yesterday"). The bot answers only after the person has been quiet for
# WAIT_SECONDS. If more messages arrive while it is still thinking, it throws that answer
# away (it is never sent or saved) and answers everything together.
WAIT_SECONDS = 5
waiting = {}       # phone -> messages not taken yet: ("text", body) or ("audio", media id)
last_message = {}  # phone -> when the person's latest message arrived (for the waiting)
asked_at = {}      # phone -> the same, as a clock time (saved with the answer)
workers = {}       # phone -> the task answering this person (at most one per person)


def call_meta(method, url, **kwargs):
    # Error 5xx, 429 (too many requests) or no connection usually passes within seconds:
    # wait and try again. Any other error (e.g. 400: Meta refuses our message) would fail
    # the same way again, so it is raised at once.
    headers = {"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"}
    for attempt in range(1, TRIES + 1):
        try:
            response = httpx.request(method, url, headers=headers, timeout=30, **kwargs)
        except httpx.TransportError as e:
            problem = f"no connection ({e!r})"
        else:
            if response.status_code < 500 and response.status_code != 429:
                if response.is_error:  # Meta's own text says why, e.g. a bad token
                    print("Meta refused:", response.status_code, response.text[:500])
                response.raise_for_status()
                return response
            problem = f"{response.status_code} {response.text[:500]}"
        print(f"Meta call failed (try {attempt} of {TRIES}):", problem)
        if attempt < TRIES:
            time.sleep(2 * attempt)  # 2 s, then 4 s
    raise RuntimeError(f"{method} {url} failed {TRIES} times, last: {problem}")

def send_text(to, text):
    text = text.replace("**", "")
    call_meta("POST", SEND_URL, json={"messaging_product": "whatsapp", "to": to, "type": "text",
                                      "text": {"body": text[:4096]}})  # WhatsApp's limit

def send_document(to, path):
    filename = os.path.basename(path)
    with open(path, "rb") as f:
        content = f.read()  # read once, so a second try uploads the same bytes again
    # 1. upload the file to Meta, which gives back a media id
    upload = call_meta("POST", MEDIA_URL, data={"messaging_product": "whatsapp", "type": XLSX},
                       files={"file": (filename, content, XLSX)})
    # 2. send a message that points to that file
    call_meta("POST", SEND_URL, json={
        "messaging_product": "whatsapp", "to": to, "type": "document",
        "document": {"id": upload.json()["id"], "filename": filename}})

def download_media(media_id):
    # 1. ask Meta where the file is
    info = call_meta("GET", f"https://graph.facebook.com/v25.0/{media_id}").json()
    # 2. download it from there (that link needs the token too)
    file = call_meta("GET", info["url"])
    return file.content, info["mime_type"]

def give_up(phone, what, error, apology=SORRY):
    # Never leave the person waiting in silence, and tell the developer at once
    print("Failed to", what, phone, ":", error)
    try:
        alert("WhatsApp bot failed", f"Could not {what} for {phone}.\n\n{error!r}")
    except Exception as e:
        print("Failed to email the alert:", e)
    try:
        send_text(phone, apology)
    except Exception as e:  # Meta itself is down: nothing more we can do
        print("Failed to send the apology", phone, ":", e)

def tell_busy(phone):
    try:
        send_text(phone, BUSY)
    except Exception as e:  # the retry still happens; the person just doesn't get the notice
        print("Failed to send the busy message", phone, ":", e)

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
            give_up(phone, "understand a voice message", e, VOICE_SORRY)
            continue
        texts.append(said)
        heard.append(said)
    return texts, heard

def asked_label(asked):
    # "[asked Sat 21 Nov 2026, 22:45]": tells the AI how old an earlier answer is
    return f"[asked {asked:%a} {asked.day} {asked:%b %Y}, {asked:%H:%M}]"

def think(phone, question):
    # The AI gets the person's earlier questions and answers (from the database) and the
    # new question. MAX_QUESTIONS counts the new question too.
    # Each earlier question carries the date and time it was asked. Without it, the AI once
    # reused a 4-day-old "last 3 days" answer for a new "recent days" question, without querying.
    messages = []
    for asked, old_question, old_answer in last_questions(phone, MAX_QUESTIONS - 1):
        messages.append({"role": "user", "content": f"{asked_label(asked)} {old_question}"})
        messages.append({"role": "assistant", "content": old_answer})
    messages.append({"role": "user", "content": question})
    result = agent.invoke({"messages": messages})
    messages = result["messages"]
    # Files made for this question (the earlier answers from the database have none)
    files = [m.artifact for m in messages if getattr(m, "artifact", None)]
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
        texts, heard = [], []
        retries = 0  # whole-question retries after "Google is busy" errors
        while True:
            await wait_until_quiet(phone)
            new_texts, new_heard = await asyncio.to_thread(to_text, phone, waiting.pop(phone, []))
            texts += new_texts
            heard += new_heard
            if not texts:
                return
            # All messages so far are one question (a voice message = the text we heard)
            question, asked = "\n".join(texts), asked_at[phone]
            try:
                reply, files = await asyncio.to_thread(think, phone, question)
            except Exception as e:
                if google_busy(e) and retries < BUSY_RETRIES:
                    # Tell the person (only the first time), wait, and ask again. Messages that
                    # arrive meanwhile are answered together with this question (the loop picks them up).
                    retries += 1
                    print(f"Google is busy, retry {retries} of {BUSY_RETRIES} in {RETRY_AFTER} s:", phone, e)
                    if retries == 1:
                        await asyncio.to_thread(tell_busy, phone)
                    await asyncio.sleep(RETRY_AFTER)
                    continue
                await asyncio.to_thread(give_up, phone, "prepare an answer", e)
                return
            # Last check before sending: did the person write more while the bot was thinking?
            if waiting.get(phone):
                print("New message while answering, answering everything together:", phone)
                continue  # this answer is never sent or saved, so it is forgotten
            try:
                await asyncio.to_thread(send_answer, phone, reply, files, heard)
            except Exception as e:  # Meta failed even after its retries
                await asyncio.to_thread(give_up, phone, "send the answer", e)
                return
            # Saved only once it was sent: the AI's answer, without the "🎤 heard" line
            try:
                await asyncio.to_thread(save_answer, phone, asked, question, reply)
            except Exception as e:  # the person got the answer; only the bot's memory of it is lost
                print("Failed to save the answer", phone, ":", e)
            return
    except Exception as e:  # anything unexpected
        await asyncio.to_thread(give_up, phone, "answer", e)
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
                asked_at[phone] = datetime.now()
                if phone not in workers:  # otherwise the running one picks the message up
                    start_worker(phone)
    return {"ok": True}
