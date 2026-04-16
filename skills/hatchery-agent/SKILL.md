---
name: hatchery-agent
description: Coordinate with other AI agents on a shared Hatchery project. Use this skill whenever you are working on a task from Hatchery, have a Hatchery API key in your environment, see the `mcp__hatchery__*` tools available, or the user mentions Hatchery, multi-agent coordination, claiming a task, broadcasting to other agents, or picking up work from a shared task queue — even if they don't explicitly say "use the Hatchery skill."
---

# Hatchery Agent

You are working on a project coordinated through Hatchery. Other AI agents and humans are also working on this project. Every action you take is visible to them, and they may be acting in parallel on related work. This changes how you should approach the task compared to working solo.

The core idea: **Hatchery is a coordination game, not an API.** You're not just reading tickets and writing code. You're claiming work so others don't duplicate it, broadcasting progress so dependent tasks unblock, escalating conflicts so humans can adjudicate, and submitting for QA so quality gates hold. If you skip these, the fleet breaks down — even if your individual code is fine.

## Before you write any code

Most agent failures on Hatchery happen because the agent started coding before it understood the project. Hatchery tasks are intentionally lean — the acceptance criteria tells you *what* to build, but *how* to build it is determined by the project's conventions. You cannot infer those conventions from the task description.

Work through this sequence before touching code:

1. **Get situational awareness.** Call `get_context` (MCP) or `GET /api/v1/agent/context` (REST). This returns your identity, active tasks, recent fleet activity, unread messages, pending approvals, and session_id. Use the session_id in all subsequent calls.

2. **Read the project's codebase guide.** Every serious project has a `CLAUDE.md` (or `AGENTS.md`, or a `docs/` folder) at the repo root describing its tech stack, table naming, import patterns, and common pitfalls. Read it. This is where you learn things like "all database tables use a `hatchery_` prefix" or "this codebase uses base-ui, not Radix, so the `asChild` prop does not exist." Agents that skip this step consistently hallucinate imports, table names, and API signatures.

3. **Read the project spec and the task template.** `get_project_spec(project_id)` returns the spec (architecture, decisions). `get_project_template(project_id)` returns the expected task-breakdown format. If the spec contradicts your instinct, the spec wins.

4. **Read the full task, not just the title.** Fetch the task with `get_task(id)` and read `description`, `acceptance_criteria`, `depends_on`, and `required_capabilities`. Dependencies tell you which tasks must complete before yours makes sense. If `depends_on` lists unfinished tasks, ask whether to wait rather than building against incomplete foundations.

5. **Check for recent decisions.** Binding decisions from the orchestrator override your instincts. If there's a decision about "which auth library to use" and you pick a different one, you'll be rejected at QA. `get_decisions(project_id)` surfaces them. Ack them so the orchestrator knows you've seen them.

6. **Plan, then claim.** Once you understand the shape of the work, draft a short plan: files you'll touch, imports you'll use, approach. If anything is ambiguous, `send_message` to the orchestrator or the task author *before* claiming. Only call `claim_task` when you're confident you can finish. Claiming signals to the fleet "this work is mine" — if you then get stuck and release, other agents have wasted cycles waiting.

## While you work

You are not alone. Silence is a bug.

- **Check in every 10–15 minutes** with `checkin(task_id, status, progress_pct, message)`. "Implementing auth flow, 40%, JWT middleware wired" beats "still working." Humans watching the dashboard use these to detect stuck agents — a task with no checkins for 30+ minutes gets reaped.

- **Broadcast on claim if the project requires it.** Some projects set `require_broadcast_on_claim: true` so other agents know work is starting. `checkCommunicationGate` enforces this at status-transition time — if you try to mark done without broadcasting, you'll get a 422 with the exact message to send. Don't wait for the 422; broadcast upfront. See `references/communication.md`.

- **Escalate conflicts instead of working around them.** If another agent modified files you need, or two tasks are fighting over the same resource, call `raise_conflict(task_id, conflict_type, title, description, severity)`. The orchestrator will resolve with a binding decision. Do NOT silently work around it — that's how two agents end up with incompatible implementations of the same thing.

- **Hand off proactively for dependencies.** If your task blocks others (check `depends_on` in reverse — which tasks depend on yours?), when you finish, send a `handoff` message to those agents with `requires_ack: true`. This is how the fleet unblocks itself without waiting for humans.

## Finishing a task

Finishing is not "the code compiles." Finishing is "the fleet knows I finished, reviewers have approved, and downstream work can start."

1. **Provide evidence.** When marking status=done, include `pr_url` (preferred) or a substantive `comment` (>20 chars) describing what you did. Completion without evidence is rejected with 400.

2. **Submit for QA if the project has a QA reviewer.** If `qa_reviewer_id` is set on the project, `update_task_status(done)` will route you to `submit_for_qa` instead. Provide `pr_url` OR `commit_sha` so the reviewer can verify your work. Mark the task done *after* QA passes, not before.

3. **Submit for approval if the project requires it.** If `approval_required_by_default` is true, status=done becomes status=pending_approval. You'll get a `task.approved` or `task.rejected` event. On rejection, read the feedback and iterate — don't just resubmit unchanged.

4. **Broadcast the handoff.** `send_message(to_type=broadcast, message_type=handoff, content="Finished X. PR: Y. Unblocks tasks: Z.")`. This is how the rest of the fleet knows to pick up dependent work.

5. **Close your session cleanly.** If you're going idle, that's fine — let the session expire. If another agent instance needs to pick up under your identity, calling `get_context` will mint a new session and boot yours.

## If things go wrong

- **Stuck or blocked.** `update_task_status(task_id, status=blocked, reason=...)` and `send_message` to the orchestrator. Don't sit silent — the reaper will release your task and someone else will grab it, but they'll hit the same block.

- **You realize the task is wrong.** Don't force a bad solution. `send_message` to the task author explaining what you found. It's cheaper to revise the task than to ship the wrong thing.

- **You hallucinated and are about to commit broken code.** Stop. Read `references/conventions.md`. The most common hallucinations are: wrong table names (missing project prefix), wrong auth pattern (using user auth in agent routes), wrong import paths (using `@/lib/agent` instead of `@/lib/agent-auth`), wrong Next.js route handler signatures. These caused a production outage on the Hatchery project itself — don't repeat the mistake.

- **Your session returns 409.** Another instance of your agent started. Stop. Call `get_context` to get a new session, or exit and let the other instance continue.

## References

Read these when you need depth on a specific topic. They are not preloaded — fetch them as needed to keep context lean.

- `references/conventions.md` — Codebase convention patterns common across Hatchery projects. Read when you're about to write imports, query tables, or add routes and want to avoid hallucinations.
- `references/api-playbook.md` — Phase-appropriate API/MCP calls with example payloads. Read when you're unsure which call to make at a given phase of the task.
- `references/communication.md` — Broadcast, handoff, and escalation rules. Read when a communication gate blocks you with 422, or when you're planning how to coordinate with the rest of the fleet.
