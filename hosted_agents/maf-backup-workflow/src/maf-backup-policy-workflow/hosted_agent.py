"""Foundry hosted-agent adapter for the backup policy workflow."""

import asyncio
import json
import logging
from typing import Any

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backup_api.app import WorkflowSession, _run_workflow_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backup_policy_hosted_agent")

OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "Backup Policy Workflow Agent",
        "version": "1.0.0",
    },
    "paths": {
        "/invocations": {
            "post": {
                "summary": "Start or advance the backup policy workflow",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "action": {
                                        "type": "string",
                                        "enum": ["start", "respond", "status"],
                                    },
                                    "request_id": {"type": "string"},
                                    "response": {},
                                },
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "Current workflow interaction"}},
            }
        }
    },
}

app = InvocationAgentServerHost(openapi_spec=OPENAPI_SPEC)

_sessions: dict[str, WorkflowSession] = {}
_invocation_to_session: dict[str, str] = {}


def _snapshot(
    session_id: str,
    invocation_id: str,
    session: WorkflowSession,
) -> dict[str, Any]:
    status = "completed" if session.completed else "running"
    if session.pending_requests:
        status = "awaiting_input"
    if session.task and session.task.done() and not session.completed:
        status = "failed"
    return {
        "session_id": session_id,
        "invocation_id": invocation_id,
        "status": status,
        "pending_request_ids": list(session.pending_requests),
        "output": session.output,
    }


async def _next_interaction(
    session_id: str,
    invocation_id: str,
    session: WorkflowSession,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    while True:
        event = await session.event_queue.get()
        events.append(event)
        event_type = event.get("type")
        if event_type in {"screen", "completed", "error"}:
            snapshot = _snapshot(session_id, invocation_id, session)
            snapshot["events"] = events
            if event_type == "screen":
                snapshot["status"] = "awaiting_input"
            elif event_type == "error":
                snapshot["status"] = "failed"
            return snapshot


def _json_response(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value)


@app.invoke_handler
async def handle_invoke(request: Request) -> Response:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("body is not a JSON object")
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(
            {
                "error": "invalid_request",
                "message": "Request body must be a JSON object.",
            },
            status_code=400,
        )

    session_id: str = request.state.session_id
    invocation_id: str = request.state.invocation_id
    action = payload.get("action", "start")
    _invocation_to_session[invocation_id] = session_id

    if action == "start":
        existing = _sessions.get(session_id)
        if existing and not existing.completed:
            return JSONResponse(_snapshot(session_id, invocation_id, existing))

        session = WorkflowSession()
        session.id = session_id
        _sessions[session_id] = session
        session.task = asyncio.create_task(_run_workflow_loop(session))
        logger.info("Started workflow session %s", session_id)
        return JSONResponse(
            await _next_interaction(session_id, invocation_id, session)
        )

    session = _sessions.get(session_id)
    if not session:
        return JSONResponse(
            {"error": "session_not_found", "session_id": session_id},
            status_code=404,
        )

    if action == "status":
        return JSONResponse(_snapshot(session_id, invocation_id, session))

    if action != "respond":
        return JSONResponse(
            {"error": "invalid_action", "message": "Use start, respond, or status."},
            status_code=400,
        )

    request_id = payload.get("request_id")
    if not request_id and len(session.pending_requests) == 1:
        request_id = next(iter(session.pending_requests))
    if request_id not in session.pending_requests:
        return JSONResponse(
            {
                "error": "unknown_request_id",
                "pending_request_ids": list(session.pending_requests),
            },
            status_code=400,
        )
    if "response" not in payload:
        return JSONResponse(
            {"error": "missing_response"},
            status_code=400,
        )

    session.responses[request_id] = _json_response(payload["response"])
    session.response_ready.set()
    logger.info("Advanced workflow session %s", session_id)
    return JSONResponse(await _next_interaction(session_id, invocation_id, session))


@app.get_invocation_handler
async def handle_get_invocation(request: Request) -> Response:
    invocation_id: str = request.state.invocation_id
    session_id = _invocation_to_session.get(invocation_id)
    session = _sessions.get(session_id) if session_id else None
    if not session or not session_id:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return JSONResponse(_snapshot(session_id, invocation_id, session))


@app.cancel_invocation_handler
async def handle_cancel_invocation(request: Request) -> Response:
    invocation_id: str = request.state.invocation_id
    session_id = _invocation_to_session.get(invocation_id)
    session = _sessions.get(session_id) if session_id else None
    if not session or not session_id:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if session.task and not session.task.done():
        session.task.cancel()
    _sessions.pop(session_id, None)
    return JSONResponse(
        {"session_id": session_id, "invocation_id": invocation_id, "status": "cancelled"}
    )


if __name__ == "__main__":
    app.run()