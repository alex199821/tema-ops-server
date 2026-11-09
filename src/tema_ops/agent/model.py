import os

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

PRIORITY_HEADERS = {
    "X-Vertex-AI-LLM-Request-Type": "shared",
    "X-Vertex-AI-LLM-Shared-Request-Type": "priority",
}

def get_model(priority=False):
    return init_chat_model(
        os.environ["AI_MODEL"],
        vertexai=True,                                  # go through Vertex AI, not an API key
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ["GOOGLE_CLOUD_LOCATION"],
        additional_headers=PRIORITY_HEADERS if priority else None,
        max_retries=6 if priority else 2,
    )

if __name__ == "__main__":
    reply = get_model().invoke("How do you say 'good morning' in Georgian?")
    print(reply.text)
    print(reply.usage_metadata)