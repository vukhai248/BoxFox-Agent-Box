---
name: work-graph-planning
description: "Coordinate plans, dependencies and artifact checks."
version: 2.0.0
license: MIT
platforms: [linux, macos, windows]
---

# Work Graph Planning Skill

The main agent is the brain. It triages, decomposes, delegates, and decides. Children produce one
deliverable each. Main receives immutable artifact refs, inspects the draft, and calls `work_check` for checks appropriate to the artifact/risk. Simple lookup and diagnosis do not require a semantic reviewer by default.
Only the main agent delegates or asks the owner.

## When to Use

- Trivial (one fact, one small edit, a greeting): answer directly. No graph.
- Research-only or design-only: a graph with discovery nodes only; the answer is the accepted
  dossier or design. Nothing is executed.
- Anything with code changes across more than one file, unclear scope, or several parts: a full graph.

## Prerequisites

Work Graph tools must be enabled: `work_graph`, `work_run`, `work_check`, `work_artifact_read` and `work_ship`.
Code checks require a Git workspace and a valid source snapshot. Keep the owner's existing model configuration.

## How to Run

Create the graph, produce drafts, inspect refs, dispatch required checks, repair findings, then verify the whole plan.
Execute only after an execution request and the existing approval gate.

## Quick Reference

| Tool | Purpose |
|---|---|
| `work_run` | Produce one draft per ready node; dependencies wait for acceptance. |
| `work_artifact_read` | Read the immutable full snapshot in pages. |
| `work_check` | Start required checks or inspect their history. |
| `work_graph` | Edit/status/whole verification/approval. |

## Procedure

1. `work_graph(action='create', goal=<owner words>, flow=plan|research|design|fix|mixed)`.
2. Add discovery nodes: `E1..En` (explore: facts from the repository with file:line), `R1..Rn`
   (research: web and documents with cited sources), `D1..Dn` (design). One question per node,
   each with concrete `acceptance` lines. Independent nodes have no `dependsOn`, so they run in parallel.
3. `work_run(phase='discover')` saves a full draft under `.plans/work/<session-id-hash>/<runId>/<nodeId>/<stage>/`.
   Read with `work_artifact_read`; a preview is not the whole output. Inspect each policy's `required` checks.
   Call `work_check(action='start', nodeId=..., stage='produce', artifactId=<current>, checkIds=[...], invocationId=<unique>)`.
   Backend selects checker roles and binds results to artifact version/hash, node definition, owner decisions and dependencies.
   Research checks source entailment and scope; consequential research adds critique. Plans always need Plan review even if a Research child produced them.
   Simple lookup/diagnosis needs real opened evidence. A patch always needs Testing; consequential code also needs code review.
   On `revise`, main routes specific findings to the producer/Debug, then calls `work_run` for a new snapshot and checks that new ref.
   `error`, `unverified`, `partial`, unread ranges, missing acceptance coverage and stale checks NEVER count as a pass. Preserve the checkpoint at the repair cap. Knowledge requests from children (`- research: ...`, `- explore: ...`) are
   answered by the engine through new research or explore children, never by the child itself.
4. Real ambiguity that changes the approach: one `interview` card with 1-5 questions, 2-4 options
   each, a recommended option, and a rationale. Never ask what the repository can answer.
5. Add plan nodes `P1..Pn`. Each sub-plan owns one coherent slice (a module, a contract, a UI surface).
   Set `dependsOn` to the real order (a contract before its callers, a schema before its readers).
   Give every plan node `files`, `tests` and `acceptance`. Each `tests` entry is an exact runnable command;
   put test names, files and expected results in the document and `acceptance`.
6. `work_graph(action='verify')`: a whole-plan reviewer checks coverage of the goal, the dependency
   order, gaps and overlaps between sub-plans, and test coverage. `REVISE <nodeId>: <fix>` resets that
   node. On ok the engine writes `.plans/work/<slug>/` (index plus one file per sub-plan).
7. Only an execution request may `submit`. Plan/research/design-only requests end with verified artifacts even with Autopilot on. Autopilot cannot add code scope.
8. `work_run(phase='execute')`: plan nodes run as build children in DAG waves, in parallel inside a wave;
   each result is a draft. Main starts `work_check` with `stage=execute` and the exact artifact ref. Testing executes the exact required commands on the same source snapshot. Tests may produce cache/logs, never source edits; source side effects invalidate checks.
   If a node is not accepted, the run status becomes "execute_failed". Call `work_graph(action='retry',
   nodeIds=[...])` to run it again with the findings, or `action='update'` to change the plan.
9. `work_ship(repoPath=...)`: a local branch, a commit, and a PR description file. Push only when a
   remote and credentials exist.

Always follow the `next` field of the tool result. If a tool returns an error code, read `error`,
fix the arguments once, and continue.

### Quality bar for every sub-plan (senior SWE design document)

A sub-plan is rejected unless it has all of these sections, grounded in evidence:

1. **Context** - what exists now, with file:line evidence from discovery nodes.
2. **Goal and non-goals** - what this slice delivers and what it deliberately does not.
3. **Design** - interfaces, data shapes, state and error codes; the decision taken and the
   alternatives rejected, each with a reason.
4. **Changes** - the exact files and functions to touch, in order.
5. **Tests** - unit and integration tests by name, the command that runs them, and the expected result;
   the edge cases and failure paths covered.
6. **Dependencies** - which sub-plans must land first and which contract this slice relies on.
7. **Risks and rollout** - what can break, how to detect it, and how to roll back (a switch, a
   migration fallback).
8. **Acceptance** - observable checks a reviewer can run without reading the author's mind.

Reviewer checklist: every claim has evidence or is marked as a proposal with a reason; no step says
"handle errors" without naming them; tests are runnable commands, not intentions; the dependency
order is acyclic and matches the data flow; the sum of sub-plans covers the whole goal with no overlap.

## Pitfalls

Never treat a preview, a citation count or a tool name in prose as verification. A failed or partial child remains a draft.
Keep valid code changes when an integrated source snapshot becomes stale; produce a fresh handoff and rerun checks.
Main chooses checks from the backend policy and routes findings; reviewers cannot delegate recursively.

## Verification

Read all assigned artifact refs with `work_artifact_read`, following nextOffset to null, then inspect original sources/code as needed.
Return findings and one fenced JSON object with `coverage`, one `{id,status,evidence}` per assigned criterion.
Statuses are `pass`, `revise`, `unverified`. End with exactly one final `VERDICT: ok` or `VERDICT: revise` line.
Only the backend records pass after completion, read coverage, bindings and actual test events are validated.
Do not delegate a reviewer-of-reviewer. Do not edit source while checking. A source URL, citation or JSON field alone does not prove a recommendation correct.
Internal user-feedback/same-child resume is W7; this protocol does not implement it.
