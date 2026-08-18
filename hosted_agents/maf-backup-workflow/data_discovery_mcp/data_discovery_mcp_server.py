"""
Data Discovery MCP Server

A Model Context Protocol (MCP) server that provides tools for discovering,
classifying, and analyzing data across cloud sources. Follows the same
FastMCP + streamable-http pattern as the AzureAgent MCP server.

Usage:
    python data_discovery_mcp_server.py
    python data_discovery_mcp_server.py --port 3002
"""

import sys
import asyncio
import argparse
import logging
import warnings

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastmcp import FastMCP

from discovery_tools import (
    run_discovery_scan,
    get_discovery_summary,
    get_sensitive_data_classification,
    get_data_context,
    get_file_extension_breakdown,
    get_data_exposure,
    get_data_access,
    list_discovered_applications,
    get_next_steps,
)

from inventory_tools import (
    get_inventory_summary,
    list_application_groups,
    get_application_objects,
    get_resiliency_coverage,
    get_resiliency_plan,
    get_protection_policy_detail,
    get_cyber_recoverability_blueprints,
    get_unprotected_objects,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Create MCP server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "Data Discovery MCP Server",
    instructions="""You are a Data Discovery and Inventory assistant. Use these tools to help users
discover, classify, and analyze data across their cloud sources, and to query
the application inventory.

Available capabilities:
- Run full data discovery scans across cloud platforms
- Classify sensitive data by category (Personal, Financial, Health, etc.)
- Analyze data context (PII, Employee data, Audit logs, etc.)
- Break down discovered data by file extension
- Assess data exposure levels (Confidential, Internal, Public)
- Report on data access patterns (agents and users)
- List discovered applications
- Provide recommended next steps based on discovery results
- Query the application inventory (apps, objects, protection status)
- Get resiliency coverage scores and resiliency plans
- Get protection policy details and cyber recoverability blueprints
- Identify unprotected objects that need backup policies

Start with get_inventory_summary or run_discovery_scan for an overview,
then use specific tools for detailed analysis.""",
)

# ---------------------------------------------------------------------------
# Register tools
# ---------------------------------------------------------------------------
mcp.tool(run_discovery_scan)
mcp.tool(get_discovery_summary)
mcp.tool(get_sensitive_data_classification)
mcp.tool(get_data_context)
mcp.tool(get_file_extension_breakdown)
mcp.tool(get_data_exposure)
mcp.tool(get_data_access)
mcp.tool(list_discovered_applications)
mcp.tool(get_next_steps)

# ---------------------------------------------------------------------------
# Inventory tools
# ---------------------------------------------------------------------------
mcp.tool(get_inventory_summary)
mcp.tool(list_application_groups)
mcp.tool(get_application_objects)
mcp.tool(get_resiliency_coverage)
mcp.tool(get_resiliency_plan)
mcp.tool(get_protection_policy_detail)
mcp.tool(get_cyber_recoverability_blueprints)
mcp.tool(get_unprotected_objects)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Data Discovery MCP Server")
    parser.add_argument("--port", type=int, default=3002, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument(
        "--transport",
        default="streamable-http",
        choices=["streamable-http", "sse", "stdio"],
        help="MCP transport type",
    )
    args = parser.parse_args()

    logger.info(
        "Starting Data Discovery MCP Server on %s:%d (transport=%s)",
        args.host,
        args.port,
        args.transport,
    )

    raw_app = mcp.http_app(path="/")

    # Add CORS support
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route
    from starlette.middleware.cors import CORSMiddleware as StarletteCORS

    async def health(_request):
        return JSONResponse({"status": "ok", "service": "data-discovery-mcp"})

    app = Starlette(
        routes=[Route("/health", health), Mount("/mcp", app=raw_app)],
        lifespan=raw_app.lifespan,
    )
    app.add_middleware(
        StarletteCORS,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
