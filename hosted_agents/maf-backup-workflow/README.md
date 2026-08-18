# Data Protection & Resiliency Workflow

This project follows the same azd layout as `agent-framework-agent-basic-responses`:

```text
maf-backup-workflow/
	azure.yaml
	infra/
	src/
		maf-backup-policy-workflow/
			agent.yaml
			hosted_agent.py
			Dockerfile
			requirements.txt
		data-discovery-mcp/
			Dockerfile
			requirements.txt
			data_discovery_mcp/
```

It deploys two
runtime services:

- `maf-backup-policy-workflow`: a Foundry hosted agent using the Invocations
	protocol (`2.0.0`) for the human-in-the-loop workflow.
- `data-discovery-mcp`: a public streamable HTTP MCP server hosted by Azure
	Container Apps and exposed to the agent through the
	`backup-discovery-tools` Foundry Toolbox.

The Foundry entry point is
`src/maf-backup-policy-workflow/hosted_agent.py`.

## Hosted Invocation Contract

Use one `agent_session_id` for the full workflow. Each invocation advances to
the next human-input boundary.

Start a workflow:

```json
{
	"action": "start"
}
```

Advance the pending request:

```json
{
	"action": "respond",
	"request_id": "<request-id-from-the-screen-event>",
	"response": {
		"platform": "Azure"
	}
}
```

Inspect the current state without advancing it:

```json
{
	"action": "status"
}
```

Responses include workflow events and a status of `awaiting_input`, `running`,
`completed`, or `failed`.

## Local Hosted-Agent Test

Change to the hosted-agent service folder, then create the environment and
install dependencies:

```powershell
Set-Location .\src\maf-backup-policy-workflow
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the MCP server:

```powershell
Set-Location ..\data-discovery-mcp
..\maf-backup-policy-workflow\.venv\Scripts\python.exe .\data_discovery_mcp\data_discovery_mcp_server.py --port 3002
```

In another terminal, start the hosted agent:

```powershell
$env:DATA_DISCOVERY_MCP_ENDPOINT = "http://localhost:3002/mcp"
$env:USE_FOUNDRY_TOOLBOX = "false"
Set-Location ..\maf-backup-policy-workflow
.\.venv\Scripts\python.exe .\hosted_agent.py
```

Invoke it locally:

```powershell
Invoke-RestMethod -Method Post `
	-Uri "http://localhost:8088/invocations?agent_session_id=backup-demo" `
	-ContentType "application/json" `
	-Body '{"action":"start"}'
```

Use the included `.vscode/launch.json` and `.vscode/tasks.json` to debug with
Foundry Toolkit Agent Inspector.

## Azure Deployment

Prerequisites:

- Azure CLI and Azure Developer CLI authenticated to the target tenant.
- The `azure.ai.agents` azd extension (azd installs the version declared in
	`azure.yaml`).
- Permission to create role assignments, a Foundry project, model deployment,
	ACR, Container Apps, and a Toolbox.
- Model capacity for `gpt-5.4`, or an updated model declaration in
	`azure.yaml` and `agent.yaml`.

Provision and deploy from this directory:

```powershell
azd auth login
azd env new
azd up
```

The Bicep deployment creates the shared ACR, Container Apps environment, and
MCP Container App. The `DATA_DISCOVERY_MCP_ENDPOINT` Bicep output is consumed by
the `backup-discovery-tools` Toolbox service. The hosted agent receives the
Toolbox endpoint from azd and authenticates to it with its Azure identity.

The MCP Container App uses an unauthenticated public endpoint because Foundry
Toolbox must reach it. Add Entra protection and a Foundry remote-tool connection
before putting non-demo data or privileged tools behind this server.

## State and Scaling

The copied workflow retains its original in-memory session index and file-based
checkpoints. This is appropriate for development and a single hosted replica,
but container restarts can lose active sessions. Before production use, replace
`FileCheckpointStorage` and the in-memory session map with shared durable
storage such as Cosmos DB or Blob Storage, then test restart and concurrent
session recovery.

