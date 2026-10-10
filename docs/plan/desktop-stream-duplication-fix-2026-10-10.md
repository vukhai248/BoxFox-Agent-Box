# Desktop 0.1.4 — duplicate reasoning/text receipts

## Scope and baseline

Owner authorized the stream/display fix. Baseline: `02dc2df4` on
`codex/desktop-startup-fix`; installed 0.1.3 was packaged from `dc60c43`.
No changes to DAG, delegation, model/tool selection, permissions, budgets or long task.
No user profile/history rewrite, automatic install, merge or push.

## Confirmed cause

Read-only inspection of one child model step found 235 thought deltas (2329 chars),
followed by an identical complete thought event. Ten text deltas (97 chars) were
followed by the identical canonical assistant text and thought. This is duplicate
publication/rendering; that evidence does not demonstrate a second model invocation.
No conversation content or production DB is included in this checkpoint.

The subagent panel previously merged only adjacent items of the same kind.
Interleaving `thought -> assistant_delta -> full thought -> assistant` therefore
created two reasoning blocks and two text rows. The main transcript had the same
adjacency assumption. Existing tests did not cover this event order.

## Patch

- Runtime emits only an unstreamed reasoning tail after completion. An identical
  final thought emits no additional delta. A rewritten final thought is explicitly
  `snapshot: true`; canonical `assistant.thought` remains complete.
- Main and subagent timelines reconcile reasoning/text within the current model
  step, independent of intervening usage or stream events. Canonical snapshots
  replace that step's content; old stored full-thought receipts still render once.
- Step/turn markers, canonical assistant and tool dispatch establish boundaries.
  Identical content in distinct steps is preserved, including old markerless histories.
- Poll/reconnect replay deduplicates positive sequence/type identities, not text.
  Retry reset drops only the abandoned attempt's text/reasoning and retains prior
  steps and tool receipts. No execution events or persisted histories are removed.
- Desktop version changes to 0.1.4 solely to distinguish the installer.

## Verification on Windows

| Command (repo/frontend cwd as appropriate) | Result |
|---|---|
| `pytest backend/tests/unit/test_stream_delta_events.py -q` | 10 passed |
| `pytest backend/tests/unit/test_retry_policy.py backend/tests/unit/test_harness_runtime.py -q` | 41 passed |
| `npm test -- src/components/chat/HarnessStepView src/components/panels/SubagentInspectorPanel src/lib/streamText` | 115 passed / 11 files |
| `npm run typecheck` | Passed |
| `npm run build` | Passed; existing large-chunk warning |

Backend test HOME/USERPROFILE/LOCALAPPDATA were isolated to temporary directories.
Fixtures cover interleaving, full/tail/rewritten/no-callback reasoning, canonical
text replacement, repeated receipts, distinct identical steps, retry, and tool results.
The runtime tests assert unchanged model call count (one normal, two for one retry).
No paid/provider request or long DAG was run. Fixture/DOM checks do not constitute
owner acceptance of the installed app; existing 0.1.3 must be replaced to use the fix.

## Packaging checkpoint

Fresh UI build precedes staging; Windows runtime blocks must match the existing lock.
Candidate destination: `desktop/release/stream-fix-0.1.4/`.
The manifest records the source commit and block hashes; owner untracked WIP remains.
Installer integrity and final hashes are recorded after packaging. The owner installs
the candidate manually; 0.1.3 and its profile are preserved for comparison/rollback.
