"""Bản port HERMES/PI cho bộ nén: ngưỡng tuyệt đối, trần byte, đo bằng usage thật, tỉa nhiều lượt,
đuôi theo token, trần tóm tắt co giãn, khoá chống-thrash và cờ `ineffective`.

Mỗi bài ở đây ứng với một mục trong bản đặc tả port; các con số lấy thẳng từ hằng số của
`agent_core/limits.py` và `agent_core/compression.py` để không chép tay lần thứ hai.
"""
import asyncio
import json

from agentbox.agent_core import compression
from agentbox.agent_core.compression import (COMPACTION_BANNER, DUPLICATE_TOOL_OUTPUT,
                                             MAX_TAIL_MESSAGE_FLOOR, SUMMARY_MAX_TOKENS_CAP,
                                             SUMMARY_MAX_TOKENS_FLOOR, ContextCompressor,
                                             context_estimate, estimate_tokens, summary_max_tokens,
                                             tail_cut, tool_result_summary, usage_reading)
from agentbox.agent_core.limits import (COMPRESSION_MAX_TOKENS, COMPRESSION_THRASH_SECONDS,
                                        ROUTER_BODY_BUDGET, ROUTER_BODY_OVERHEAD_TOKENS)
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
import pytest


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ; khóa tổng `BOXFOX_REFORM` đã bị xoá ở bước B5
# (HANDOFF §10.3) nên nhãn `legacy_path` không còn kèm env nào để pin.
pytestmark = pytest.mark.legacy_path


BODY_CEILING_TOKENS = ROUTER_BODY_BUDGET // 3 - ROUTER_BODY_OVERHEAD_TOKENS


def _call(index, pad=0, name='terminal_exec'):
    args = {'command': f'echo {index}' + 'c' * pad} if name == 'terminal_exec' else {'question': f'q{index}'}
    return {'id': f'call_{index}', 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args)}}


def _turn(index, pad, name='terminal_exec'):
    """Một lượt công cụ trọn vẹn: hàng gọi và kết quả của nó.

    Nội dung mỗi kết quả một khác (`[7] …`): hai kết quả giống nhau từng chữ sẽ bị phép khử trùng
    lặp thay bằng một dòng trỏ về bản mới nhất — đúng thiết kế, nhưng không phải thứ các bài về
    lượt tóm tắt muốn đo.
    """
    return [{'role': 'assistant', 'content': None, 'tool_calls': [_call(index, pad, name)]},
            {'role': 'tool', 'tool_call_id': f'call_{index}', 'name': name,
             'content': f'[{index}] ' + 'x' * pad}]


def _answer(text, finish='stop'):
    return {'choices': [{'message': {'content': text}, 'finish_reason': finish}]}


def _bulky_tail_history():
    """20 lượt cũ nhỏ + 8 message cuối nặng (~24k token): vượt ngưỡng của cửa sổ 40k, và phần đuôi
    được sàn số message giữ lại nằm sát ngưỡng — đúng ca mà mục E muốn nói tới."""
    messages = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal'}]
    for index in range(20):
        messages += _turn(index, 300)
    for index in range(20, 24):
        messages += _turn(index, 9000)
    return messages


def _one_huge_tool_result():
    """Cửa sổ 1M: ~305k token — trên trần byte, dưới hẳn ngưỡng 70 % (697k)."""
    return [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal-0'},
            {'role': 'assistant', 'content': None, 'tool_calls': [_call(0)]},
            {'role': 'tool', 'tool_call_id': 'call_0', 'name': 'terminal_exec', 'content': 'x' * 915_000},
            {'role': 'user', 'content': 'goal-1'},
            {'role': 'assistant', 'content': None, 'tool_calls': [_call(1)]},
            {'role': 'tool', 'tool_call_id': 'call_1', 'name': 'terminal_exec', 'content': 'small'},
            {'role': 'user', 'content': 'latest'}]


def _long_chat(turns=40, pad=1000):
    messages = [{'role': 'system', 'content': 'stable'}]
    for index in range(turns):
        messages += [{'role': 'user', 'content': f'goal-{index}'}] + _turn(index, pad)
    return messages


