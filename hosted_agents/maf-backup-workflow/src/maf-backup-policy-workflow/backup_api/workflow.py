"""
Backup Policy Configuration Workflow using Microsoft Agent Framework.

Workflow graph:
  SourceSelector → SourceConfigurator → DiscoveryRunner →
    ProtectionAdvisor (Agent) → ResiliencyPlanner (Agent) → ApprovalGateway
                   ↑                                              |
                   └─────────────── (reject) ─────────────────────┘

Each executor emits a ScreenRequest via request_info to pause for human input.
The frontend renders the recommended screen and sends the user's response back.
"""

import asyncio
import contextvars
import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from agent_framework import (
    Agent,
    Executor,
    FileCheckpointStorage,
    MCPStreamableHTTPTool,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    handler,
    response_handler,
)

logger = logging.getLogger(__name__)

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

MOCK_DATA_PATH = Path(__file__).parent.parent / "backup_mock_data.json"
with open(MOCK_DATA_PATH, encoding="utf-8") as _f:
    MOCK_DATA: dict[str, Any] = json.load(_f)

CHECKPOINT_DIR = Path(__file__).parent.parent / "backup_checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# MCP server endpoint for data discovery
# ---------------------------------------------------------------------------

DATA_DISCOVERY_MCP_URL = os.getenv("DATA_DISCOVERY_MCP_ENDPOINT", "http://localhost:3002/mcp")
FOUNDRY_REQUEST_TIMEOUT_SECONDS = float(
    os.getenv("FOUNDRY_REQUEST_TIMEOUT_SECONDS", "30")
)


# ---------------------------------------------------------------------------
# MCP call tracking — emits tool_call events to the frontend via callback
# ---------------------------------------------------------------------------

_tool_call_emitter: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "tool_call_emitter", default=None
)


def set_tool_call_emitter(emitter):
    """Set the async callback that emits tool_call events to the frontend."""
    _tool_call_emitter.set(emitter)


async def _emit_tool_call(tool_name: str, server: str, status: str, error: str | None = None):
    """Emit a tool_call event if an emitter is configured."""
    emitter = _tool_call_emitter.get()
    if emitter:
        info = {"tool": tool_name, "server": server, "status": status}
        if error:
            info["error"] = error
        await emitter(info)


# ---------------------------------------------------------------------------
# Shared dataclass sent to frontend via request_info
# ---------------------------------------------------------------------------

@dataclass
class ScreenRequest:
    """HITL request that tells the frontend which screen to render."""
    screen: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    step: int = 0
    total_steps: int = 6


# ---------------------------------------------------------------------------
# Agent helper
# ---------------------------------------------------------------------------

def _create_mcp_tool() -> MCPStreamableHTTPTool:
    """Create an MCP tool instance for the Data Discovery server."""
    toolbox_endpoint = os.getenv("TOOLBOX_ENDPOINT")
    toolbox_name = os.getenv("TOOLBOX_NAME", "backup-discovery-tools")
    project_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").rstrip("/")

    if not toolbox_endpoint and toolbox_name:
        injected_name = f"TOOLBOX_{toolbox_name.upper().replace('-', '_')}_MCP_ENDPOINT"
        toolbox_endpoint = os.getenv(injected_name)
    if not toolbox_endpoint and os.getenv("USE_FOUNDRY_TOOLBOX") == "true" and project_endpoint:
        toolbox_endpoint = (
            f"{project_endpoint}/toolboxes/{toolbox_name}/mcp?api-version=v1"
        )

    if toolbox_endpoint:
        import httpx
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://ai.azure.com/.default"
        )

        class ToolboxAuth(httpx.Auth):
            def auth_flow(self, request):
                request.headers["Authorization"] = f"Bearer {token_provider()}"
                yield request

        http_client = httpx.AsyncClient(
            auth=ToolboxAuth(),
            headers={"Foundry-Features": "Toolboxes=V1Preview"},
            timeout=120.0,
        )
        return MCPStreamableHTTPTool(
            name=toolbox_name,
            url=toolbox_endpoint,
            http_client=http_client,
            load_prompts=False,
        )

    return MCPStreamableHTTPTool(
        name="data_discovery_mcp",
        url=DATA_DISCOVERY_MCP_URL,
    )


