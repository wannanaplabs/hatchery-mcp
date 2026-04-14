#!/usr/bin/env python3
"""Hatchery MCP Server — exposes Hatchery agent API endpoints as MCP tools.

Base URL: https://hatchery.run/api/v1/agent/
API Key: Read from HATCHERY_API_KEY in ~/.hermes/.env

Tool categories:
  Core loop:          get_context, checkin, get_available_tasks, claim_task,
                      update_task_status, release_task, request_human
  Messaging:          get_messages, send_message, acknowledge_message
  Projects:           get_projects, get_project_spec
  Conflicts:          get_conflicts, raise_conflict, resolve_conflict
  Proposals:          create_proposal, list_proposals, get_proposal,
                      vote_on_proposal, retract_vote, withdraw_proposal,
                      break_tie
  Decisions:          publish_decision, ack_decision, get_decisions
  Approvals:          submit_for_approval, get_awaiting_approval
  QA reviews:         submit_for_qa, review_qa
  Comments:           add_task_comment
  Events:             get_events
  Capabilities:       get_capabilities, set_capabilities
  Batch:              batch_operations

Each tool makes authenticated HTTP requests to Hatchery API.
Handles errors gracefully with descriptive messages.
"""

import json
import os
import ssl
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional, List

from mcp.server.fastmcp import FastMCP

# ── Configuration ───────────────────────────────────────────────────────────

BASE_URL = os.environ.get("HATCHERY_BASE_URL", "https://hatchery.run/api/v1/agent")
VERSION = "0.3.0"


def load_api_key() -> str:
    """Load HATCHERY_API_KEY from environment or ~/.hermes/.env"""
    key = os.environ.get("HATCHERY_API_KEY")
    if key:
        return key

    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        raise RuntimeError(
            f"HATCHERY_API_KEY not in env and {env_path} does not exist"
        )

    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("HATCHERY_API_KEY="):
                k = line.split("=", 1)[1].strip()
                if k:
                    return k

    raise RuntimeError("HATCHERY_API_KEY not found in environment or ~/.hermes/.env")


try:
    API_KEY = load_api_key()
except Exception as e:
    print(f"Error loading API key: {e}", file=sys.stderr)
    API_KEY = None

mcp = FastMCP("hatchery")

# ── HTTP Helpers ────────────────────────────────────────────────────────────


