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
| ESLint on four changed frontend source/test files | Passed |

Backend test HOME/USERPROFILE/LOCALAPPDATA were isolated to temporary directories.
Fixtures cover interleaving, full/tail/rewritten/no-callback reasoning, canonical
text replacement, repeated receipts, distinct identical steps, retry, and tool results.
The runtime tests assert unchanged model call count (one normal, two for one retry).
No paid/provider request or long DAG was run. Fixture/DOM checks do not constitute
owner acceptance of the installed app; existing 0.1.3 must be replaced to use the fix.

## Packaging checkpoint

Fresh UI build precedes staging; Windows runtime blocks must match the existing lock.
Final candidate destination: `desktop/release/stream-fix-0.1.4-final/`.
The manifest records the source commit and block hashes; owner untracked WIP remains.
Installer integrity and final hashes are recorded after packaging. The owner installs
the candidate manually; 0.1.3 and its profile are preserved for comparison/rollback.

### Final installer evidence

- Packaged source: `d5ad6139a85a7dc4913ae981d0a2a1ead51b5e84`.
- `BoxFox-Desktop-Alpha-0.1.4-Setup.exe`: 167429971 bytes; SHA256
  `5ec04712f59ab51f9f0508d5a7c8dcc08545ffcf03014d0395051eccf1c7ce1a`;
  NotSigned. `7za t` reports Everything is Ok for the embedded application archive,
  with a data-after-archive warning for the installer tail. This does not test installation.
- Extracted installer manifest, app.asar, UI JS and harness runtime match the unpacked
  candidate; the extracted harness runtime also matches the committed source.
- Desktop compiled JS is byte-identical to 0.1.3. Staged router/runtime/Docker-context
  block hashes are identical to 0.1.3; only UI/harness blocks change.
- Post-package harness/runtime/router hashes match the manifest. UI and Docker context
  omit `.gitkeep` (also absent in 0.1.3); all other file bytes match. This packaging
  exclusion is recorded rather than claiming every aggregate manifest hash matches.
- The first staging pass found an extra local runtime/git directory outside the lock.
  It is excluded from the final candidate by staging isolated copies of the locked
  node/python/wheels blocks. Original local cache remains untouched. Preliminary
  `stream-fix-0.1.4/` is not accepted and carries `DO-NOT-INSTALL.txt`; command policy
  rejected deleting that generated folder (`blocked by policy`), so no deletion workaround was used.
- Rebuild: fresh frontend build; copy only node/python/wheels from the verified runtime
  into an isolated source, then from desktop/:

  ```powershell
  npm run build-app -- --target win-x64 --ui-dir ../frontend/dist --runtime-source ../.tmp/stream-fix-runtime-014
  npm run dist:win -- --config.directories.output=release/stream-fix-0.1.4-final
  ```
- Manifest, runtime lock, `SHA256SUMS` and `build-receipt.json` are next to the final
  installer. `dirty=true` reflects preserved owner untracked WIP, not a modified
  tracked product source at packaging. No installation/upgrade or provider call was made.
- Owner update: Quit from tray before installing in the existing install directory.
  X hides the window; it does not quit. Keep the profile and projects intact.