def _try_create_agent(
    name: str,
    instructions: str,
    tools: list | None = None,
) -> Agent | None:
    """Create a Foundry-backed Agent if credentials are configured."""
    try:
        from agent_framework.foundry import FoundryChatClient
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

        endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
        model = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME") or os.environ.get(
            "FOUNDRY_MODEL"
        )
        if not endpoint or not model:
            return None
        credential = (
            ManagedIdentityCredential()
            if os.getenv("FOUNDRY_AGENT_NAME")
            else DefaultAzureCredential()
        )
        return Agent(
            client=FoundryChatClient(
                project_endpoint=endpoint,
                model=model,
                credential=credential,
            ),
            instructions=instructions,
            name=name,
            tools=tools or [],
        )
    except Exception:
        return None


async def _run_agent(agent: Agent, prompt: str, agent_name: str):
    """Run a Foundry agent without allowing a remote call to stall the workflow."""
    print(f"[workflow] Calling Foundry agent: {agent_name}")
    try:
        response = await asyncio.wait_for(
            agent.run(prompt),
            timeout=FOUNDRY_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        error_detail = str(exc) or "request timed out"
        print(
            f"[workflow] Foundry agent {agent_name} failed: "
            f"{type(exc).__name__}: {error_detail}; using fallback"
        )
        raise
    print(f"[workflow] Foundry agent completed: {agent_name}")
    return response


# =========================================================================
# Executor 1 — Select Source
# =========================================================================

class SourceSelector(Executor):
    """Step 1: Agent analyzes available sources and presents recommendations."""

    def __init__(self, id: str = "source_selector", agent: Agent | None = None):
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, intent: str, ctx: WorkflowContext) -> None:
        sources = MOCK_DATA["screen_1_select_source_platforms"]
        message = "Select the cloud platform or SaaS source you want to protect."

        if self._agent:
            try:
                prompt = (
                    "You are a backup source selection advisor. Analyze the available "
                    "cloud platforms and SaaS sources and provide a recommendation for "
                    "which sources to prioritize for backup protection. "
                    "Respond with valid JSON containing 'sources' (the list) and "
                    "'recommendation' (your advice).\n\n"
                    f"Available sources: {json.dumps(sources)[:2000]}\n"
                    f"User intent: {intent}"
                )
                agent_response = await _run_agent(self._agent, prompt, self.id)
                result = json.loads(agent_response.text)
                recommended_sources = result.get("sources")
                if isinstance(recommended_sources, list):
                    selected_names = {
                        item.get("name")
                        for item in recommended_sources
                        if isinstance(item, dict) and item.get("selected") is True
                    }
                    if selected_names:
                        sources = [
                            {**source, "selected": source["name"] in selected_names}
                            for source in sources
                        ]
                if "recommendation" in result:
                    message = result["recommendation"]
            except Exception:
                pass

        await ctx.request_info(
            request_data=ScreenRequest(
                screen="select_source",
                data={"sources": sources},
                message=message,
                step=1,
            ),
            response_type=str,
        )

    @response_handler
    async def on_response(self, req: ScreenRequest, response: str, ctx: WorkflowContext) -> None:
        await ctx.send_message(response, target_id="source_configurator")

    @override
    async def on_checkpoint_save(self) -> dict[str, Any]:
        return {}

    @override
    async def on_checkpoint_restore(self, state: dict[str, Any]) -> None:
        pass


# =========================================================================
# Executor 2 — Source Details & Discovery Options
# =========================================================================

