# BoxFox Agent Box

> **Self-Hosted AI Computer & Secure Autonomous Agent Environment**
> A local-first platform that gives autonomous LLM agents a dedicated computer — running inside an isolated sandbox, strictly governed by Information Flow Control (IFC) labels and temporal capability leases.

---

## Table of Contents

- [Why BoxFox](#why-boxfox)
- [Architecture](#architecture)
- [Security Model](#security-model)
- [Workspace UI](#workspace-ui)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Run the Workspace (Frontend)](#run-the-workspace-frontend)
  - [Build the AI Computer (Sandbox)](#build-the-ai-computer-sandbox)
  - [Verify with the Smoke Test](#verify-with-the-smoke-test)
  - [Using the Box](#using-the-box)
  - [Network Toggle](#network-toggle)
- [Repository Structure](#repository-structure)
- [Documentation](#documentation)

---

## Why BoxFox

Today's coding agents cannot distinguish *instructions from their owner* from *text they merely read* — a malicious `README.md`, web page, or screenshot can silently hijack them. BoxFox addresses this with three mechanisms working together:

1. **Provenance labels** — every piece of data entering the agent's context carries an immutable tag: where it came from, whether it may direct the agent, and where it may be sent.
2. **Temporal capability leases** — sensitive actions (file writes, command execution, egress) require scoped, expiring permissions granted *after* the most-tainted input has entered context. This closes the carry-over approval attack (arXiv 2510.26328).
3. **A hard sandbox boundary** — the agent works inside a real container ("AI Computer"), not behind string-matching heuristics.

## Architecture

Seven layers, from user to external world:

| Layer | Component | Location |
|---|---|---|
| **L1** | User Interface — React 19 workspace | `frontend/` |
| **L2** | Controller — task epochs, leases, approvals | `backend/src/agentbox/controller/` |
| **L3** | Agent Core & Model Router — Plan/Act loop | `backend/src/agentbox/agent_core/`, `router/` |
| **L4** | Security Gateway — Policy Engine, Label Store, Lease Store, Audit Ledger | `backend/src/agentbox/security/` |
| **L5** | Tools & Skills — risk-tiered tool suite | `backend/src/agentbox/tools/` |
| **L6** | Sandbox / AI Computer — isolated container | `backend/src/agentbox/sandbox/`, `deploy/docker/` |
| **L7** | External World — reached only through gated channels | — |

## Security Model

Five non-negotiable principles (full rationale: plan §2.2):

- **N1 — Single enforcement point.** Every outbound action passes exactly one Security Gateway.
- **N2 — The LLM is untrusted.** Controller and Policy Engine never delegate decisions to the model.
- **N3 — Leases are issued by the Controller only.** The agent cannot self-grant or escalate.
- **N4 — The boundary is physical.** Container mounts and network state enforce scope — not command-string inspection.
- **N5 — Tainted context never self-heals.** Only explicit human endorsement of specific artifacts restores trust.

## Workspace UI

Built with **React 19 · TypeScript · Vite · Tailwind CSS v4 · Zustand**:

- Dual-pane layout: chat on the left, VS Code-style multi-tab workspace on the right.
- Eight workspace views: Plan document, Decisions & Approvals, live Sandbox Screen, Files with provenance dots, integrated Terminal, Labels & Leases, immutable Audit log, Pull Requests.
- Human-in-the-loop permission cards; Plan→Act mode switch is a **user-only** action that bundles one approval instead of dozens.
- Transport abstraction (`mock` | `websocket` | `webrtc`) — the UI never knows which backend it talks to.

## Getting Started

### Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Node.js | 20+ | Frontend |
| npm | 9+ | Frontend |
| Python | 3.11+ | Backend *(when it lands)* |
| Docker Desktop | latest | Sandbox / AI Computer |

<details>
<summary><strong>Windows note — enable WSL2 before Docker Desktop</strong></summary>

```powershell
# PowerShell (Administrator)
wsl --install --no-distribution
# reboot, then install Docker Desktop with "Use WSL 2 based engine" enabled
wsl -l -v        # must list docker-desktop with VERSION 2
```
</details>

### Run the Workspace (Frontend)

```powershell
cd frontend
npm.cmd install
npm.cmd run dev          # → http://localhost:3100
```

Validation gates (all should pass):

```powershell
npm.cmd run typecheck    # TypeScript: 0 errors
npm.cmd run test         # vitest unit suite
npm.cmd run lint         # ESLint
```

By default the frontend runs against the built-in **mock transport** — an 8-step scripted security scenario (tainted fetch → permission card → lease invalidation). No backend required.

### Build the AI Computer (Sandbox)

The sandbox is a blank Ubuntu 24.04 machine provisioned entirely from code — nothing is installed by hand:

```powershell
cd deploy/docker
docker compose build     # first run pulls Ubuntu + Chromium + code-server (~5–15 min)
docker compose up -d
```

What gets baked into the image (and what deliberately does not):

| Baked in — agent's own body | Deliberately absent — agent installs on demand |
|---|---|
| Chromium via **Playwright 1.49.0** (pinned) | Node.js, language SDKs, frameworks |
| Xvfb virtual display + x11vnc (screen sharing) | Any API keys or credentials (rule ⑤) |
| code-server (VS Code in browser) | `sudo` for the runtime user |
| git, curl, base shell tools | Root access — runs as non-root `agent` (rule ⑥) |

### Verify with the Smoke Test

```bash
bash smoke-test.sh       # run from Git Bash / WSL / any real bash
```

Expected result: **9 PASS / 0 FAIL**, proving each design rule with evidence:

| Check | Proves |
|---|---|
| Container up · non-root `agent` | rule ⑥ hardening |
| Xvfb alive · VNC :5900 listening · code-server :8080 | screen + editor furniture (§7.5) |
| Playwright 1.49.0 + `chromium-1148` present | pinned, reproducible tooling (§13.6) |
| `curl` **fails** out of the box | rule ②a — network ships OFF |
| toggle ON → `curl` succeeds → toggle OFF → sealed again | rule ②b — your network switch works |

### Using the Box

| Access point | URL / address |
|---|---|
| VS Code web (inside the box) | <http://localhost:8080> |
| Box screen via any VNC Viewer | `localhost:5900` |
| Shell into the box | `docker exec -it agentbox-box bash` |

### Network Toggle

The box ships with its data-plane network **off** (§7.4.1). Research-style reads go through the host-side `fetch_url` tool regardless; raw operations (package installs, `git clone`, interactive browsing) need the toggle:

```bash
# ON  — attach the internet network to the box
docker network connect agentbox_internet agentbox-box

# OFF — detach it (takes effect immediately, no restart)
docker network disconnect agentbox_internet agentbox-box
```

Every toggle transition belongs in the audit ledger (`actor: user`). When network is on, content fetched by raw commands is labeled untrusted by default. A domain allow-list proxy is planned as a post-thesis upgrade (plan §XV).

## Repository Structure

```
.
├── backend/       FastAPI + Python — agent core, security gateway, sandbox driver
├── frontend/      React 19 + TypeScript + Vite + Tailwind CSS v4 — workspace UI
├── benchmark/     Evaluation suites & attack corpora (AgentDojo, VPI-Bench, T1–T7)
├── deploy/
│   └── docker/    Sandbox image: Dockerfile · compose · entrypoint · smoke-test
├── docs/          Architecture specification, threat model, research briefs
└── scripts/       Development utilities
```

## Documentation

- **[Full Architectural & Security Plan](docs/plan/agent-box-plan.md)** — complete 16-section specification.
- **[Plan Summary](docs/plan/agent-box-plan-summary.md)** — executive overview, effort budget, decision gates.
- **[Research & Threat Analysis](docs/research/)** — market evidence and computer-use security research.

---

<div align="center">
<sub>Built as a graduation thesis project. Local-first by design — your keys, your data, your machine.</sub>
</div>