def _unprunable_middle():
    """~230k token trong các hàng assistant (không tỉa được) và một đuôi nhỏ — trên ngưỡng của
    cửa sổ 300k, nhưng phần bị gộp thì lớn nên bản tóm tắt thừa sức nhỏ hơn."""
    messages = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal-0'}]
    for index in range(23):
        messages += [{'role': 'assistant', 'content': 'w' * 30_000, 'tool_calls': [_call(index)]},
                     {'role': 'tool', 'tool_call_id': f'call_{index}', 'name': 'terminal_exec',
                      'content': f'[{index}] ok'}]
    messages += _turn(90, 3000)
    messages.append({'role': 'user', 'content': 'latest'})
    return messages


# ------------------------------------------------------------------ P1: ngưỡng tuyệt đối theo model

def test_the_threshold_can_be_an_absolute_number():
    small = ContextCompressor(40_000)
    assert small.budget == 40_000 - 4096
    assert small.threshold == int(small.budget * 0.7) == 25_132, 'mặc định vẫn là 70 % như trước'
    assert ContextCompressor(40_000, threshold_percent=0.5).threshold == int(small.budget * 0.5)
    assert ContextCompressor(1_000_000, threshold_tokens=50_000).threshold == 50_000
    # Trần của dải mục tiêu (Phần D đợt 20) đứng trên cả trần byte: đặt ngưỡng cao hơn cũng vô ích,
    # vì cửa sổ 1M mà nén ở 300k token là phiên dài vô hạn — đo trên máy Vorflux: 65–185k/lần gộp.
    assert ContextCompressor(1_000_000, threshold_tokens=900_000).threshold == COMPRESSION_MAX_TOKENS


# --------------------------------------------------------------------- P2: trần byte của router

def test_the_byte_ceiling_comes_before_the_percent_threshold():
    compressor = ContextCompressor(1_000_000)
    assert compressor.byte_threshold == BODY_CEILING_TOKENS
    # Phần D: trên cửa sổ 1M, thứ chặn trước là trần của dải mục tiêu, rồi mới tới trần byte, rồi
    # mới tới tỉ lệ 70 %. Cả ba đều phải nằm dưới trần body của router.
    assert compressor.threshold == COMPRESSION_MAX_TOKENS < compressor.byte_threshold
    assert compressor.byte_threshold < compressor.percent_threshold
    assert compressor.threshold * 3 <= ROUTER_BODY_BUDGET, 'ngưỡng phải quy ra được dưới trần body'


def test_the_byte_ceiling_still_wins_when_the_band_is_raised_above_it(monkeypatch):
    """Trần byte của router không được biến mất sau đợt 20: nếu ai nâng trần dải lên quá nó thì
    ngưỡng vẫn phải dừng ở `byte_threshold` (ca `UPSTREAM_HTTP_413` đo ngày 2026-09-20)."""
    monkeypatch.setattr(compression, 'COMPRESSION_MAX_TOKENS', 10_000_000)
    compressor = ContextCompressor(1_000_000)
    assert compressor.threshold == compressor.byte_threshold == BODY_CEILING_TOKENS


def test_a_transcript_the_percent_rule_would_ignore_is_still_compacted():
    """Trước đợt này: cửa sổ 1M → ngưỡng 70 % = 697 132 token, mà router từ chối body quá 900 KiB
    (~300k token) — request bị trả `UPSTREAM_HTTP_413` mà bộ nén chưa từng chạy."""
    messages = _one_huge_tool_result()
    compressor = ContextCompressor(1_000_000)
    assert compressor.threshold < estimate_tokens(messages) < compressor.percent_threshold
    calls = []

    async def summarize(history, max_tokens=None):
        calls.append(max_tokens)
        raise AssertionError('tỉa là đủ ở đây, không cần lượt tóm tắt')

    async def run():
        return await compressor.compact(messages, [], summarize)

    result, event = asyncio.run(run())
    assert event is not None and event['kind'] == 'prune', event
    assert not calls, 'chỉ tỉa thôi: không đốt một lượt model'
    assert estimate_tokens(result, []) < compressor.threshold, 'request đã về dưới trần byte'
    kept = json.dumps(result, ensure_ascii=False)
    assert '[terminal_exec] `echo 0`' in kept, 'kết quả cũ thành một dòng có tên lệnh'
    assert 'x' * 1000 not in kept


