# Codebase Convention Patterns

This file captures the most common hallucination sources across Hatchery-coordinated projects. Every bullet here traces back to a real incident where an agent wrote code that didn't compile, referenced a nonexistent module, or bypassed an authentication layer — usually because the agent assumed a convention that wasn't in the project's codebase.

You will not find the project-specific conventions in this file. You find those in the project's `CLAUDE.md` or equivalent. What this file gives you is the *kinds of things to look for* before you start writing.

## Table and column naming

Databases shared across products namespace their tables with a prefix. If the project uses Supabase, Postgres, or any shared instance, check the `supabase/migrations/` directory or the schema section of `CLAUDE.md` before writing queries. Bare table names (`tasks`, `users`, `projects`) almost never exist in a multi-tenant codebase. Typical patterns:

- Prefix per product: `hatchery_tasks`, `hatchery_agents`, `hatchery_projects`
- Prefix per tenant: `acme_customers`, `acme_orders`
- Schema-qualified: `public.users` vs `auth.users`

Column names are where the subtler mistakes happen. `assignee_agent_id` vs `agent_id` vs `assigned_agent_id` — these are not synonyms, and only one exists. Before you write `update({ agent_id: ... })`, grep the migrations for the actual column name. Writing to a nonexistent column throws a 500, not a compile error, so typecheck won't catch it.

Common columns that don't exist despite sounding like they should: `claimed_by` (usually `assignee_agent_id` + `claimed_at`), `released_at`, `release_comment`, `last_error`. If your instinct says "surely there's a column for X," verify before writing.

## Authentication patterns

Agent routes and human routes use different auth. Mixing them is the single most common source of broken agent endpoints.

- **Human dashboard routes** use Supabase cookie auth: `const { data: { user } } = await supabase.auth.getUser()`. The user is a real person who signed in with email/password.
- **Agent API routes** use API key auth: `const { agent, workspace } = await authenticateAgent(request)`. The agent is a registered bot calling with `Authorization: Bearer htch_...`.

If you see `supabase.auth.getUser()` in a file under `app/api/v1/agent/`, that's wrong — agents don't have cookies. If you see `authenticateAgent` in a file under `app/(dashboard)/`, that's wrong — humans don't send API keys.

There's usually a helper like `handleAgentRouteError(err)` that unifies error handling for agent routes. Use it in `catch` blocks — don't reinvent the error-mapping logic.

## Import paths

The `@/` alias points to the project root. Import paths like `@/lib/agent-auth` resolve to `<root>/lib/agent-auth.ts`. Before importing, verify the file actually exists at that path. Common hallucinations:

- `@/lib/agent` — usually doesn't exist; the real module is `@/lib/agent-auth`
- `@/lib/db` — usually doesn't exist if the project uses Supabase; there's no Prisma
- `@/lib/db/task-utils` — the kind of path that sounds right but isn't there
- `@prisma/client` — only exists if the project actually uses Prisma

When in doubt, do a `grep -r "from \"@/lib/<whatever>\""` or look at `tsconfig.json` path aliases.

## Next.js route handler signatures

Next.js 15 App Router changed the handler signature. Route files at `app/**/route.ts` export `GET`, `POST`, etc. with this shape:

```ts
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  // ...
}
```

Things that are wrong and will fail at runtime:
- `POST(params: { id: string }, request: Request)` — arguments are reversed AND params isn't a Promise
- `POST(request, { params: { id } })` — destructuring a Promise directly
- Omitting the `await` on `params`

If you're editing a route and the signature looks different from this, the existing code is likely broken from a prior hallucination.

## UI library conventions

The project's UI library is specified in `CLAUDE.md` and usually matters a lot. The most common trap: shadcn/ui components built on top of **base-ui** behave differently than shadcn/ui on Radix. Base-ui does not have an `asChild` prop. If you try to write `<Button asChild><Link href="/x">Go</Link></Button>`, it silently does the wrong thing. Check the project's component source before assuming shadcn conventions carry over.

Tailwind version matters too. Tailwind v4 uses `@import "tailwindcss"` in globals.css and has no `tailwind.config.ts`. Writing `@tailwind base;` in v4 won't break visibly but isn't canonical, and adding a config file may get auto-deleted.

## Status values and enums

Task statuses, agent statuses, message types — these are enums, and using the wrong value throws a check constraint violation at the database level. Typical task status set:

```
backlog | ready | claimed | in_progress | review | done | cancelled | pending_approval
```

Things that aren't statuses despite sounding like them: `completed` (it's `done`), `available` (it's `ready`), `failed` (tracked separately via `last_failed_at`, not as a status). Check `lib/types.ts` or the migration file for the canonical set.

## What to do if you're unsure

If you can't find what you need in `CLAUDE.md` and the codebase doesn't make it obvious, don't guess. Send a `question` message to the orchestrator or the task author:

```
send_message(
  to_type="agent",
  to_agent_id=<orchestrator_id>,
  message_type="question",
  content="Building task X. Project CLAUDE.md doesn't specify whether tests go in __tests__/ or tests/. Which convention?"
)
```

An extra 30 seconds of clarification beats a PR rejected at QA for violating conventions.
