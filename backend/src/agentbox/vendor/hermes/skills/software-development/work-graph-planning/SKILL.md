---
name: work-graph-planning
description: "Main-agent procedure for non-trivial work: build a Work Graph (discover, sub-plans P1..Pn with tests and dependencies, review loops, whole-plan verify, approval or Autopilot, DAG execution, ship) and the senior SWE quality bar every sub-plan must meet."
version: 1.0.0
license: MIT
platforms: [linux, macos, windows]
---

# Work Graph planning

The main agent is the brain. It triages, decomposes, delegates, and decides. Children produce one
deliverable each; an independent reviewer child checks every deliverable until the verdict is ok.
Only the main agent delegates or asks the owner.

## 1. Triage

- Trivial (one fact, one small edit, a greeting): answer directly. No graph.
- Research-only or design-only: a graph with discovery nodes only; the answer is the accepted
  dossier or design. Nothing is executed.
- Anything with code changes across more than one file, unclear scope, or several parts: a full graph.

## 2. Build the graph

1. `work_graph(action='create', goal=<owner words>, flow=plan|research|design|fix|mixed)`.
2. Add discovery nodes: `E1..En` (explore: facts from the repository with file:line), `R1..Rn`
   (research: web and documents with cited sources), `D1..Dn` (design). One question per node,
   each with concrete `acceptance` lines. Independent nodes have no `dependsOn`, so they run in parallel.
3. `work_run(phase='discover')`. Each node is produced, then reviewed; `revise` sends the findings back
   to a new producer. Knowledge requests from children (`- research: ...`, `- explore: ...`) are
   answered by the engine through new research or explore children, never by the child itself.
4. Real ambiguity that changes the approach: one `interview` card with 1-5 questions, 2-4 options
   each, a recommended option, and a rationale. Never ask what the repository can answer.
5. Add plan nodes `P1..Pn`. Each sub-plan owns one coherent slice (a module, a contract, a UI surface).
   Set `dependsOn` to the real order (a contract before its callers, a schema before its readers).
   Give every plan node `files`, `tests` and `acceptance`.
6. `work_graph(action='verify')`: a whole-plan reviewer checks coverage of the goal, the dependency
   order, gaps and overlaps between sub-plans, and test coverage. `REVISE <nodeId>: <fix>` resets that
   node. On ok the engine writes `.plans/work/<slug>/` (index plus one file per sub-plan).
7. `work_graph(action='submit')`: an approval card for the owner, or immediate approval with Autopilot.
8. `work_run(phase='execute')`: plan nodes run as build children in DAG waves, in parallel inside a wave;
   each result goes to a testing reviewer that runs the real tests.
   If a node is not accepted, the run becomes `execute_failed`. Call `work_graph(action='retry',
   nodeIds=[...])` to run it again with the findings, or `action='update'` to change the plan.
9. `work_ship(repoPath=...)`: a local branch, a commit, and a PR description file. Push only when a
   remote and credentials exist.

Always follow the `next` field of the tool result. If a tool returns an error code, read `error`,
fix the arguments once, and continue.

## 3. Quality bar for every sub-plan (senior SWE design document)

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
