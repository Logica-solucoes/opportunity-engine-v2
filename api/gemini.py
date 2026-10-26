import os

from google import genai
from google.genai import types

# alias that follows the current Flash model; pin a version if the suggestions start drifting
MODEL = "gemini-flash-latest"
TIMEOUT_MS = 20_000


class Unavailable(Exception):
    pass


def ask(prompt: str, response_schema: dict) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise Unavailable("no_key")
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_json_schema=response_schema, temperature=0.2
            ),
        )
    except Exception as e:  # any SDK or network failure falls back to the data suggestions
        raise Unavailable(type(e).__name__) from e
    return response.text or ""