class SourceConfigurator(Executor):
    """Step 2: Agent recommends source configuration and discovery toggles."""

    def __init__(self, id: str = "source_configurator", agent: Agent | None = None):
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, selection_json: str, ctx: WorkflowContext) -> None:
        try:
            selection = json.loads(selection_json)
        except (json.JSONDecodeError, TypeError):
            selection = {}

        platform = selection.get("platform", "Azure")
        details = dict(MOCK_DATA["screen_2_source_details"])
        details["platform"] = platform

        source_types = {
            "AWS": "AWS Account",
            "Azure": "Azure Subscription",
            "GCP": "GCP Project",
        }
        details["source_type"] = source_types.get(platform, platform)
        message = f"Configure {platform} source details and start discovery."

        if self._agent:
            try:
                prompt = (
                    "You are a backup source configuration advisor. Recommend optimal "
                    "discovery settings for the selected platform. Suggest which import "
                    "options to enable (application discovery, tags, metadata, IAM). "
                    "Respond with valid JSON containing 'details' (config object) and "
                    "'message' (your recommendation).\n\n"
                    f"Platform: {platform}\n"
                    f"Current config: {json.dumps(details)[:2000]}"
                )
                agent_response = await _run_agent(self._agent, prompt, self.id)
                result = json.loads(agent_response.text)
                if "details" in result:
                    details.update(result["details"])
                if "message" in result:
                    message = result["message"]
            except Exception:
                pass

        await ctx.request_info(
            request_data=ScreenRequest(
                screen="source_details",
                data=details,
                message=message,
                step=2,
            ),
            response_type=str,
        )

    @response_handler
    async def on_response(self, req: ScreenRequest, response: str, ctx: WorkflowContext) -> None:
        await ctx.send_message(response, target_id="discovery_runner")

    @override
    async def on_checkpoint_save(self) -> dict[str, Any]:
        return {}

    @override
    async def on_checkpoint_restore(self, state: dict[str, Any]) -> None:
        pass


# =========================================================================
# Executor 3 — Data Discovery (via MCP Server)
# =========================================================================

class DiscoveryRunner(Executor):
    """Step 3: Agent-driven data discovery — agent uses MCP tools autonomously."""

    def __init__(self, id: str = "discovery_runner", agent: Agent | None = None):
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, config_json: str, ctx: WorkflowContext) -> None:
        try:
            config = json.loads(config_json)
        except (json.JSONDecodeError, TypeError):
            config = {}

        discovery_data = None
        message = "Discovery complete. Review the discovered data and proceed."

        if self._agent:
            try:
                platform = config.get("platform", "Azure")
                org_id = config.get("organization_id", "auto-detected")
                prompt = (
                    "Use the run_discovery_scan tool to scan and classify data for "
                    f"platform '{platform}' with organization_id '{org_id}'. "
                    "Then analyze the results for sensitivity patterns and exposure risks. "
                    "Respond with valid JSON containing 'discovery' (the scan results "
                    "enriched with your analysis) and 'message' (your summary)."
                )
                agent_response = await _run_agent(self._agent, prompt, self.id)
                result = json.loads(agent_response.text)
                discovery_data = result.get("discovery")
                if "message" in result:
                    message = result["message"]
            except Exception:
                pass

        if discovery_data is None:
            discovery_data = MOCK_DATA["screen_3_data_discovered"]

        await ctx.request_info(
            request_data=ScreenRequest(
                screen="data_discovered",
                data=discovery_data,
                message=message,
                step=3,
            ),
            response_type=str,
        )

    @response_handler
    async def on_response(self, req: ScreenRequest, response: str, ctx: WorkflowContext) -> None:
        # Pass discovery results + user-selected capabilities to the protection advisor
        try:
            user_resp = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            user_resp = {}
        context = json.dumps({
            "discovery": req.data,
            "capabilities": user_resp.get("capabilities", []),
        })
        await ctx.send_message(context, target_id="protection_advisor")

    @override
    async def on_checkpoint_save(self) -> dict[str, Any]:
        return {}

    @override
    async def on_checkpoint_restore(self, state: dict[str, Any]) -> None:
        pass


# =========================================================================
# Executor 4 — Protection Advisor (Agent-powered)
# =========================================================================

