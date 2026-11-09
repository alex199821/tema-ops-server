import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

load_dotenv()

app = FastAPI()


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
    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            for message in change["value"].get("messages", []):
                if message["type"] == "text":
                    print("From:", message["from"], "| Text:", message["text"]["body"])
    return {"ok": True}