"""
Assign the Cosmos DB Built-in Data Contributor role to the current logged-in user
on a Cosmos DB account discovered in a given resource group.

Usage:
    python assign_cosmosdb_role.py
"""

import os
import sys
import uuid

import requests as http_requests
from azure.identity import DefaultAzureCredential
from azure.mgmt.resource import ResourceManagementClient
from dotenv import load_dotenv

load_dotenv()

COSMOS_DATA_CONTRIBUTOR_ROLE_ID = "00000000-0000-0000-0000-000000000002"


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


def get_current_user_object_id(credential) -> tuple[str, str]:
    """Get the current user's object ID and display name from Microsoft Graph."""
    token = credential.get_token("https://graph.microsoft.com/.default").token
    resp = http_requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    user = resp.json()
    return user["id"], user.get("userPrincipalName", user.get("displayName", "unknown"))


def discover_cosmosdb(credential, subscription_id: str, resource_group: str) -> tuple[str, str]:
    """Find the first Cosmos DB account in the resource group. Returns (account_name, account_id)."""
    resource_client = ResourceManagementClient(credential, subscription_id)
    for resource in resource_client.resources.list_by_resource_group(
        resource_group,
        filter="resourceType eq 'Microsoft.DocumentDB/databaseAccounts'",
    ):
        print(f"Found Cosmos DB account: {resource.name}")
        return resource.name, resource.id

    print(f"No Cosmos DB account found in resource group '{resource_group}'.", file=sys.stderr)
    sys.exit(1)


def assign_cosmosdb_data_contributor(credential, cosmos_account_id: str, principal_id: str):
    """Assign Cosmos DB Built-in Data Contributor role using the Cosmos DB SQL RBAC API."""
    token = credential.get_token("https://management.azure.com/.default").token
    role_assignment_id = str(uuid.uuid4())
    role_definition_id = f"{cosmos_account_id}/sqlRoleDefinitions/{COSMOS_DATA_CONTRIBUTOR_ROLE_ID}"

    url = (
        f"https://management.azure.com{cosmos_account_id}"
        f"/sqlRoleAssignments/{role_assignment_id}?api-version=2024-12-01-preview"
    )

    body = {
        "properties": {
            "roleDefinitionId": role_definition_id,
            "scope": cosmos_account_id,
            "principalId": principal_id,
        }
    }

    resp = http_requests.put(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
    )

    if resp.status_code in (200, 201, 202):
        print("Role assignment created successfully.")
    elif resp.status_code == 409:
        print("Role assignment already exists.")
    else:
        print(f"Failed to create role assignment: {resp.status_code}", file=sys.stderr)
        print(resp.json(), file=sys.stderr)
        sys.exit(1)


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

    # 3. Discover Cosmos DB account
    cosmos_name, cosmos_id = discover_cosmosdb(credential, subscription_id, resource_group)

    # 4. Get current user
    user_id, user_name = get_current_user_object_id(credential)
    print(f"Current user: {user_name} ({user_id})")

    # 5. Confirm
    print(f"\nReady to assign Cosmos DB Built-in Data Contributor role:")
    print(f"  Cosmos DB Account: {cosmos_name}")
    print(f"  Principal:         {user_name} ({user_id})")
    confirm = input("\nProceed? (y/N): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    # 6. Assign role
    assign_cosmosdb_data_contributor(credential, cosmos_id, user_id)


if __name__ == "__main__":
    main()