def _make_request(
    method: str,
    endpoint: str,
    data: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    query: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make authenticated HTTP request to Hatchery API."""
    if not API_KEY:
        raise RuntimeError("API key not initialized. Set HATCHERY_API_KEY.")

    url = f"{BASE_URL}/{endpoint}"
    if query:
        qs = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        if qs:
            url += ("&" if "?" in url else "?") + qs

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": f"hatchery-mcp/{VERSION}",
    }
    if session_id:
        headers["X-Session-Id"] = session_id

    req_data = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get("error") or error_json.get("message") or error_body
        except json.JSONDecodeError:
            error_msg = error_body
        raise RuntimeError(f"HTTP {e.code}: {error_msg}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")
    except Exception as e:
        raise RuntimeError(f"Request failed: {str(e)}")


def _ok(result: Dict[str, Any]) -> str:
    return json.dumps(result, indent=2)


def _err(e: Exception, **context) -> str:
    return json.dumps({"error": str(e), "status": "failed", **context})


# ══════════════════════════════════════════════════════════════════════════════
# Core loop: session, tasks, checkin
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_context(session_id: Optional[str] = None) -> str:
    """Get full situational awareness at session start. Returns agent info,
    tasks, unread messages, projects, pending approvals, decisions needing
    ack, QA reviews, and github_integration status. Call this FIRST every
    session. Store the returned session_id and pass it to all subsequent
    tool calls."""
    try:
        return _ok(_make_request("GET", "context", session_id=session_id))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_available_tasks(session_id: Optional[str] = None) -> str:
    """List tasks with status=ready that you can claim. Filtered by your
    capabilities and unmet dependencies. Sorted by priority."""
    try:
        return _ok(_make_request("GET", "tasks/available", session_id=session_id))
    except Exception as e:
        return _err(e)


@mcp.tool()
def claim_task(task_id: str, session_id: Optional[str] = None) -> str:
    """Claim a task. Broadcasts a claim notification to other agents.
    Task becomes status=claimed and assigned to you."""
    try:
        return _ok(_make_request("POST", f"tasks/{task_id}/claim", session_id=session_id))
    except Exception as e:
        return _err(e, task_id=task_id)


@mcp.tool()
def update_task_status(
    task_id: str,
    status: str,
    comment: Optional[str] = None,
    pr_url: Optional[str] = None,
    needs_human: Optional[bool] = None,
    session_id: Optional[str] = None,
) -> str:
    """Update task status. Valid values: backlog, ready, claimed, in_progress,
    review, done, cancelled. Include pr_url when moving to review or done
    (required for GitHub auto-close integration). Returns reminder text
    hinting what to do next.

    If workspace has GitHub integration connected (check /context's
    github_integration.connected), you don't need to call status=done after
    PR merge — webhook auto-closes it."""
    try:
        data: Dict[str, Any] = {"status": status}
        if comment:
            data["comment"] = comment
        if pr_url:
            data["pr_url"] = pr_url
        if needs_human is not None:
            data["needs_human"] = needs_human
        return _ok(_make_request("POST", f"tasks/{task_id}/status", data=data, session_id=session_id))
    except Exception as e:
        return _err(e, task_id=task_id)


@mcp.tool()
def release_task(task_id: str, comment: str, session_id: Optional[str] = None) -> str:
    """Release a claimed task back to ready state. Use when you realize you
    can't complete it. A 5-minute cooldown prevents you from re-claiming
    the same task immediately.

    Args:
        task_id: ID of the task to release
        comment: Required explanation of why you're releasing
    """
    try:
        return _ok(_make_request(
            "POST", f"tasks/{task_id}/release",
            data={"comment": comment}, session_id=session_id
        ))
    except Exception as e:
        return _err(e, task_id=task_id)


@mcp.tool()
def request_human(task_id: str, reason: str, session_id: Optional[str] = None) -> str:
    """Flag a task as needing human input. Shows up in the Action Queue for
    humans to resolve. Use when you hit a decision or blocker only a human
    can resolve (e.g., business logic, API keys, credentials)."""
    try:
        return _ok(_make_request(
            "POST", f"tasks/{task_id}/request-human",
            data={"reason": reason}, session_id=session_id
        ))
    except Exception as e:
        return _err(e, task_id=task_id)


@mcp.tool()
def checkin(
    status: str,
    task_id: Optional[str] = None,
    progress_pct: Optional[int] = None,
    project_id: Optional[str] = None,
    assumptions: Optional[Dict[str, Any]] = None,
    touched_files: Optional[List[str]] = None,
    session_id: Optional[str] = None,
) -> str:
    """Send a heartbeat with progress and context. Call every few minutes
    while working. Exempt from iteration limits — does not count against
    your session cap.

    Args:
        status: Free-form description of what you're doing right now
        task_id: Task you're working on (defaults to current_task_id)
        progress_pct: 0-100 progress estimate
        project_id: Override auto-resolved project context
        assumptions: Dict of tech assumptions (e.g. {"api_style": "rest"})
        touched_files: List of file paths being edited (for conflict detection)
    """
    try:
        data: Dict[str, Any] = {"status": status}
        if task_id:
            data["task_id"] = task_id
        if progress_pct is not None:
            data["progress_pct"] = max(0, min(100, progress_pct))
        if project_id:
            data["project_id"] = project_id
        if assumptions:
            data["assumptions"] = assumptions
        if touched_files:
            data["touched_files"] = touched_files
        return _ok(_make_request("POST", "checkin", data=data, session_id=session_id))
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════════════════════════
# Messaging
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_messages(session_id: Optional[str] = None) -> str:
    """Fetch unread messages directed to you. Auto-marked as read after
    retrieval. Messages with requires_ack=true must be explicitly
    acknowledged via acknowledge_message before you can claim tasks or
    checkin — otherwise you get 409."""
    try:
        return _ok(_make_request("GET", "messages", session_id=session_id))
    except Exception as e:
        return _err(e)


@mcp.tool()
def send_message(
    to_type: str,
    message_type: str,
    content: str,
    to_agent_id: Optional[str] = None,
    priority: Optional[str] = None,
    expires_at: Optional[str] = None,
    requires_ack: Optional[bool] = None,
    parent_message_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> str:
    """Send a message. Use broadcast for FYIs, handoffs, status updates.
    Use agent-to-agent for questions and direct blockers.

    Args:
        to_type: "agent" | "human" | "broadcast"
        message_type: "handoff" | "question" | "blocker" | "fyi" | "status_update"
        content: Message body
        to_agent_id: Required if to_type="agent"
        priority: "urgent" | "normal" (default) | "low" — blockers auto-set to urgent
        expires_at: ISO timestamp when message becomes irrelevant (skipped from unread)
        requires_ack: Force ack requirement (blocker/handoff default to true)
        parent_message_id: To reply in a thread
        metadata: Arbitrary context
    """
    try:
        data: Dict[str, Any] = {
            "to_type": to_type,
            "message_type": message_type,
            "content": content,
        }
        if to_agent_id:
            data["to_agent_id"] = to_agent_id
        if priority:
            data["priority"] = priority
        if expires_at:
            data["expires_at"] = expires_at
        if requires_ack is not None:
            data["requires_ack"] = requires_ack
        if parent_message_id:
            data["parent_message_id"] = parent_message_id
        if metadata:
            data["metadata"] = metadata
        return _ok(_make_request("POST", "messages", data=data, session_id=session_id))
    except Exception as e:
        return _err(e, to_type=to_type)


@mcp.tool()
def acknowledge_message(
    message_id: str,
    response: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Acknowledge a message that requires_ack. Clears the block on your
    task claims and checkins. Optionally include a response.

    Args:
        message_id: ID of the message to ack
        response: Optional text response to the sender
    """
    try:
        data: Dict[str, Any] = {}
        if response:
            data["response"] = response
        return _ok(_make_request(
            "POST", f"messages/{message_id}/acknowledge",
            data=data or None, session_id=session_id
        ))
    except Exception as e:
        return _err(e, message_id=message_id)


# ══════════════════════════════════════════════════════════════════════════════
# Projects
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_projects(session_id: Optional[str] = None) -> str:
    """List all active projects in your workspace."""
    try:
        return _ok(_make_request("GET", "projects", session_id=session_id))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_project_spec(project_id: str, session_id: Optional[str] = None) -> str:
    """Get the spec (detailed requirements doc) for a project."""
    try:
        return _ok(_make_request("GET", f"projects/{project_id}/spec", session_id=session_id))
    except Exception as e:
        return _err(e, project_id=project_id)


@mcp.tool()
def write_project_spec(
    project_id: str,
    title: str,
    content: str,
    session_id: Optional[str] = None,
) -> str:
    """Create or update the spec for a project. Spec is the living
    document of requirements, decisions, and architectural choices."""
    try:
        return _ok(_make_request(
            "PUT", f"projects/{project_id}/spec",
            data={"title": title, "content": content},
            session_id=session_id
        ))
    except Exception as e:
        return _err(e, project_id=project_id)


@mcp.tool()
def get_workspace_state(project_id: str, session_id: Optional[str] = None) -> str:
    """Get the shared workspace state for a project — the blackboard where
    agents record decisions, assumptions, completed artifacts, and
    conventions. Read this before starting work to avoid conflicts.

    Returns: { current_approach, decisions[], assumptions[],
    completed_artifacts[], blocking_questions[], conventions{},
    active_files{} }"""
    try:
        return _ok(_make_request(
            "GET", f"projects/{project_id}/workspace",
            session_id=session_id
        ))
    except Exception as e:
        return _err(e, project_id=project_id)


@mcp.tool()
def update_workspace_state(
    project_id: str,
    updates: Dict[str, Any],
    session_id: Optional[str] = None,
) -> str:
    """Update shared workspace state. Updates are shallow-merged into
    existing state. Update whenever you make architectural decisions,
    complete artifacts, or change assumptions so other agents see them.

    Args:
        project_id: Project to update
        updates: Shallow merge of fields like current_approach,
                 decisions, assumptions, conventions, active_files
    """
    try:
        return _ok(_make_request(
            "PATCH", f"projects/{project_id}/workspace",
            data=updates, session_id=session_id
        ))
    except Exception as e:
        return _err(e, project_id=project_id)


# ══════════════════════════════════════════════════════════════════════════════
# Conflicts
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_conflicts(project_id: Optional[str] = None, session_id: Optional[str] = None) -> str:
    """List open conflicts for your workspace, optionally filtered by project."""
    try:
        endpoint = "conflicts"
        if project_id:
            endpoint += f"?project_id={project_id}"
        return _ok(_make_request("GET", endpoint, session_id=session_id))
    except Exception as e:
        return _err(e)


@mcp.tool()
def raise_conflict(
    conflict_type: str,
    severity: str,
    title: str,
    description: str,
    project_id: Optional[str] = None,
    affected_task_ids: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> str:
    """Raise a conflict to alert the team about a coordination issue.

    Args:
        conflict_type: overlapping_task | contradictory_assumption |
                       file_edit_overlap | tool_mismatch | general
        severity: warning | error (error blocks progress)
        title: Short title
        description: Detailed description
        project_id: Which project
        affected_task_ids: Task IDs implicated
        metadata: Additional context
    """
    try:
        data: Dict[str, Any] = {
            "conflict_type": conflict_type,
            "severity": severity,
            "title": title,
            "description": description,
        }
        if project_id:
            data["project_id"] = project_id
        if affected_task_ids:
            data["affected_task_ids"] = affected_task_ids
        if metadata:
            data["metadata"] = metadata
        return _ok(_make_request("POST", "conflicts", data=data, session_id=session_id))
    except Exception as e:
        return _err(e, title=title)


@mcp.tool()
def resolve_conflict(
    conflict_id: str,
    resolution: str,
    rationale: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Resolve a conflict (orchestrator agents only). Non-orchestrators
    will get 403.

    Args:
        conflict_id: ID of the conflict
        resolution: "use_option_1" | "use_option_2" | "hybrid" | "defer"
                    "defer" creates a decision for team buy-in
        rationale: Why this resolution was chosen
    """
    try:
        data: Dict[str, Any] = {"resolution": resolution}
        if rationale:
            data["rationale"] = rationale
        return _ok(_make_request(
            "POST", f"conflicts/{conflict_id}/resolve",
            data=data, session_id=session_id
        ))
    except Exception as e:
        return _err(e, conflict_id=conflict_id)


# ══════════════════════════════════════════════════════════════════════════════
# Proposals (consensus voting across agents)
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def create_proposal(
    title: str,
    options: List[str],
    description: Optional[str] = None,
    project_id: Optional[str] = None,
    quorum: Optional[int] = None,
    expires_at: Optional[str] = None,
    is_blocking: Optional[bool] = None,
    blocks_task_ids: Optional[List[str]] = None,
    tie_breaker: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Create a proposal for agent consensus voting. Use when multiple
    agents need to agree on an approach without an orchestrator decision.

    Args:
        title: Short title of the proposal
        options: List of at least 2 options to vote on
        description: Detailed context
        project_id: Scope to a specific project
        quorum: Minimum votes needed to resolve (default 2)
        expires_at: ISO timestamp deadline
        is_blocking: If true, blocks task claims until resolved
        blocks_task_ids: Task IDs this proposal blocks
        tie_breaker: "orchestrator" (default) | "first_vote" | "random" | "revote"
    """
    try:
        data: Dict[str, Any] = {"title": title, "options": options}
        if description:
            data["description"] = description
        if project_id:
            data["project_id"] = project_id
        if quorum is not None:
            data["quorum"] = quorum
        if expires_at:
            data["expires_at"] = expires_at
        if is_blocking is not None:
            data["is_blocking"] = is_blocking
        if blocks_task_ids:
            data["blocks_task_ids"] = blocks_task_ids
        if tie_breaker:
            data["tie_breaker"] = tie_breaker
        return _ok(_make_request("POST", "proposals", data=data, session_id=session_id))
    except Exception as e:
        return _err(e, title=title)


@mcp.tool()
def list_proposals(
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """List proposals. status default is "open".

    Args:
        status: open | passed | tied | rejected | expired | withdrawn
        project_id: Filter by project
    """
    try:
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        if project_id:
            query["project_id"] = project_id
        return _ok(_make_request("GET", "proposals", query=query, session_id=session_id))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_proposal(proposal_id: str, session_id: Optional[str] = None) -> str:
    """Get a proposal's full details including current vote tally and
    individual votes with rationales."""
    try:
        return _ok(_make_request("GET", f"proposals/{proposal_id}", session_id=session_id))
    except Exception as e:
        return _err(e, proposal_id=proposal_id)


@mcp.tool()
def vote_on_proposal(
    proposal_id: str,
    option: str,
    rationale: str,
    session_id: Optional[str] = None,
) -> str:
    """Cast a vote on an open proposal. Rationale is REQUIRED — helps
    other agents understand your reasoning.

    When your vote pushes a proposal to quorum, the system auto-resolves:
    - Single winner → status=passed, decision created
    - Tie → resolved per tie_breaker strategy or status=tied
    """
    try:
        return _ok(_make_request(
            "POST", f"proposals/{proposal_id}/vote",
            data={"option": option, "rationale": rationale},
            session_id=session_id
        ))
    except Exception as e:
        return _err(e, proposal_id=proposal_id)


@mcp.tool()
def retract_vote(
    proposal_id: str,
    reason: str,
    session_id: Optional[str] = None,
) -> str:
    """Retract your vote on a proposal. Reason is required. Your vote
    is marked retracted but kept for audit."""
    try:
        return _ok(_make_request(
            "POST", f"proposals/{proposal_id}/vote/retract",
            data={"reason": reason}, session_id=session_id
        ))
    except Exception as e:
        return _err(e, proposal_id=proposal_id)


@mcp.tool()
def withdraw_proposal(
    proposal_id: str,
    reason: str,
    session_id: Optional[str] = None,
) -> str:
    """Withdraw a proposal you created. Sets status=withdrawn.
    Only the creator can withdraw."""
    try:
        return _ok(_make_request(
            "POST", f"proposals/{proposal_id}/withdraw",
            data={"reason": reason}, session_id=session_id
        ))
    except Exception as e:
        return _err(e, proposal_id=proposal_id)


@mcp.tool()
def break_tie(
    proposal_id: str,
    winning_option: str,
    rationale: str,
    session_id: Optional[str] = None,
) -> str:
    """Break a tie on a proposal (orchestrator only). Use when a proposal
    has status=tied and tie_breaker=orchestrator."""
    try:
        return _ok(_make_request(
            "POST", f"proposals/{proposal_id}/break-tie",
            data={"winning_option": winning_option, "rationale": rationale},
            session_id=session_id
        ))
    except Exception as e:
        return _err(e, proposal_id=proposal_id)


# ══════════════════════════════════════════════════════════════════════════════
# Decisions (orchestrator-published binding decisions)
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def publish_decision(
    project_id: str,
    title: str,
    description: str,
    options: List[str],
    chosen_option: str,
    rationale: str,
    requires_ack: Optional[bool] = None,
    deadline: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Publish a binding decision (orchestrator only). Broadcasts to all
    agents with requires_ack=true by default — each agent must ack the
    decision before continuing work."""
    try:
        data: Dict[str, Any] = {
            "project_id": project_id,
            "title": title,
            "description": description,
            "options": options,
            "chosen_option": chosen_option,
            "rationale": rationale,
        }
        if requires_ack is not None:
            data["requires_ack"] = requires_ack
        if deadline:
            data["deadline"] = deadline
        return _ok(_make_request("POST", "decisions", data=data, session_id=session_id))
    except Exception as e:
        return _err(e, title=title)


@mcp.tool()
def ack_decision(decision_id: str, session_id: Optional[str] = None) -> str:
    """Acknowledge a decision. Marks it read in your agent record and
    removes it from decisions_needing_ack in /context."""
    try:
        return _ok(_make_request("POST", f"decisions/{decision_id}/ack", session_id=session_id))
    except Exception as e:
        return _err(e, decision_id=decision_id)


@mcp.tool()
def get_decisions(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    requires_ack: Optional[bool] = None,
    session_id: Optional[str] = None,
) -> str:
    """List decisions. Default returns active decisions.

    Args:
        project_id: Filter by project
        status: active | archived | superseded
        requires_ack: Only decisions needing your ack
    """
    try:
        query: Dict[str, Any] = {}
        if project_id:
            query["project_id"] = project_id
        if status:
            query["status"] = status
        if requires_ack is not None:
            query["requires_ack"] = "true" if requires_ack else "false"
        return _ok(_make_request("GET", "decisions", query=query, session_id=session_id))
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════════════════════════
# Approvals (task completion gate)
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def submit_for_approval(
    task_id: str,
    completion_notes: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Submit a task for approval instead of directly marking done.
    Use when the project has approval_required_by_default=true (check
    /context). Task moves to pending_approval and orchestrator is notified.
    """
    try:
        data: Dict[str, Any] = {}
        if completion_notes:
            data["completion_notes"] = completion_notes
        return _ok(_make_request(
            "POST", f"tasks/{task_id}/submit-for-approval",
            data=data or None, session_id=session_id
        ))
    except Exception as e:
        return _err(e, task_id=task_id)


@mcp.tool()
def get_awaiting_approval(session_id: Optional[str] = None) -> str:
    """Get tasks you've submitted that are pending approval."""
    try:
        return _ok(_make_request("GET", "tasks/awaiting-approval", session_id=session_id))
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════════════════════════
# QA reviews
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def submit_for_qa(
    task_id: str,
    notes: str,
    session_id: Optional[str] = None,
) -> str:
    """Submit a task for QA review. QA reviewer (human or agent) must
    pass/fail the submission. Use when project has QA enabled.

    Args:
        task_id: Task to submit
        notes: Required summary of what was done (e.g. "Tests pass, no
               regressions, ready for review")
    """
    try:
        return _ok(_make_request(
            "POST", f"tasks/{task_id}/submit-for-qa",
            data={"notes": notes}, session_id=session_id
        ))
    except Exception as e:
        return _err(e, task_id=task_id)


@mcp.tool()
def review_qa(
    review_id: str,
    verdict: str,
    notes: str,
    checklist: Optional[List[str]] = None,
    session_id: Optional[str] = None,
) -> str:
    """Pass/fail a QA review (QA reviewer only).

    Args:
        review_id: QA review ID
        verdict: "pass" | "fail" | "changes_requested"
        notes: Required — explain the verdict
        checklist: Optional checklist of things verified/failed
    """
    try:
        data: Dict[str, Any] = {"verdict": verdict, "notes": notes}
        if checklist:
            data["checklist"] = checklist
        return _ok(_make_request(
            "POST", f"qa/{review_id}/review",
            data=data, session_id=session_id
        ))
    except Exception as e:
        return _err(e, review_id=review_id)


# ══════════════════════════════════════════════════════════════════════════════
# Task comments
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def add_task_comment(
    task_id: str,
    content: str,
    session_id: Optional[str] = None,
) -> str:
    """Add a comment to a task. Comments appear in the task timeline for
    humans and agents. Use for progress notes, decisions, rationale."""
    try:
        return _ok(_make_request(
            "POST", f"tasks/{task_id}/comments",
            data={"content": content}, session_id=session_id
        ))
    except Exception as e:
        return _err(e, task_id=task_id)


# ══════════════════════════════════════════════════════════════════════════════
# Events (polling/long-polling)
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_events(
    since: Optional[str] = None,
    types: Optional[str] = None,
    limit: Optional[int] = None,
    session_id: Optional[str] = None,
) -> str:
    """Poll for events since a timestamp. Events are synthesized from
    messages, task changes, conflicts, approvals, QA, decisions.

    Args:
        since: ISO timestamp — return events after this
        types: Comma-separated event types (e.g. "message,task,conflict")
        limit: Max events to return (default 50)

    Returns { events, next_since, has_more }.
    """
    try:
        query: Dict[str, Any] = {}
        if since:
            query["since"] = since
        if types:
            query["types"] = types
        if limit:
            query["limit"] = limit
        return _ok(_make_request("GET", "events", query=query, session_id=session_id))
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════════════════════════
# Capabilities
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_capabilities(session_id: Optional[str] = None) -> str:
    """Get your agent's declared capabilities (e.g. ["frontend", "python"]).
    Tasks with required_capabilities filter available_tasks to only show
    work you can take on."""
    try:
        return _ok(_make_request("GET", "capabilities", session_id=session_id))
    except Exception as e:
        return _err(e)


@mcp.tool()
def set_capabilities(
    capabilities: List[str],
    session_id: Optional[str] = None,
) -> str:
    """Declare your capabilities. Controls which tasks appear in
    get_available_tasks. Examples: ["frontend", "react", "python",
    "database"]. Keep them short and stable."""
    try:
        return _ok(_make_request(
            "PUT", "capabilities",
            data={"capabilities": capabilities}, session_id=session_id
        ))
    except Exception as e:
        return _err(e)


# ══════════════════════════════════════════════════════════════════════════════
# Batch
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def batch_operations(
    operations: List[Dict[str, Any]],
    session_id: Optional[str] = None,
) -> str:
    """Execute multiple API calls in a single round-trip. Use when you
    need to do several things atomically (e.g. mark task done + create
    follow-up + broadcast). Max 50 operations per batch.

    Args:
        operations: Each op is {"action": str, ...params}
                    Supported actions: create_project, create_task,
                    update_task, claim_task, send_message, checkin,
                    write_spec
                    Use "$0", "$1" to reference resources from earlier ops.

    Returns { results: [...], summary: {total, succeeded, failed} }.
    """
    if not operations:
        return _err(ValueError("operations list is empty"))
    try:
        return _ok(_make_request(
            "POST", "batch",
            data={"operations": operations}, session_id=session_id
        ))
    except Exception as e:
        return _err(e)


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    """Entry point for the Hatchery MCP server (installed as `hatchery-mcp`)."""
    if not API_KEY:
        print(
            "Warning: HATCHERY_API_KEY not set. Set it with: "
            "export HATCHERY_API_KEY=your-key",
            file=sys.stderr,
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
