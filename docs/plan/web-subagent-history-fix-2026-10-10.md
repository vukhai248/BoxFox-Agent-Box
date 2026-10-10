# Web checkpoint — sub-agent reasoning/history across completion and later turns

## Scope

Baseline: `0a19597b`, branch `codex/desktop-startup-fix`. Owner requested web-first
debugging using the desktop backend. This patch changes event hydration, reader
selection and development proxy configuration. It does not change agent execution,
delegation, prompts, grants, tool catalog, budgets or long-task setup.
No installer build, installation, profile rewrite, merge or push was performed.

## Evidence and diagnosis

Read-only inspection through the installed desktop gateway on Windows, 2026-10-10:

| Session from the screenshot | Events | Pages | Final canonical reasoning | Last receipt |
|---|---:|---:|---:|---|
| Main `7379d11f…` | 7,421 | 15 | Present | `finish`, seq 21943 |
| Child `415f019c…` | 109 | 1 | 400 characters | `finish`, seq 21046 |
| Child `4e6c85f7…` | 257 | 1 | 150 characters | `finish`, seq 21163 |

The two children each have two distinct model steps. Two collapsed Thinking blocks
in this screenshot therefore do not establish duplicate execution or lost reasoning.
Their final reasoning exists in the durable events; these children do not exceed
the 500-event page limit. Conversation content and production DB are not included.

Confirmed reader defects:

- Both main refresh and child inspector fetched only the first event page and ignored
  `hasMore` / `nextAfter`. A completed session could stop polling before its final
  reasoning/result was hydrated. Other stored children exceed 500 events.
- Child refresh depended only on ID/status: another delivery with the same ID and
  completed status did not trigger a fetch.
- Overlapping child requests could replace newer history; failures were swallowed.
- The default latest-parent-turn filter removed the previously viewed child when
  main received another user turn. Previously selected same-ID children could resolve
  to their earliest occurrence.
- Main refresh used a captured snapshot; a slow older response could overwrite the
  second turn's newer events/status. Pagination increases exposure to this race.

## Patch and reader behavior

- `frontend/src/lib/harnessSessionPages.ts`: drain all event pages, validate forward
  cursors, deduplicate receipt identities and support abort/legacy one-page responses.
  A failed later page is an error, not a successful empty history.
- `frontend/src/store/harnessChatStore.ts`: hydrate the complete tail before applying
  status. Ignore stale refresh success/error after a newer refresh or submitted turn.
  Allow slow hydration to fill an unchanged cache while a later periodic poll is
  pending; never replace a newer event cursor with an older snapshot.
- `frontend/src/components/panels/SubagentInspectorPanel.tsx`: retain per-child history,
  fetch incremental tails, cancel obsolete requests, avoid overlapping polling,
  refresh on new parent receipts and expose load failure with Retry.
- Reading a child row or expanding Thinking pins its parent turn. Expanded reasoning
  survives completion and another parent turn. The newest receipt of a reused child
  still drives fetching even while the earlier turn is pinned. Turn chips / all-turns
  remain available; an uninspected panel still defaults to the newest turn.
- Stable keys include child identity. Equal content in separate steps is retained;
  the prior duplicate-stream fix remains in effect.

## Web using the same desktop services

Open Desktop, then run from the repository root:

```powershell
powershell -NoProfile -File .\scripts\start-web-desktop.ps1 -WebPort 3110
```

Open **http://localhost:3110/**. Keep Desktop running as the service owner.
The script reads gateway ports from the selected desktop profile's `machine.json`;
it never prints/passes the admin token. It verifies gateway mode, port availability
and Vite readiness. Logs go to `.tmp/web-desktop-shared/`.

At this checkpoint: web 3110 → desktop gateway 64557 → router 64558 / harness 64559,
Host mode. These gateway/backend values are observations, not hard-coded defaults.
This web origin has separate browser local storage but uses the SAME backend
profile, session IDs/events, project bindings, grants and model router as Desktop.
It does not create another router/harness. The installed app still has its packaged
UI; the updated web UI is served directly from source.

`frontend/dev/desktopProxy.ts` forwards all desktop API and WebSocket route prefixes
through one validated loopback gateway. Only the dev server's own browser Origin
is translated; foreign/missing headers remain subject to gateway checks. Default
standalone web 3100 → 3101/3102 remains unchanged when the opt-in env is absent.
Node types were added as an exact dev dependency for the Vite server configuration;
model/runtime package versions were not changed.

## Verification

- Focused frontend command:
  `npm test -- src/components/panels/SubagentInspectorPanel src/lib/harnessSessionPages src/store/harnessChatStore dev/desktopProxy src/components/chat/HarnessStepView --maxWorkers=4`.
  Includes pagination beyond 500, canonical final reasoning, completion, second user
  turn, reused child on a pinned older turn, late old-child response, API failure,
  stale main refresh success/error, a newly submitted turn's starting state and
  slow hydration spanning overlapping periodic polls. **217 passed / 22 files.**
- `npm run typecheck` and ESLint on changed TypeScript files: **passed**.
- Real HTTP health checks succeeded through both web 3110 and desktop gateway.
  For the same child, session ID, status, full events and cursor were identical.
  Main history was drained to its actual final receipt across 15 pages.
- Harmless POST to an absent session: own web Origin reached backend (404);
  foreign Origin and missing Origin were rejected (403). No turn was created.
- Launcher readiness verified on temporary port 3111; only that owned probe process
  was stopped. Web 3110 and the existing standalone 3100 stack remain running.

Fixture/DOM tests and real read-only HTTP checks are evidence for reader behavior.
Native browser inspection was unavailable due to the browser tool initialization
failure. No real model run, CUA/terminal action or live gateway WebSocket 101 probe
was performed. Owner acceptance of the web interaction remains to be confirmed.

## Remaining scope

Long-task setup, `JOURNAL_DEGRADED` / project-trust policy and Explore's terminal
catalog are separate work. This checkpoint does not reinterpret them or bypass
their guards. Do not attribute model repetition to a display defect without a
distinct invocation/step trace.
