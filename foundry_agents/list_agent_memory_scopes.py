"""List memory-store scope expressions configured on Foundry prompt agents."""

import argparse
import contextlib
import io
import json
import os
import sys
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from create_simple_prompt_agent import discover_foundry_project, get_subscription_id


def as_dict(value: Any) -> dict[str, Any]:
    """Convert an SDK model or mapping to a plain dictionary."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return dict(value)


def list_memory_scope_configs(
    client: AIProjectClient,
    agent_name: str | None = None,
    latest_only: bool = False,
) -> list[dict[str, Any]]:
    """Return memory tool configuration from matching agent versions."""
    records: list[dict[str, Any]] = []

    for agent in client.agents.list():
        if agent_name and agent.name != agent_name:
            continue

        versions = [agent.versions.latest] if latest_only else client.agents.list_versions(agent.name)
        for version in versions:
            definition = getattr(version, "definition", None)
            if definition is None:
                continue

            definition_data = as_dict(definition)
            for tool in definition_data.get("tools", []):
                tool_data = as_dict(tool)
                if tool_data.get("type") != "memory_search_preview":
                    continue

                scope = tool_data.get("scope")
                records.append(
                    {
                        "agent_name": agent.name,
                        "agent_version": version.version,
                        "memory_store_name": tool_data.get("memory_store_name"),
                        "scope_expression": scope,
                        "scope_kind": "dynamic_user" if scope == "{{$userId}}" else "static",
                        "update_delay": tool_data.get("update_delay"),
                    }
                )

    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "List memory scope expressions configured on Foundry agent versions. "
            "This does not enumerate resolved scope partitions stored in a memory store."
        )
    )
    parser.add_argument("--resource-group", "-g", help="Azure resource group containing the Foundry project")
    parser.add_argument("--agent-name", "-a", help="Only inspect this agent")
    parser.add_argument("--latest-only", action="store_true", help="Only inspect each agent's latest version")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    resource_group = args.resource_group or os.getenv("FOUNDRY_RESOURCE_GROUP", "").strip()
    if not resource_group:
        resource_group = input("Enter the Azure resource group name: ").strip()
    if not resource_group:
        parser.error("a resource group is required")

    credential = DefaultAzureCredential()
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip() or get_subscription_id(credential)
    if args.json:
        with contextlib.redirect_stdout(io.StringIO()):
            account_name, project_name = discover_foundry_project(credential, subscription_id, resource_group)
    else:
        account_name, project_name = discover_foundry_project(credential, subscription_id, resource_group)
    endpoint = f"https://{account_name}.services.ai.azure.com/api/projects/{project_name}"
    client = AIProjectClient(endpoint=endpoint, credential=credential)

    records = list_memory_scope_configs(client, args.agent_name, args.latest_only)

    if args.json:
        print(json.dumps(records, indent=2))
        return

    print(f"\nProject endpoint: {endpoint}")
    if not records:
        target = f"agent '{args.agent_name}'" if args.agent_name else "any agent version"
        print(f"No memory search tool was found on {target}.")
        return

    for record in records:
        print(f"\nAgent:            {record['agent_name']}")
        print(f"Version:          {record['agent_version']}")
        print(f"Memory store:     {record['memory_store_name']}")
        print(f"Scope expression: {record['scope_expression']}")
        print(f"Scope kind:       {record['scope_kind']}")
        print(f"Update delay:     {record['update_delay']} seconds")

    print(
        "\nNote: these are agent configuration expressions. The Memory Store API "
        "does not enumerate concrete resolved scope partitions."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)
