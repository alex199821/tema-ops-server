import base64

from tema_ops.agent.model import get_model

TRANSCRIBE_PROMPT = """Write down exactly what is said in this voice message, in the language it was spoken.
Output only the spoken words, nothing else. Do not answer the question and do not translate it.
The speaker works at Tema, a fast-food chain in Tbilisi. Words you may hear: the branches
სანაპირო, ლისი, დოლაბაური; Wolt; products like ქათმის როლი, პიტა ცეზარი, ბურგერი, კარტოფილი ფრი."""

model = get_model()


def transcribe(audio_bytes, mime_type):
    reply = model.invoke([{
        "role": "user",
        "content": [
            {"type": "text", "text": TRANSCRIBE_PROMPT},
            {"type": "audio", "base64": base64.b64encode(audio_bytes).decode(), "mime_type": mime_type},
        ],
    }])
    return reply.text.strip()