# ------------------------------------------------------------------------ P3: đo bằng usage thật

def test_the_router_usage_decides_the_trigger_before_the_estimate():
    messages = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal'},
                {'role': 'assistant', 'content': 'x' * 200_000}, {'role': 'user', 'content': 'latest'}]
    compressor = ContextCompressor(40_000)
    assert estimate_tokens(messages) > compressor.threshold, 'ước lượng một mình thì vượt ngưỡng'
    reading = usage_reading({'prompt_tokens': 10_000}, 3)
    assert reading == {'tokens': 10_000, 'index': 3}
    assert context_estimate(messages, [], reading) == 10_000 + estimate_tokens(messages[3:])
    assert context_estimate(messages, [], reading) < compressor.threshold
    assert context_estimate(messages, [], None) == estimate_tokens(messages)
    assert context_estimate(messages, [], {'tokens': 10, 'index': 99}) == estimate_tokens(messages), 'chỉ số cũ'
    assert context_estimate(messages, [], {'tokens': 'x', 'index': 0}) == estimate_tokens(messages)
    assert usage_reading({}, 3) is None
    assert usage_reading({'prompt_tokens': 0}, 3) is None
    assert usage_reading(None, 3) is None
    assert usage_reading({'total_tokens': 500}, 3) == {'tokens': 500, 'index': 3}
    calls = []

    async def summarize(history, max_tokens=None):
        calls.append(max_tokens)
        return _answer('Goal: none.')

    async def run():
        return await compressor.compact(messages, [], summarize, usage=reading)

    result, event = asyncio.run(run())
    assert result is messages and event is None, 'hóa đơn thật cho thấy chưa cần nén'
    assert not calls


def test_a_usage_trigger_with_nothing_to_prune_is_a_no_op():
    """F2 của vòng đánh giá: ngưỡng khởi động đo bằng số neo hoá đơn, phép kiểm sau đo thô.

    Khi nhà cung cấp đếm nhiều token hơn ước lượng `bytes/3` cho cùng nội dung, `compact` vào vòng
    tỉa vì hoá đơn vượt ngưỡng, rồi thoát sớm vì ước lượng thô vẫn dưới ngưỡng — mà chẳng tỉa được
    gì. Hợp đồng no-op: trả CHÍNH danh sách cũ và KHÔNG event, nếu không người gọi ghi thêm một
    checkpoint trùng và hiện "đã nén" cho một lượt không nén gì.
    """
    messages = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal'}]
    compressor = ContextCompressor(40_000)
    reading = usage_reading({'prompt_tokens': 70_000}, len(messages))
    assert context_estimate(messages, [], reading) > compressor.threshold
    assert estimate_tokens(messages) < compressor.threshold, 'ước lượng thô vẫn dưới ngưỡng'
    calls = []

    async def summarize(history, max_tokens=None):
        calls.append(1)
        return _answer('unreachable')

    async def run():
        return await compressor.compact(messages, [], summarize, usage=reading)

    result, event = asyncio.run(run())
    assert result is messages, 'không tỉa được gì thì không trả bản sao'
    assert event is None, 'và không báo một lần nén chưa xảy ra'
    assert not calls, 'không gọi tóm tắt'


# --------------------------------------------------- P4: khử trùng lặp + một dòng cho mỗi công cụ

