import os
import urllib.request
import json

api_key = os.getenv("OPENAI_API_KEY")

payload = json.dumps({"api_key": api_key}).encode()

req = urllib.request.Request(
    "http://localhost:7432/set_api_key",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST"
)

urllib.request.urlopen(req)

print("API key saved!")