class ProtectionAdvisor(Executor):
    """Step 4: Agent recommends SmartProtect rules + threat monitoring config.
    When resilience orchestration is selected, fetches apps from inventory MCP."""

    def __init__(self, id: str = "protection_advisor", agent: Agent | None = None):
        super().__init__(id=id)
        self._agent = agent
        self._iteration = 0

    @handler
    async def handle(self, context_json: str, ctx: WorkflowContext) -> None:
        self._iteration += 1

        # Parse which capabilities the user selected
        try:
            context = json.loads(context_json)
        except (json.JSONDecodeError, TypeError):
            context = {}
        capabilities = context.get("capabilities", [])
        # Normalize: if empty or coming from a reject loop, enable all
        if not capabilities:
            capabilities = ["Enable SmartProtect", "Enable Always-On Threat Monitoring",
                            "Setup Application Resilience Orchestration"]

        recommendations = None
        if self._agent:
            try:
                prompt = (
                    "You are an enterprise backup protection advisor. "
                    "Based on the discovered data, recommend protection configuration. "
                    f"The user wants these capabilities: {', '.join(capabilities)}. "
                    "Use the list_application_groups tool to fetch the current application "
                    "inventory for resilience orchestration. "
                    "Respond with valid JSON containing your recommendations "
                    "(smartprotect_rules, threat_monitoring, resilience_orchestration, "
                    "inventory_applications as needed).\n\n"
                    f"Context: {context_json[:2000]}"
                )
                agent_response = await _run_agent(self._agent, prompt, self.id)
                recommendations = json.loads(agent_response.text)
            except Exception:
                recommendations = None

        if recommendations is None:
            want_smartprotect = any("SmartProtect" in c for c in capabilities)
            want_threat = any("Threat" in c for c in capabilities)
            want_resilience = any("Resilience" in c or "Orchestration" in c for c in capabilities)
            recommendations = {}
            if want_smartprotect:
                recommendations["smartprotect_rules"] = MOCK_DATA["screen_4_smartprotect_rules"]
            if want_threat:
                recommendations["threat_monitoring"] = MOCK_DATA["screen_5_threat_monitoring_config"]["threat_monitoring"]
            if want_resilience:
                recommendations["resilience_orchestration"] = MOCK_DATA["screen_5_threat_monitoring_config"]["resilience_orchestration"]
                inv = MOCK_DATA["screen_6_inventory_and_copilot"]["inventory"]
                recommendations["inventory_applications"] = [
                    {"application_group": ag, "object_count": sum(
                        1 for o in inv["objects"] if o["application_group"] == ag
                    )}
                    for ag in inv["application_groups"]
                ]

        recommendations["enabled_capabilities"] = capabilities

        await ctx.request_info(
            request_data=ScreenRequest(
                screen="protection_advisor",
                data=recommendations,
                message=f"AI recommendations for: {', '.join(capabilities)}.",
                step=4,
            ),
            response_type=str,
        )

    @response_handler
    async def on_response(self, req: ScreenRequest, response: str, ctx: WorkflowContext) -> None:
        # Combine confirmed protection config and forward to resiliency planner
        context = json.dumps({
            "confirmed_protection": req.data,
            "user_response": response,
        })
        await ctx.send_message(context, target_id="resiliency_planner")

    @override
    async def on_checkpoint_save(self) -> dict[str, Any]:
        return {"iteration": self._iteration}

    @override
    async def on_checkpoint_restore(self, state: dict[str, Any]) -> None:
        self._iteration = state.get("iteration", 0)


# =========================================================================
# Executor 5 — Resiliency Planner (Agent-powered)
# =========================================================================

class ResiliencyPlanner(Executor):
    """Step 5: Agent creates comprehensive resiliency plan with copilot view.
    Fetches inventory data from the Data Discovery MCP server."""

    def __init__(self, id: str = "resiliency_planner", agent: Agent | None = None):
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, confirmed_json: str, ctx: WorkflowContext) -> None:
        plan = None

        if self._agent:
            try:
                prompt = (
                    "You are a resiliency planning agent. Create a comprehensive "
                    "application resiliency plan. Use these MCP tools to gather data:\n"
                    "- get_inventory_summary: get inventory overview\n"
                    "- list_application_groups: get app groups with protection status\n"
                    "- get_resiliency_plan: get the current resiliency plan\n"
                    "- get_protection_policy_detail: get 3-2-1 protection policy\n"
                    "- get_cyber_recoverability_blueprints: get recovery blueprints\n\n"
                    "Call these tools, then respond with JSON containing 'inventory', "
                    "'resiliency_plan', 'protection_policy', and 'cyber_recoverability'.\n\n"
                    f"Confirmed protection config: {confirmed_json[:2000]}"
                )
                agent_response = await _run_agent(self._agent, prompt, self.id)
                plan = json.loads(agent_response.text)
            except Exception:
                plan = None

        if plan is None:
            inv_data = MOCK_DATA["screen_6_inventory_and_copilot"]
            # Extract platform from upstream data to fix source_id display
            platform = "Azure"
            try:
                confirmed = json.loads(confirmed_json)
                disc = confirmed.get("confirmed_protection", {}).get("discovery", {})
                if isinstance(disc, dict):
                    platform = disc.get("source_platform", disc.get("platform", "Azure"))
            except Exception:
                pass

            inventory = dict(inv_data["inventory"])
            org_num = "20387136734"
            source_id_map = {
                "AWS": f"AWS-OrgID-{org_num}",
                "Azure": f"Azure-SubscriptionID-{org_num}",
                "GCP": f"GCP-ProjectID-{org_num}",
            }
            inventory["source_id"] = source_id_map.get(platform, f"{platform}-OrgID-{org_num}")

            plan = {
                "inventory": inventory,
                "resiliency_plan": inv_data["resiliency_plan"],
                "protection_policy": MOCK_DATA["screen_7_protection_policy_detail"],
                "cyber_recoverability": MOCK_DATA["screen_8_cyber_recoverability"],
            }

        await ctx.request_info(
            request_data=ScreenRequest(
                screen="resiliency_plan",
                data=plan,
                message="Review the AI-generated resiliency plan. Approve or request changes.",
                step=5,
            ),
            response_type=str,
        )

    @response_handler
    async def on_response(self, req: ScreenRequest, response: str, ctx: WorkflowContext) -> None:
        # Forward the plan + user decision to approval gateway
        context = json.dumps({
            "plan": req.data,
            "user_response": response,
        })
        await ctx.send_message(context, target_id="approval_gateway")

    @override
    async def on_checkpoint_save(self) -> dict[str, Any]:
        return {}

    @override
    async def on_checkpoint_restore(self, state: dict[str, Any]) -> None:
        pass