def test_an_older_copy_of_a_tool_result_points_at_the_newest_one():
    """Hai kết quả giống nhau từng chữ: bản cũ thành một dòng trỏ về bản mới nhất. Nội dung ở đây
    ngắn hơn ngưỡng 1500 ký tự của phép tỉa nên chỉ phép khử trùng lặp đụng vào chúng."""
    same = '[dup] ' + 'x' * 1200
    messages = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal-0'},
                {'role': 'assistant', 'content': None, 'tool_calls': [_call(0)]},
                {'role': 'tool', 'tool_call_id': 'call_0', 'name': 'terminal_exec', 'content': same},
                {'role': 'assistant', 'content': None, 'tool_calls': [_call(1)]},
                {'role': 'tool', 'tool_call_id': 'call_1', 'name': 'terminal_exec', 'content': same}]
    for index in range(2, 7):
        messages += _turn(index, 9000)
    for index in range(7, 11):
        messages += _turn(index, 50)
    messages.append({'role': 'user', 'content': 'latest'})

    async def summarize(history, max_tokens=None):
        raise AssertionError('tỉa là đủ ở đây')

    async def run():
        return await ContextCompressor(40_000).compact(messages, [], summarize)

    result, event = asyncio.run(run())
    assert event['kind'] == 'prune' and event['pruned'] >= 1, event
    assert result[3]['content'] == DUPLICATE_TOOL_OUTPUT, 'bản cũ trỏ về bản mới nhất'
    assert result[5]['content'] == same, 'bản mới nhất giữ nguyên'
    assert messages[3]['content'] == same, 'transcript gốc không bị đụng'


def test_an_old_tool_result_becomes_one_named_line():
    content = json.dumps({'content': 'pytest output', 'exit_code': 1, 'is_error': True})
    line = tool_result_summary('terminal_exec', {'command': 'pytest -q'}, content)
    assert line.startswith('[terminal_exec] `pytest -q` → exit 1')
    assert line.endswith('chars')
    assert tool_result_summary('request_approval', {}, content) is None, 'không có dòng riêng'
    assert tool_result_summary('terminal_exec', None, content).startswith('[terminal_exec] `?`'), 'thiếu tham số'


def test_a_tool_without_a_line_keeps_both_ends():
    """Bản cũ chỉ giữ `content[:1000]` — lỗi của một lệnh nằm ở những dòng cuối thường xuyên như ở đầu."""
    messages = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal-0'},
                {'role': 'assistant', 'content': None, 'tool_calls': [_call(0, name='ask_user')]},
                {'role': 'tool', 'tool_call_id': 'call_0', 'name': 'ask_user',
                 'content': 'HEAD of the answer' + 'm' * 90_000 + 'TAIL of the answer'}]
    for index in range(1, 9):
        messages += _turn(index, 50)
    messages.append({'role': 'user', 'content': 'latest'})

    async def summarize(history, max_tokens=None):
        raise AssertionError('tỉa là đủ ở đây')

    async def run():
        return await ContextCompressor(40_000).compact(messages, [], summarize)

    result, event = asyncio.run(run())
    assert event['kind'] == 'prune', event
    kept = json.dumps(result, ensure_ascii=False)
    assert 'HEAD of the answer' in kept and 'TAIL of the answer' in kept
    assert 'm' * 1000 not in kept, 'khúc giữa bị bỏ'


# ------------------------------------------------------------------- P5: đuôi theo ngân sách token

def test_the_tail_is_a_token_budget_not_a_user_turn():
    messages = _long_chat(turns=20, pad=1000)
    users = [i for i, m in enumerate(messages) if m['role'] == 'user']
    # Ngân sách rộng hơn cả transcript: không có gì để cắt, quy tắc "hai lượt người dùng cuối" của
    # `compact` vẫn là phương án cuối cùng.
    assert tail_cut(messages, 25_000) == 0
    cut = tail_cut(messages, 3000)
    assert cut < users[-2], 'ngân sách token giữ NHIỀU hơn hai lượt người dùng cuối'
    assert len(messages) - cut >= MAX_TAIL_MESSAGE_FLOOR, 'sàn số message của HERMES'

    heavy = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal'}]
    for index in range(6):
        heavy += _turn(index, 9000)
    heavy_cut = tail_cut(heavy, 25_000)
    assert len(heavy) - heavy_cut >= MAX_TAIL_MESSAGE_FLOOR
    assert estimate_tokens(heavy[heavy_cut:]) > 25_000, 'sàn thắng ngân sách: đuôi vẫn to hơn ngân sách'


