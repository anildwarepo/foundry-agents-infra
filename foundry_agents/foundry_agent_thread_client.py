"""
Chat with a Foundry agent using the Responses API with conversation history.
Messages are persisted in Cosmos DB via previous_response_id chaining.

Usage:
    python foundry_agent_thread_client.py
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import requests as http_requests
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.mgmt.resource import ResourceManagementClient
from dotenv import load_dotenv

load_dotenv()


def get_subscription_id(credential) -> str:
    token = credential.get_token("https://management.azure.com/.default").token
    resp = http_requests.get(
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
    ai_account = None
    for acct in cs_client.accounts.list_by_resource_group(resource_group):
        if acct.kind == "AIServices":
            ai_account = acct
            break
    if not ai_account:
        print(f"No AI Services account found in resource group '{resource_group}'.", file=sys.stderr)
        sys.exit(1)
    account_name = ai_account.name
    print(f"Found AI Services account: {account_name}")

    resource_client = ResourceManagementClient(credential, subscription_id)
    project_name = None
    for resource in resource_client.resources.list_by_resource_group(
        resource_group,
        filter="resourceType eq 'Microsoft.CognitiveServices/accounts/projects'",
    ):
        parts = resource.name.split("/")
        if len(parts) == 2 and parts[0] == account_name:
            project_name = parts[1]
            break
    if not project_name:
        print(f"No project found under account '{account_name}'.", file=sys.stderr)
        sys.exit(1)
    print(f"Found project: {project_name}")
    return account_name, project_name


def main() -> int:
    credential = DefaultAzureCredential()

    # 1. Get resource group
    resource_group = input("Enter the Azure resource group name: ").strip()
    if not resource_group:
        print("Resource group name is required.", file=sys.stderr)
        return 1

    # 2. Get subscription ID
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
    if not subscription_id:
        subscription_id = get_subscription_id(credential)
    print(f"Using subscription: {subscription_id}")

    # 3. Discover account and project
    account_name, project_name = discover_foundry_project(credential, subscription_id, resource_group)
    endpoint = f"https://{account_name}.services.ai.azure.com/api/projects/{project_name}"

    # 4. Get agent name
    agent_name = input("Enter the agent name: ").strip()
    if not agent_name:
        print("Agent name is required.", file=sys.stderr)
        return 1

    client = AIProjectClient(endpoint=endpoint, credential=credential)

    # Get the agent
    agent = client.agents.get(agent_name=agent_name)
    print(f"Retrieved agent: {agent.name} (id: {agent.id})")

    # Get OpenAI client for Responses API
    openai_client = client.get_openai_client()

    print("\nType your message and press Enter.")
    print("Commands: /exit, /quit\n")

    last_response_id: Optional[str] = None

    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            return 0

        if not user_text:
            continue

        if user_text.lower() in {"/exit", "/quit", "exit", "quit"}:
            print("bye.")
            return 0

        try:
            # Use Responses API with agent_reference and previous_response_id for conversation history
            kwargs = dict(
                input=[{"role": "user", "content": user_text}],
                extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
            )
            if last_response_id is not None:
                kwargs["previous_response_id"] = last_response_id

            resp = openai_client.responses.create(**kwargs)
            last_response_id = resp.id
            print(f"agent> {resp.output_text}\n")

        except Exception as e:
            print(f"error> {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    raise SystemExit(main())
