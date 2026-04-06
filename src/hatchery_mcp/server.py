#!/usr/bin/env python3
"""Hatchery MCP Server — exposes Hatchery agent API endpoints as MCP tools.

Base URL: https://hatchery-tau.vercel.app/api/v1/agent/
API Key: Read from HATCHERY_API_KEY environment variable

Tools:
  get_context              — full situational awareness
  get_available_tasks      — list ready tasks
  claim_task               — claim a specific task
  update_task_status       — update task status with optional comment
  checkin                  — send checkin with status and optional progress
  get_messages             — fetch unread messages
  send_message             — send message to agent or channel
  get_projects             — list all projects
  get_project_spec         — get specification for a project
  get_workspace            — fetch shared workspace state for coordination
  update_workspace         — modify workspace state (decisions, assumptions, etc.)
  acknowledge_message      — acknowledge blocking messages to unlock checkins
  batch_operations         — batch multiple API calls

Each tool makes authenticated HTTP requests to Hatchery API.
Handles errors gracefully with descriptive messages.
"""

import json
import os
import ssl
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, List

from mcp.server.fastmcp import FastMCP

# ── Configuration ───────────────────────────────────────────────────────────

BASE_URL = "https://hatchery-tau.vercel.app/api/v1/agent"


def _load_api_key() -> str:
    """Load HATCHERY_API_KEY from environment variable."""
    key = os.environ.get("HATCHERY_API_KEY", "")
    if not key:
        print(
            "Warning: HATCHERY_API_KEY environment variable not set.",
            file=sys.stderr,
        )
    return key


mcp = FastMCP("hatchery")

# ── HTTP Helpers ────────────────────────────────────────────────────────────


def _make_request(
    method: str,
    endpoint: str,
    data: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Make authenticated HTTP request to Hatchery API.

    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint (e.g., "context", "tasks/available")
        data: Optional request body (will be JSON-encoded)
        session_id: Optional X-Session-Id header value

    Returns:
        Parsed JSON response as dict

    Raises:
        RuntimeError: On network or API errors
    """
    api_key = _load_api_key()
    if not api_key:
        raise RuntimeError(
            "HATCHERY_API_KEY environment variable not set. "
            "Set it with: export HATCHERY_API_KEY=your-key"
        )

    url = f"{BASE_URL}/{endpoint}"

    # Prepare headers
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if session_id:
        headers["X-Session-Id"] = session_id

    # Prepare request
    req_data = None
    if data:
        req_data = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=req_data,
        headers=headers,
        method=method,
    )

    # Create SSL context
    ssl_context = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get("message", error_body)
        except json.JSONDecodeError:
            error_msg = error_body
        raise RuntimeError(f"HTTP {e.code}: {error_msg}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")
    except Exception as e:
        raise RuntimeError(f"Request failed: {str(e)}")


# ── Tools ───────────────────────────────────────────────────────────────────


@mcp.tool()
def get_context(session_id: Optional[str] = None) -> str:
    """Get full situational awareness — current context, status, and environment.

    Returns structured context including agent identity, available tasks,
    current status, and system state.
    """
    try:
        result = _make_request("GET", "context", session_id=session_id)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "status": "failed"})


@mcp.tool()
def get_available_tasks(session_id: Optional[str] = None) -> str:
    """Get list of available tasks ready to be claimed.

    Returns array of tasks with their IDs, titles, descriptions, and status.
    """
    try:
        result = _make_request("GET", "tasks/available", session_id=session_id)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "status": "failed"})


@mcp.tool()
def claim_task(task_id: str, session_id: Optional[str] = None) -> str:
    """Claim a specific task by ID.

    Args:
        task_id: ID of the task to claim
        session_id: Optional session identifier

    Returns confirmation of task claim with task details.
    """
    try:
        result = _make_request(
            "POST",
            f"tasks/{task_id}/claim",
            session_id=session_id,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "task_id": task_id, "status": "failed"})


@mcp.tool()
def update_task_status(
    task_id: str,
    status: str,
    comment: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Update task status and optionally add a comment.

    Args:
        task_id: ID of the task to update
        status: New status (e.g., "in_progress", "completed", "blocked")
        comment: Optional comment to attach to status update
        session_id: Optional session identifier

    Returns confirmation of status update.
    """
    try:
        data = {"status": status}
        if comment:
            data["comment"] = comment

        result = _make_request(
            "POST",
            f"tasks/{task_id}/status",
            data=data,
            session_id=session_id,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps(
            {
                "error": str(e),
                "task_id": task_id,
                "status": "failed",
            }
        )


@mcp.tool()
def checkin(
    status: str,
    task_id: Optional[str] = None,
    progress_pct: Optional[int] = None,
    session_id: Optional[str] = None,
) -> str:
    """Send a checkin with current status and optional progress.

    Args:
        status: Current status description
        task_id: Optional task ID this checkin relates to
        progress_pct: Optional progress percentage (0-100)
        session_id: Optional session identifier

    Returns confirmation of checkin receipt.
    """
    try:
        data = {"status": status}
        if task_id:
            data["task_id"] = task_id
        if progress_pct is not None:
            data["progress_pct"] = max(0, min(100, progress_pct))

        result = _make_request(
            "POST",
            "checkin",
            data=data,
            session_id=session_id,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "status": "failed"})


@mcp.tool()
def get_messages(session_id: Optional[str] = None) -> str:
    """Fetch unread messages from other agents and broadcasts.

    Returns array of unread messages with sender, type, content, and timestamp.
    """
    try:
        result = _make_request("GET", "messages", session_id=session_id)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "status": "failed"})