def test_a_multi_turn_chat_folds_the_middle_and_keeps_the_pairs():
    """Đuôi theo token cũng chạy cho chat nhiều lượt, không chỉ cho nhiệm vụ CUA một lời nhắc."""
    messages = _long_chat(turns=40, pad=1000)
    seen = {}

    async def summarize(history, max_tokens=None):
        seen['max_tokens'] = max_tokens
        return _answer('Goal: older turns. Evidence: tool results.')

    async def run():
        return await ContextCompressor(40_000).compact(messages, [], summarize)

    result, event = asyncio.run(run())
    assert event['kind'] == 'summary', event
    assert result[0] == messages[0] and result[-1] == messages[-1]
    assert result[1]['content'].startswith('[Context compaction')
    call_ids = {c['id'] for m in result for c in m.get('tool_calls') or []}
    assert call_ids == {m['tool_call_id'] for m in result if m['role'] == 'tool'}, 'không cặp nào bị chia đôi'
    assert 'goal-39' in json.dumps(result, ensure_ascii=False), 'lượt đang làm vẫn còn nguyên'
    assert seen['max_tokens'] == summary_max_tokens(event['beforeEstimate'])


def test_the_fold_never_takes_the_whole_tail_of_a_parallel_batch():
    """F1 của vòng đánh giá: loạt kết quả công cụ song song dài hơn `tail_budget`.

    Vòng "không để kết quả công cụ mồ côi" tiến `cut` qua cả loạt và chạm cuối danh sách. Nếu không
    kẹp lại, bản gộp thay mọi thứ sau tiền tố hệ thống: model nhận `[system, summary]` — không còn
    lượt người dùng nào lẫn kết quả mới nhất — và phiên bị lưu ở dạng đã gộp. Lượt nén chạy ở đầu
    mỗi bước, còn BoxFox cho tới 16 lời gọi song song, nên đường này chạm được với cửa sổ ≤ 128k.
    """
    messages = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal'}]
    for index in range(12):
        messages += [{'role': 'assistant', 'content': 'w' * 5000}]
    messages.append({'role': 'assistant', 'content': None,
                     'tool_calls': [_call(index) for index in range(8)]})
    messages += [{'role': 'tool', 'tool_call_id': f'call_{index}', 'name': 'terminal_exec',
                  'content': f'[{index}] ' + 'x' * 6000} for index in range(8)]
    compressor = ContextCompressor(32_768)
    assert estimate_tokens(messages[-9:]) > compressor.tail_budget, 'cả loạt to hơn ngân sách đuôi'

    cut = compression.keep_tail(messages, len(messages))
    assert messages[cut].get('role') != 'tool', 'đuôi bắt đầu ở hàng gọi, không phải kết quả'
    assert len(messages) - cut >= MAX_TAIL_MESSAGE_FLOOR, 'sàn số message vẫn được giữ'

    async def summarize(history, max_tokens=None):
        return _answer('Goal: older turns. Evidence: reads.')

    async def run():
        return await compressor.compact(messages, [], summarize)

    result, event = asyncio.run(run())
    assert event['kind'] == 'summary', event
    assert len(result) > 2, 'không được gộp thành [system, summary]'
    assert result[-1] == messages[-1], 'kết quả công cụ mới nhất còn nguyên văn'
    kept = [m['tool_call_id'] for m in result if m['role'] == 'tool']
    assert kept == [f'call_{index}' for index in range(8)], 'cả loạt song song được giữ cùng hàng gọi'
    assert {c['id'] for m in result for c in m.get('tool_calls') or []} == set(kept), 'không mồ côi'
    assert len(result) - 1 >= MAX_TAIL_MESSAGE_FLOOR


# ----------------------------------------------------------------- P6: trần `max_tokens` co giãn

