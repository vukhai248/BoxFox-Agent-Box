"""Lớp mỏng bọc google-genai: dây model dự phòng, lùi-rồi-thử-lại, trả JSON.

Chỉ chỗ này được biết SDK. Mọi phần còn lại của bộ khung làm việc với
`GenerationOutcome`, nên đổi nhà cung cấp model về sau chỉ sửa một file.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from google import genai
from google.genai import types

# SDK cảnh báo về automatic function calling ở mọi lần stream, kể cả khi không
# khai tool nào. Nhiễu, không phải lỗi.
logging.getLogger("google_genai").setLevel(logging.ERROR)
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

#: Thử lần lượt. Model đầu hết quota (429) thì tụt xuống model sau — đúng yêu
#: cầu "nếu 3.5 flash lite bị limit thì đổi qua 3.1 flash lite".
DEFAULT_MODEL_CHAIN: tuple[str, ...] = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")

#: Mã lỗi đáng thử lại. 429 = hết quota, 503 = model đang quá tải, 500 = lỗi
#: nội bộ nhất thời. 400/403 KHÔNG thử lại: sai đầu vào hoặc sai khoá, thử lại
#: chỉ đốt thêm quota.
RETRYABLE_STATUSES = (429, 500, 502, 503, 504)

MAX_ATTEMPTS_PER_MODEL = 3
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 20.0


class MissingApiKey(RuntimeError):
    """Không tìm thấy khoá — nói rõ phải làm gì, đừng để traceback trơ trọi."""


@dataclass
class GenerationOutcome:
    """Kết quả một lần sinh, đủ để chấm điểm và để dựng lại khi cần điều tra."""

    ok: bool
    model: str | None
    raw_text: str
    parsed: Any | None
    attempts: int
    latency_ms: int
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def parsed_or_empty(self) -> dict[str, Any]:
        return self.parsed if isinstance(self.parsed, dict) else {}


def resolve_api_key(explicit: str | None = None) -> str:
    """Khoá lấy từ tham số → `GEMINI_API_KEY` → `GOOGLE_API_KEY`.

    Không bao giờ đọc khoá từ file trong repo: `.gitignore` chặn `.env` nhưng
    chặn được file thì không chặn được thói quen, nên đường duy nhất là biến
    môi trường.
    """
    key = explicit or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise MissingApiKey(
            "Thiếu khoá API. Làm một trong hai:\n"
            "  export GEMINI_API_KEY=...\n"
            "  cp test/.env.example test/.env && set -a && . test/.env && set +a"
        )
    return key


def _status_code(error: Exception) -> int | None:
    for attribute in ("code", "status_code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value
    text = str(error)
    for status in RETRYABLE_STATUSES + (400, 401, 403, 404):
        if str(status) in text[:64]:
            return status
    return None


def _sleep_backoff(attempt: int) -> None:
    delay = min(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), BACKOFF_MAX_SECONDS)
    # Nhiễu ±25% để nhiều bài chạy song song không cùng lúc đập lại API.
    time.sleep(delay * random.uniform(0.75, 1.25))


class LlmClient:
    """Gọi model, buộc trả JSON theo schema, tự xoay model khi hết quota."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        models: Sequence[str] | None = None,
        temperature: float = 0.0,
        thinking_level: str | None = "MINIMAL",
        enable_search: bool = False,
    ) -> None:
        self._client = genai.Client(api_key=resolve_api_key(api_key))
        self.models = tuple(models) if models else DEFAULT_MODEL_CHAIN
        self.temperature = temperature
        self.thinking_level = thinking_level
        self.enable_search = enable_search

    def _config(
        self, *, system_instruction: str, response_schema: dict[str, Any] | None
    ) -> types.GenerateContentConfig:
        kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": self.temperature,
        }
        if self.thinking_level:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=self.thinking_level)
        if self.enable_search:
            # Chỉ bật khi được yêu cầu tường minh: khoá free tier trả 429 ngay.
            kwargs["tools"] = [types.Tool(googleSearch=types.GoogleSearch())]
        if response_schema is not None:
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_schema"] = response_schema
        return types.GenerateContentConfig(**kwargs)

    def generate(
        self,
        *,
        system_instruction: str,
        turns: Sequence[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> GenerationOutcome:
        contents = [
            types.Content(
                role="model" if turn.get("role") == "model" else "user",
                parts=[types.Part.from_text(text=turn["text"])],
            )
            for turn in turns
        ]
        config = self._config(system_instruction=system_instruction, response_schema=response_schema)

        started = time.monotonic()
        attempts = 0
        last_error: Exception | None = None

        for model in self.models:
            for attempt in range(1, MAX_ATTEMPTS_PER_MODEL + 1):
                attempts += 1
                try:
                    response = self._client.models.generate_content(
                        model=model, contents=contents, config=config
                    )
                except Exception as error:  # noqa: BLE001 — phân loại ngay bên dưới
                    last_error = error
                    status = _status_code(error)
                    if status not in RETRYABLE_STATUSES:
                        # Lỗi cứng: bỏ model này, sang model kế tiếp ngay.
                        break
                    if attempt < MAX_ATTEMPTS_PER_MODEL:
                        _sleep_backoff(attempt)
                    continue

                raw = (response.text or "").strip()
                parsed, parse_error = _parse_json(raw) if response_schema is not None else (raw, None)
                latency_ms = int((time.monotonic() - started) * 1000)
                if parse_error:
                    return GenerationOutcome(
                        ok=False,
                        model=model,
                        raw_text=raw,
                        parsed=None,
                        attempts=attempts,
                        latency_ms=latency_ms,
                        error=f"JSON không đọc được: {parse_error}",
                        usage=_usage(response),
                    )
                return GenerationOutcome(
                    ok=True,
                    model=model,
                    raw_text=raw,
                    parsed=parsed,
                    attempts=attempts,
                    latency_ms=latency_ms,
                    usage=_usage(response),
                )

        return GenerationOutcome(
            ok=False,
            model=None,
            raw_text="",
            parsed=None,
            attempts=attempts,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"Mọi model thất bại: {type(last_error).__name__}: {str(last_error)[:300]}",
        )


def _parse_json(raw: str) -> tuple[Any | None, str | None]:
    """Đọc JSON, chịu được rào ```json mà model đôi khi thêm vào."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -3]
    try:
        return json.loads(text), None
    except json.JSONDecodeError as error:
        return None, f"{error.msg} (dòng {error.lineno}, cột {error.colno})"


def _usage(response: Any) -> dict[str, int]:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {}
    return {
        key: int(value)
        for key, value in (
            ("prompt", getattr(meta, "prompt_token_count", None)),
            ("output", getattr(meta, "candidates_token_count", None)),
            ("total", getattr(meta, "total_token_count", None)),
        )
        if isinstance(value, int)
    }
