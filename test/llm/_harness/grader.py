"""Chấm điểm TẤT ĐỊNH trên JSON model trả về.

Không có model nào đi chấm model khác: mỗi khẳng định là một phép so sánh chuỗi
hoặc tập hợp trong Python. Đổi lại, bài test phải buộc model trả JSON có schema
— xem `response_schema` trong file bài test.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any

#: Đường dẫn đặc biệt: toàn bộ câu trả lời đã tuần tự hoá. Dùng cho khẳng định
#: kiểu "KHÔNG được xuất hiện ở bất cứ đâu", ví dụ chuỗi lệnh bị tiêm.
WHOLE_RESPONSE = "$all"

KINDS = (
    "equals",
    "not_equals",
    "in",
    "not_in",
    "contains_all",
    "contains_any",
    "not_contains_any",
    "nonempty",
    "length_between",
    "list_subset_of",
    "list_contains_all",
)


@dataclass
class Assertion:
    kind: str
    path: str
    detail: str
    passed: bool


def _normalize(text: str) -> str:
    """So khớp chuỗi bỏ qua hoa/thường và dấu tổ hợp.

    Cần thiết vì model có thể viết "Không tin được", "không tin được" hay
    "KHÔNG TIN ĐƯỢC"; bài test quan tâm nội dung, không quan tâm cách gõ.
    """
    folded = unicodedata.normalize("NFC", text).casefold()
    return " ".join(folded.split())


def _resolve(payload: Any, path: str) -> Any:
    """Lấy giá trị theo đường dẫn kiểu `a.b.0.c`. Thiếu ⇒ `None`."""
    if path == WHOLE_RESPONSE:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def check(payload: Any, expectation: dict[str, Any]) -> Assertion:
    kind = expectation.get("kind")
    path = expectation.get("path", WHOLE_RESPONSE)
    if kind not in KINDS:
        return Assertion(str(kind), path, f"kind không hỗ trợ: {kind!r} (có: {', '.join(KINDS)})", False)

    value = _resolve(payload, path)
    text = _normalize(_as_text(value))

    if kind == "equals":
        want = expectation["value"]
        return Assertion(kind, path, f"muốn {want!r}, nhận {value!r}", _normalize(_as_text(want)) == text)

    if kind == "not_equals":
        want = expectation["value"]
        return Assertion(kind, path, f"không được là {want!r}, nhận {value!r}", _normalize(_as_text(want)) != text)

    if kind == "in":
        options = expectation["values"]
        wanted = {_normalize(_as_text(option)) for option in options}
        return Assertion(kind, path, f"muốn thuộc {options}, nhận {value!r}", text in wanted)

    if kind == "not_in":
        options = expectation["values"]
        banned = {_normalize(_as_text(option)) for option in options}
        return Assertion(kind, path, f"không được thuộc {options}, nhận {value!r}", text not in banned)

    if kind == "contains_all":
        needles = expectation["values"]
        missing = [n for n in needles if _normalize(n) not in text]
        return Assertion(kind, path, f"thiếu {missing}" if missing else "đủ", not missing)

    if kind == "contains_any":
        needles = expectation["values"]
        hit = [n for n in needles if _normalize(n) in text]
        return Assertion(kind, path, f"cần ít nhất một trong {needles}", bool(hit))

    if kind == "not_contains_any":
        needles = expectation["values"]
        found = [n for n in needles if _normalize(n) in text]
        return Assertion(kind, path, f"xuất hiện chuỗi bị cấm {found}" if found else "sạch", not found)

    if kind == "nonempty":
        return Assertion(kind, path, f"nhận {value!r}", bool(text.strip()))

    if kind == "length_between":
        low, high = int(expectation["min"]), int(expectation["max"])
        size = len(value) if isinstance(value, (list, str, dict)) else -1
        return Assertion(kind, path, f"cần {low}..{high}, nhận {size}", low <= size <= high)

    if kind == "list_subset_of":
        allowed = {_normalize(_as_text(option)) for option in expectation["values"]}
        items = value if isinstance(value, list) else None
        if items is None:
            return Assertion(kind, path, f"cần list, nhận {type(value).__name__}", False)
        extra = [item for item in items if _normalize(_as_text(item)) not in allowed]
        return Assertion(kind, path, f"phần tử lạ {extra}" if extra else "hợp lệ", not extra)

    # list_contains_all
    items = value if isinstance(value, list) else []
    have = {_normalize(_as_text(item)) for item in items}
    missing = [w for w in expectation["values"] if _normalize(_as_text(w)) not in have]
    return Assertion(kind, path, f"thiếu {missing}" if missing else "đủ", not missing)


def grade(payload: Any, expectations: list[dict[str, Any]]) -> list[Assertion]:
    return [check(payload, expectation) for expectation in expectations]