def test_the_summary_cap_scales_with_the_transcript():
    # Phần D đợt 20 nâng sàn 2048 → 4096: ba phiên sống chết vì bản tóm tắt bị cắt ở trần quá nhỏ
    # (935 541 / 992 249 / 732 528). Đợt 2026-10-09 nâng tiếp (sàn 8192, tỉ lệ 10 %, trần 50 000)
    # vì sàn cũ là trần thật của tác vụ dài và model tiêu hết nó vào phần suy luận.
    assert summary_max_tokens(10_000) == SUMMARY_MAX_TOKENS_FLOOR == 8_192
    assert summary_max_tokens(200_000) == 20_000, 'tỉ lệ 10 % vượt sàn ở mức này'
    assert summary_max_tokens(10_000_000) == SUMMARY_MAX_TOKENS_CAP == 50_000


def test_the_summary_turn_gets_the_scaled_cap():
    messages = _unprunable_middle()
    compressor = ContextCompressor(300_000)
    assert estimate_tokens(messages) > compressor.threshold
    calls = []

    async def summarize(history, max_tokens=None):
        calls.append(max_tokens)
        return _answer('Goal: older turns. Evidence: tool calls.')

    async def run():
        return await compressor.compact(messages, [], summarize)

    result, event = asyncio.run(run())
    assert event['kind'] == 'summary', event
    assert calls == [summary_max_tokens(event['beforeEstimate'])]
    assert SUMMARY_MAX_TOKENS_FLOOR < calls[0] < SUMMARY_MAX_TOKENS_CAP, 'co giãn, không phải sàn/trần'


# ---------------------------------------------------------------------------- D: khoá chống-thrash

# Đợt 20 đổi luật: `finish_reason == 'length'` mà vẫn CÓ chữ thì nay được nhận, nên các bài về
# khoá chống-thrash dùng một lượt hỏng thật — nhà cung cấp trả về không có chữ nào.


def test_a_failed_summary_arms_a_cooldown_instead_of_retrying_every_step():
    messages = _bulky_tail_history()
    compressor = ContextCompressor(40_000)
    calls = []

    async def failing(history, max_tokens=None):
        calls.append(max_tokens)
        return _answer('', finish='stop')

    async def run():
        first = await compressor.compact(messages, [], failing)
        second = await compressor.compact(messages, [], failing)
        return first, second

    (result, event), (again, none) = asyncio.run(run())
    assert result is messages and event['kind'] == 'summary_failed'
    assert again is messages and none is None, 'lượt sau không đốt thêm một lượt tóm tắt'
    assert len(calls) == 1
    assert COMPRESSION_THRASH_SECONDS == 300.0, 'cửa sổ của HERMES (:2501), nằm trong limits.py'


def test_the_cooldown_lets_one_attempt_through_after_the_window(monkeypatch):
    monkeypatch.setattr(compression, 'COMPRESSION_THRASH_SECONDS', 0.0)
    messages = _bulky_tail_history()
    compressor = ContextCompressor(40_000)
    calls = []

    async def failing(history, max_tokens=None):
        calls.append(max_tokens)
        return _answer('', finish='stop')

    async def run():
        await compressor.compact(messages, [], failing)
        return await compressor.compact(messages, [], failing)

    _, event = asyncio.run(run())
    assert event['kind'] == 'summary_failed', 'hết cửa sổ thì được thử lại'
    assert len(calls) == 2


def test_a_forced_compaction_ignores_the_cooldown():
    """`/compact` là hành động có ý thức của người dùng: khoá chống-thrash không được chặn nó."""
    messages = _bulky_tail_history()
    compressor = ContextCompressor(40_000)
    calls = []

    async def failing(history, max_tokens=None):
        calls.append(max_tokens)
        return _answer('', finish='stop')

    async def summarize(history, max_tokens=None):
        calls.append(max_tokens)
        return _answer('Goal: older turns. Evidence: tool results.')

    async def run():
        first = await compressor.compact(messages, [], failing)
        return first, await compressor.compact(messages, [], summarize, force=True)

    (_, failed), (result, event) = asyncio.run(run())
    assert failed['kind'] == 'summary_failed'
    assert event['kind'] == 'summary', event
    assert len(calls) == 2


