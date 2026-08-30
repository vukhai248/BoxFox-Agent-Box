"""Đọc và kiểm tra file bài test.

Một bài test là một file JSON trong `cases/<mục>/`. Loader này cố ý KHẮT KHE:
file bài test sai hình dạng làm cả bộ mất giá trị, nên nó ném lỗi ngay lúc nạp
thay vì để bài đó âm thầm luôn đậu.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LLM_DIR = Path(__file__).resolve().parent.parent
CONTRACT_DIR = LLM_DIR / "contract"
FIXTURE_DIR = LLM_DIR / "fixtures"
CASES_DIR = LLM_DIR / "cases"

REQUIRED_KEYS = ("id", "title", "why", "contracts", "turns", "expect")
ALLOWED_KEYS = REQUIRED_KEYS + (
    "fixtures",
    "response_schema",
    "repeat",
    "min_pass_ratio",
    "tags",
    "temperature",
)


class CaseError(ValueError):
    """Bài test sai hình dạng — nêu rõ file nào, thiếu gì."""


@dataclass
class Case:
    id: str
    title: str
    why: str
    category: str
    path: Path
    contracts: list[str]
    turns: list[dict[str, str]]
    expect: list[dict[str, Any]]
    fixtures: list[str] = field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    repeat: int = 1
    min_pass_ratio: float = 1.0
    tags: list[str] = field(default_factory=list)
    temperature: float | None = None

    def system_instruction(self) -> str:
        """Ghép các file hợp đồng thành system prompt, đúng thứ tự đã khai."""
        blocks = []
        for name in self.contracts:
            path = CONTRACT_DIR / name
            if not path.is_file():
                raise CaseError(f"{self.path}: không có file hợp đồng {name}")
            blocks.append(path.read_text(encoding="utf-8").strip())
        return "\n\n---\n\n".join(blocks)

    def rendered_turns(self) -> list[dict[str, str]]:
        """Thay `{{fixture:tên}}` bằng nội dung fixture, dạng khối dữ liệu có nhãn.

        Fixture LUÔN được bọc trong khối phân giới rõ ràng kèm dòng nhãn, đúng
        như `formatInspectedElementForAgent()` phía giao diện làm. Bài test phải
        thử đúng thứ hệ thống thật đưa vào model, không phải một biến thể dễ hơn.
        """
        rendered = []
        for turn in self.turns:
            text = turn["text"]
            for name in self.fixtures:
                token = "{{fixture:" + name + "}}"
                if token in text:
                    text = text.replace(token, _render_fixture(name))
            if "{{fixture:" in text:
                raise CaseError(f"{self.path}: còn fixture chưa thay: {text[:80]!r}")
            rendered.append({"role": turn.get("role", "user"), "text": text})
        return rendered


def _render_fixture(name: str) -> str:
    path = FIXTURE_DIR / name
    if not path.is_file():
        raise CaseError(f"Không có fixture {name} trong {FIXTURE_DIR}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    label = payload.get("label", {})
    header = (
        f"integrity={label.get('integrity', 'khong_tin_duoc')} "
        f"confidentiality={label.get('confidentiality', 'noi_bo')} "
        f"source_kind={label.get('source_kind', 'screen_capture')} "
        f"tool_name={label.get('tool_name', 'inspect_element')}"
    )
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "<<<DU_LIEU_KHONG_TIN_DUOC "
        + header
        + ">>>\n"
        + body
        + "\n<<<HET_DU_LIEU_KHONG_TIN_DUOC>>>"
    )


def load_case(path: Path) -> Case:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CaseError(f"{path}: JSON sai — {error}") from error
    if not isinstance(payload, dict):
        raise CaseError(f"{path}: gốc file phải là object")

    missing = [key for key in REQUIRED_KEYS if key not in payload]
    if missing:
        raise CaseError(f"{path}: thiếu khoá {missing}")
    unknown = [key for key in payload if key not in ALLOWED_KEYS]
    if unknown:
        raise CaseError(f"{path}: khoá lạ {unknown} (gõ sai tên là bài test tự vô hiệu)")
    if not payload["expect"]:
        raise CaseError(f"{path}: `expect` rỗng — bài test không khẳng định gì thì luôn đậu")
    if not payload["turns"]:
        raise CaseError(f"{path}: `turns` rỗng")

    repeat = int(payload.get("repeat", 1))
    if repeat < 1:
        raise CaseError(f"{path}: `repeat` phải ≥ 1")
    ratio = float(payload.get("min_pass_ratio", 1.0))
    if not 0 < ratio <= 1:
        raise CaseError(f"{path}: `min_pass_ratio` phải trong (0, 1]")

    return Case(
        id=payload["id"],
        title=payload["title"],
        why=payload["why"],
        category=path.parent.name,
        path=path,
        contracts=list(payload["contracts"]),
        turns=list(payload["turns"]),
        expect=list(payload["expect"]),
        fixtures=list(payload.get("fixtures", [])),
        response_schema=payload.get("response_schema"),
        repeat=repeat,
        min_pass_ratio=ratio,
        tags=list(payload.get("tags", [])),
        temperature=payload.get("temperature"),
    )


def discover_cases(category: str | None = None, case_id: str | None = None) -> list[Case]:
    cases = [load_case(path) for path in sorted(CASES_DIR.rglob("*.json"))]
    seen: dict[str, Path] = {}
    for case in cases:
        if case.id in seen:
            raise CaseError(f"Trùng id {case.id}: {seen[case.id]} và {case.path}")
        seen[case.id] = case.path
    if category:
        cases = [c for c in cases if c.category == category or c.category.endswith(category)]
    if case_id:
        cases = [c for c in cases if c.id == case_id]
    return cases
