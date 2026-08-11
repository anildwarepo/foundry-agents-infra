# Searching Memory Stores in Azure AI Foundry

This document covers how to search memory items stored in an Azure AI Foundry Memory Store using the REST API, including authentication setup, scope resolution, and working around current preview limitations.

## Environment

| Property | Value |
|---|---|
| AI Services Account | `foundrymkmz` |
| Project | `projectmkmz` |
| Endpoint | `https://foundrymkmz.services.ai.azure.com/api/projects/projectmkmz` |
| Memory Store | `MemoryStore-sweet_coconut_y6xmj4x2w1` |
| User | `anildwa@MngEnvMCAP347541.onmicrosoft.com` |
| User OID | `b47a4e95-787e-4f49-81cd-7dee3584e855` |
| Subscription | `e4718866-4e88-411f-a0b8-10c8051dc165` |
| Resource Group | `rg-foundry4-ch` |

## Memory Store Configuration (from Foundry Portal)

The agent `simple-prompt-agent` uses a memory tool with the following config:

- **Memory Store Name**: `MemoryStore-sweet_coconut_y6xmj4x2w1`
- **Scope**: `{{$userId}}` (resolves to the caller's Entra OID)
- **Update delay**: 5 seconds
- **Chat model**: `gpt-4.1-mini`
- **Embedding model**: `text-embedding-ada-002`
- **user_profile_enabled**: `true`
- **chat_summary_enabled**: `true`

![Agent Playground showing memory search results](screenshots/agent-playground-memory.png)
![Memory store edit dialog showing scope configuration](screenshots/memory-store-edit.png)

> **To add screenshots**: Save the Foundry portal screenshots to the `screenshots/` folder:
> - `agent-playground-memory.png` — Agent playground showing memory_search_call results with bright green preferences
> - `memory-store-edit.png` — Edit memory store dialog showing scope `{{$userId}}` and update delay 5s

## Authentication Setup

### Token Audience

The Foundry data-plane API requires the audience `https://ai.azure.com`:

```python
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
token = credential.get_token("https://ai.azure.com/.default").token
```

> **Note**: Using `https://management.azure.com/.default` or `https://cognitiveservices.azure.com/.default` returns 401 with message:
> `"Unauthorized. Access token is missing, invalid, audience is incorrect (https://ai.azure.com), or have expired."`

### Required Headers

All Memory Stores API calls require the `Foundry-Features` header:

```
Foundry-Features: MemoryStores=V1Preview
```

### RBAC Role Assignment

The AI Services account's managed identity needs `Cognitive Services OpenAI User` role on itself so the memory store service can call the model deployments internally:

```bash
# Get the account's managed identity principal ID
az cognitiveservices account show \
  --name foundrymkmz \
  --resource-group rg-foundry4-ch \
  --query "identity.principalId" -o tsv
# Output: a142f068-c392-4566-b310-0334ea16d287

# Assign the role
az role assignment create \
  --assignee-object-id "a142f068-c392-4566-b310-0334ea16d287" \
  --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" \
  --scope "/subscriptions/e4718866-4e88-411f-a0b8-10c8051dc165/resourceGroups/rg-foundry4-ch/providers/Microsoft.CognitiveServices/accounts/foundrymkmz"
```

### Known Issue: `disableLocalAuth=true` Blocks search_memories

When the AI account has `disableLocalAuth=true`, the direct `search_memories` REST endpoint fails with 403:

```
POST /memory_stores/{name}:search_memories?api-version=v1

403 Forbidden
{
  "code": "forbidden",
  "message": "Memory search failed with code '': {\"code\":\"ResourceError\",
    \"message\":\"{\\\"message\\\":\\\"Provided Azure resource encountered an error.\\\",
    \\\"deployment\\\":\\\"22cca8235ac54970b971d30f6614f0a1/deployments/text-embedding-ada-002\\\",
    \\\"details\\\":{\\\"type\\\":\\\"Authentication\\\",\\\"status_code\\\":401,
    \\\"description\\\":\\\"Authentication to the Azure OpenAI resource failed.\\\"}}\"}"
}
```

This happens because the memory store service internally calls the embedding model using API key auth, which is blocked when local auth is disabled.

**Workaround**: Use the **Responses API** with the `memory_search_preview` tool instead — it uses the agent's managed identity and works regardless of `disableLocalAuth`.

## Step-by-Step: Searching Memories

### Step 1: List Memory Stores

```
GET {endpoint}/memory_stores?api-version=v1
Headers:
  Authorization: Bearer {token}
  Foundry-Features: MemoryStores=V1Preview
```

**Output**:
```json
{
  "data": [
    {
      "object": "memory_store",
      "id": "memstore_6af4d527a608b830000Y6491ZRCkRxPUtpFQM8qhrvyJVSsnMs",
      "created_at": 1778195990,
      "updated_at": 1778195990,
      "name": "MemoryStore-sweet_coconut_y6xmj4x2w1",
      "description": "",
      "metadata": {},
      "definition": {
        "kind": "default",
        "chat_model": "gpt-4.1-mini",
        "embedding_model": "text-embedding-ada-002",
        "options": {
          "user_profile_enabled": true,
          "user_profile_details": "",
          "chat_summary_enabled": true
        }
      }
    }
  ],
  "has_more": false,
  "object": "list"
}
```

### Step 2: Determine the Scope

The scope `{{$userId}}` resolves to the caller's Entra OID at runtime. To find your OID:

```python
import jwt
claims = jwt.decode(token, options={"verify_signature": False})
user_oid = claims.get("oid")
# b47a4e95-787e-4f49-81cd-7dee3584e855
```

Or via Azure CLI:

```bash
az ad signed-in-user show --query id -o tsv
```

### Step 3a: Search via search_memories (requires local auth enabled)

```
POST {endpoint}/memory_stores/{name}:search_memories?api-version=v1
Headers:
  Authorization: Bearer {token}
  Content-Type: application/json
  Foundry-Features: MemoryStores=V1Preview

Body:
{
  "scope": "b47a4e95-787e-4f49-81cd-7dee3584e855",
  "items": [
    {"type": "message", "role": "user", "content": "What are my preferences?"}
  ],
  "options": {"max_memories": 100}
}
```

> **Status**: Currently returns **403** due to `disableLocalAuth=true` on the AI account.

### Step 3b: Search via Responses API (workaround — works always)

```
POST {endpoint}/openai/v1/responses
Headers:
  Authorization: Bearer {token}
  Content-Type: application/json
  Foundry-Features: MemoryStores=V1Preview

Body:
{
  "model": "gpt-4.1-mini",
  "input": "What color do I like? What are my clothing preferences?",
  "tools": [
    {
      "type": "memory_search_preview",
      "memory_store_name": "MemoryStore-sweet_coconut_y6xmj4x2w1",
      "scope": "b47a4e95-787e-4f49-81cd-7dee3584e855"
    }
  ]
}
```

**Output** (relevant parts):
```json
{
  "status": "completed",
  "output": [
    {
      "type": "memory_search_call",
      "memories": [
        {
          "content": "On May 8, 2026, the assistant indicated it did not have information about the user's color preferences...",
          "kind": "chat_summary",
          "memory_id": "91b2a450c149486bb72732deacd67e03",
          "scope": "b47a4e95-787e-4f49-81cd-7dee3584e855",
          "updated_at": 1778206291
        }
      ],
      "search_id": "d0fffea2c86a40ea8421c9c195cacfa1",
      "status": "in_progress"
    },
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "Currently, I do not have any information about your favorite color..."
        }
      ]
    }
  ]
}
```

## Script Output: search_memories.py

```
User OID: b47a4e95-787e-4f49-81cd-7dee3584e855

=== List Memory Stores ===
Status: 200
  Store: MemoryStore-sweet_coconut_y6xmj4x2w1 (id=memstore_6af4d527a608b830000Y6491ZRCkRxPUtpFQM8qhrvyJVSsnMs)

=== Search Memories via Responses API ===

Query 1: What color do I like? What are my clothing preferences? What...
  Status: 200
  Response: Currently, I do not have any information about your favorite color,
            clothing preferences, or preferred season because you have not
            shared those details with me yet.
  Memory search: 3 memories, status=in_progress
    [chat_summary] On May 8, 2026, the assistant indicated it did not have
                   information about the user's color preferences and asked
                   the user to share which colors they liked...
    [chat_summary] The assistant informed the user that it currently has no
                   information regarding the user's personal preferences...
    [chat_summary] As of May 8, 2026, at 02:17 UTC, the assistant has no
                   stored personal details, preferences, or other information
                   about the user...

Query 2: List ALL my preferences, profile details, and everything you...
  Status: 200
  Response: As of now, I have no stored information about your personal
            preferences, profile details, or any other personal data...
  Memory search: 3 memories, status=in_progress (deduplicated)

Query 3: Summarize every conversation we have had....
  Status: 429 (rate limited)

Saved 3 memory items to memory_items_dump.json
```

## Dumped Memory Items

| # | Kind | Memory ID | Content |
|---|------|-----------|---------|
| 1 | `chat_summary` | `91b2a450c149486bb72732deacd67e03` | User asked about color preferences, no definitive preference established |
| 2 | `chat_summary` | `2160bfbd63ab4719a1a42c7cab11c31a` | Assistant has no stored personal details; user asked for exhaustive list |
| 3 | `chat_summary` | `797a8c214ec44675a5ab4403809aeaab` | No stored personal details as of May 8, 2026 |

## Memory Store API Reference

| Operation | Method | Endpoint |
|---|---|---|
| Create memory store | POST | `/memory_stores` |
| List memory stores | GET | `/memory_stores` |
| Get memory store | GET | `/memory_stores/{name}` |
| Update memory store | POST | `/memory_stores/{name}` |
| Delete memory store | DELETE | `/memory_stores/{name}` |
| Search memories | POST | `/memory_stores/{name}:search_memories` |
| Update memories | POST | `/memory_stores/{name}:update_memories` |
| Get update result | GET | `/memory_stores/{name}/updates/{update_id}` |
| Delete scope memories | POST | `/memory_stores/{name}:delete_scope` |

Full API docs: https://learn.microsoft.com/en-us/rest/api/aifoundry/aiproject#memory-stores

## Files

- [`memory_store_client.py`](memory_store_client.py) — Reusable REST client for all Memory Stores API operations
- [`search_memories.py`](search_memories.py) — Script to list stores and search memories via Responses API
- [`dump_memory_items.py`](dump_memory_items.py) — Script to dump memory items (uses direct API, fails when local auth disabled)
- [`memory_items_dump.json`](memory_items_dump.json) — Exported memory items
