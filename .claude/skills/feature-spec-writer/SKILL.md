---
name: feature-spec-writer
description: Generate a detailed, implementation-ready feature specification document from a project's shared context plus a feature description, for spec-driven development with Claude Code. Use this skill whenever the user provides (or references) a shared/project context and asks for a spec, feature spec, SDD document, implementation plan, or "detailed spec for feature X" — and also when they paste a SPEC.md or shared-context section and name a feature to build, even if they don't use the word "spec". Also use it when the user asks to "plan feature N", "write the F3 spec", "break this feature down for a Claude Code session", or to add a new feature to an existing spec-driven project.
---

# Feature Spec Writer

Turn (shared project context + a feature description) into a single, self-contained feature spec that one Claude Code session can implement without asking questions. The spec's job is to make "done" objective and to make contradictions with the rest of the project impossible.

## Inputs

Expect two inputs, in the conversation or as files:

1. **Shared context** — the project-wide source of truth: goal, engineering principles, tech stack, repo layout, data/state schemas, API contracts, design system, definition of done. It may be a `SPEC.md` section, a `CLAUDE.md`, a README, or prose.
2. **Feature context** — what this feature should do. May be one sentence ("add auth") or detailed. May include a feature ID (F5, FEAT-12) and its position among other features.

If the shared context is missing pieces the feature depends on (e.g., the feature touches an API but no API contract exists), do NOT silently invent project-wide decisions. Either ask one focused question, or — if the user prefers momentum — make the minimal decision, and record it in the spec's **Context deltas** section as a proposed addition to the shared context.

## Process

Work through these five steps in order.

### Step 1 — Extract the authoritative contracts

Read the shared context and pull out everything this feature could touch: schema/type definitions, API routes and payloads, naming conventions, directory layout, constants and limits, design tokens, engineering principles, and the list of already-specced features. These are constraints, not suggestions — the spec must use these exact names, paths, and shapes. Quote them into the spec's Context digest so the implementing session doesn't have to re-derive them.

### Step 2 — Check fit before writing

Before drafting, verify the feature against the shared context and existing features:

- Does it duplicate or overlap an existing feature's scope? If so, say which and propose the boundary.
- Does it require changing a shared contract (new state field, new route, renamed type)? Any such change is a **context delta** — it must be listed explicitly so the shared context can be updated first. A feature spec that silently drifts from the shared contracts is the failure mode this skill exists to prevent.
- Does it violate an engineering principle (e.g., project says "no component libraries" and the feature asks for one)? Surface the conflict to the user instead of quietly picking a side.

### Step 3 — Verify library APIs (do not spec from memory)

Where the feature touches external libraries, verify the APIs before writing implementation notes:

- In a repo: check installed versions (`pip show <pkg>`, `npm ls <pkg>`, lockfiles) and read the actual package source or type stubs when unsure.
- Otherwise: search current documentation for the pinned versions in the shared context.

Specs that cite deprecated APIs (e.g., a module that moved between major versions) send the implementing session down a broken path — the spec is where stale knowledge must be caught. Record the verified version and any version-specific gotchas in **Implementation notes**.

### Step 4 — Write the spec using the template

Use the exact template in the next section. Sizing rule: one feature = one Claude Code session. If honest scoping produces more than ~8 scope items or multiple unrelated subsystems, split it and tell the user ("this is really F7a and F7b").

### Step 5 — Consistency pass

Re-read the draft against the shared context with fresh eyes and check:

- Every type, route, path, constant, and env var in the spec appears in (or is declared as a delta to) the shared context — exact spelling.
- The Verify block is runnable as written and exercises the acceptance criteria.
- Every acceptance criterion is objectively checkable (a test passes, a command succeeds, a file exists) — no "works well", no "is clean".
- Nothing in Scope contradicts Out of scope or a previous feature's spec.
- Dependencies list every prior feature whose outputs this spec assumes.

Fix what fails, then deliver.

## Output template