@mcp.tool()
def send_message(
    to_type: str,
    message_type: str,
    content: str,
    to_agent_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> str:
    """Send a message to another agent or broadcast to a channel.

    Args:
        to_type: Recipient type ("agent", "channel", "broadcast")
        message_type: Type of message (e.g., "text", "task_update", "status")
        content: Message content/body
        to_agent_id: Recipient agent ID (for to_type="agent")
        metadata: Optional metadata dict to include with message
        session_id: Optional session identifier

    Returns confirmation with message ID and delivery status.
    """
    try:
        data = {
            "to_type": to_type,
            "message_type": message_type,
            "content": content,
        }
        if to_agent_id:
            data["to_agent_id"] = to_agent_id
        if metadata:
            data["metadata"] = metadata

        result = _make_request(
            "POST",
            "messages/send",
            data=data,
            session_id=session_id,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps(
            {
                "error": str(e),
                "to_type": to_type,
                "status": "failed",
            }
        )


@mcp.tool()
def get_projects(session_id: Optional[str] = None) -> str:
    """Get list of all projects.

    Returns array of project summaries with IDs, names, status, and metadata.
    """
    try:
        result = _make_request("GET", "projects", session_id=session_id)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "status": "failed"})


@mcp.tool()
def get_project_spec(
    project_id: str,
    session_id: Optional[str] = None,
) -> str:
    """Get detailed specification for a specific project.

    Args:
        project_id: ID of the project
        session_id: Optional session identifier

    Returns full project specification including goals, tasks, requirements,
    timeline, and current progress.
    """
    try:
        result = _make_request(
            "GET",
            f"projects/{project_id}",
            session_id=session_id,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps(
            {
                "error": str(e),
                "project_id": project_id,
                "status": "failed",
            }
        )


@mcp.tool()
def get_workspace(
    project_id: str,
    session_id: Optional[str] = None,
) -> str:
    """Get the shared workspace state (blackboard) for a project.

    Args:
        project_id: ID of the project to get workspace state for
        session_id: Optional session identifier

    Returns structured JSON with:
    current_approach, decisions[], assumptions[], completed_artifacts[], 
    blocking_questions[], conventions{}, active_files{}
    """
    try:
        result = _make_request(
            "GET",
            f"projects/{project_id}/workspace",
            session_id=session_id,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps(
            {
                "error": str(e),
                "project_id": project_id,
                "status": "failed",
            }
        )


@mcp.tool()
def update_workspace(
    project_id: str,
    updates: Dict[str, Any],
    session_id: Optional[str] = None,
) -> str:
    """Update workspace state. Body is a JSON object merged (shallow) into existing state.

    Args:
        project_id: ID of the project to update workspace state for
        updates: Dict of updates to merge into workspace state
        session_id: Optional session identifier

    Always update when you make architectural decisions, complete artifacts, 
    or change assumptions. The system auto-sets last_updated_by and last_updated_at.
    """
    try:
        result = _make_request(
            "PATCH",
            f"projects/{project_id}/workspace",
            data=updates,
            session_id=session_id,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps(
            {
                "error": str(e),
                "project_id": project_id,
                "status": "failed",
            }
        )


@mcp.tool()
def acknowledge_message(
    message_id: str,
    response: str,
    session_id: Optional[str] = None,
) -> str:
    """Acknowledge a message that requires acknowledgment.

    Args:
        message_id: ID of the message to acknowledge
        response: How the message changes your approach (not just "ok")
        session_id: Optional session identifier

    You MUST acknowledge all blocking messages before you can check in or claim tasks.
    The response should explain HOW the message changes your approach.
    """
    try:
        data = {"response": response}
        result = _make_request(
            "POST",
            f"messages/{message_id}/acknowledge",
            data=data,
            session_id=session_id,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps(
            {
                "error": str(e),
                "message_id": message_id,
                "status": "failed",
            }
        )


@mcp.tool()
def batch_operations(
    operations: List[Dict[str, Any]],
    session_id: Optional[str] = None,
) -> str:
    """Execute multiple API calls in a batch operation.

    Args:
        operations: Array of operation dicts, each with:
            - "method": HTTP method ("GET", "POST", etc.)
            - "endpoint": API endpoint path
            - "data": Optional request body (for POST/PATCH/etc.)
        session_id: Optional session identifier

    Returns array of results corresponding to each operation,
    with success/error status for each.

    Example:
        [
            {"method": "GET", "endpoint": "context"},
            {"method": "POST", "endpoint": "tasks/123/status", "data": {"status": "in_progress"}}
        ]
    """
    if not operations:
        return json.dumps({"error": "operations list is empty", "status": "failed"})

    results = []

    for i, op in enumerate(operations):
        try:
            if not isinstance(op, dict):
                results.append(
                    {
                        "index": i,
                        "error": "Operation must be a dict",
                        "status": "failed",
                    }
                )
                continue

            method = op.get("method", "GET").upper()
            endpoint = op.get("endpoint")
            data = op.get("data")

            if not endpoint:
                results.append(
                    {
                        "index": i,
                        "error": "endpoint is required",
                        "status": "failed",
                    }
                )
                continue

            result = _make_request(
                method,
                endpoint,
                data=data,
                session_id=session_id,
            )
            results.append(
                {
                    "index": i,
                    "method": method,
                    "endpoint": endpoint,
                    "result": result,
                    "status": "success",
                }
            )

        except Exception as e:
            results.append(
                {
                    "index": i,
                    "method": op.get("method", "GET"),
                    "endpoint": op.get("endpoint"),
                    "error": str(e),
                    "status": "failed",
                }
            )

    return json.dumps(
        {"operations": results, "total": len(operations)}, indent=2
    )


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    """Entry point for the Hatchery MCP server."""
    api_key = os.environ.get("HATCHERY_API_KEY", "")
    if not api_key:
        print(
            "Warning: HATCHERY_API_KEY not set. Set it with: "
            "export HATCHERY_API_KEY=your-key",
            file=sys.stderr,
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
