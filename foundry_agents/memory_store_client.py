"""
REST client for Azure AI Foundry Memory Stores API (api-version=v1).

Usage:
    python memory_store_client.py

The script will:
  1. Prompt for a resource group name (or use FOUNDRY_RESOURCE_GROUP env var)
  2. Auto-discover the Foundry account and project in that resource group
  3. Demonstrate CRUD operations on memory stores, plus search/update memories

Requires:
  pip install requests azure-identity azure-mgmt-cognitiveservices azure-mgmt-resource python-dotenv

API Reference:
  https://learn.microsoft.com/en-us/rest/api/aifoundry/aiproject#memory-stores
"""

import json
import os
import sys
import time
from typing import Any

import requests
from azure.identity import DefaultAzureCredential
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.mgmt.resource import ResourceManagementClient
from dotenv import load_dotenv

load_dotenv()

API_VERSION = "v1"
FEATURE_HEADER = "MemoryStores=V1Preview"


class MemoryStoreClient:
    """REST client for Azure AI Foundry Memory Stores API."""

    def __init__(self, endpoint: str, credential: DefaultAzureCredential):
        """
        Args:
            endpoint: Foundry Project endpoint, e.g.
                https://<account>.services.ai.azure.com/api/projects/<project>
            credential: Azure credential for token acquisition.
        """
        self.endpoint = endpoint.rstrip("/")
        self.credential = credential

    def _get_headers(self) -> dict[str, str]:
        token = self.credential.get_token("https://ai.azure.com/.default").token
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Foundry-Features": FEATURE_HEADER,
        }

    def _url(self, path: str) -> str:
        return f"{self.endpoint}/{path}?api-version={API_VERSION}"

    def _request(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
        url = self._url(path)
        if params:
            url += "&" + "&".join(f"{k}={v}" for k, v in params.items())
        resp = requests.request(method, url, headers=self._get_headers(), json=body)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _request_safe(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> tuple[int, dict]:
        """Like _request but returns (status_code, body) without raising."""
        url = self._url(path)
        if params:
            url += "&" + "&".join(f"{k}={v}" for k, v in params.items())
        resp = requests.request(method, url, headers=self._get_headers(), json=body)
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"raw": resp.text}
        return resp.status_code, data

    # ── Memory Store CRUD ─────────────────────────────────────────────

    def create_memory_store(
        self,
        name: str,
        chat_model: str,
        embedding_model: str,
        *,
        description: str | None = None,
        metadata: dict | None = None,
        chat_summary_enabled: bool = True,
    ) -> dict[str, Any]:
        """
        POST /memory_stores
        Create a memory store.
        """
        body: dict[str, Any] = {
            "name": name,
            "definition": {
                "kind": "default",
                "chat_model": chat_model,
                "embedding_model": embedding_model,
                "options": {
                    "chat_summary_enabled": chat_summary_enabled,
                },
            },
        }
        if description:
            body["description"] = description
        if metadata:
            body["metadata"] = metadata
        return self._request("POST", "memory_stores", body)

    def list_memory_stores(
        self,
        *,
        limit: int | None = None,
        order: str | None = None,
        after: str | None = None,
        before: str | None = None,
    ) -> dict[str, Any]:
        """
        GET /memory_stores
        List all memory stores.
        """
        params: dict[str, str] = {}
        if limit is not None:
            params["limit"] = str(limit)
        if order:
            params["order"] = order
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._request("GET", "memory_stores", params=params)

    def get_memory_store(self, name: str) -> dict[str, Any]:
        """
        GET /memory_stores/{name}
        Retrieve a memory store.
        """
        return self._request("GET", f"memory_stores/{name}")

    def update_memory_store(
        self,
        name: str,
        *,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """
        POST /memory_stores/{name}
        Update a memory store's description or metadata.
        """
        body: dict[str, Any] = {}
        if description is not None:
            body["description"] = description
        if metadata is not None:
            body["metadata"] = metadata
        return self._request("POST", f"memory_stores/{name}", body)

    def delete_memory_store(self, name: str) -> dict[str, Any]:
        """
        DELETE /memory_stores/{name}
        Delete a memory store.
        """
        return self._request("DELETE", f"memory_stores/{name}")

    # ── Memory Operations ─────────────────────────────────────────────

    def update_memories(
        self,
        name: str,
        scope: str,
        items: list[dict[str, Any]],
        *,
        update_delay: int = 0,
        previous_update_id: str | None = None,
    ) -> dict[str, Any]:
        """
        POST /memory_stores/{name}:update_memories
        Update memory store with conversation memories.

        Args:
            name: Memory store name.
            scope: Namespace for grouping memories (e.g. user ID).
            items: Conversation items (OpenAI InputItem format) to extract memories from.
            update_delay: Seconds to wait before processing (0 = immediate). Default 300 on server.
            previous_update_id: ID of previous update for incremental updates.
        """
        body: dict[str, Any] = {
            "scope": scope,
            "items": items,
            "update_delay": update_delay,
        }
        if previous_update_id:
            body["previous_update_id"] = previous_update_id
        return self._request("POST", f"memory_stores/{name}:update_memories", body)

    def get_update_result(self, name: str, update_id: str) -> dict[str, Any]:
        """
        GET /memory_stores/{name}/updates/{update_id}
        Get memory store update result.
        """
        return self._request("GET", f"memory_stores/{name}/updates/{update_id}")

    def search_memories(
        self,
        name: str,
        scope: str,
        items: list[dict[str, Any]] | None = None,
        *,
        max_memories: int | None = None,
        previous_search_id: str | None = None,
    ) -> dict[str, Any]:
        """
        POST /memory_stores/{name}:search_memories
        Search for relevant memories based on conversation context.

        Args:
            name: Memory store name.
            scope: Namespace for grouping memories (e.g. user ID).
            items: Conversation items to search against.
            max_memories: Maximum number of memory items to return.
            previous_search_id: ID of previous search for incremental search.
        """
        body: dict[str, Any] = {"scope": scope}
        if items:
            body["items"] = items
        if max_memories is not None:
            body["options"] = {"max_memories": max_memories}
        if previous_search_id:
            body["previous_search_id"] = previous_search_id
        return self._request("POST", f"memory_stores/{name}:search_memories", body)

    def list_items(
        self,
        name: str,
        scope: str,
        kind: str,
    ) -> dict[str, Any]:
        """
        POST /memory_stores/{name}/items
        List memory items by scope and kind.

        Args:
            name: Memory store name.
            scope: Namespace that groups memories (e.g. user ID).
            kind: Memory item kind — 'user_profile' or 'chat_summary'.
        """
        return self._request("POST", f"memory_stores/{name}/items", {"scope": scope, "kind": kind})

    def delete_scope_memories(self, name: str, scope: str) -> dict[str, Any]:
        """
        POST /memory_stores/{name}:delete_scope
        Delete all memories associated with a specific scope.
        """
        return self._request("POST", f"memory_stores/{name}:delete_scope", {"scope": scope})

    # ── Polling helper ────────────────────────────────────────────────

    def wait_for_update(
        self, name: str, update_id: str, *, poll_interval: int = 5, timeout: int = 300
    ) -> dict[str, Any]:
        """Poll an update operation until it completes or times out."""
        start = time.time()
        while time.time() - start < timeout:
            result = self.get_update_result(name, update_id)
            status = result.get("status", "")
            if status in ("completed", "failed", "cancelled"):
                return result
            time.sleep(poll_interval)
        raise TimeoutError(f"Update {update_id} did not complete within {timeout}s")


# ── Discovery helpers (same pattern as other scripts) ─────────────────


def get_subscription_id(credential) -> str:
    token = credential.get_token("https://management.azure.com/.default").token
    resp = requests.get(
        "https://management.azure.com/subscriptions?api-version=2022-12-01",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    subs = resp.json().get("value", [])
    if not subs:
        print("No Azure subscriptions found.", file=sys.stderr)
        sys.exit(1)
    return subs[0]["subscriptionId"]


def discover_foundry_project(credential, subscription_id: str, resource_group: str) -> tuple[str, str]:
    cs_client = CognitiveServicesManagementClient(credential, subscription_id)
    accounts = list(cs_client.accounts.list_by_resource_group(resource_group))
    ai_accounts = [a for a in accounts if a.kind == "AIServices"]
    if not ai_accounts:
        print(f"No AIServices accounts found in resource group '{resource_group}'.", file=sys.stderr)
        sys.exit(1)
    account = ai_accounts[0]
    account_name = account.name

    rm_client = ResourceManagementClient(credential, subscription_id)
    resources = list(rm_client.resources.list_by_resource_group(
        resource_group,
        filter="resourceType eq 'Microsoft.CognitiveServices/accounts/projects'",
    ))
    if not resources:
        print(f"No Foundry projects found in resource group '{resource_group}'.", file=sys.stderr)
        sys.exit(1)
    project_name = resources[0].name.split("/")[-1]
    return account_name, project_name


def build_endpoint(account_name: str, project_name: str) -> str:
    return f"https://{account_name}.services.ai.azure.com/api/projects/{project_name}"


# ── Demo ──────────────────────────────────────────────────────────────


def main():
    resource_group = os.environ.get("FOUNDRY_RESOURCE_GROUP") or input("Resource group: ").strip()
    if not resource_group:
        print("Resource group is required.", file=sys.stderr)
        sys.exit(1)

    credential = DefaultAzureCredential()
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID") or get_subscription_id(credential)
    account_name, project_name = discover_foundry_project(credential, subscription_id, resource_group)
    endpoint = build_endpoint(account_name, project_name)

    print(f"Endpoint: {endpoint}\n")
    client = MemoryStoreClient(endpoint, credential)

    store_name = "demo-memory-store"
    chat_model = os.environ.get("CHAT_MODEL", "gpt-4o")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "text-embedding-ada-002")

    # 1. Create memory store
    print("=== Creating memory store ===")
    store = client.create_memory_store(
        name=store_name,
        chat_model=chat_model,
        embedding_model=embedding_model,
        description="Demo memory store for testing the REST client",
    )
    print(json.dumps(store, indent=2))

    # 2. List memory stores
    print("\n=== Listing memory stores ===")
    stores = client.list_memory_stores()
    print(json.dumps(stores, indent=2))

    # 3. Get memory store
    print("\n=== Getting memory store ===")
    store = client.get_memory_store(store_name)
    print(json.dumps(store, indent=2))

    # 4. Update memory store metadata
    print("\n=== Updating memory store ===")
    store = client.update_memory_store(store_name, description="Updated description")
    print(json.dumps(store, indent=2))

    # 5. Update memories (ingest conversation)
    print("\n=== Updating memories (ingesting conversation) ===")
    conversation_items = [
        {"type": "message", "role": "user", "content": "My name is Alice and I live in Seattle."},
        {"type": "message", "role": "assistant", "content": "Nice to meet you, Alice! Seattle is a great city."},
        {"type": "message", "role": "user", "content": "I work as a software engineer at Contoso."},
        {"type": "message", "role": "assistant", "content": "That sounds like a great job! How do you like working at Contoso?"},
    ]
    update_resp = client.update_memories(
        name=store_name,
        scope="user-alice-123",
        items=conversation_items,
        update_delay=0,
    )
    print(json.dumps(update_resp, indent=2))

    # 5a. Poll for update completion
    update_id = update_resp.get("id")
    if update_id:
        print("\n=== Polling for update completion ===")
        result = client.wait_for_update(store_name, update_id, poll_interval=3, timeout=120)
        print(json.dumps(result, indent=2))

    # 6. Search memories
    print("\n=== Searching memories ===")
    search_resp = client.search_memories(
        name=store_name,
        scope="user-alice-123",
        items=[{"type": "message", "role": "user", "content": "Where does Alice work?"}],
        max_memories=5,
    )
    print(json.dumps(search_resp, indent=2))

    # 7. Delete scope memories
    print("\n=== Deleting scope memories ===")
    delete_scope_resp = client.delete_scope_memories(store_name, scope="user-alice-123")
    print(json.dumps(delete_scope_resp, indent=2))

    # 8. Delete memory store
    print("\n=== Deleting memory store ===")
    delete_resp = client.delete_memory_store(store_name)
    print(json.dumps(delete_resp, indent=2))

    print("\nDone!")


if __name__ == "__main__":
    main()
