# Microsoft Foundry Agent Service — Infrastructure Templates

Bicep templates and Python scripts for deploying [Microsoft Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/overview) across three deployment configurations, from quick dev/test to enterprise network-secured environments.

---

## Deployment Options

| Option | Folder | Data Storage | Network | Provisioning Time | Use Case |
|---|---|---|---|---|---|
| **Basic Agent Setup** | [`bicep-basic-agent-setup/`](bicep-basic-agent-setup/) | Microsoft-managed multitenant | Public | ~2 min | Dev/test, quick prototyping |
| **Standard Agent Setup** | [`bicep-standard-agent-setup-with-public-capability-host/`](bicep-standard-agent-setup-with-public-capability-host/) | Customer-managed (BYO Cosmos DB, Storage, AI Search) | Public | ~10 min | Complex agent orchestration for tracking and analysing user requests, where agents do not store business-critical data |
| **Managed VNet Setup** | [`foundy-managed-vnet-setup/`](foundy-managed-vnet-setup/) | Customer-managed (BYO) | Private endpoints + managed VNet | ~40-50 min | Enterprise network isolation |

### Basic Agent Setup

Uses Microsoft-managed, multitenant search and storage. No Cosmos DB, AI Search, or Storage account needed — the agent service handles everything. Ideal for getting started quickly.