An end-to-end **Data Protection and Resiliency Plan Configuration** experience built with the [Microsoft Agent Framework](https://pypi.org/project/agent-framework/). It guides administrators through a multi-step wizard to configure data protection policies — collecting inputs, validating choices, explaining trade-offs, and producing a deployable policy configuration.

## Overview

![Demo](docs/webapp_demo.gif)

Configuring data protection and resilience plans across multi-cloud environments is complex, tedious, and error-prone. Administrators must understand data classification, retention policies, replication strategies, compliance requirements, and cyber recoverability — all while navigating platform-specific settings. A single misconfiguration can leave critical data unprotected or violate regulatory mandates.

AI agents transform this experience. Instead of manually researching and configuring each setting, agents autonomously discover data, classify sensitivity, recommend protection rules, and generate resiliency plans — turning hours of expert work into a guided conversation. The administrator stays in control through human-in-the-loop checkpoints at every step, while agents handle the heavy lifting:

1. **Select Source** — agents analyze available cloud platforms and SaaS sources, prioritizing which to protect based on data volume and criticality.
2. **Source Details** — agents recommend optimal discovery settings, suggesting which import options to enable for the selected platform.
3. **Data Discovery** — agents autonomously scan and classify data via MCP tools, surfacing sensitivity patterns, exposure risks, and access footprints that would take hours to assess manually.
4. **Protection Advisor** — agents query the application inventory and recommend SmartProtect rules, threat monitoring, and resilience orchestration tailored to the discovered data and compliance posture.
5. **Resiliency Plan** — agents synthesize data from multiple MCP tools to generate a comprehensive 3-2-1 protection policy with cyber recoverability blueprints, eliminating guesswork around backup frequency, retention, and replication.
6. **Final Approval** — agents perform compliance review, flagging gaps and best-practice violations before the administrator signs off — or rejects to iterate.

![Data Protection Workflow Diagram](docs/backup_workflow_diagram.svg)

Each executor emits a `ScreenRequest` via `request_info` to pause for human input. The frontend renders the recommended screen and sends the user's response back.

## Architecture

| Component | Description |
|---|---|
| **Backend** (`backup_api/`) | FastAPI server with SSE streaming for real-time workflow events and human-in-the-loop interactions |
| **Frontend** (`backup-ui/`) | React + Vite UI that renders the guided wizard experience |
| **MCP Server** (`data_discovery_mcp/`) | FastMCP-based Model Context Protocol server providing data discovery, classification, and inventory tools |
| **Workflow** (`backup_api/workflow.py`) | Microsoft Agent Framework workflow definition with executors and agents |

## Key Capabilities of Microsoft Agent Framework

The framework uses a modified **Pregel execution model** — a Bulk Synchronous Parallel (BSP) approach with superstep-based processing. This provides:

- **Deterministic execution** — given the same input, the workflow always executes in the same order
- **Reliable checkpointing** — state can be saved at superstep boundaries for fault tolerance
- **Workflow state persistence** — pause and resume from any step in the workflow, even across server restarts; the full workflow state including pending human-in-the-loop requests is persisted to disk and restored on resume
- **Simpler reasoning** — no race conditions between supersteps; each sees a consistent view of messages

The framework performs comprehensive **validation** when building workflows:

- **Type compatibility** — ensures message types are compatible between connected executors
- **Graph connectivity** — verifies all executors are reachable from the start executor
- **Executor binding** — confirms all executors are properly bound and instantiated
- **Edge validation** — checks for duplicate edges and invalid connections

## Prerequisites

- Python 3.12+
- Node.js (for the frontend)
- A [Microsoft Foundry](https://ai.azure.com/) project with a model deployment (e.g. `gpt-5.4` or `gpt-5.4-mini`) — the same model endpoint is used by all agents in the workflow
- Azure CLI logged in (`az login`) — used for authenticating to Foundry via `AzureCliCredential`

## Getting Started

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Configure environment variables

Copy and edit the environment file at `backup_api/.env`:

```env
# Data Discovery MCP Server (default works for local development)
DATA_DISCOVERY_MCP_ENDPOINT=http://localhost:3002/mcp

# Microsoft Foundry — required for AI-powered agent steps
FOUNDRY_PROJECT_ENDPOINT=https://<your-foundry-resource>.services.ai.azure.com/api/projects/<project-name>
FOUNDRY_MODEL=gpt-5.4
# Optional; defaults to 30 seconds before using mock fallback data
FOUNDRY_REQUEST_TIMEOUT_SECONDS=30
```

| Variable | Description |
|---|---|
| `DATA_DISCOVERY_MCP_ENDPOINT` | URL of the Data Discovery MCP server. Defaults to `http://localhost:3002/mcp` (started automatically by `run.ps1`) |
| `FOUNDRY_PROJECT_ENDPOINT` | Your Foundry project endpoint. Find it in the [Azure AI Foundry portal](https://ai.azure.com/) under your project's **Overview** page |
| `FOUNDRY_MODEL` | The deployed model name in your Foundry project (e.g. `gpt-5.4`, `gpt-5.4-mini`). All agents in the workflow share this model |
| `FOUNDRY_REQUEST_TIMEOUT_SECONDS` | Maximum time to wait for each Foundry agent call before continuing with mock fallback data. Defaults to `30` seconds |

Ensure you've run `az login` before starting the workflow — the backend authenticates to Foundry using `AzureCliCredential`.

### 3. Run

The launch script installs all dependencies, starts the MCP server, FastAPI backend, and Vite frontend, and streams their logs:

**Windows (PowerShell):**

```powershell
.\run.ps1
```

**macOS / Linux:**

```bash
chmod +x run.sh
./run.sh
```

This launches:

| Service | URL | Port |
|---|---|---|
| Data Discovery MCP Server | http://localhost:3002 | 3002 |
| FastAPI Backend | http://localhost:8000 | 8000 |
| Vite Frontend | http://localhost:5173 | 5173 |

Open http://localhost:5173 in your browser to start the data protection policy wizard.

Press `Ctrl+C` to stop all services.

## Superstep Execution Model

![Superstep Execution Model](docs/maf_superstep_execution_model.svg)

Learn more about workflows in the [Microsoft Agent Framework Workflows documentation](https://learn.microsoft.com/en-us/agent-framework/workflows/workflows?pivots=programming-language-python).
