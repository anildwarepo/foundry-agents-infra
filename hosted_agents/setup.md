# Hosted Agents — Setup & Troubleshooting

End-to-end steps to build, deploy, and run a Foundry **hosted agent** against a
**network-isolated** Foundry project (managed VNet, `AllowOnlyApprovedOutbound`,
public network access disabled). Includes the issues hit during setup and how
each was resolved.

> Reference: [Quickstart: Deploy your first hosted agent](https://learn.microsoft.com/azure/foundry/agents/quickstarts/quickstart-hosted-agent?pivots=azd)
> · [Deploy a hosted agent (SDK/REST)](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent)

---

## Environment used

| Item | Value |
| --- | --- |
| Foundry account | `aiservicesnjdz` (RG `rg-foundrywestus`, West US) |
| Project | `projectnjdz` |
| Project endpoint | `https://aiservicesnjdz.services.ai.azure.com/api/projects/projectnjdz` |
| ACR | `anildwapremacr` (RG `aifoundry-hubs`, Premium, `LegacyRegistryPermissions`) |
| Image | `anildwapremacr.azurecr.io/agent-framework-agent-basic-responses:1.0` |
| Model | `gpt-5.4` (GlobalStandard) |
| Network | Managed VNet `V2`, `AllowOnlyApprovedOutbound`, account `publicNetworkAccess: Disabled` |

---

## Prerequisites

- Azure Developer CLI (azd) **1.25.3+** — `azd version`
- Azure CLI **2.80+** — `az version`
- Python 3.13 + `azure-ai-projects>=2.1.0`
- Roles: **Foundry Project Manager** at project scope (create/deploy agents)

Install the Foundry azd extension and make sure the agent dependency is current:

```powershell
azd ext install microsoft.foundry
# --deploy-mode requires azure.ai.agents >= 0.1.34-preview
azd ext upgrade azure.ai.agents
azd ext list
```

> **Gotcha:** `azd ai agent init ... --deploy-mode code` fails with
> `unknown flag: --deploy-mode` when `azure.ai.agents` is older (e.g. 0.1.2-preview).
> Upgrade the extension as above.

---

## Step 1 — Scaffold the sample agent

```powershell
azd ai agent init -m "https://github.com/microsoft-foundry/foundry-samples/blob/main/samples/python/hosted-agents/agent-framework/responses/01-basic/agent.manifest.yaml" --deploy-mode code
cd agent-framework-agent-basic-responses
```

## Step 2 — Build & push the container image

The container must be **linux/amd64**. `az acr build` produces amd64 by default.

```powershell
cd src/agent-framework-agent-basic-responses   # folder containing the Dockerfile
az acr build --registry anildwapremacr --image agent-framework-agent-basic-responses:1.0 --file Dockerfile .
```

> Use a **unique tag** (`:1.0`), not `:latest`, for reproducible pulls. If you
> only pushed `:latest`, create the referenced tag:
> `az acr import --name anildwapremacr --source anildwapremacr.azurecr.io/<img>:latest --image <img>:1.0 --force`

## Step 3 — Provision Azure resources

```powershell
azd provision
```

## Step 4 — Create the hosted agent version (Python SDK)

See [create_hosted_agent.py](../../hostedagents-jun25/create_hosted_agent.py). Key points:

- `environment_variables` **must** match the names `main.py` reads
  (here `AZURE_AI_MODEL_DEPLOYMENT_NAME`).
- The `image` tag must exist in the ACR.

```powershell
python .\create_hosted_agent.py
```

## Step 5 — Test

```powershell
azd ai agent invoke "hello"
azd ai agent monitor --session-id <id>   # console logs for a session
```

---

## Required RBAC & networking for a locked-down project

These are the non-obvious requirements that make a hosted agent actually run on a
network-isolated project. All were needed in this environment.

### 1. AcrPull for the **project** managed identity (not the account)

The hosted agent pulls its image using the **project** sub-resource's
system-assigned identity — which is **different** from the account identity.

```powershell
# Get the PROJECT identity (note: distinct from the account identity)
az rest --method get --url "https://management.azure.com/subscriptions/<sub>/resourceGroups/rg-foundrywestus/providers/Microsoft.CognitiveServices/accounts/aiservicesnjdz/projects?api-version=2025-04-01-preview" --query "value[].{name:name, principalId:identity.principalId}" -o json

# Grant AcrPull on the ACR
az role assignment create --assignee-object-id <project-principalId> --assignee-principal-type ServicePrincipal --role "AcrPull" --scope <acr-resource-id>
```

> **Legacy vs ABAC registries:** `anildwapremacr` is in `LegacyRegistryPermissions`
> mode. In that mode the **classic `AcrPull`** role grants data-plane pull. The
> newer ABAC role **`Container Registry Repository Reader`** is *inert* in legacy
> mode — the tooling assigned it automatically, which is why pulls still failed
> until classic `AcrPull` was added. Check with:
> `az acr show -n anildwapremacr --query roleAssignmentMode`

Also confirm the registry's AAD-as-ARM policy is enabled:

```powershell
az acr config authentication-as-arm show -r anildwapremacr   # expect status: enabled
```

### 2. A model deployment must exist

The account had **zero** deployments. Deploy the model referenced by
`AZURE_AI_MODEL_DEPLOYMENT_NAME`:

```powershell
az cognitiveservices account deployment create -n aiservicesnjdz -g rg-foundrywestus \
  --deployment-name "gpt-5.4" --model-name "gpt-5.4" --model-version "2026-03-05" \
  --model-format OpenAI --sku-name GlobalStandard --sku-capacity 10
```

### 3. Managed-VNet outbound private-endpoint rules

With `AllowOnlyApprovedOutbound`, the agent container can only reach destinations
that have an **approved** outbound rule. Required rules:

| Destination | Subresource | Purpose |
| --- | --- | --- |
| Storage account | `blob` | artifacts / storage |
| AI Search | `searchService` | knowledge |
| Cosmos DB | `Sql` | threads |
| Container Registry | `registry` | image pull |
| **Foundry account itself** | **`account`** | **data plane (`*.services.ai.azure.com`) for conversation/history** |

The account self-rule is the easy one to miss — `update_outbound_rules.py` now adds
it automatically (rule `aiservices-account-rule`, subresource `account`). Apply with:

```powershell
python .\update_outbound_rules.py -g rg-foundrywestus --acr anildwapremacr --acr-resource-group aifoundry-hubs
```

Verify rules are `Active`:

```powershell
$sub="<sub>"
az rest --method GET --url "https://management.azure.com/subscriptions/$sub/resourceGroups/rg-foundrywestus/providers/Microsoft.CognitiveServices/accounts/aiservicesnjdz/managedNetworks/default?api-version=2025-10-01-preview" --query "properties.managedNetwork.outboundRules" -o json
```

---

## Troubleshooting log (symptoms → cause → fix)

| Symptom | Root cause | Fix |
| --- | --- | --- |
| `azd ai agent init: unknown flag: --deploy-mode` | `azure.ai.agents` extension too old | `azd ext upgrade azure.ai.agents` (need ≥ 0.1.34-preview) |
| `ServiceRequestTimeoutError` / connect timeout to `*.services.ai.azure.com` from local Python | `hosts` file pins the endpoint to a private-endpoint IP (`10.0.4.x`) but **no VPN** is connected → no route | Connect the VPN that routes the private subnet, **or** comment the `hosts` entry + `ipconfig /flushdns` to use the public IP (only if public access is enabled) |
| Playground: **ImageError — Container registry authentication failed** | The **project** managed identity lacked `AcrPull`; the auto-assigned `Container Registry Repository Reader` is inert on a `LegacyRegistryPermissions` registry | Grant classic **`AcrPull`** to the **project** identity on the ACR |
| Image pull would 404 after auth fix | Script referenced `:1.0` but only `:latest` was pushed | `az acr import` to create the `:1.0` tag (or push the right tag) |
| Playground: **Session did not become ready / `/readiness` not 200** | Container crashed at startup: `main.py` reads `AZURE_AI_MODEL_DEPLOYMENT_NAME` but the version set `MODEL_DEPLOYMENT_NAME` → `KeyError`; also no model deployed | Fix the env-var name to match `main.py`; deploy the model |
| **HTTP 500 / no response** at runtime; logs show `Foundry storage GET .../storage/history/item_ids` → `ConnectionReset (Errno 104)` after ~4.5 min | Managed VNet `AllowOnlyApprovedOutbound` had **no outbound rule for the account's own data plane**; account `publicNetworkAccess: Disabled` so the only path is a private endpoint to the account (`subresourceTarget: account`) | Add the `aiservices-account-rule` PrivateEndpoint outbound rule; wait for `Active`, then retry (a new session picks up the change) |

### Useful diagnostics

```powershell
# DNS / reachability of a private-endpoint-pinned host
nslookup aiservices<...>.services.ai.azure.com
Test-NetConnection -ComputerName <host> -Port 443

# Managed network isolation mode + rules
az rest --method GET --url ".../accounts/<acct>/managedNetworks/default?api-version=2025-10-01-preview" --query "properties.managedNetwork.{mode:isolationMode,rules:outboundRules}"

# Account network posture
az rest --method GET --url ".../accounts/<acct>?api-version=2025-04-01-preview" --query "{public:properties.publicNetworkAccess, inject:properties.networkInjections}"

# Live agent logs
azd ai agent invoke "hello" --session-id dbg-1
azd ai agent monitor --session-id dbg-1
```

---

## Key learnings

- The **project** identity ≠ the **account** identity. Hosted-agent image pulls use
  the project identity — grant `AcrPull` there.
- On **legacy-mode** registries, use classic `AcrPull`; ABAC roles
  (`Container Registry Repository Reader`) only work in RBAC/ABAC mode.
- Container **env-var names must exactly match** what the agent code reads; a
  missing var crashes startup and shows up as a `/readiness` timeout.
- A model deployment must actually exist for the agent to respond.
- On a `AllowOnlyApprovedOutbound` managed VNet with public access disabled, the
  agent needs a private-endpoint outbound rule to the **account itself**
  (`subresourceTarget: account`) — not just to dependent resources — or runtime
  data-plane calls (conversation/history) hang and reset.
