#!/usr/bin/env python3
"""Gọi thử Gemini — bản chạy được của đoạn mã Google AI Studio sinh ra.

Đây là bài kiểm tra khói (smoke test) nhỏ nhất: chứng minh khoá API hợp lệ,
mạng đi được, và model trả về chữ. Không kiểm tra chất lượng câu trả lời —
việc đó thuộc `run_tests.py`.

    pip install google-genai
    export GEMINI_API_KEY=...            # xem test/.env.example
    python3 test/llm/generate_basic.py "Câu hỏi của bạn"

BỐN CHỖ ĐÃ SỬA so với đoạn mã AI Studio dán ra, và lý do:

1. `tools=[Tool(googleSearch=...)]` bị BỎ khỏi mặc định. Trên khoá free tier,
   grounding bằng Google Search trả `429 RESOURCE_EXHAUSTED` ngay từ lần gọi
   đầu, trong khi cùng khoá đó gọi model thường vẫn 200. Bật lại bằng
   `--search` nếu khoá của bạn có quota.
2. `audio_transcription_config` giữ lại nhưng chỉ bật khi `--audio`: nó vô
   nghĩa với đầu vào chỉ có chữ (đã kiểm: không lỗi, nhưng cũng không tác dụng).
3. Có DÂY MODEL DỰ PHÒNG. `gemini-3.5-flash-lite` hết quota thì tự tụt xuống
   `gemini-3.1-flash-lite` thay vì ném lỗi — đúng yêu cầu "nếu bị limit có thể
   đổi qua 3.1 flash lite".
4. Khoá đọc từ biến môi trường `GEMINI_API_KEY`, KHÔNG viết thẳng vào file.
   `.gitignore` của repo đã chặn `.env`; đừng đưa khoá vào mã nguồn.
"""

from __future__ import annotations

import argparse
import os
import sys

from google import genai
from google.genai import types

# Thứ tự thử: hết quota model đầu thì tụt xuống model sau.
MODEL_CHAIN = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")


def build_config(*, search: bool, audio: bool) -> types.GenerateContentConfig:
    tools = [types.Tool(googleSearch=types.GoogleSearch())] if search else None
    return types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
        audio_transcription_config=types.AudioTranscriptionConfig() if audio else None,
        tools=tools,
    )


def generate(prompt: str, *, search: bool = False, audio: bool = False) -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(
            "Thiếu GEMINI_API_KEY. Xem test/.env.example rồi:\n"
            "  export GEMINI_API_KEY=...",
            file=sys.stderr,
        )
        return 2

    client = genai.Client(api_key=api_key)
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
    config = build_config(search=search, audio=audio)

    last_error: Exception | None = None
    for model in MODEL_CHAIN:
        try:
            print(f"[model={model}]", file=sys.stderr)
            for chunk in client.models.generate_content_stream(
                model=model, contents=contents, config=config
            ):
                if text := chunk.text:
                    print(text, end="", flush=True)
            print()
            return 0
        except Exception as error:  # noqa: BLE001 — muốn thử model kế tiếp với mọi lỗi
            last_error = error
            print(f"\n[{model} thất bại: {type(error).__name__}] thử model kế tiếp", file=sys.stderr)

    print(f"Mọi model đều thất bại. Lỗi cuối: {last_error!r}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Gọi thử Gemini một lần.")
    parser.add_argument(
        "prompt",
        nargs="?",
        default="Trả lời ngắn: bạn là model nào và đang ở phiên bản nào?",
    )
    parser.add_argument("--search", action="store_true", help="Bật grounding Google Search (cần quota).")
    parser.add_argument("--audio", action="store_true", help="Bật audio_transcription_config.")
    args = parser.parse_args()
    return generate(args.prompt, search=args.search, audio=args.audio)


if __name__ == "__main__":
    raise SystemExit(main())
