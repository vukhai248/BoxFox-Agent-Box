---
name: planning
description: "Root-owned Plan workflow: ground intent, interview, confirm brief, design, critique, approve and separately execute."
version: 2.0.0
license: MIT
platforms: [linux, macos, windows]
---

# Planning a decision-complete implementation

Invariant: without a critique you cannot request approval.

When ACTIVE MODE: PLAN is present this procedure is mandatory, even if skills were disabled.
Use BoxFox tools only. Child specialists return evidence, proposed designs and missing questions;
the main session owns interview, brief and the official document.

1. Read goal, attachments and relevant code before asking. Classify a bounded code task, software
system or AI system. Distinguish observed existing components from proposed components. Old plans
are evidence to inspect, not automatically requirements to inherit.
2. Call plan_scope status, then update brief with source per field (goal/users/workflow/scope/data/
constraints/success). Exact user quotes, observed paths/URLs actually read, or proposed choices with
reasons and alternatives. Never promote a proposal to user-confirmed. Important unknowns are blocking
decisions; do not hide them in an assumptions section and continue writing.
3. Ask 1–3 consequential questions with plan_scope ask. Include options/tradeoffs when helpful,
always permit free text, and accept 'recommend'. End the compute turn and wait for durable answers.
Do not ask code facts you can read. A fully specified small task does not need an interview.
For a medical synthesis app first establish user/job, inputs and permission to use real data,
prototype vs production and operating constraints. Do not select offline/cloud/OCR/RAG by guessing.
4. Research alternatives and recommend technology. Explain cost/data consequences in a concise brief.
For software/AI call plan_scope confirm and wait for the user's confirmation before drafting.
5. write_plan requires runId, briefRevision and traceability covering requirement -> decision ->
milestone -> acceptance. The requirement IDs are brief field keys, plus any explicitly modeled
requirements. Each milestone specifies dependencies, concrete changes, deliverables and meaningful
checks. Describe product, existing state/evidence, stack/architecture/alternatives, data/schema/
lifecycle/errors/migrations, component/API contracts/errors/auth/async, deployment/config/secrets/
observability/retries/idempotency/backup/rollback. Explain any inapplicable part; bounded tasks can
combine sections. Existing paths must really exist; label new paths 'planned'. Never claim tests ran.
6. AI plans must justify AI vs a simple baseline, choose/evaluate models, define grounding and any
OCR/retrieval, fallback/abstention/human review, latency and cost. Define evaluation dataset, unit,
annotation/scoring method, baseline and calibrated thresholds. Unmeasured thresholds are proposed
targets requiring calibration. Evaluate correctness, omissions, unsupported claims and insufficient
evidence separately. Citation presence alone does not prove a synthesized claim is correct.
7. Delegate plan-review on the exact written path with reviewTarget. Reviewer receives original goal,
answers, brief, evidence and snapshot. Require every SWE-AI/1 dimension with evidence, blocking
findings and PLAN_REVIEW_JSON before a final VERDICT: ok or revise. Record with plan_verify.
P1–P8 scores are structural/proxy checks, not semantic SWE/AI quality. Missing/provider-failed critique
means unevaluated; one provider retry in budget. Repair at most two rounds per batch; otherwise save
blocked checkpoint and report exact findings. Changed decisions/hash invalidate old conclusions.
8. Only a ready plan may request approval. Approval stores acceptance only. Implementation needs
the separate Execute action and exact approved version/hash; never delegate Build after approval.

Write in the user's language. Vietnamese must have accents even with misspelled input. Preserve code,
identifiers, paths and verbatim quotes. Put the full technical plan in the document and summarize in
chat. Stop with an honest saved checkpoint on budget exhaustion.

Outside Plan mode, preserve legacy write_plan -> independent plan-review -> plan_verify gates.
For a substantive new planning request open Plan rather than inventing an unconfirmed architecture.
