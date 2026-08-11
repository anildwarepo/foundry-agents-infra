#!/usr/bin/env python3
"""
Discover dependent resources in a resource group and create/update the managed
network outbound PrivateEndpoint rules on an Azure AI Foundry (CognitiveServices)
account.

The script uses the Azure CLI (`az`) for authentication and REST calls, so make
sure you are logged in (`az login`) and have selected the right subscription
before running it.

What it does:
  1. Discovers the Foundry account (Microsoft.CognitiveServices/accounts) plus the
     dependent Storage, AI Search, Cosmos DB and Container Registry resources in
     the given resource group.
  2. Reads the existing managed network outbound rules (so they are preserved).
  3. Builds a PrivateEndpoint outbound rule per discovered resource and submits
     them in a single batch call to the `batchOutboundRules` REST endpoint.

Examples:
  # Discover everything in one resource group and apply
  python update_outbound_rules.py -g my-foundry-rg

  # ACR lives in a different resource group
  python update_outbound_rules.py -g my-foundry-rg --acr-resource-group aifoundry-hubs

  # Just preview the payload without changing anything
  python update_outbound_rules.py -g my-foundry-rg --dry-run
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

API_VERSION = "2025-10-01-preview"

# resource type -> private endpoint sub-resource target + rule name used in the body
SERVICES = {
    "storage": {
        "type": "Microsoft.Storage/storageAccounts",
        "subresource": "blob",
        "rule": "storage-rule",
    },
    "search": {
        "type": "Microsoft.Search/searchServices",
        "subresource": "searchService",
        "rule": "aisearch-rule",
    },
    "cosmos": {
        "type": "Microsoft.DocumentDB/databaseAccounts",
        "subresource": "Sql",
        "rule": "cosmosdb-rule",
    },
    "acr": {
        "type": "Microsoft.ContainerRegistry/registries",
        "subresource": "registry",
        "rule": "acr-rule",
    },
}

AZ = shutil.which("az") or "az"


def run_az(args, allow_fail=False):
    """Run an `az` command and return parsed JSON (or None)."""
    cmd = [AZ] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        if allow_fail:
            return None
        sys.stderr.write(f"\nCommand failed: {' '.join(cmd)}\n{result.stderr}\n")
        sys.exit(result.returncode)
    out = result.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out


def get_subscription(explicit):
    if explicit:
        return explicit
    acct = run_az(["account", "show", "-o", "json"])
    if not acct or "id" not in acct:
        sys.stderr.write("Could not determine subscription. Use --subscription.\n")
        sys.exit(1)
    return acct["id"]


def list_resources(subscription, resource_group, resource_type):
    return run_az(
        [
            "resource",
            "list",
            "--subscription",
            subscription,
            "-g",
            resource_group,
            "--resource-type",
            resource_type,
            "-o",
            "json",
        ],
        allow_fail=True,
    ) or []


def pick_one(resources, label, override_name=None):
    """Choose a single resource from a discovered list."""
    if override_name:
        for r in resources:
            if r.get("name") == override_name:
                return r
        sys.stderr.write(f"  ! {label}: '{override_name}' not found in resource group.\n")
        return None
    if not resources:
        return None
    if len(resources) > 1:
        names = ", ".join(r.get("name", "?") for r in resources)
        sys.stderr.write(
            f"  ! {label}: multiple found ({names}); using '{resources[0].get('name')}'. "
            f"Pass an explicit name to override.\n"
        )
    return resources[0]


def discover_account(subscription, resource_group, override_name):
    accounts = list_resources(subscription, resource_group, "Microsoft.CognitiveServices/accounts")
    # Prefer AIServices kind when present.
    ai = [a for a in accounts if str(a.get("kind", "")).lower() in ("aiservices", "openai")]
    candidates = ai if ai else accounts
    account = pick_one(candidates, "Foundry account", override_name)
    if not account:
        sys.stderr.write("Could not find a CognitiveServices account. Use --account.\n")
        sys.exit(1)
    return account


def get_account_principal_id(account_id):
    """Return the system-assigned managed identity principalId of the account."""
    data = run_az(["resource", "show", "--ids", account_id, "-o", "json"], allow_fail=True)
    if isinstance(data, dict):
        return (data.get("identity", {}) or {}).get("principalId")
    return None


def ensure_role_assignment(principal_id, role, scope):
    """Grant `role` to `principal_id` at `scope` if not already assigned (idempotent)."""
    existing = run_az(
        [
            "role", "assignment", "list",
            "--assignee", principal_id,
            "--role", role,
            "--scope", scope,
            "-o", "json",
        ],
        allow_fail=True,
    )
    if existing:
        print(f"  = role '{role}' already assigned on {scope.rsplit('/', 1)[-1]}")
        return
    print(f"  + granting role '{role}' to {principal_id} on {scope.rsplit('/', 1)[-1]} ...")
    run_az([
        "role", "assignment", "create",
        "--assignee-object-id", principal_id,
        "--assignee-principal-type", "ServicePrincipal",
        "--role", role,
        "--scope", scope,
        "-o", "none",
    ])


def get_existing_rules(subscription, resource_group, account_name, api_version):
    url = (
        f"https://management.azure.com/subscriptions/{subscription}"
        f"/resourceGroups/{resource_group}/providers/Microsoft.CognitiveServices"
        f"/accounts/{account_name}/managedNetworks/default?api-version={api_version}"
    )
    data = run_az(["rest", "--method", "GET", "--url", url, "-o", "json"], allow_fail=True)
    if isinstance(data, dict):
        props = data.get("properties", {}) or {}
        managed = props.get("managedNetwork", {}) or {}
        # Outbound rules live under properties.managedNetwork.outboundRules; fall
        # back to properties.outboundRules for older API shapes.
        return managed.get("outboundRules") or props.get("outboundRules") or {}
    return {}


def print_rules(title, rules):
    """Pretty-print a map of outbound rules."""
    print(f"\n{title} ({len(rules)}):")
    if not rules:
        print("  (none)")
        return
    for name, rule in sorted(rules.items()):
        dest = rule.get("destination", {}) or {}
        resource_id = dest.get("serviceResourceId", "")
        target = dest.get("subresourceTarget", "")
        rtype = rule.get("type", "")
        resource_name = resource_id.rsplit("/", 1)[-1] if resource_id else "?"
        print(f"  - {name}: [{rtype}] {resource_name} ({target})")


def destination_key(dest):
    """Stable identity for an outbound rule destination (resource id + target)."""
    dest = dest or {}
    resource_id = str(dest.get("serviceResourceId", "")).lower()
    target = str(dest.get("subresourceTarget", "")).lower()
    return (resource_id, target)


def build_rule(resource_id, subresource):
    return {
        "type": "PrivateEndpoint",
        "destination": {
            "serviceResourceId": resource_id,
            "subresourceTarget": subresource,
            "sparkEnabled": False,
            "sparkStatus": "Inactive",
        },
        "category": "UserDefined",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Discover dependent resources and update Foundry managed network outbound rules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-g", "--resource-group", required=True,
                        help="Resource group that contains the Foundry account and dependent resources.")
    parser.add_argument("-s", "--subscription",
                        help="Subscription ID (defaults to the current `az` subscription).")
    parser.add_argument("--account",
                        help="Foundry (CognitiveServices) account name. Auto-discovered if omitted.")
    parser.add_argument("--storage", help="Storage account name override.")
    parser.add_argument("--search", help="AI Search service name override.")
    parser.add_argument("--cosmos", help="Cosmos DB account name override.")
    parser.add_argument("--acr", help="Container Registry name override.")
    parser.add_argument("--acr-resource-group",
                        help="Resource group to search for the Container Registry (if different).")
    parser.add_argument("--acr-role", default="Contributor",
                        help="Role to grant the Foundry identity on the ACR so it can approve "
                             "the private endpoint (default: Contributor).")
    parser.add_argument("--skip-acr-role", action="store_true",
                        help="Do not grant the ACR role assignment automatically.")
    parser.add_argument("--isolation-mode", default="AllowOnlyApprovedOutbound",
                        help="Managed network isolation mode (default: AllowOnlyApprovedOutbound).")
    parser.add_argument("--api-version", default=API_VERSION,
                        help=f"REST API version (default: {API_VERSION}).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the request payload without submitting it.")
    args = parser.parse_args()

    subscription = get_subscription(args.subscription)
    rg = args.resource_group

    print(f"Subscription : {subscription}")
    print(f"Resource grp : {rg}")

    account = discover_account(subscription, rg, args.account)
    account_name = account["name"]
    print(f"Foundry acct : {account_name}")

    overrides = {
        "storage": args.storage,
        "search": args.search,
        "cosmos": args.cosmos,
        "acr": args.acr,
    }

    discovered_rules = {}
    discovered_resources = {}
    for key, meta in SERVICES.items():
        search_rg = args.acr_resource_group if (key == "acr" and args.acr_resource_group) else rg
        resources = list_resources(subscription, search_rg, meta["type"])
        chosen = pick_one(resources, key, overrides[key])
        if not chosen:
            print(f"  - {key:8}: not found (skipped)")
            continue
        rule = build_rule(chosen["id"], meta["subresource"])
        discovered_rules[meta["rule"]] = rule
        discovered_resources[key] = chosen
        print(f"  + {key:8}: {chosen['name']} -> {meta['subresource']}")

    # The Foundry account's own data plane (https://<account>.services.ai.azure.com)
    # must be reachable from the managed VNet so hosted agents can call project
    # APIs (e.g. conversation/history storage) at runtime. When the account has
    # public network access disabled, the only path is a private endpoint to the
    # account itself (subresource "account"). Without this rule, agent requests
    # hang and fail with "Connection reset by peer" on /storage/history calls.
    discovered_rules["aiservices-account-rule"] = build_rule(account["id"], "account")
    discovered_resources["account"] = account
    print(f"  + {'account':8}: {account_name} -> account")

    if not discovered_rules:
        sys.stderr.write("No dependent resources discovered; nothing to do.\n")
        sys.exit(1)

    existing = get_existing_rules(subscription, rg, account_name, args.api_version)
    print_rules("Existing outbound rules", existing)

    # The batchOutboundRules endpoint only ADDS rules and rejects any destination
    # that already exists, so submit only the rules whose destination is new.
    existing_destinations = set()
    for rule in existing.values():
        dest = rule.get("destination", {}) or {}
        existing_destinations.add(destination_key(dest))

    new_rules = {}
    for name, rule in discovered_rules.items():
        key = destination_key(rule.get("destination", {}))
        if key in existing_destinations:
            print(f"  = {name}: already exists, skipping")
        else:
            new_rules[name] = rule

    if not new_rules:
        print("\nAll discovered resources already have outbound rules. Nothing to submit.")
        return

    managed_network_id = (
        f"/subscriptions/{subscription}/resourceGroups/{rg}"
        f"/providers/Microsoft.CognitiveServices/accounts/{account_name}/managedNetworks/default"
    )

    body = {
        "id": managed_network_id,
        "name": "default",
        "type": "Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules",
        "properties": {
            "IsolationMode": args.isolation_mode,
            "outboundRules": new_rules,
            "managedNetworkKind": "V2",
        },
    }

    url = (
        f"https://management.azure.com/subscriptions/{subscription}"
        f"/resourceGroups/{rg}/providers/Microsoft.CognitiveServices"
        f"/accounts/{account_name}/managedNetworks/default/batchOutboundRules"
        f"?api-version={args.api_version}"
    )

    print_rules("New rules to add", new_rules)

    if args.dry_run:
        print("\n--- DRY RUN (no changes submitted) ---")
        print(f"POST {url}")
        print(json.dumps(body, indent=2))
        return

    # The Foundry managed identity must be able to approve the private endpoint
    # connection on the ACR, which usually lives in another resource group.
    if "acr-rule" in new_rules and not args.skip_acr_role:
        acr = discovered_resources.get("acr")
        principal_id = get_account_principal_id(account["id"])
        if acr and principal_id:
            print("\nEnsuring ACR private endpoint approval permissions ...")
            ensure_role_assignment(principal_id, args.acr_role, acr["id"])
        elif not principal_id:
            sys.stderr.write(
                "  ! Could not resolve the account managed identity; skipping ACR role grant. "
                "The submit may fail with a permissions error.\n"
            )

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(body, fh)
            tmp_path = fh.name
        print("\nSubmitting batch outbound rules ...")
        result = run_az(["rest", "--method", "POST", "--url", url, "--body", f"@{tmp_path}", "-o", "json"])
        print("Done.")
        if result:
            print(json.dumps(result, indent=2))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


if __name__ == "__main__":
    main()
