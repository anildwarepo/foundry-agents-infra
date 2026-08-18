"""
FastAPI backend with SSE streaming for the Backup Policy Workflow.

Endpoints:
  POST /api/sessions              — Start a new workflow session
  GET  /api/sessions/{id}/events  — SSE stream of workflow events
  POST /api/sessions/{id}/respond — Send a human response to a pending HITL request
"""

import asyncio
import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_framework import FileCheckpointStorage, WorkflowViz

from .workflow import WORKFLOW_NAME, ScreenRequest, create_backup_workflow, set_tool_call_emitter

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Backup Policy Workflow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CHECKPOINT_DIR = Path(__file__).parent.parent / "backup_checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class WorkflowSession:
    """Tracks a single workflow run with its event queue and HITL state."""

    # ScreenRequest must be in the allowlist so checkpoint deserialization works
    _ALLOWED_TYPES = ["backup_api.workflow:ScreenRequest"]

    def __init__(self) -> None:
        self.id: str = str(uuid.uuid4())
        self.storage = FileCheckpointStorage(
            storage_path=CHECKPOINT_DIR,
            allowed_checkpoint_types=self._ALLOWED_TYPES,
        )
        self.workflow = create_backup_workflow(checkpoint_storage=self.storage)
        self.event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.pending_requests: dict[str, Any] = {}
        self.responses: dict[str, str] = {}
        self.response_ready = asyncio.Event()
        self.completed: bool = False
        self.output: Any = None
        self.task: asyncio.Task | None = None


sessions: dict[str, WorkflowSession] = {}


@app.on_event("startup")
async def _clear_stale_sessions() -> None:
    """Clear in-memory sessions on startup / hot-reload so stale sessions
    from a previous run don't cause the UI to hang on resume."""
    sessions.clear()
    _clear_active_session()


# ---------------------------------------------------------------------------
# Workflow runner (background task)
# ---------------------------------------------------------------------------

async def _run_workflow_loop(session: WorkflowSession, *, checkpoint_id: str | None = None) -> None:
    """Drive the workflow, pushing events to the session queue."""
    print(f"[LOOP] Starting workflow loop for session {session.id[:8]}")

    # Wire up tool call emitter so workflow MCP calls emit events to the frontend
    async def _emit_tool_call(info: dict) -> None:
        await session.event_queue.put({"type": "tool_call", **info})

    set_tool_call_emitter(_emit_tool_call)

    initial_message = "Configure backup protection policy"
    responses: dict[str, str] | None = None

    while True:
        try:
            session.response_ready.clear()
            if responses:
                event_stream = session.workflow.run(stream=True, responses=responses)
                responses = None
            elif checkpoint_id:
                event_stream = session.workflow.run(
                    checkpoint_id=checkpoint_id, stream=True
                )
                checkpoint_id = None  # only used on first iteration
            else:
                event_stream = session.workflow.run(
                    message=initial_message, stream=True
                )
                initial_message = None  # only used on first iteration

            requests: dict[str, ScreenRequest] = {}

            async for event in event_stream:
                if event.type == "status":
                    status_str = str(event)
                    # Parse executor info from status string
                    event_data: dict[str, Any] = {"type": "status", "data": status_str}
                    # Extract executor name if present (e.g. "executor=source_selector")
                    import re
                    exec_match = re.search(r'executor[=:](\w+)', status_str)
                    if exec_match:
                        event_data["executor"] = exec_match.group(1)
                    # Check for state transitions
                    state_match = re.search(r'state=(\w+)', status_str)
                    if state_match:
                        event_data["state"] = state_match.group(1)
                    await session.event_queue.put(event_data)

                elif event.type == "request_info":
                    if isinstance(event.data, ScreenRequest):
                        req_dict = asdict(event.data)
                        requests[event.request_id] = event.data
                        session.pending_requests[event.request_id] = event.data
                        print(f"[LOOP] Putting screen event in queue: screen={req_dict['screen']}, qsize={session.event_queue.qsize()}")
                        await session.event_queue.put({
                            "type": "screen",
                            "request_id": event.request_id,
                            "screen": req_dict["screen"],
                            "data": req_dict["data"],
                            "message": req_dict["message"],
                            "step": req_dict["step"],
                            "total_steps": req_dict["total_steps"],
                        })
                        print(f"[LOOP] Queue size after put: {session.event_queue.qsize()}")

                elif event.type == "output":
                    session.completed = True
                    session.output = event.data
                    _clear_active_session()
                    await session.event_queue.put({
                        "type": "completed",
                        "data": event.data if isinstance(event.data, str) else str(event.data),
                    })

            if session.completed:
                break

            if requests:
                session.pending_requests = requests
                print(f"[LOOP] Waiting for response. pending_requests={list(requests.keys())}")
                # Wait for the frontend to send a response
                await session.response_ready.wait()
                responses = dict(session.responses)
                session.responses.clear()
                session.pending_requests.clear()
                continue

            # No requests and not completed — shouldn't happen
            await session.event_queue.put({
                "type": "error",
                "data": "Workflow stopped without output or pending requests.",
            })
            break

        except Exception as exc:
            await session.event_queue.put({
                "type": "error",
                "data": str(exc),
            })
            break


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ResponsePayload(BaseModel):
    request_id: str
    response: str


