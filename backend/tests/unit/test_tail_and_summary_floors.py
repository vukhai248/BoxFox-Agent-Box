"""Sàn phần đuôi theo token và sàn `max_tokens` của lượt tóm tắt (Phần D đợt 20).

Hai sàn này chữa hai ca đo được ngày 2026-09-21: (1) trên cửa sổ 32 768, `tail_budget` cũ chỉ
5 734 token nên sàn theo SỐ message (`MAX_TAIL_MESSAGE_FLOOR = 8`) có thể không lọt; (2) ba phiên
sống chết vì bản tóm tắt bị nhà cung cấp cắt ở trần `max_tokens` (935 541 / 992 249 / 732 528).
"""
import asyncio
import json
from pathlib import Path

from agentbox.agent_core import compression
from agentbox.agent_core.compression import (COMPACTION_BANNER, ContextCompressor, estimate_tokens,
                                             summary_max_tokens)
from agentbox.agent_core.limits import MAX_TAIL_TOKEN_FLOOR


def _call(index, pad=0):
    """Lời gọi công cụ có `pad`: phần đệm nằm ở CẢ tham số lẫn kết quả, đúng khuôn của
    `test_compression_port.py` — nếu chỉ đệm kết quả thì transcript nhẹ đi một nửa và các bài dưới
    đây không còn vượt ngưỡng của cửa sổ 40 000."""
    args = {'command': f'echo {index}' + 'c' * pad}
    return {'id': f'call_{index}', 'type': 'function',
            'function': {'name': 'terminal_exec', 'arguments': json.dumps(args)}}


def _turn(index, pad):
    return [{'role': 'assistant', 'content': None, 'tool_calls': [_call(index, pad)]},
            {'role': 'tool', 'tool_call_id': f'call_{index}', 'name': 'terminal_exec',
             'content': f'[{index}] ' + 'x' * pad}]


def _history(turns, pad):
    messages = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal'}]
    for index in range(turns):
        messages += _turn(index, pad)
    return messages


def _bulky_tail_history():
    """20 lượt cũ nhỏ + 4 lượt cuối nặng: phần đuôi được sàn giữ lại nằm sát ngưỡng của cửa sổ
    40 000, nên phép tỉa một mình không đủ — đúng ca cần tới lượt tóm tắt (khuôn của
    `test_compression_port.py`)."""
    return _history(20, 300) + sum((_turn(20 + index, 9000) for index in range(4)), [])


def _answer(text, finish='stop'):
    return {'choices': [{'message': {'content': text}, 'finish_reason': finish}]}


# ------------------------------------------------------------------ N7: sàn đuôi theo token

