"""
Data Discovery Tools

MCP tools for data discovery, classification, and analysis.
Returns mock data matching the Data Discovered dashboard UI.
"""

import json
import logging
from pathlib import Path
from typing import Annotated, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load mock data
# ---------------------------------------------------------------------------
MOCK_DATA_PATH = Path(__file__).parent.parent / "backup_mock_data.json"
with open(MOCK_DATA_PATH, encoding="utf-8") as _f:
    _ALL_MOCK: dict[str, Any] = json.load(_f)

DISCOVERY_DATA: dict[str, Any] = _ALL_MOCK["screen_3_data_discovered"]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


async def run_discovery_scan(
    source_platform: Annotated[str, "Cloud platform to scan (e.g. AWS, Azure, GCP)"] = "Azure",
    organization_id: Annotated[str | None, "Organization or account ID to scope the scan"] = None,
) -> dict:
    """
    Run a full data discovery scan on the specified cloud source.
    Scans objects, discovers applications, classifies sensitive data,
    and assesses exposure levels. Returns a complete discovery summary.
    """
    logger.info("Running discovery scan for %s (org=%s)", source_platform, organization_id)

    return {
        "status": "completed",
        "source_platform": source_platform,
        "organization_id": organization_id or "auto-detected",
        "total_objects": DISCOVERY_DATA["total_objects"],
        "applications_discovered": DISCOVERY_DATA["applications_discovered"],
        "classified_sensitive_data": DISCOVERY_DATA["classified_sensitive_data"],
        "next_steps": DISCOVERY_DATA["next_steps"],
    }


async def get_discovery_summary() -> dict:
    """
    Get a high-level summary of the most recent data discovery scan.
    Returns total objects, applications discovered, and top-level stats.
    """
    classified = DISCOVERY_DATA["classified_sensitive_data"]
    total_sensitive = sum(classified["data_categories"].values())
    total_exposure = sum(classified["exposure"].values())

    return {
        "total_objects": DISCOVERY_DATA["total_objects"],
        "applications_discovered": DISCOVERY_DATA["applications_discovered"],
        "total_sensitive_objects": total_sensitive,
        "total_exposure_objects": total_exposure,
        "data_categories_count": len(classified["data_categories"]),
        "file_types_count": len(classified["file_extensions"]),
        "access_agents": classified["access"]["agents"],
        "access_users": classified["access"]["users"],
    }


async def get_sensitive_data_classification(
    category: Annotated[str | None, "Filter by category (Personal, Financial, Business & IP, IT & Security, Health). Leave empty for all."] = None,
) -> dict:
    """
    Get classified sensitive data broken down by category.
    Categories include Personal, Financial, Business & IP, IT & Security, and Health.
    """
    categories = DISCOVERY_DATA["classified_sensitive_data"]["data_categories"]

    if category and category in categories:
        return {
            "category": category,
            "count": categories[category],
            "percentage": round(categories[category] / sum(categories.values()) * 100, 1),
        }

    total = sum(categories.values())
    return {
        "total_classified": total,
        "categories": {
            k: {"count": v, "percentage": round(v / total * 100, 1)}
            for k, v in categories.items()
        },
    }


async def get_data_context() -> dict:
    """
    Get data context information including data types (PII, Employee data, Audit logs),
    region, and identifiability status.
    """
    ctx = DISCOVERY_DATA["classified_sensitive_data"]["data_context"]
    return {
        "data_types": ctx["types"],
        "region": ctx["region"],
        "identifiability": ctx["identifiability"],
    }


async def get_file_extension_breakdown(
    extension: Annotated[str | None, "Filter by specific extension (e.g. parquet, PDF, CSV). Leave empty for all."] = None,
) -> dict:
    """
    Get a breakdown of discovered data by file extension.
    Shows counts for parquet, PDF, txt, CSV, docx, json, and other file types.
    """
    extensions = DISCOVERY_DATA["classified_sensitive_data"]["file_extensions"]

    if extension and extension in extensions:
        return {
            "extension": extension,
            "count": extensions[extension],
            "percentage": round(extensions[extension] / sum(extensions.values()) * 100, 1),
        }

    total = sum(extensions.values())
    return {
        "total_files": total,
        "extensions": {
            k: {"count": v, "percentage": round(v / total * 100, 1)}
            for k, v in sorted(extensions.items(), key=lambda x: x[1], reverse=True)
        },
    }


async def get_data_exposure(
    level: Annotated[str | None, "Filter by exposure level (Confidential, Internal, Public). Leave empty for all."] = None,
) -> dict:
    """
    Get data exposure assessment showing how data is classified by exposure level.
    Levels: Confidential, Internal, Public.
    """
    exposure = DISCOVERY_DATA["classified_sensitive_data"]["exposure"]

    if level and level in exposure:
        return {
            "level": level,
            "count": exposure[level],
            "percentage": round(exposure[level] / sum(exposure.values()) * 100, 1),
        }

    total = sum(exposure.values())
    return {
        "total_objects": total,
        "exposure_levels": {
            k: {"count": v, "percentage": round(v / total * 100, 1)}
            for k, v in exposure.items()
        },
    }


async def get_data_access() -> dict:
    """
    Get data access information showing how many agents and users
    have access to the discovered data.
    """
    access = DISCOVERY_DATA["classified_sensitive_data"]["access"]
    return {
        "agents": access["agents"],
        "users": access["users"],
        "total_principals": access["agents"] + access["users"],
    }


async def list_discovered_applications() -> dict:
    """
    List all applications discovered during the data scan.
    Returns the count and names of discovered applications.
    """
    return {
        "count": DISCOVERY_DATA["applications_discovered"],
        "applications": [
            f"app-{i+1}" for i in range(DISCOVERY_DATA["applications_discovered"])
        ],
    }


async def get_next_steps() -> dict:
    """
    Get recommended next steps based on the discovery scan results.
    Includes capabilities like SmartProtect, Threat Monitoring,
    and Application Resilience Orchestration.
    """
    return {
        "steps": DISCOVERY_DATA["next_steps"],
        "total_steps": len(DISCOVERY_DATA["next_steps"]),
    }