class SessionResponse(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Active session tracking (persisted to disk for resume on refresh)
# ---------------------------------------------------------------------------

ACTIVE_SESSION_FILE = CHECKPOINT_DIR / "_active_session.json"


def _save_active_session(session_id: str) -> None:
    """Save the active session ID so it can be resumed after page refresh."""
    ACTIVE_SESSION_FILE.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")


def _load_active_session() -> str | None:
    """Load the saved active session ID."""
    if ACTIVE_SESSION_FILE.exists():
        try:
            data = json.loads(ACTIVE_SESSION_FILE.read_text(encoding="utf-8"))
            return data.get("session_id")
        except Exception:
            pass
    return None


def _clear_active_session() -> None:
    """Clear the saved active session."""
    if ACTIVE_SESSION_FILE.exists():
        ACTIVE_SESSION_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/workflow/visualization")
async def get_workflow_visualization() -> dict[str, str]:
    """Return a Mermaid diagram of the workflow DAG."""
    import io, sys
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()  # suppress create_backup_workflow print noise
    try:
        workflow = create_backup_workflow()
    finally:
        sys.stdout = old_stdout
    viz = WorkflowViz(workflow)
    return {"mermaid": viz.to_mermaid()}


@app.post("/api/sessions", response_model=SessionResponse)
async def create_session() -> SessionResponse:
    """Start a new workflow session."""
    session = WorkflowSession()
    sessions[session.id] = session
    print(f"[API] Created session {session.id[:8]}, total sessions={len(sessions)}")
    session.task = asyncio.create_task(_run_workflow_loop(session))
    _save_active_session(session.id)
    return SessionResponse(session_id=session.id)


@app.get("/api/sessions/active")
async def get_active_session() -> dict[str, Any]:
    """Check if there's an active in-progress session that can be resumed."""
    # Check in-memory sessions first (browser tab closed, server still running).
    # Only report a session as active if it has pending HITL requests — a running
    # task with no pending requests is either still initialising or is a stale
    # leftover from a previous run that never got cleaned up.
    for sid, session in sessions.items():
        if (not session.completed
                and session.task
                and not session.task.done()
                and session.pending_requests):
            return {"has_active": True, "session_id": sid, "source": "memory"}

    # Check for persisted checkpoint on disk only if an active session was recorded.
    # Without this guard, stale checkpoints from previous (completed) runs would
    # cause the Resume button to appear permanently.
    saved_sid = _load_active_session()
    if saved_sid:
        storage = FileCheckpointStorage(
            storage_path=CHECKPOINT_DIR,
            allowed_checkpoint_types=WorkflowSession._ALLOWED_TYPES,
        )
        latest = await storage.get_latest(workflow_name=WORKFLOW_NAME)
        if latest and latest.pending_request_info_events:
            return {"has_active": True, "session_id": None, "source": "checkpoint",
                    "checkpoint_id": latest.checkpoint_id}

    return {"has_active": False, "session_id": None}


@app.post("/api/sessions/resume", response_model=SessionResponse)
async def resume_from_checkpoint() -> SessionResponse:
    """Resume a workflow from the latest persisted checkpoint on disk.

    Creates a fresh workflow instance and restores state from the checkpoint,
    enabling resume even after a full server restart.
    """
    storage = FileCheckpointStorage(
        storage_path=CHECKPOINT_DIR,
        allowed_checkpoint_types=WorkflowSession._ALLOWED_TYPES,
    )
    latest = await storage.get_latest(workflow_name=WORKFLOW_NAME)
    if not latest:
        raise HTTPException(status_code=404, detail="No checkpoint found to resume from")
    if not latest.pending_request_info_events:
        raise HTTPException(status_code=400, detail="Checkpoint has no pending requests to resume")

    session = WorkflowSession()
    sessions[session.id] = session
    session.task = asyncio.create_task(
        _run_workflow_loop(session, checkpoint_id=latest.checkpoint_id)
    )
    _save_active_session(session.id)
    return SessionResponse(session_id=session.id)


@app.post("/api/sessions/{session_id}/resume", response_model=SessionResponse)
async def resume_session(session_id: str) -> SessionResponse:
    """Resume an in-memory workflow session.

    The SSE generator re-emits pending screen requests on connect,
    so we don't need to put them in the queue here (which caused
    duplicate events and race conditions).
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.completed:
        raise HTTPException(status_code=400, detail="Session already completed")

    _save_active_session(session_id)
    return SessionResponse(session_id=session_id)


@app.post("/api/sessions/{session_id}/respond")
async def respond(session_id: str, payload: ResponsePayload) -> dict[str, str]:
    """Send a human response to a pending HITL request."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if payload.request_id not in session.pending_requests:
        raise HTTPException(status_code=400, detail="Unknown request_id")

    session.responses[payload.request_id] = payload.response
    session.response_ready.set()
    return {"status": "ok"}


@app.get("/api/sessions/{session_id}/events")
async def events_stream(session_id: str) -> StreamingResponse:
    """SSE stream that delivers workflow events to the frontend."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    print(f"[SSE] Connection opened for session {session_id[:8]}, pending_requests={bool(session.pending_requests)}, qsize={session.event_queue.qsize()}")

    async def generate():
        # Re-emit any pending screen requests so the client always gets
        # them when it (re-)connects, avoiding the race where the event
        # was queued before the SSE connection was established.
        if session.pending_requests:
            for req_id, req_data in session.pending_requests.items():
                req_dict = asdict(req_data)
                event = {
                    "type": "screen",
                    "request_id": req_id,
                    "screen": req_dict["screen"],
                    "data": req_dict["data"],
                    "message": req_dict["message"],
                    "step": req_dict["step"],
                    "total_steps": req_dict["total_steps"],
                }
                yield f"data: {json.dumps(event, default=str)}\n\n"

        while True:
            try:
                event = await asyncio.wait_for(
                    session.event_queue.get(), timeout=30.0
                )
                print(f"[SSE] Yielding event: type={event.get('type')}, screen={event.get('screen', 'n/a')}")
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("type") in ("completed", "error"):
                    break
            except asyncio.TimeoutError:
                # Keep-alive heartbeat
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

