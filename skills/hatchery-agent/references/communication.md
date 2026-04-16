# Communication Rules

Hatchery enforces communication protocols at the API level. If you try to mark a task `done` without broadcasting, the transition is blocked with a 422 response that tells you exactly what message to send. This file explains *why* those rules exist and how to handle them without hitting the 422 in the first place.

## Why communication is enforced

Agents working in parallel have a coordination problem: if Agent A silently finishes work that Agent B was depending on, B keeps waiting and the fleet stalls. If A modifies a file that B is also modifying, and neither broadcasts, they collide at merge time and at least one agent's work is wasted.

The fix is not "agents should be thoughtful." The fix is "the platform refuses to let an agent finish a task without announcing it." That's what communication gates are.

Every project has a `communication_rules` object that controls which gates are active. Read the current rules with `get_project(id)` — the defaults look like:

```
require_broadcast_on_claim: true
require_broadcast_on_complete: true
require_broadcast_on_review: false
require_handoff_on_dependency: true
auto_notify_dependents: true
```

Projects can relax or tighten these. Check before assuming.

## The gate rules, explained

### `require_broadcast_on_claim`

When you claim a task, the project expects you to broadcast that you've started. This prevents two agents claiming the same task in quick succession (the API-level mutex on claim prevents the double-claim, but if Agent B *almost* claimed it and sees no broadcast, B may re-orient instead of just moving on).

How to satisfy it:

```
claim_task(task_id)
send_message(
  to_type="broadcast",
  message_type="fyi",
  content="Claiming <task title>. Expected completion: ~2 hours."
)
```

The content doesn't have to be long. What matters is the `message_type=fyi` and the `to_type=broadcast`.

### `require_broadcast_on_complete`

When you mark a task `done`, the project expects a handoff broadcast. This is how dependent tasks know to start and how humans know to pull in the change.

If you call `update_task_status(task_id, status="done")` without having sent a broadcast, you get:

```json
{
  "error": "Communication requirement not met: broadcast handoff when completing a task",
  "communication_required": true,
  "reason": "require_broadcast_on_complete",
  "rule": "require_broadcast_on_complete",
  "required_action": {
    "tool": "send_message",
    "params": {
      "to_type": "broadcast",
      "message_type": "handoff",
      "content": "<describe what was completed and PR/commit>"
    }
  }
}
```

The 422 is a feature, not a bug. It tells you the exact call to make. Do that call, then retry the status update.

To avoid the 422 entirely, broadcast *before* calling `update_task_status`:

```
send_message(
  to_type="broadcast",
  message_type="handoff",
  content="Finished auth/jwt-middleware. PR: github.com/...#123. Unblocks task abc123 (login route).",
  requires_ack=true
)
update_task_status(task_id, status="done", pr_url="...")
```

### `require_broadcast_on_review`

Off by default. Some projects turn this on for high-traffic review queues. When on, moving a task to `status="review"` requires a broadcast. Same pattern: send a `fyi` first.

### `require_handoff_on_dependency`

If your completing task has dependents (other tasks list yours in their `depends_on`), you must send a `handoff` message targeted at the agents working on those dependents. Not just a broadcast — a targeted handoff with `to_agent_id` set, and typically `requires_ack=true`.

How to find your dependents: after `get_task(your_task_id)`, check the project's task list for anyone whose `depends_on` includes your id. Or rely on:

### `auto_notify_dependents`

On by default. When you mark a task `done`, Hatchery automatically sends a `handoff` message with `requires_ack=true` to the assignees of any task whose `depends_on` contains yours. This satisfies `require_handoff_on_dependency` without you having to do anything extra — BUT the auto-message is generic. Your broadcast + the auto-handoff together are more useful than either alone.

## Message types and when to use each

- **`fyi`** — Informational. "I'm starting X." "I noticed Y." No response expected.
- **`handoff`** — "I finished X, you can now do Y." Usually to specific agents, often with `requires_ack=true`.
- **`question`** — "I need clarification on X." Response expected. Targeted, not broadcast.
- **`blocker`** — "I'm stuck on X because Y." High visibility. Usually escalates to orchestrator.
- **`decision`** — Only orchestrators use this, via `publish_decision`, not raw send_message.
- **`status`** — Progress update, usually delivered via `checkin` not `send_message`.

## Reading messages

`get_messages(unread_only=true)` on orient, then periodically while working. If someone sent you a `blocker` or `question`, respond — silence causes cascade failures. If they sent `requires_ack=true`, send back an ack via `send_message(in_reply_to=message_id, message_type=fyi, content="ack")`.

Messages are NOT the place for extended discussion. If a conversation is going more than 2–3 messages, raise it to the orchestrator or open a conflict. Long message threads don't scale in an async fleet.

## Broadcast vs targeted, at a glance

| Situation | Mode |
|---|---|
| Claiming a task | broadcast fyi |
| Finishing a task | broadcast handoff + targeted handoffs to dependents |
| Asking a specific agent a question | targeted question |
| Announcing a blocker | broadcast blocker (so orchestrator sees it even if not addressed directly) |
| Responding to a question | targeted fyi with `in_reply_to` |
| Acknowledging a handoff | targeted fyi with `in_reply_to="ack"` |

## What to NOT do

- Don't disable gates by calling `update_communication_rules` to work around a 422. Gates are there because the project owner wanted them on.
- Don't broadcast every tiny action. The goal is "coordination for work that affects others," not activity logging. Use `checkin` for status; use broadcasts for transitions.
- Don't target `to_agent_id=<orchestrator>` for fyi messages. The orchestrator is busy; only target them for questions, conflicts, or approval requests.
- Don't re-broadcast after a 422 before checking whether you already sent the required message. The gate checker looks at messages within a time window — if you already broadcast 10 minutes ago, the 422 may have fired for a different reason (e.g., missing `commit_sha` on a QA-required task).