def test_the_tail_budget_on_a_small_window_is_lifted_to_the_token_floor():
    """Cửa sổ 32 768: 0,7 không phải là chuyện của đuôi — 20 % ngân sách = 5 734 token, mà sàn
    token đòi 8 000. Trần của sàn là 1/4 ngân sách nên con số mới là 7 168, vẫn dưới 25 %."""
    compressor = ContextCompressor(32_768)
    fraction = int(compressor.budget * compression.TAIL_MAX_CONTEXT_FRACTION)
    assert fraction == 5_734, 'con số cũ, dùng làm mốc so'
    assert compressor.tail_budget == min(MAX_TAIL_TOKEN_FLOOR, compressor.budget // 4) == 7_168
    assert compressor.tail_budget > fraction, 'sàn đã nâng ngân sách đuôi lên'
    assert compressor.tail_budget <= compressor.budget // 4, 'sàn không được ăn quá 1/4 ngân sách'


def test_a_large_window_keeps_its_capped_tail_budget():
    """Cửa sổ 1M: trần 25 000 token đã chặt hơn sàn, nên sàn không được HẠ nó xuống."""
    compressor = ContextCompressor(1_000_000)
    assert compressor.tail_budget == compression.TAIL_MAX_TOKENS == 25_000
    assert compressor.tail_budget > MAX_TAIL_TOKEN_FLOOR


def test_the_tail_floor_never_eats_the_summary_room_on_a_tiny_window():
    """Cửa sổ 8 192: sàn bị kẹp xuống 1/4 ngân sách, không đòi 8 000."""
    compressor = ContextCompressor(8_192)
    assert compressor.tail_budget == compressor.budget // 4 == 1_536
    assert compressor.tail_budget > int(compressor.budget * compression.TAIL_MAX_CONTEXT_FRACTION)


# ------------------------------------------------- N8: sàn `max_tokens` của lượt tóm tắt

def test_the_summary_floor_is_8192_and_the_cap_is_50000():
    # 2026-10-09 (phiên `72106f67`): tác vụ dài chết vì sàn 4096 là trần thật của mọi transcript
    # dưới ~205k token, mà model tóm tắt tiêu hết ngần ấy token vào phần suy luận rồi trả
    # `content: null`. Sàn 8192, tỉ lệ 10 %, trần 50 000.
    assert summary_max_tokens(10_000) == 8_192
    assert summary_max_tokens(200_000) == 20_000, 'tỉ lệ 10 % đã vượt sàn ở mức này'
    assert summary_max_tokens(400_000) == 40_000
    assert summary_max_tokens(10_000_000) == compression.SUMMARY_MAX_TOKENS_CAP == 50_000
    assert compression.SUMMARY_MAX_TOKENS_CAP < 64_000, 'trần `max_tokens` của router'


def test_a_summary_truncated_at_the_provider_cap_is_accepted_and_marked():
    """`finish_reason == 'length'` mà VẪN có chữ thì nhận, và bản ghi phải nói ra là đã bị cắt."""
    messages = _bulky_tail_history()
    compressor = ContextCompressor(40_000)
    assert estimate_tokens(messages) > compressor.threshold, 'bài này cần transcript quá ngưỡng'
    calls = []

    async def summarize(history, max_tokens=None):
        calls.append(max_tokens)
        return _answer('Goal: older turns. Evidence: tool results.', finish='length')

    result, event = asyncio.run(compressor.compact(messages, [], summarize))
    assert event['kind'] == 'summary', event
    assert event['summaryTruncated'] is True
    assert result is not messages, 'bản bị cắt vẫn thay được transcript cũ'
    assert result[1]['content'].startswith(COMPACTION_BANNER[:20])
    assert compression.SUMMARY_MAX_TOKENS_FLOOR == 8_192
    assert calls == [compression.SUMMARY_MAX_TOKENS_FLOOR], 'lượt tóm tắt nhận sàn mới'


def test_usable_summary_is_the_one_judge_for_both_paths():
    """`usable_summary` — luật duy nhất cho \"bản tóm tắt dùng được\", hỏi bởi `compact()` VÀ closure
    `summarize` của `runtime.py`.

    Ca sống 2026-10-09 (phiên `72106f67`): closure cũ chỉ nhận `completion_reason == 'complete'`,
    nên nó ném đi bản `finishReason: length` kèm 2 898 ký tự đã viết xong; phiên mắc
    `OUTPUT_CONTEXT_EXHAUSTED` ở bước 539/2400. Bản bị cắt mà CÓ chữ phải dùng được.
    """
    assert compression.usable_summary({'choices': [{'message': {'content': 'Goal: x'},
                                                     'finish_reason': 'stop'}]})
    assert compression.usable_summary({'choices': [{'message': {'content': 'Goal: x'},
                                                     'finish_reason': 'length'}]}), 'bản bị cắt vẫn dùng được'
    assert not compression.usable_summary({'choices': [{'message': {'content': ''},
                                                        'finish_reason': 'length'}]})
    assert not compression.usable_summary({'choices': [{'message': {'content': None},
                                                        'finish_reason': 'stop'}]})
    assert not compression.usable_summary({'choices': [{'message': {'content': 'Goal: x'},
                                                        'finish_reason': 'stream_incomplete'}]})
    assert not compression.usable_summary({'choices': [{'message': {'content': 'x',
                                                                    'refusal': 'no'}}]})
    assert not compression.usable_summary({})
    assert not compression.usable_summary(None)
    # Closure `summarize` của `runtime.py` phải hỏi CHÍNH hàm này, không tự phán bằng
    # `completion_reason` (cổng cũ nằm ở đó và chặn trước luật Phần D).
    runtime_source = (Path(compression.__file__).with_name('runtime.py')).read_text(encoding='utf-8')
    closure = runtime_source.split('async def summarize(history, max_tokens=None):')[1].split('compressor =')[0]
    assert 'usable_summary(response)' in closure
    assert "completion_reason(response) != 'complete'" not in closure


def test_a_truncated_summary_without_text_is_still_a_failure():
    """Cắt tới mức không còn chữ nào thì không phải bản tóm tắt — lượt gốc được giữ nguyên."""
    messages = _bulky_tail_history()
    compressor = ContextCompressor(40_000)

    async def summarize(history, max_tokens=None):
        return _answer('', finish='length')

    result, event = asyncio.run(compressor.compact(messages, [], summarize))
    assert event['kind'] == 'summary_failed', event
    assert event['beforeEstimate'] > 0
    assert len(result) > 2, 'transcript cũ không bị thay bằng [system, summary]'
