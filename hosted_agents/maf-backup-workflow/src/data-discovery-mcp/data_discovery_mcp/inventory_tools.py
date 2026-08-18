"""
Inventory Tools

MCP tools for querying the application inventory — apps, objects,
resiliency coverage, and resiliency plans.
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

INVENTORY_DATA: dict[str, Any] = _ALL_MOCK["screen_6_inventory_and_copilot"]["inventory"]
RESILIENCY_PLAN: dict[str, Any] = _ALL_MOCK["screen_6_inventory_and_copilot"]["resiliency_plan"]
PROTECTION_POLICY: dict[str, Any] = _ALL_MOCK["screen_7_protection_policy_detail"]
CYBER_RECOVERABILITY: dict[str, Any] = _ALL_MOCK["screen_8_cyber_recoverability"]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


async def get_inventory_summary() -> dict:
    """
    Get a high-level summary of the application inventory including
    organization, source ID, resiliency coverage scores, and application group list.
    """
    return {
        "organization": INVENTORY_DATA["organization"],
        "source_id": INVENTORY_DATA["source_id"],
        "resiliency_coverage": INVENTORY_DATA["resiliency_coverage"],
        "application_groups": INVENTORY_DATA["application_groups"],
        "total_objects": len(INVENTORY_DATA["objects"]),
    }


async def list_application_groups() -> dict:
    """
    List all discovered application groups with their object counts,
    protection status breakdown, and data sensitivity summary.
    """
    apps: dict[str, dict] = {}
    for obj in INVENTORY_DATA["objects"]:
        app = obj["application_group"]
        if app not in apps:
            apps[app] = {
                "application_group": app,
                "object_count": 0,
                "protection_breakdown": {},
                "data_classes": set(),
                "data_sensitivities": set(),
            }
        apps[app]["object_count"] += 1

        status = obj.get("protection_status", "Unknown")
        apps[app]["protection_breakdown"][status] = (
            apps[app]["protection_breakdown"].get(status, 0) + 1
        )
        apps[app]["data_classes"].add(obj.get("data_classes", ""))
        apps[app]["data_sensitivities"].add(obj.get("data_sensitivity", ""))

    result = []
    for info in apps.values():
        result.append({
            "application_group": info["application_group"],
            "object_count": info["object_count"],
            "protection_breakdown": info["protection_breakdown"],
            "data_classes": sorted(info["data_classes"]),
            "data_sensitivities": sorted(info["data_sensitivities"]),
        })

    return {
        "total_applications": len(result),
        "applications": result,
    }


async def get_application_objects(
    application_group: Annotated[str, "Application group name (e.g. checkout-app, billing-invoice-app)"],
) -> dict:
    """
    Get all objects belonging to a specific application group.
    Returns object name, SLA, protection status, data classes, data sensitivity,
    source platform, region, last backup time, and backup size.
    """
    objects = [
        obj for obj in INVENTORY_DATA["objects"]
        if obj["application_group"] == application_group
    ]

    if not objects:
        available = INVENTORY_DATA["application_groups"]
        return {
            "error": f"Application group '{application_group}' not found.",
            "available_groups": available,
        }

    return {
        "application_group": application_group,
        "object_count": len(objects),
        "objects": objects,
    }


async def get_resiliency_coverage() -> dict:
    """
    Get resiliency coverage scores across five dimensions:
    Protection, Cyber Orchestration, Recoverability, Data Classification,
    and Threat Monitoring. Scores are percentages (0-100).
    """
    return {
        "organization": INVENTORY_DATA["organization"],
        "source_id": INVENTORY_DATA["source_id"],
        "coverage": INVENTORY_DATA["resiliency_coverage"],
    }


async def get_resiliency_plan(
    application_group: Annotated[str | None, "Application group to get the plan for. Leave empty for the default plan."] = None,
) -> dict:
    """
    Get the AI-generated application resiliency plan including key highlights
    (Protection Policy, Threat Monitoring, Cyber Recoverability) and
    suggested actions with backup frequency, retention, replication, and blueprints.
    """
    plan = dict(RESILIENCY_PLAN)
    if application_group:
        plan["application"] = application_group

    return plan


async def get_protection_policy_detail() -> dict:
    """
    Get the 3-2-1 protection policy detail including the rule name,
    condition (application + data sensitivity), policy tier, and the
    multi-cluster replication chain (Primary, Secondary, Tertiary/Vault).
    """
    return PROTECTION_POLICY


async def get_cyber_recoverability_blueprints() -> dict:
    """
    Get cyber recoverability blueprints including core blueprints
    (Scheduled-Rehearsal-Blueprint, Cleanroom-Blueprint-Threat-Scan) and
    additional blueprints with their workflow steps, frequency, and run status.
    """
    return CYBER_RECOVERABILITY


async def get_unprotected_objects(
    application_group: Annotated[str | None, "Filter by application group. Leave empty for all."] = None,
) -> dict:
    """
    List all objects with 'Unprotected' protection status.
    Useful for identifying objects that need backup policies assigned.
    """
    objects = [
        obj for obj in INVENTORY_DATA["objects"]
        if obj["protection_status"] == "Unprotected"
        and (application_group is None or obj["application_group"] == application_group)
    ]

    return {
        "unprotected_count": len(objects),
        "total_objects": len(INVENTORY_DATA["objects"]),
        "objects": objects,
    }