# --------------------------------------------------------------- E: cờ `ineffective` + banner

def test_a_compaction_that_stays_near_the_threshold_reports_ineffective():
    messages = _bulky_tail_history()
    compressor = ContextCompressor(40_000)
    calls = []

    async def summarize(history, max_tokens=None):
        calls.append(max_tokens)
        return _answer('Goal: older turns. Evidence: tool results.')

    async def run():
        first = await compressor.compact(messages, [], summarize)
        second = await compressor.compact(messages, [], summarize)
        return first, second

    (result, event), (again, none) = asyncio.run(run())
    assert event['kind'] == 'summary', event
    assert event['ineffective'] is True
    assert event['afterEstimate'] > compressor.threshold * 0.95
    assert event['afterEstimate'] < event['beforeEstimate'], 'bản nén vẫn nhỏ hơn transcript'
    assert result is not messages, 'bản nén vẫn được dùng'
    assert again is messages and none is None, 'cờ ineffective mở luôn khoá chống-thrash'
    assert len(calls) == 1
    assert result[1]['content'].startswith('[Context compaction')
    assert 'tools stay fully active' in result[1]['content']


def test_the_compaction_banner_says_the_tools_stay_active():
    """Sự cố 7/2026 của HERMES: khung "REFERENCE ONLY" đủ mạnh để mô hình ngừng gọi công cụ
    (bảy lượt chỉ thuật lại việc định làm). Thứ tự câu giữ nguyên như `SUMMARY_PREFIX` (:199-239)."""
    assert COMPACTION_BANNER.index('background reference') < COMPACTION_BANNER.index('latest user request')
    assert COMPACTION_BANNER.index('latest user request') < COMPACTION_BANNER.index('tools stay fully active')
    assert COMPACTION_BANNER.startswith('[Context compaction')


# ------------------------------------------------------------- nối dây vào harness (P3 và D)

class _Model:
    """Mô hình giả: trả lần lượt các câu trả lời đã soạn, ghi lại từng request."""

    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    async def complete(self, messages, tools, route, on_thought=None, on_content=None, max_tokens=4096):
        self.requests.append(json.dumps(messages, ensure_ascii=False))
        return next(self.replies)


class _Executor:
    async def execute(self, name, args, sid):
        return {'content': 'observed'}

    async def cleanup(self, sid):
        return None


def _reply(text='done', calls=None, prompt_tokens=None):
    """Câu trả lời của mô hình giả; `prompt_tokens=None` là nhà cung cấp không báo usage."""
    reply = {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                          'finish_reason': 'tool_calls' if calls else 'stop'}]}
    if prompt_tokens is not None:
        reply['usage'] = {'prompt_tokens': prompt_tokens, 'completion_tokens': 2}
    return reply


def _fat_tool_results(rows=6, chars=30_000):
    """Kết quả công cụ rất to, tham số thì nhỏ, và ba lượt cuối thì nhẹ: phần DUY NHẤT tỉa được là
    thứ làm transcript vượt ngưỡng, còn đuôi được giữ lại (8 message cuối) thì rẻ — nên lượt tỉa là
    đủ, lượt tóm tắt không bị gọi."""
    messages = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal-0'}]
    for index in range(rows):
        messages += [{'role': 'assistant', 'content': None, 'tool_calls': [_call(index)]},
                     {'role': 'tool', 'tool_call_id': f'call_{index}', 'name': 'terminal_exec',
                      'content': f'[{index}] ' + 'x' * chars}]
    for index in range(rows, rows + 3):
        messages += _turn(index, 300)
    return messages


def _small_session(store, runtime, turns=3):
    session = runtime.create({'skills': [], 'contextWindow': 40_000})
    seeded = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'goal-0'}]
    for index in range(turns):
        seeded += _turn(index, 300)
    store.save(session['id'], seeded)
    assert estimate_tokens(seeded) < ContextCompressor(40_000).threshold, 'bài này cần nền dưới ngưỡng'
    return session, seeded


