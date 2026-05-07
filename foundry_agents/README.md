# Foundry Agent Scripts

Python scripts for creating and interacting with agents in a [Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/agents/overview) project. All scripts auto-discover the Foundry account and project from an Azure resource group — no manual endpoint configuration needed.

## Prerequisites

- Python 3.9+
- An Azure subscription with a deployed Foundry project (see the [deployment options](../README.md))
- Logged in: `az login`

## Setup

```bash
cd foundry_agents
python -m venv .venv
.venv\Scripts\activate    # Windows
pip install -r requirements.txt
```

## Scripts

### 1. Create a Simple Prompt Agent

Creates a basic prompt agent (no tools) using `gpt-4.1-mini`:

```
> python create_simple_prompt_agent.py

Enter the Azure resource group name: rg-foundry4-ch
Using subscription: e4718866-...
Found AI Services account: foundrymkmz
Found project: projectmkmz
Enter a name for the agent [simple-prompt-agent]:

Ready to create agent:
  Resource Group: rg-foundry4-ch
  Account:        foundrymkmz
  Project:        projectmkmz
  Agent Name:     simple-prompt-agent
  Model:          gpt-4.1-mini
  Endpoint:       https://foundrymkmz.services.ai.azure.com/api/projects/projectmkmz

Proceed? (y/N): y

Agent created successfully!
  Name:    simple-prompt-agent
  ID:      simple-prompt-agent:1
  Version: 1
```

### 2. Chat with Conversation History

Interactive chat that chains `previous_response_id` to maintain multi-turn conversation context. State is persisted in Cosmos DB (standard agent setup):

```
> python foundry_agent_thread_client.py

Enter the Azure resource group name: rg-foundry4-ch
Enter the agent name: simple-prompt-agent

you> hello
agent> Hello! How can I assist you today?

you> remember my name is Alice
agent> Got it, Alice! I'll remember that. How can I help you?

you> what's my name?
agent> Your name is Alice!
```

### 3. Assign Cosmos DB Role

Assigns the Cosmos DB Built-in Data Contributor role to the current logged-in user. Required for the Foundry portal to load agents in standard agent setup:

```
> python assign_cosmosdb_role.py

Enter the Azure resource group name: rg-foundry4-ch
Found Cosmos DB account: mkmzcosmosdb
Current user: user@example.com (b47a4e95-...)

Ready to assign Cosmos DB Built-in Data Contributor role:
  Cosmos DB Account: mkmzcosmosdb
  Principal:         user@example.com

Proceed? (y/N): y
Role assignment created successfully.
```

### 4. Create Multi-Tool Agent

Creates an agent with MCP tools and Fabric Data Agent connections. Requires additional environment variables in `.env` (see `.env.sample`):

```bash
python create_multitool_prompt_agent.py
```

## Environment Variables

Copy `.env.sample` to `.env` and fill in values. Most scripts prompt interactively and don't require `.env`, but `create_multitool_prompt_agent.py` does.

| Variable | Used By | Description |
|---|---|---|
| `AZURE_SUBSCRIPTION_ID` | All scripts | Auto-detected if not set |
| `foundry_account_name` | `create_multitool_prompt_agent.py` | Foundry account name |
| `foundry_project_name` | `create_multitool_prompt_agent.py` | Foundry project name |
| `foundry_resource_group` | `create_multitool_prompt_agent.py` | Resource group name |
| `agent_name` | `create_multitool_prompt_agent.py` | Agent name to create/update |