# =========================================================================
# Executor 6 — Final Approval Gateway
# =========================================================================

class ApprovalGateway(Executor):
    """Step 6: Agent-powered final review & approval. Approve outputs policy, reject loops back."""

    def __init__(self, id: str = "approval_gateway", agent: Agent | None = None):
        super().__init__(id=id)
        self._agent = agent
        self._iteration = 0

    @handler
    async def handle(self, plan_json: str, ctx: WorkflowContext) -> None:
        self._iteration += 1
        try:
            plan_data = json.loads(plan_json)
        except (json.JSONDecodeError, TypeError):
            plan_data = {}

        final_rules = {
            "rules": MOCK_DATA["screen_10_protection_rules"],
            "backup_policies": MOCK_DATA["backup_policies"],
            "plan_summary": plan_data.get("plan", {}),
            "iteration": self._iteration,
        }
        message = "Review the final protection rules. Approve to create or reject to revise."

        if self._agent:
            try:
                prompt = (
                    "You are a backup policy compliance reviewer. Analyze the final "
                    "protection rules and backup policies for completeness, compliance "
                    "gaps, and best-practice adherence. Highlight any risks. "
                    "Respond with valid JSON containing 'rules' (reviewed rules), "
                    "'backup_policies' (reviewed policies), and 'message' (your review summary).\n\n"
                    f"Rules: {json.dumps(final_rules)[:2000]}\n"
                    f"Plan: {plan_json[:1000]}"
                )
                agent_response = await _run_agent(self._agent, prompt, self.id)
                result = json.loads(agent_response.text)
                if "rules" in result:
                    final_rules["rules"] = result["rules"]
                if "backup_policies" in result:
                    final_rules["backup_policies"] = result["backup_policies"]
                if "message" in result:
                    message = result["message"]
            except Exception:
                pass

        await ctx.request_info(
            request_data=ScreenRequest(
                screen="final_approval",
                data=final_rules,
                message=message,
                step=6,
            ),
            response_type=str,
        )

    @response_handler
    async def on_response(self, req: ScreenRequest, response: str, ctx: WorkflowContext) -> None:
        try:
            resp = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            resp = {"action": response.strip().lower()}

        action = resp.get("action", "approve")

        if action == "approve":
            from datetime import datetime, timezone
            final_policy = {
                "status": "approved",
                "rules": req.data.get("rules", []),
                "backup_policies": req.data.get("backup_policies", []),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "iteration": self._iteration,
            }
            await ctx.yield_output(json.dumps(final_policy, default=str))
        else:
            # Reject — loop back to protection advisor with feedback
            feedback = resp.get("feedback", "User requested revisions")
            await ctx.send_message(
                json.dumps({"action": "revise", "feedback": feedback}),
                target_id="protection_advisor",
            )

    @override
    async def on_checkpoint_save(self) -> dict[str, Any]:
        return {"iteration": self._iteration}

    @override
    async def on_checkpoint_restore(self, state: dict[str, Any]) -> None:
        self._iteration = state.get("iteration", 0)


