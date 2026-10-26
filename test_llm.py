
import time
import requests
from dotenv import dotenv_values

config = dotenv_values(".env")

api_key = config.get("LLM_API_KEY")
base_url = config.get("LLM_BASE_URL", "").rstrip("/")
model = config.get("LLM_MODEL")

if not api_key or not base_url or not model:
    print("Missing API key, base URL, or model in .env")
    raise SystemExit(1)

url = f"{base_url}/chat/completions"

payload = {
    "model": model,
    "max_tokens": 100,
    "messages": [
        {
            "role": "user",
            "content": "Reply with only: Gemini connection works."
        }
    ]
}

print(f"Testing model: {model}")
print("Sending a short request...")

start = time.time()

try:
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=45
    )

    print(f"HTTP status: {response.status_code}")
    print(f"Time taken: {time.time() - start:.1f} seconds")
    print("Response:", response.text[:1200])

except requests.RequestException as error:
    print(f"Request failed after {time.time() - start:.1f} seconds")
    print(f"Error type: {type(error).__name__}")
    print(f"Error: {error}")
