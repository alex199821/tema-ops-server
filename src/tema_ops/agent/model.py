import os

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

PRIORITY_HEADERS = {
    "X-Vertex-AI-LLM-Request-Type": "shared",
    "X-Vertex-AI-LLM-Shared-Request-Type": "priority",
}

def get_model(priority=False, timeout=None, name=None, tries=2):
    # name: which model, e.g. "google_genai:gemini-3.5-flash-lite" (default: AI_MODEL from .env)
    # tries: how many times one call is sent before it counts as failed
    # timeout: seconds to wait for one answer (None = wait forever). Some Gemini calls hang
    # for 2-3 minutes; after the timeout the call counts as failed and is sent again.
    # max_retries=2 means 2 tries in total (the first one + 1 re-send). If both fail, the
    # agent's backup model takes over (agent.py, ModelFallbackMiddleware).
    return init_chat_model(
        name or os.environ["AI_MODEL"],
        vertexai=True,                                  # go through Vertex AI, not an API key
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ["GOOGLE_CLOUD_LOCATION"],
        additional_headers=PRIORITY_HEADERS if priority else None,
        max_retries=tries,
        timeout=timeout,
    )

if __name__ == "__main__":
    reply = get_model().invoke("How do you say 'good morning' in Georgian?")
    print(reply.text)
    print(reply.usage_metadata)