# =========================================================================
# Workflow Builder
# =========================================================================

WORKFLOW_NAME = "backup_policy_workflow"


def create_backup_workflow(checkpoint_storage: FileCheckpointStorage | None = None) -> Workflow:
    """Assemble the backup policy configuration workflow."""

    if checkpoint_storage is None:
        checkpoint_storage = FileCheckpointStorage(
            storage_path=CHECKPOINT_DIR,
            allowed_checkpoint_types=["backup_api.workflow:ScreenRequest"],
        )

    # Optional AI agents — one per executor for fully agent-driven workflow
    # MCP tool for agents that need data discovery / inventory access
    mcp_tool = _create_mcp_tool()

    selector_agent = _try_create_agent(
        "source_selector_ai",
        "You are a backup source selection advisor. Analyze available cloud platforms "
        "and SaaS sources to recommend which to prioritize for backup protection. "
        "Always respond with valid JSON only.",
    )
    configurator_agent = _try_create_agent(
        "source_configurator_ai",
        "You are a backup source configuration advisor. Recommend optimal discovery "
        "settings, import options, and credential requirements for each platform. "
        "Always respond with valid JSON only.",
    )
    discovery_agent = _try_create_agent(
        "discovery_analyst_ai",
        "You are a data discovery analyst. You have access to MCP tools for scanning "
        "and classifying data. Use run_discovery_scan to scan cloud sources. "
        "Analyze results for sensitivity patterns and exposure risks. "
        "Always respond with valid JSON only.",
        tools=[mcp_tool],
    )
    advisor_agent = _try_create_agent(
        "protection_advisor_ai",
        "You are an expert backup protection advisor. You have access to MCP tools "
        "for querying the application inventory. Use list_application_groups to get "
        "current app groups and their protection status. Recommend optimal SmartProtect "
        "rules and threat monitoring configurations. Always respond with valid JSON only.",
        tools=[mcp_tool],
    )
    planner_agent = _try_create_agent(
        "resiliency_planner_ai",
        "You are a resiliency planning expert. You have access to MCP tools for "
        "querying inventory, resiliency plans, protection policies, and cyber "
        "recoverability blueprints. Use get_inventory_summary, list_application_groups, "
        "get_resiliency_plan, get_protection_policy_detail, and "
        "get_cyber_recoverability_blueprints to gather data. Create comprehensive "
        "resiliency plans following a 3-2-1 backup strategy. "
        "Always respond with valid JSON only.",
        tools=[mcp_tool],
    )
    approval_agent = _try_create_agent(
        "approval_reviewer_ai",
        "You are a backup policy compliance reviewer. You have access to MCP tools "
        "for verifying inventory and policy data. Analyze final protection rules "
        "and backup policies for completeness, compliance gaps, and best-practice "
        "adherence. Always respond with valid JSON only.",
        tools=[mcp_tool],
    )

    agent_names = {
        "selector": selector_agent,
        "configurator": configurator_agent,
        "discovery": discovery_agent,
        "advisor": advisor_agent,
        "planner": planner_agent,
        "approval": approval_agent,
    }
    for name, agent in agent_names.items():
        if agent:
            print(f"[workflow] Using Foundry-backed {name} agent")
        else:
            print(f"[workflow] {name.capitalize()} agent not configured — using mock/fallback")

    # Executors — all agent-driven
    source_selector = SourceSelector(agent=selector_agent)
    source_configurator = SourceConfigurator(agent=configurator_agent)
    discovery_runner = DiscoveryRunner(agent=discovery_agent)
    protection_advisor = ProtectionAdvisor(agent=advisor_agent)
    resiliency_planner = ResiliencyPlanner(agent=planner_agent)
    approval_gateway = ApprovalGateway(agent=approval_agent)

    # Workflow DAG
    builder = (
        WorkflowBuilder(
            name=WORKFLOW_NAME,
            max_iterations=50,
            start_executor=source_selector,
            checkpoint_storage=checkpoint_storage,
        )
        .add_edge(source_selector, source_configurator)
        .add_edge(source_configurator, discovery_runner)
        .add_edge(discovery_runner, protection_advisor)
        .add_edge(protection_advisor, resiliency_planner)
        .add_edge(resiliency_planner, approval_gateway)
        .add_edge(approval_gateway, protection_advisor)  # reject loop
    )

    return builder.build()