ALWAYS use this exact structure. Save as a Markdown file (default `specs/<ID>-<slug>.md`, e.g. `specs/F5-hitl-approval.md`) unless the user wants it inline.

```markdown
## <ID> — <Feature name>

**Goal:** <one sentence: the user-visible or system-visible outcome>

**Depends on:** <feature IDs whose outputs this assumes, or "none">

### Context digest

<the specific contracts, schemas, routes, principles, and constants from the
shared context that this feature touches — quoted with exact names, so the
implementing session needs no other document open>

### Context deltas

<contract changes this feature introduces (new fields, routes, env vars,
constants). Each delta = a required edit to the shared context BEFORE
implementation. Write "none" when the feature fits the existing contracts.>

### Scope

1. <numbered, concrete steps with exact file paths, function signatures,
   and payload shapes. Include short code skeletons where the shape matters
   more than prose (state models, tricky API calls, routing functions).>

### Out of scope

- <adjacent work explicitly deferred, with the feature ID that owns it>

### Implementation notes

- <verified library versions and version-specific gotchas>
- <known pitfalls, idempotency/determinism requirements, performance limits>

### Test plan

- <the specific unit/integration tests to write, each testing one behavior>

### Verify

<one runnable command or short command sequence + what its output must show>

### Acceptance criteria

- [ ] <objective, checkable statements — each maps to a test or the Verify block>
```

## Quality bar

- **Concrete over descriptive.** "Implement `route_after_review(state) -> list[Send] | str` in `graph/routing.py`" — not "add routing logic". Every scope item names its file.
- **Contracts are load-bearing.** When the feature consumes a shared schema, restate the exact field names in the Context digest rather than pointing at the other document — the implementing session should never guess a field name.
- **Bounded loops and budgets.** Any retry, revision, polling, or agentic loop in scope must state its cap and where the cap lives.
- **Honest tradeoffs.** When the spec chooses a simplification (in-memory registry, no migrations), say so and name the production alternative — don't hide it.
- **Acceptance criteria mirror the goal.** If the goal survives with a criterion deleted, the criterion is filler; if a failure mode isn't caught by any criterion, add one.

## Example (condensed)

**Input** — Shared context: FastAPI + LangGraph project; state schema has `plan: list[SectionPlan]`, `status` literal; API contract lists `POST /api/runs/{id}/resume`; principle: "interrupts must be deterministic". Feature context: "F5: pause the graph after planning for human approval".

**Output** (abbreviated):

```markdown
## F5 — Human-in-the-loop approval gate

**Goal:** The graph pauses after planning and resumes with the human's
approve/edit decision, surviving process restarts.

**Depends on:** F2 (state schema, compiled graph), F4 (routing)

### Context digest

- State fields consumed: `plan: list[SectionPlan]`, `plan_approved: bool`,
  `status` (set to "researching" on resume). Constant `MAX_SECTIONS = 6`.
- API route (already in contract): `POST /api/runs/{run_id}/resume
{action, plan?} → 202`.
- Principle: nodes calling `interrupt()` re-execute from the top on resume —
  no side effects before the interrupt call.

### Context deltas

none

### Scope

1. `app/graph/nodes/approval.py::approval_gate(state)` — single
   `interrupt({"plan": ...})` as the first statement; resume payload
   `{"action": "approve"} | {"action": "edit", "plan": [...]}`; edited
   plans clamped to MAX_SECTIONS.
   ...

### Verify

`uv run python -m app.graph.demo "topic" --interactive` — kill the process
at the pause, rerun with the same thread id, resume completes.

### Acceptance criteria

- [ ] Resume survives process restart (sqlite checkpointer test passes).
- [ ] Editing the plan at approval changes the downstream fan-out.
```

## Multi-feature requests

If asked to spec several features at once, still produce one spec per feature using the template, then run the consistency pass **across** them (shared names identical, no scope overlaps, dependency order valid). If asked to create the shared context itself, that is a different task — build it first (goal, principles, stack, schemas, contracts, layout), then spec features against it.
