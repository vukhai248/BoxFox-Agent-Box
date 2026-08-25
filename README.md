# BoxFox Agent Box

> **Self-Hosted AI Computer & Secure Autonomous Agent Environment**  
> An enterprise-grade, local-first AI Computer providing isolated sandbox execution, cryptographic Information Flow Control (IFC), and temporal capability leases for autonomous LLM agents.

---

## Overview

**BoxFox Agent Box** is an open-source, local-first platform designed to run autonomous AI agents safely on a dedicated virtual machine. The agent can inspect code, run terminal commands, and operate a browser within an isolated container boundary, strictly governed by a zero-trust security architecture:

- **Information Flow Control (IFC):** Every data chunk ingested into the context carries an immutable provenance tag determining its integrity floor and confidentiality ceiling.
- **Temporal Capability Leases:** Sensitive actions (file modifications, command executions, external network egress) require explicit, epoch-bound permissions granted *after* untrusted inputs enter the agent's context.
- **Hard Container Boundary:** Sandboxed execution via Docker containers with isolated browser frames (Playwright, Xvfb, WebRTC) and restricted network proxies.
- **Immutable Audit Ledger:** Append-only cryptographic security log recording all agent decisions, tool invocations, and human-in-the-loop approvals.

---

## 7-Layer Architecture

| Layer | Component | Description & Location |
|---|---|---|
| **L1** | **User Interface** | React 19 + TypeScript frontend with 8 workspace views (`frontend/`) |
| **L2** | **Controller** | State machine orchestrating task epochs, leases, and event dispatch (`backend/src/agentbox/controller/`) |
| **L3** | **Agent Core & Router** | Planning engine, tool execution loop, and model router (`backend/src/agentbox/agent_core/`) |
| **L4** | **Security Gateway** | Policy Engine, Label Store, Lease Store, Secret Manager, Audit Ledger (`backend/src/agentbox/security/`) |
| **L5** | **Tools & Skills** | Sandboxed tool suite with 4-tier risk classification (`backend/src/agentbox/tools/`) |
| **L6** | **Sandbox / AI Computer** | Isolated Docker container environment (`backend/src/agentbox/sandbox/`, `deploy/docker/`) |
| **L7** | **External World** | External networks and VCS providers accessed strictly via proxy gateways |

---

## 5 Core Security Principles

- **N1 — Single Enforcement Point:** All agent actions must pass through exactly one unified Security Gateway.
- **N2 — Untrusted LLM:** The LLM is strictly untrusted. The Controller and Security Gateway never delegate policy enforcement to the model.
- **N3 — External Capability Leases:** Capabilities are issued exclusively by the Controller; the LLM cannot self-grant or elevate permissions.
- **N4 — Physical Sandbox Boundary:** The container sandbox is a real hardware/virtual isolation boundary, not a soft prompt constraint.
- **N5 — Non-Degrading Provenance:** Tainted context never automatically self-cleans; only explicit human elevation on specific verified content can reset trust levels.

---

## Frontend Architecture & Workspace

Built with **React 19**, **TypeScript**, **Vite**, **Tailwind CSS v4**, and **Zustand**:

- **Dual-Pane Workspace:** Split-view layout pairing natural language agent interaction with an interactive multi-tab workspace panel.
- **Live Sandbox & Container Inspection:** Visual container stream, interactive terminal, source tree with diff viewer, and pull request workflows.
- **Security & Governance Panels:** Human-in-the-loop permission approvals, Information Flow Control (IFC) label inspection, and audit logs.
- **Settings & Administration:** Multi-provider LLM routing, recurring scheduled tasks, webhook automations, and sandbox environment secrets.

---

## Repository Structure

```
.
├── backend/       FastAPI + Python — Agent core, security gateway, sandbox driver
├── frontend/      React 19 + TypeScript + Vite + Tailwind CSS v4 — Workspace & settings UI
├── benchmark/     Empirical evaluation suite & attack test cases (AgentDojo, VPI-Bench)
├── deploy/        Docker compose, sandbox container definitions, and deployment scripts
├── docs/          Architecture specifications, threat models, and security design plans
└── scripts/       Development utilities and automation scripts
```

---

## Quickstart Guide

### Prerequisites
- **Node.js** 20+ & `npm`
- **Python** 3.11+ (Conda environment `DL` recommended)
- **Docker** & Docker Compose

### 1. Frontend Setup
```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```
Access the application at `http://localhost:3100/`.

### 2. Frontend Validation & Testing
```powershell
npm.cmd run typecheck   # TypeScript validation (0 errors)
npm.cmd run test        # Unit test suite (vitest)
npm.cmd run lint        # Code style & ESLint
```

---

## Documentation

- **[Full Architectural & Security Plan](docs/plan/agent-box-plan.md)** — Complete 16-section design specification.
- **[Plan Summary](docs/plan/agent-box-plan-summary.md)** — Executive overview of architecture and core decisions.
- **[Research & Threat Analysis](docs/research/)** — Market evidence and computer use security research.
