"""Chạy bài test, tổng hợp kết quả, ghi báo cáo."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .case import Case
from .client import LlmClient, GenerationOutcome
from .grader import Assertion, grade

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"


@dataclass
class Attempt:
    index: int
    passed: bool
    model: str | None
    latency_ms: int
    error: str | None
    assertions: list[dict[str, Any]]
    response: Any | None


@dataclass
class CaseResult:
    id: str
    title: str
    category: str
    why: str
    status: str  # PASS | FAIL | ERROR
    pass_ratio: float
    required_ratio: float
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def first_failure(self) -> str | None:
        for attempt in self.attempts:
            if attempt.error:
                return attempt.error
            failed = [a for a in attempt.assertions if not a["passed"]]
            if failed:
                first = failed[0]
                return f"{first['kind']}({first['path']}): {first['detail']}"
        return None


def run_case(case: Case, client: LlmClient) -> CaseResult:
    system_instruction = case.system_instruction()
    turns = case.rendered_turns()

    attempts: list[Attempt] = []
    for index in range(1, case.repeat + 1):
        outcome: GenerationOutcome = client.generate(
            system_instruction=system_instruction,
            turns=turns,
            response_schema=case.response_schema,
        )
        if not outcome.ok:
            attempts.append(
                Attempt(
                    index=index,
                    passed=False,
                    model=outcome.model,
                    latency_ms=outcome.latency_ms,
                    error=outcome.error,
                    assertions=[],
                    response=None,
                )
            )
            continue

        assertions: list[Assertion] = grade(outcome.parsed, case.expect)
        attempts.append(
            Attempt(
                index=index,
                passed=all(a.passed for a in assertions),
                model=outcome.model,
                latency_ms=outcome.latency_ms,
                error=None,
                assertions=[asdict(a) for a in assertions],
                response=outcome.parsed,
            )
        )

    errored = [a for a in attempts if a.error]
    passed = [a for a in attempts if a.passed]
    ratio = len(passed) / len(attempts) if attempts else 0.0

    if len(errored) == len(attempts):
        status = "ERROR"  # không gọi được model lần nào — không phải PASS, không phải FAIL
    elif ratio >= case.min_pass_ratio:
        status = "PASS"
    else:
        status = "FAIL"

    return CaseResult(
        id=case.id,
        title=case.title,
        category=case.category,
        why=case.why,
        status=status,
        pass_ratio=ratio,
        required_ratio=case.min_pass_ratio,
        attempts=attempts,
    )


def run_all(cases: Iterable[Case], client: LlmClient, *, on_result=None) -> list[CaseResult]:
    results = []
    for case in cases:
        result = run_case(case, client)
        results.append(result)
        if on_result:
            on_result(result)
    return results


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    by_category: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = by_category.setdefault(result.category, {"PASS": 0, "FAIL": 0, "ERROR": 0})
        bucket[result.status] += 1
    return {
        "total": len(results),
        "pass": sum(1 for r in results if r.status == "PASS"),
        "fail": sum(1 for r in results if r.status == "FAIL"),
        "error": sum(1 for r in results if r.status == "ERROR"),
        "by_category": by_category,
    }


def write_report(results: list[CaseResult], *, models: tuple[str, ...], label: str = "") -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = f"{stamp}{'-' + label if label else ''}"
    json_path = REPORT_DIR / f"{slug}.json"
    md_path = REPORT_DIR / f"{slug}.md"

    stats = summarize(results)
    json_path.write_text(
        json.dumps(
            {
                "generated_at": stamp,
                "models": list(models),
                "summary": stats,
                "results": [asdict(r) for r in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "# Báo cáo test LLM — BoxFox Agent Box",
        "",
        f"- Thời điểm: `{stamp}`",
        f"- Dây model: `{' → '.join(models)}`",
        f"- Kết quả: **{stats['pass']} PASS · {stats['fail']} FAIL · {stats['error']} ERROR** "
        f"trên {stats['total']} bài",
        "",
        "## Theo mục",
        "",
        "| Mục | PASS | FAIL | ERROR |",
        "|---|---|---|---|",
    ]
    for category in sorted(stats["by_category"]):
        bucket = stats["by_category"][category]
        lines.append(f"| `{category}` | {bucket['PASS']} | {bucket['FAIL']} | {bucket['ERROR']} |")

    lines += ["", "## Từng bài", "", "| Bài | Trạng thái | Tỉ lệ đậu | Ghi chú |", "|---|---|---|---|"]
    for result in results:
        note = result.first_failure or result.title
        note = note.replace("|", "\\|")[:160]
        lines.append(
            f"| `{result.id}` | **{result.status}** | "
            f"{result.pass_ratio:.0%} (cần {result.required_ratio:.0%}) | {note} |"
        )

    failing = [r for r in results if r.status != "PASS"]
    if failing:
        lines += ["", "## Chi tiết bài không đậu", ""]
        for result in failing:
            lines += [f"### `{result.id}` — {result.title}", "", f"*Vì sao có bài này:* {result.why}", ""]
            for attempt in result.attempts:
                if attempt.error:
                    lines.append(f"- Lần {attempt.index}: LỖI GỌI MODEL — {attempt.error}")
                    continue
                for assertion in attempt.assertions:
                    if not assertion["passed"]:
                        lines.append(
                            f"- Lần {attempt.index} ({attempt.model}): "
                            f"`{assertion['kind']}` tại `{assertion['path']}` — {assertion['detail']}"
                        )
            first_response = next((a.response for a in result.attempts if a.response is not None), None)
            if first_response is not None:
                lines += [
                    "",
                    "<details><summary>Câu trả lời lần đầu</summary>",
                    "",
                    "```json",
                    json.dumps(first_response, ensure_ascii=False, indent=2),
                    "```",
                    "",
                    "</details>",
                    "",
                ]

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path
