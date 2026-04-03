"""
PLAYGROUND — Phase 4.1 / Chat Endpoint
=======================================
Demonstrates multi-turn chat via the REST API:
  POST /repos/{id}/chat              — blocking JSON response
  POST /repos/{id}/chat (stream)     — SSE token stream
  GET  /repos/{id}/sessions          — list active sessions
  DELETE /repos/{id}/sessions/{sid}  — evict a session

Prerequisites:
    docker compose up -d
    Data already ingested (run 02_ingest_and_status.py first)
    uv run aquila serve   (in a separate terminal)

Run:
    uv run python playground/phase4/04_chat.py
"""

from __future__ import annotations

import json
import os

import httpx

# ──────────────────────────────────────────────
# Config — change these to explore
# ──────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
REPO_ID = "playground-full"
API_KEY = os.getenv("API_KEY", "")
CONVERSATION = [
    "Give me a high-level overview of this codebase.",
    "How does the hybrid search work?",
    "Where exactly is the RRF merge implemented?",
]

headers = {"X-API-Key": API_KEY} if API_KEY else {}
client = httpx.Client(base_url=BASE_URL, headers=headers, timeout=120)

# ──────────────────────────────────────────────
# 1. Non-streaming multi-turn conversation
# ──────────────────────────────────────────────
print("=" * 60)
print("Non-streaming multi-turn chat (stream=false)")
print("=" * 60)
session_id: str | None = None
for turn, message in enumerate(CONVERSATION, 1):
    payload: dict[str, object] = {"message": message, "stream": False}
    if session_id:
        payload["session_id"] = session_id
    resp = client.post(f"/repos/{REPO_ID}/chat", json=payload)
    if resp.status_code != 200:
        print(f"Error: {resp.status_code} — {resp.text}")
        break
    data = resp.json()
    session_id = data.get("session_id")
    response = data.get("response", "")
    print(f"\n[Turn {turn}] You: {message}")
    print(f"Aquila: {response[:300]}{'…' if len(response) > 300 else ''}")
    print(f"(session_id={session_id})")
print()

# ──────────────────────────────────────────────
# 2. SSE streaming — single question, tokens printed live
# ──────────────────────────────────────────────
print("=" * 60)
print("SSE streaming  (stream=true)")
print("=" * 60)
STREAMING_QUESTION = "Explain what VectorStore.search does in one paragraph."
print(f"Question: {STREAMING_QUESTION}\n")
print("Aquila: ", end="", flush=True)

with client.stream(
    "POST",
    f"/repos/{REPO_ID}/chat",
    json={"message": STREAMING_QUESTION, "stream": True},
    timeout=120,
) as sse_resp:
    for line in sse_resp.iter_lines():
        if not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("done"):
            print(f"\n\n(stream complete — session_id={event.get('session_id')})")
            break
        token = event.get("token", "")
        print(token, end="", flush=True)
print()

# ──────────────────────────────────────────────
# 3. List active sessions
# ──────────────────────────────────────────────
print("=" * 60)
print(f"GET /repos/{REPO_ID}/sessions")
print("=" * 60)
resp = client.get(f"/repos/{REPO_ID}/sessions")
print(f"Status   : {resp.status_code}")
data = resp.json()
sessions = data.get("sessions", [])
print(f"Sessions : {sessions}  (total={data.get('total')})")
print()

# ──────────────────────────────────────────────
# 4. Delete the session created in step 1
# ──────────────────────────────────────────────
if session_id and session_id in sessions:
    print("=" * 60)
    print(f"DELETE /repos/{REPO_ID}/sessions/{session_id}")
    print("=" * 60)
    resp = client.delete(f"/repos/{REPO_ID}/sessions/{session_id}")
    print(f"Status : {resp.status_code}")
    print(f"Body   : {resp.json()}")
    print()

client.close()
print("Done.")
