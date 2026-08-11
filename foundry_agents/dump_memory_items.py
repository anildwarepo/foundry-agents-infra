"""
Dump all memory items from all memory stores in a Foundry project to a JSON file.

Usage:
    python dump_memory_items.py [--scope SCOPE] [--output FILE]

Environment variables:
    FOUNDRY_RESOURCE_GROUP  - Resource group (default: rg-foundry4-ch)
    AZURE_SUBSCRIPTION_ID   - Subscription ID
    CHAT_MODEL / EMBEDDING_MODEL - Model deployment names (for store creation)
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from memory_store_client import (
    MemoryStoreClient,
    build_endpoint,
    discover_foundry_project,
)

load_dotenv()


def dump_all_memory_items(
    client: MemoryStoreClient,
    scopes: list[str] | None = None,
) -> dict:
    """
    Enumerate all memory stores and dump every memory item we can find.

    Returns a dict with store metadata + items organized by scope/kind.
    """
    stores_resp = client.list_memory_stores()
    stores = stores_resp.get("data", [])
    print(f"Found {len(stores)} memory store(s)")

    result = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "stores": [],
    }

    # Default scopes to try if none specified
    if not scopes:
        scopes = ["default"]

    for store in stores:
        store_name = store["name"]
        print(f"\n── Store: {store_name} ──")

        store_dump = {
            "store": store,
            "items_by_scope": {},
            "search_results_by_scope": {},
        }

        for scope in scopes:
            print(f"  Scope: {scope}")

            # 1. Try list_items for each kind
            items_for_scope = {}
            for kind in ["user_profile", "chat_summary"]:
                status, data = client._request_safe(
                    "POST", f"memory_stores/{store_name}/items", {"scope": scope, "kind": kind}
                )
                if status == 200:
                    items = data.get("data", data.get("items", []))
                    items_for_scope[kind] = items
                    print(f"    list_items({kind}): {len(items)} item(s)")
                else:
                    items_for_scope[kind] = {"error": data, "status": status}
                    print(f"    list_items({kind}): HTTP {status}")

            store_dump["items_by_scope"][scope] = items_for_scope

            # 2. Try search_memories (with empty items to avoid embedding calls)
            status, search_data = client._request_safe(
                "POST",
                f"memory_stores/{store_name}:search_memories",
                {"scope": scope, "items": []},
            )
            if status == 200:
                memories = search_data.get("memories", [])
                store_dump["search_results_by_scope"][scope] = memories
                print(f"    search_memories(empty): {len(memories)} result(s)")
            else:
                store_dump["search_results_by_scope"][scope] = {"error": search_data, "status": status}
                print(f"    search_memories(empty): HTTP {status}")

            # 3. Also try search with a broad query (may fail if embedding model has auth issues)
            status, search_data = client._request_safe(
                "POST",
                f"memory_stores/{store_name}:search_memories",
                {
                    "scope": scope,
                    "items": [{"type": "message", "role": "user", "content": "Tell me everything you remember"}],
                    "options": {"max_memories": 100},
                },
            )
            if status == 200:
                memories = search_data.get("memories", [])
                if memories:
                    store_dump["search_results_by_scope"][f"{scope}_broad"] = memories
                    print(f"    search_memories(broad): {len(memories)} result(s)")
                else:
                    print(f"    search_memories(broad): 0 results")
            else:
                err_msg = search_data.get("error", {}).get("message", "unknown error")[:80]
                print(f"    search_memories(broad): HTTP {status} - {err_msg}")

        result["stores"].append(store_dump)

    return result


def main():
    parser = argparse.ArgumentParser(description="Dump all memory items from Foundry memory stores")
    parser.add_argument("--scope", nargs="+", default=None, help="Scope(s) to query (default: tries common values)")
    parser.add_argument("--output", "-o", default="memory_items_dump.json", help="Output JSON file")
    parser.add_argument("--rg", default="rg-foundry4-ch", help="Resource group")
    parser.add_argument("--sub", default="e4718866-4e88-411f-a0b8-10c8051dc165", help="Subscription ID")
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    account_name, project_name = discover_foundry_project(credential, args.sub, args.rg)
    endpoint = build_endpoint(account_name, project_name)
    print(f"Endpoint: {endpoint}")

    client = MemoryStoreClient(endpoint, credential)

    result = dump_all_memory_items(client, scopes=args.scope)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nDumped to {args.output}")


if __name__ == "__main__":
    main()
