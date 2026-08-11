"""Retrieve all memory items from a Foundry Memory Store using the search_memories API."""

import json
import sys

import jwt
import requests
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

credential = DefaultAzureCredential()
token = credential.get_token("https://ai.azure.com/.default").token
endpoint = "https://foundrymkmz.services.ai.azure.com/api/projects/projectmkmz"

claims = jwt.decode(token, options={"verify_signature": False})
user_oid = claims.get("oid", "")
print(f"User OID: {user_oid}")

HEADERS = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Foundry-Features": "MemoryStores=V1Preview",
}

# Step 1: List memory stores
print("\n=== List Memory Stores ===")
resp = requests.get(
    f"{endpoint}/memory_stores?api-version=v1",
    headers=HEADERS,
    timeout=30,
)
print(f"Status: {resp.status_code}")
stores_data = resp.json()
for store in stores_data.get("data", []):
    print(f"  Store: {store['name']} (id={store['id']})")

store_name = stores_data["data"][0]["name"]

# Step 2: Search memories using search_memories API
print("\n=== Search Memories ===")

all_memories = []

queries = [
    "What color do I like? What are my clothing preferences? What season do I prefer?",
    "List ALL my preferences, profile details, and everything you know about me from memory.",
    "Summarize every conversation we have had.",
]

for i, query in enumerate(queries):
    print(f"\nQuery {i+1}: {query[:60]}...")
    resp = requests.post(
        f"{endpoint}/memory_stores/{store_name}:search_memories?api-version=v1",
        headers=HEADERS,
        json={
            "scope": user_oid,
            "items": [
                {"type": "message", "role": "user", "content": query}
            ],
            "options": {"max_memories": 100},
        },
        timeout=60,
    )
    print(f"  Status: {resp.status_code}")
    data = resp.json()

    if resp.status_code != 200:
        print(f"  Error: {json.dumps(data, indent=2)}")
        continue

    memories = data.get("memories", [])
    search_id = data.get("search_id", "")
    usage = data.get("usage", {})
    print(f"  search_id: {search_id}")
    print(f"  Found: {len(memories)} memories")
    print(f"  Usage: embedding_tokens={usage.get('embedding_tokens', 0)}, total_tokens={usage.get('total_tokens', 0)}")

    for m in memories:
        mi = m.get("memory_item", m)
        mid = mi.get("memory_id", "")
        # Deduplicate
        if mid and any(x.get("memory_id") == mid for x in all_memories):
            print(f"    [dup] {mid}")
            continue
        print(f"    [{mi.get('kind')}] {mi.get('content', '')[:120]}")
        all_memories.append(mi)

# Save to file
output = {
    "user_oid": user_oid,
    "store_name": store_name,
    "memories": all_memories,
}

with open("memory_items_dump.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\nSaved {len(all_memories)} memory items to memory_items_dump.json")