- [Setup docs](https://learn.microsoft.com/en-us/azure/foundry/agents/environment-setup)
- Deploy: `cd bicep-basic-agent-setup && azd up`

### Standard Agent Setup (Public Networking)

Provisions your own Cosmos DB (thread storage), Azure AI Search (vector store), and Azure Storage (file storage) with full RBAC configuration and a capability host. All data stays in your Azure tenant.

- [Standard setup docs](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/standard-agent-setup)
- [Capability hosts](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/capability-hosts)
- Deploy: `cd bicep-standard-agent-setup-with-public-capability-host && azd up`

### Managed VNet Setup (Network Isolated)

Adds managed virtual network isolation with private endpoints, DNS configuration, and outbound rules. Requires the `AI.ManagedVnetPreview` feature flag. Supports existing VNets and DNS zones.

- [Managed VNet docs](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/standard-agent-setup)
- Deploy: `cd foundy-managed-vnet-setup && azd up`

---

## Prerequisites

### Azure Account & Subscription

- An [Azure subscription](https://azure.microsoft.com/pricing/purchase-options/azure-account). [Create one for free](https://azure.microsoft.com/free/).
- **Azure AI Account Owner** or **Contributor** role to create Foundry resources.
- **Owner** or **Role Based Access Administrator** role to assign RBAC (required for Standard and Managed VNet setups).
- **Azure AI User** role to create and run agents.

### Model Availability

- An agent-compatible model available in your target region (e.g., `gpt-4o`, `gpt-4.1`, `gpt-4.1-mini`). Check [model availability by region](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models). Models are deployed as part of the infrastructure setup — no pre-deployed model is required.
- Sufficient model quota (TPM) in your target region.

### Tools

| Tool | Install | Verify |
|---|---|---|
| **Azure CLI** | [Install](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) | `az --version` (2.50+) |
| **Azure Developer CLI (azd)** | [Install](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) | `azd version` |
| **Bicep CLI** | Included with Azure CLI | `az bicep version` |
| **Python** | [Install](https://www.python.org/downloads/) | `python --version` (3.9+) |

### Authentication

Log in before deploying:

```bash
az login
azd auth login
```

### For Managed VNet Setup (additional)

- Register the preview feature: `az feature register --namespace Microsoft.CognitiveServices --name AI.ManagedVnetPreview`
- Network administrator permissions (enterprise environments)
- An existing VNet or permission to create one

---

## Python Agent Scripts

The [`foundry_agents/`](foundry_agents/) folder contains scripts for creating, testing, and inspecting prompt agents and their managed long-term memory:

| Script | Description |
|---|---|
| `create_simple_prompt_agent.py` | Creates a prompt agent with a managed Memory Store and per-user `{{$userId}}` scope |
| `foundry_agent_thread_client.py` | Interactive chat client with conversation history via previous_response_id |
| `list_agent_memory_scopes.py` | Lists the memory store and scope expression configured on every agent version; supports `--json` |
| `memory_store_client.py` | REST client for Memory Store administration, update, search, and deletion operations |
| `dump_memory_items.py` | Exports memory items for caller-supplied scopes |
| `search_memories.py` | Searches a memory store for the signed-in user's scope |
| `assign_cosmosdb_role.py` | Assigns Cosmos DB Built-in Data Contributor role to the current user |

```bash
cd foundry_agents
pip install -r requirements.txt
python create_simple_prompt_agent.py
python foundry_agent_thread_client.py
python list_agent_memory_scopes.py --resource-group <resource-group> --latest-only
```

### Managed Memory Store API

[Memory in Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-memory) is managed long-term memory. It is separate from the conversation/thread history persisted by a standard capability host in customer-managed Cosmos DB.

The Python SDK exposes memory operations through `AIProjectClient.beta.memory_stores` (`azure-ai-projects>=2.3.0`):

| Operation | Python method | Scope required? |
|---|---|---|
| List/get/create/update/delete stores | `list`, `get`, `create`, `update`, `delete` | No |
| Extract and consolidate conversation memories | `begin_update_memories` | Yes |
| Search relevant or static memories | `search_memories` | Yes |
| List memory items | `list_memories` | Yes |
| Create an item | `create_memory` | Yes |
| Get/update/delete an item by memory ID | `get_memory`, `update_memory`, `delete_memory` | No scope argument; requires a known memory ID |
| Delete all memories in one scope | `delete_scope` | Yes |

Use `scope="{{$userId}}"` on a prompt agent's `MemorySearchPreviewTool` for per-user isolation. At response time, Foundry resolves it from the `x-memory-user-id` header when supplied; otherwise it derives the scope from the caller's Microsoft Entra identity. Low-level Memory Store API calls do not perform this identity resolution, so the caller must provide the concrete scope.

> **Scope discovery limitation:** The agent definition exposes its configured expression, such as `{{$userId}}`, and `list_agent_memory_scopes.py` can enumerate that configuration across agent versions. The Memory Store API does not provide an operation to enumerate the concrete scope partitions that exist in a store. Applications that set `x-memory-user-id` should retain their own user-to-scope registry for administration, export, and deletion workflows.

Memory Store documentation:

- [Create and use memory](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/memory-usage)
- [Memory concepts, limits, and availability](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-memory)
- [Python `BetaMemoryStoresOperations` API](https://learn.microsoft.com/en-us/python/api/azure-ai-projects/azure.ai.projects.operations.betamemorystoresoperations)

---

## Hosted Agents

The [`hosted_agents/`](hosted_agents/) folder contains containerized agents that run in Foundry-managed, per-session sandboxes. Use hosted agents when you need custom Python/C# orchestration, your own framework, custom HTTP payloads, persistent session files, or protocols beyond a prompt agent definition.

| Path | Description |
|---|---|
| [`hosted_agents/setup.md`](hosted_agents/setup.md) | End-to-end deployment and troubleshooting for hosted agents in a network-isolated project |
| [`hosted_agents/create_hosted_agent.py`](hosted_agents/create_hosted_agent.py) | Creates a hosted-agent version from an ACR image |
| [`hosted_agents/call_agent.py`](hosted_agents/call_agent.py) | Calls a deployed hosted agent |
| [`hosted_agents/agent-framework-agent-basic-responses/`](hosted_agents/agent-framework-agent-basic-responses/) | Basic Microsoft Agent Framework agent using the Responses protocol |
| [`hosted_agents/maf-backup-workflow/`](hosted_agents/maf-backup-workflow/) | Multi-agent backup workflow using the Invocations protocol and Foundry Toolbox |

Hosted agents can expose one or more protocols:

| Protocol | Use case | History/state ownership |
|---|---|---|
| Responses | Conversational agents and OpenAI-compatible clients | Foundry manages conversation history by conversation ID |
| Invocations | Webhooks, arbitrary JSON, batch jobs, and custom SSE | Agent code manages conversational state; Foundry manages session lifecycle |
| Invocations WebSocket | Real-time voice and bidirectional streaming | Agent-defined protocol and state behavior |

Each hosted agent receives a dedicated endpoint and Microsoft Entra agent identity. The container runs in an isolated sandbox per session; `$HOME` and `/files` persist across idle/resume cycles. A hosted agent can call the Memory Store APIs from its own code, but it must retain or derive the concrete scope just like any other low-level API caller. The Memory Store API does not enumerate scope partitions for hosted agents either.

Hosted-agent documentation:

- [Hosted agents concepts](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)
- [Quickstart: deploy a hosted agent](https://learn.microsoft.com/en-us/azure/foundry/agents/quickstarts/quickstart-hosted-agent)
- [Deploy a hosted agent](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent)
- [Manage hosted agents](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/manage-hosted-agent)

---

## Related Documentation

- [Foundry Agent Service overview](https://learn.microsoft.com/en-us/azure/foundry/agents/overview)
- [Environment setup guide](https://learn.microsoft.com/en-us/azure/foundry/agents/environment-setup)
- [Standard agent setup](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/standard-agent-setup)
- [Capability hosts](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/capability-hosts)
- [Memory Store API](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/memory-usage)
- [Hosted agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)
- [Azure AI Projects Python SDK](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-projects-readme)
- [SDK samples](https://aka.ms/azsdk/azure-ai-projects-v2/python/samples/)
- [Bicep templates (foundry-samples)](https://github.com/microsoft-foundry/foundry-samples/tree/main/infrastructure/infrastructure-setup-bicep)

---

## Deployment Notes (Managed VNet)

The following sections document a deployment into an existing VNet. Replace `<placeholder>` values with your own.

### Environment Details

| Setting | Value |
|---|---|
| Subscription | `<subscription-name>` (`<subscription-id>`) |
| Resource Group | `<resource-group>` |
| Location | `<location>` |
| VNet | `<vnet-name>` (`<vnet-address-space>`) |
| PE Subnet | `<pe-subnet-name>` (`<pe-subnet-prefix>`) — created by template |
| Isolation Mode | `AllowOnlyApprovedOutbound` |
| Deployment Name | `<deployment-name>` |

### Resources Created

| Resource | Name | Type |
|---|---|---|
| AI Services Account | `<aiservices-name>` | Microsoft.CognitiveServices/accounts |
| AI Foundry Project | `<project-name>` | Microsoft.CognitiveServices/accounts (project) |
| Cosmos DB | `<cosmosdb-name>` | Microsoft.DocumentDB/databaseAccounts |
| AI Search | `<search-name>` | Microsoft.Search/searchServices |
| Storage Account | `<storage-name>` | Microsoft.Storage/storageAccounts |

---

## Step 1: Clone the Template (Sparse Checkout)

```powershell
cd <your-repo-path>
git init
git remote add origin https://github.com/microsoft-foundry/foundry-samples.git
git config core.sparseCheckout true
"infrastructure/infrastructure-setup-bicep/18-managed-virtual-network-preview/*" | Out-File -Encoding ascii .git/info/sparse-checkout
git pull origin main
```

Files are placed under `infra/` due to the sparse checkout path mapping.

---

## Step 2: Verify Prerequisites

### 2.1 Preview Feature Registration

```powershell
az feature show --namespace Microsoft.CognitiveServices --name "AI.ManagedVnetPreview" --query "{name:name, state:properties.state}" -o table
```

Expected: `State = Registered`

### 2.2 Existing VNet Details

```powershell
az network vnet show --name <vnet-name> --resource-group <resource-group> --query "{id:id, addressSpace:addressSpace.addressPrefixes, subnets:subnets[].{name:name, prefix:addressPrefix}}" -o json
```

Review your VNet's address space and existing subnets to choose an unused prefix for the PE subnet.

### 2.3 Existing Private DNS Zones

Check for existing private DNS zones you can reuse:

| DNS Zone | Resource Group |
|---|---|
| `privatelink.services.ai.azure.com` | `<rg-or-empty>` |
| `privatelink.openai.azure.com` | `<rg-or-empty>` |
| `privatelink.cognitiveservices.azure.com` | `<rg-or-empty>` |
| `privatelink.blob.core.windows.net` | `<rg-or-empty>` |
| `privatelink.documents.azure.com` | `<rg-or-empty>` |
| `privatelink.search.windows.net` | `<rg-or-empty>` |
| `privatelink.azure-api.net` | `<rg-or-empty>` |

Set the value to the resource group name where the zone exists, or leave empty to create a new one.

---

## Step 3: Configure Parameters

Edit `infra/main.bicepparam` with values for the existing VNet and DNS zones:

```bicep
using './main.bicep'

param location = '<location>'
param isolationMode = 'AllowOnlyApprovedOutbound'
param aiServices = 'aiservices'
param firstProjectName = 'project'
param projectDescription = 'A project for the AI Foundry account with managed network secured deployed Agent'
param displayName = 'project'
param peSubnetName = '<pe-subnet-name>'

// Existing VNet
param existingVnetResourceId = '/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Network/virtualNetworks/<vnet-name>'
param vnetName = '<vnet-name>'

// Leave empty to create new resources
param aiSearchResourceId = ''
param azureStorageAccountResourceId = ''
param azureCosmosDBAccountResourceId = ''
param apiManagementResourceId = ''

// Reuse existing DNS zones (value = resource group name, empty = create new)
param existingDnsZones = {
  'privatelink.services.ai.azure.com': '<rg-or-empty>'
  'privatelink.openai.azure.com': '<rg-or-empty>'
  'privatelink.cognitiveservices.azure.com': '<rg-or-empty>'
  'privatelink.search.windows.net': '<rg-or-empty>'
  'privatelink.blob.core.windows.net': '<rg-or-empty>'
  'privatelink.documents.azure.com': '<rg-or-empty>'
  'privatelink.azure-api.net': '<rg-or-empty>'
}

// Subnet prefix for the new pe-subnet in the existing VNet
param vnetAddressPrefix = ''
param peSubnetPrefix = '<pe-subnet-prefix>'
```

Key decisions:
- **`existingVnetResourceId`**: Full ARM resource ID of your existing VNet.
- **`peSubnetPrefix`**: Choose an unused CIDR block in the existing VNet address space.
- **`existingDnsZones`**: Map to resource groups where each zone already exists. Leave empty to create new.

---

## Step 4: Deploy

```powershell
cd <your-repo-path>/infra

az deployment group create `
  --resource-group <resource-group> `
  --template-file main.bicep `
  --parameters main.bicepparam `
  --name <deployment-name> `
  --verbose
```

### Deployment Modules (in order)

| # | Module | Duration | Description |
|---|---|---|---|
| 1 | `validate-existing-resources` | ~1 min | Validates existing resource IDs |
| 2 | `vnet-<vnet-name>` | ~2 min | Creates PE subnet in existing VNet |
| 3 | `ai-<aiservices-name>` | ~3 min | Creates AI Services account with system-assigned identity |
| 4 | `dependencies` | ~15 min | Creates Cosmos DB, AI Search, Storage |
| 5 | `managed-network` | ~15 min | Configures managed VNet outbound rules |
| 6 | `private-endpoint` | ~5 min | Creates private endpoints in `pe-subnet` |
| 7 | `ai-project` | ~5 min | Creates the Foundry project |
| 8 | RBAC + capability host | ~2 min | Role assignments and project capability host |

Total deployment time: ~40-50 minutes.

### Monitor Deployment Progress

```powershell
# Check overall status
az deployment group show --resource-group vnet --name mvnet-deploy-202604131640 --query properties.provisioningState -o tsv

# Check individual operations
az deployment operation group list --resource-group vnet --name mvnet-deploy-202604131640 -o json | python -c "import sys,json; ops=json.load(sys.stdin); states={}; [states.update({o['properties'].get('targetResource',{}).get('resourceName','n/a'):o['properties']['provisioningState']}) for o in ops]; [print(v,k) for k,v in states.items()]"
```

---

## Step 5: Verify Managed Network

```powershell
az rest --method GET `
  --url "https://management.azure.com/subscriptions/e4718866-4e88-411f-a0b8-10c8051dc165/resourceGroups/vnet/providers/Microsoft.CognitiveServices/accounts/aiservicesgxwb/managedNetworks/default?api-version=2025-10-01-preview" `
  --query "properties.managedNetwork"
```

Expected result:

| Property | Value |
|---|---|
| Isolation Mode | `AllowOnlyApprovedOutbound` |
| Provisioning State | `Succeeded` |
| Status | `Active` |

### Outbound Rules Created

| Rule | Type | Target | Status |
|---|---|---|---|
| `storage-outbound-rule` | PrivateEndpoint | `aiservicesgxwbstorage` (blob) | Active |
| `Connection_aiservicesgxwbcosmosdb_sql` | PrivateEndpoint | `aiservicesgxwbcosmosdb` (sql) | Active |
| `__SYS_ST_AzureActiveDirectory_TCP` | ServiceTag | AAD (ports 80, 443) | Active |

> **Note:** Additional outbound rules for AI Search and other services should be created using the CLI scripts in `infra/update-outbound-rules-cli/`.

---

## Step 6: Assign Cosmos DB Data Plane Role

The Bicep template assigns control-plane RBAC, but the Cosmos DB **data plane** contributor role must be assigned separately:

```powershell
# Get your user object ID
$userId = az ad signed-in-user show --query id -o tsv

# Assign Cosmos DB Built-in Data Contributor (00000000-0000-0000-0000-000000000002)
az cosmosdb sql role assignment create `
  --account-name aiservicesgxwbcosmosdb `
  --resource-group vnet `
  --role-definition-id "00000000-0000-0000-0000-000000000002" `
  --principal-id $userId `
  --scope "/subscriptions/e4718866-4e88-411f-a0b8-10c8051dc165/resourceGroups/vnet/providers/Microsoft.DocumentDB/databaseAccounts/aiservicesgxwbcosmosdb"
```

---

## Step 7: Access via P2S VPN — DNS Configuration

Since the Foundry resource has public network access disabled, you must connect via the P2S VPN and resolve private endpoint FQDNs to their private IPs.

### Private Endpoint DNS Records

| FQDN | Private IP | Service |
|---|---|---|
| `aiservicesgxwb.services.ai.azure.com` | `10.0.4.7` | AI Foundry Portal |
| `aiservicesgxwb.cognitiveservices.azure.com` | `10.0.4.5` | Cognitive Services API |
| `aiservicesgxwb.openai.azure.com` | `10.0.4.6` | OpenAI API |
| `aiservicesgxwbstorage.blob.core.windows.net` | `10.0.4.8` | Blob Storage |
| `aiservicesgxwbsearch.search.windows.net` | `10.0.4.4` | AI Search |
| `aiservicesgxwbcosmosdb.documents.azure.com` | `10.0.4.9` | Cosmos DB (global) |
| `aiservicesgxwbcosmosdb-westus.documents.azure.com` | `10.0.4.10` | Cosmos DB (regional) |

### Option A: Hosts File (Quick Workaround)

Edit `C:\Windows\System32\drivers\etc\hosts` (as Administrator):

```
# AI Foundry - Managed VNet
10.0.4.7   aiservicesgxwb.services.ai.azure.com
10.0.4.5   aiservicesgxwb.cognitiveservices.azure.com
10.0.4.6   aiservicesgxwb.openai.azure.com
10.0.4.8   aiservicesgxwbstorage.blob.core.windows.net
10.0.4.4   aiservicesgxwbsearch.search.windows.net
10.0.4.9   aiservicesgxwbcosmosdb.documents.azure.com
10.0.4.10  aiservicesgxwbcosmosdb-westus.documents.azure.com
```

Then flush DNS:

```powershell
ipconfig /flushdns
```

> **Important:** Cosmos DB requires **both** the global (`aiservicesgxwbcosmosdb.documents.azure.com`) and regional (`aiservicesgxwbcosmosdb-westus.documents.azure.com`) entries. Missing the regional entry causes the SDK to fall back to the public IP, resulting in: `Error: Request originated from IP x.x.x.x through public internet`.

### Option B: Azure Private DNS Resolver (Production Recommended)

Deploy an Azure Private DNS Resolver in the VNet with an inbound endpoint. Configure your VPN client DNS to use the resolver's IP. This eliminates the need for hosts file entries.

### Option C: VPN Gateway Custom DNS

Set the VPN Gateway's P2S DNS server to `168.63.129.16` (Azure DNS) so the VPN client automatically resolves private DNS zones linked to the VNet.

### Verify DNS Resolution

While connected to the VPN:

```powershell
nslookup aiservicesgxwb.services.ai.azure.com
# Expected: 10.0.4.7

nslookup aiservicesgxwbcosmosdb.documents.azure.com
# Expected: 10.0.4.9

nslookup aiservicesgxwbcosmosdb-westus.documents.azure.com
# Expected: 10.0.4.10
```

---

## Accessing Foundry Portal

1. Connect to P2S VPN
2. Ensure DNS is configured (hosts file or DNS resolver)
3. Navigate to: `https://ai.azure.com`
4. Select the `aiservicesgxwb` account and `projectgxwb` project

---

## Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| "Private network access required" in browser | DNS not resolving to private IPs | Add hosts file entries or configure DNS resolver |
| Cosmos DB "Request originated from public internet" | Missing regional Cosmos DB DNS entry | Add `aiservicesgxwbcosmosdb-westus.documents.azure.com` → `10.0.4.10` |
| Deployment stuck on `dependencies` module | Cosmos DB / AI Search provisioning is slow | Normal — can take 15+ minutes |
| Deployment stuck on `managed-network` module | Managed VNet outbound rules provisioning | Normal — can take 15+ minutes |
| `AI.ManagedVnetPreview` not registered | Feature flag missing | Run `az feature register --namespace Microsoft.CognitiveServices --name AI.ManagedVnetPreview` |
