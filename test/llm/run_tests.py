#!/usr/bin/env python3
"""Chạy bộ test LLM.

    export GEMINI_API_KEY=...
    python3 test/llm/run_tests.py                       # chạy tất cả
    python3 test/llm/run_tests.py --category 04-injection
    python3 test/llm/run_tests.py --case INJ-01 --repeat 5
    python3 test/llm/run_tests.py --dry-run             # không gọi API, chỉ kiểm file bài test

`--dry-run` chạy được KHÔNG cần khoá: nó nạp và kiểm tra hình dạng mọi file bài
test, mọi hợp đồng, mọi fixture. Dùng nó trong CI để bắt lỗi gõ sai — bài test
gõ sai tên trường sẽ âm thầm luôn đậu, đó là kiểu hỏng tệ nhất của một bộ test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness.case import CaseError, discover_cases  # noqa: E402
from _harness.client import LlmClient, MissingApiKey  # noqa: E402
from _harness.runner import run_all, summarize, write_report  # noqa: E402

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
BADGE = {"PASS": f"{GREEN}PASS{RESET}", "FAIL": f"{RED}FAIL{RESET}", "ERROR": f"{YELLOW}ERROR{RESET}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Bộ test phản hồi LLM cho BoxFox.")
    parser.add_argument("--category", help="Chỉ chạy một mục, ví dụ 04-injection.")
    parser.add_argument("--case", dest="case_id", help="Chỉ chạy một bài theo id.")
    parser.add_argument("--repeat", type=int, help="Ghi đè số lần lặp của mọi bài.")
    parser.add_argument("--model", action="append", help="Ghi đè dây model (lặp lại cờ để xếp thứ tự).")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--search", action="store_true", help="Bật grounding Google Search (cần quota).")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ kiểm file bài test, không gọi API.")
    parser.add_argument("--label", default="", help="Hậu tố tên file báo cáo.")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()

    try:
        cases = discover_cases(args.category, args.case_id)
    except CaseError as error:
        print(f"{RED}File bài test sai:{RESET} {error}", file=sys.stderr)
        return 2

    if not cases:
        print("Không có bài nào khớp bộ lọc.", file=sys.stderr)
        return 2

    if args.repeat:
        for case in cases:
            case.repeat = args.repeat

    if args.dry_run:
        problems = 0
        for case in cases:
            try:
                case.system_instruction()
                case.rendered_turns()
                if case.response_schema is not None and case.response_schema.get("type") not in ("OBJECT", "object"):
                    raise CaseError(f"{case.path}: response_schema gốc phải là OBJECT")
                print(f"  ok   {case.category}/{case.id} — {case.title}")
            except CaseError as error:
                problems += 1
                print(f"{RED}  sai  {case.id}: {error}{RESET}")
        print(f"\nĐã kiểm {len(cases)} bài, {problems} sai.")
        return 1 if problems else 0

    try:
        client = LlmClient(
            models=args.model,
            temperature=args.temperature,
            enable_search=args.search,
        )
    except MissingApiKey as error:
        print(f"{RED}{error}{RESET}", file=sys.stderr)
        return 2

    print(f"Chạy {len(cases)} bài · dây model {' → '.join(client.models)}\n")

    def report_line(result) -> None:
        detail = result.first_failure or ""
        suffix = f" {DIM}{detail[:110]}{RESET}" if result.status != "PASS" else ""
        print(
            f"  {BADGE[result.status]}  {result.category}/{result.id} "
            f"({result.pass_ratio:.0%}) {result.title}{suffix}"
        )

    results = run_all(cases, client, on_result=report_line)
    stats = summarize(results)

    print(
        f"\n{stats['pass']} PASS · {stats['fail']} FAIL · {stats['error']} ERROR "
        f"trên {stats['total']} bài"
    )
    if stats["error"]:
        print(f"{YELLOW}ERROR = không gọi được model (thường là 429 hết quota), không phải model trả lời sai.{RESET}")

    if not args.no_report:
        md_path, json_path = write_report(results, models=client.models, label=args.label)
        print(f"Báo cáo: {md_path}\n         {json_path}")

    return 0 if stats["fail"] == 0 and stats["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
