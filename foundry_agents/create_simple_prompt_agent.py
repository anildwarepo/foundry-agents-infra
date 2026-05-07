"""
Create a simple prompt agent (no tools) in an Azure AI Foundry project.

Usage:
    python create_simple_prompt_agent.py

The script will:
  1. Prompt for a resource group name (or use FOUNDRY_RESOURCE_GROUP env var)
  2. Auto-discover the Foundry account and project in that resource group
  3. Create a simple prompt agent with no tools
"""

import os
import sys

import requests
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.mgmt.resource import ResourceManagementClient
from dotenv import load_dotenv

load_dotenv()


def get_subscription_id(credential) -> str:
    """Get the first subscription ID using the credential."""
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
    """
    Find the first AI Services account (kind=AIServices) and its first project
    in the given resource group using the Azure Python SDK.

    Returns (account_name, project_name).
    """
    cs_client = CognitiveServicesManagementClient(credential, subscription_id)

    # Find the first AIServices account in the RG
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

    # Find projects under the account
    resource_client = ResourceManagementClient(credential, subscription_id)
    project_name = None
    for resource in resource_client.resources.list_by_resource_group(
        resource_group,
        filter="resourceType eq 'Microsoft.CognitiveServices/accounts/projects'",
    ):
        # resource.name is "accountName/projectName"
        parts = resource.name.split("/")
        if len(parts) == 2 and parts[0] == account_name:
            project_name = parts[1]
            break

    if not project_name:
        print(f"No project found under account '{account_name}' in resource group '{resource_group}'.", file=sys.stderr)
        sys.exit(1)

    print(f"Found project: {project_name}")
    return account_name, project_name


def main():
    credential = DefaultAzureCredential()

    # 1. Get resource group
    resource_group = input("Enter the Azure resource group name: ").strip()
    if not resource_group:
        print("Resource group name is required.", file=sys.stderr)
        sys.exit(1)

    # 2. Get subscription ID
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
    if not subscription_id:
        subscription_id = get_subscription_id(credential)
    print(f"Using subscription: {subscription_id}")

    # 3. Discover account and project
    account_name, project_name = discover_foundry_project(credential, subscription_id, resource_group)

    # 4. Get agent name
    agent_name = input("Enter a name for the agent [simple-prompt-agent]: ").strip() or "simple-prompt-agent"

    # 5. Confirm before creating
    endpoint = f"https://{account_name}.services.ai.azure.com/api/projects/{project_name}"
    print(f"\nReady to create agent:")
    print(f"  Resource Group: {resource_group}")
    print(f"  Account:        {account_name}")
    print(f"  Project:        {project_name}")
    print(f"  Agent Name:     {agent_name}")
    print(f"  Model:          gpt-4.1-mini")
    print(f"  Endpoint:       {endpoint}")
    confirm = input("\nProceed? (y/N): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    # 6. Create the agent
    print(f"\nConnecting to: {endpoint}")

    client = AIProjectClient(
        endpoint=endpoint,
        credential=credential,
    )

    # Delete existing agent version if it exists
    try:
        existing = client.agents.get(agent_name=agent_name)
        if existing:
            print(f"Agent '{agent_name}' already exists (version {existing.versions.latest.version}). Replacing...")
            client.agents.delete_version(
                agent_name=existing.name,
                agent_version=existing.versions.latest.version,
            )
    except Exception:
        pass  # Agent doesn't exist yet

    agent = client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model="gpt-4.1-mini",
            instructions="""You are a helpful assistant. 
Answer questions clearly and concisely. 
If you don't know the answer, say so honestly.""",
            tools=[],
        ),
    )
    print(f"\nAgent created successfully!")
    print(f"  Name:    {agent.name}")
    print(f"  ID:      {agent.id}")
    print(f"  Version: {agent.version}")
    print(f"\nEndpoint:  {endpoint}")


if __name__ == "__main__":
    main()