def test_the_harness_records_the_router_usage_for_the_session(tmp_path):
    """P3 — hóa đơn của router được ghi lại cho phiên, kèm vị trí mà nó mô tả."""
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = _Model([_reply('final', prompt_tokens=10)])
        runtime = HarnessRuntime(store, _Executor(), model)
        session, seeded = _small_session(store, runtime)
        await runtime.start(session['id'], 'latest')
        assert runtime.last_usage[session['id']] == {'tokens': 10, 'index': len(seeded) + 1}
        assert not [e for e in store.events(session['id']) if e['type'] == 'compression']
        store.close()
    asyncio.run(run())


def test_a_compaction_replaces_the_live_list_and_drops_the_stale_usage(tmp_path):
    """P3 — sau khi nén, hóa đơn cũ mô tả một danh sách khác nên nó bị bỏ (nếu chưa có hóa đơn mới)."""
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, _Executor(), _Model([_reply('final')]))
        session = runtime.create({'skills': [], 'contextWindow': 40_000})
        seeded = _fat_tool_results()
        assert estimate_tokens(seeded) > ContextCompressor(40_000).threshold
        store.save(session['id'], seeded)
        await runtime.start(session['id'], 'latest')
        events = [e for e in store.events(session['id']) if e['type'] == 'compression']
        assert [e['data']['kind'] for e in events] == ['prune'], events
        assert runtime.last_usage.get(session['id']) is None, 'hóa đơn cũ bị bỏ sau khi transcript được thay'
        after = store.get(session['id'])['messages']
        assert estimate_tokens(after) < 5_000, 'transcript sống đã nhỏ lại'
        assert not any('x' * 2000 in json.dumps(m.get('content'), ensure_ascii=False) for m in after)
        store.close()
    asyncio.run(run())


def test_the_compressor_state_is_kept_per_session_across_turns(tmp_path):
    """D — khoá chống-thrash là trạng thái của phiên, không phải của một lượt."""
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, _Executor(), _Model([_reply('one'), _reply('two')]))
        session, _ = _small_session(store, runtime, turns=0)
        await runtime.start(session['id'], 'first')
        first = runtime.compressors[session['id']]
        await runtime.start(session['id'], 'second')
        assert runtime.compressors[session['id']] is first
        store.close()
    asyncio.run(run())


def test_the_manual_compact_command_anchors_on_the_recorded_usage(tmp_path):
    """Khe hở bàn giao đợt 19: điểm gọi `/compact` chưa có bài nào chạm, nên dây `usage=` mới chỉ được
    phủ ở tầng bộ nén. Hoá đơn đã ghi của phiên phải là con số mà lệnh dùng, không phải ước lượng thô.
    """
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, _Executor(), _Model([_answer('Goal: older turns.')]))
        session = runtime.create({'skills': [], 'contextWindow': 40_000})
        seeded = _fat_tool_results()
        store.save(session['id'], seeded)
        raw = estimate_tokens(seeded)
        assert raw > ContextCompressor(40_000).threshold, 'bài này cần transcript thật sự quá ngưỡng'
        reading = {'tokens': 40_000, 'index': len(seeded)}
        anchored = context_estimate(seeded, [], reading)
        assert anchored != raw
        runtime.last_usage[session['id']] = reading
        result = await runtime.submit(session['id'], '/compact')
        assert result['resolution']['command'] == 'compact', result
        await runtime.tasks[session['id']]
        events = [e['data'] for e in store.events(session['id']) if e['type'] == 'compression']
        assert events and events[-1]['kind'] == 'summary', events
        assert events[-1]['beforeEstimate'] == anchored, 'số neo của phiên, không phải ước lượng thô'
        assert runtime.last_usage.get(session['id']) is None, 'hoá đơn cũ bị bỏ sau khi danh sách thay'
        after = store.get(session['id'])['messages']
        assert estimate_tokens(after) < raw, 'transcript sống đã nhỏ lại'
        # Bề mặt context chèn khối refs canonical trước phần tóm tắt, nên tìm ở mọi vị trí.
        assert any(m['content'].startswith('[Context compaction') for m in after)
        store.close()
    asyncio.run(run())
