import os
import httpx
from dotenv import load_dotenv

load_dotenv()
AIPIPE_API_KEY = os.getenv("AIPIPE_API_KEY")

AIPIPE_CHAT_URL = "https://aipipe.org/openrouter/v1/chat/completions"


async def call_aipipe(prompt: str, model="openai/gpt-4.1-nano"):
    """Call AI Pipe to generate a response for a simple prompt."""
    headers = {
        "Authorization": f"Bearer {AIPIPE_API_KEY}",
        "Content-Type": "application/json",
    }
    json_data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            AIPIPE_CHAT_URL, headers=headers, json=json_data, timeout=60.0
        )
    response.raise_for_status()
    return response.json()
