---
name: research-team
description: Coordinate question-driven research with source evidence, independent review and durable checkpoints.
version: 2.0.0
---
# Research team

Main owns the decision, branch plan, synthesis, dossier and final answer. Research children read public sources and user-provided material, add source rows, and report results and inaccessible pages. Research children cannot write files or dossiers. Review children read the dossier, ledger and public web independently; they cannot add source rows or edit the dossier. Tool rights shown in `roles.py` and `tool_contracts.py` are authoritative.

## Start

Apply `research-scoping` and choose a tier appropriate to the decision. Call `research_brief` with goal, questions, methods, output, budgetSeconds and a reason for the tier. A task may mix papers, repositories, official documents, product evidence and public community signals. The legacy `jobProfile` is an extraction template, not the research strategy; omit it for a mixed v2 job, which receives the neutral `mixed` profile. Give each branch a bounded question, scope, likely source channels, evidence to return, stopping condition and time. Spawn by problem, not by site. Start with up to three concurrent branches.

## Read and checkpoint

Research children use `research-search`, `research-reading` and `research-evidence`. They must report findings that oppose the working hypothesis, searches that found nothing useful and sources that could not be opened. Main calls `research_update` after results to maintain each question's state, important findings and blocked sources. `source_verify` checks the passage's presence only; a matching passage can contradict the row claim. Keep the ledger row id next to each decisive conclusion.

## Synthesize and challenge

Apply `research-synthesis` to compare options under fixed criteria. Write a dossier even when incomplete; the new job keeps it as a draft with missing gate findings. Follow `job.reviewModes` returned by `research_brief`: a consequential decision with several high importance questions requires independent evidence and critique reviews even when its time budget fits tier 2. Call `delegate_task(role="research-review")` with `reviewTarget={kind:"research",researchId,version,mode:"evidence"}` and separately with `mode:"critique"` when both are listed, or with `mode:"coverage"` when a high-impact direction of the map is still unexplored. Each reviewer must use `file_read` through all slices of the bound path. Record each result with `research_verify` and its matching mode. Main neither supplies its own verdict nor treats a previous version's verdict as current.

Turn each serious reviewer finding into a specific follow-up question and evidence condition. Repeat only if the answer can plausibly change the choice; after two unproductive continuations, switch source strategy or report a conditional result. Stop when decision-critical questions are answered or explicitly unknown with impact, pivotal claims are grounded, and serious evidence, reasoning and plan issues are resolved. Never fabricate a counterexample just to fill a template.

## Plan and final answer

Use `research-to-plan` if the requested output is a plan. Explain the chosen option, alternatives, tradeoffs, unresolved disputes, source and access limits, and what would change the recommendation. Report the saved dossier's actual state from `research_status`. A draft or exhausted job must be labelled partial with a `stopReason` saying what is missing; it is not a verified conclusion.
