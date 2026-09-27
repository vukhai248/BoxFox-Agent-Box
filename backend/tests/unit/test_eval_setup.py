"""Bộ khung đánh giá: rubric, chỉ số vội, manifest, dry-run và fixture.

Kiểm tra những điều dễ nói suông nhất:

1. toán của rubric C1-C8 (tổng, điều kiện cứng, thang báo cáo, đồng thuận giám khảo);
2. tín hiệu S1-S10 trên dòng nhật ký tổng hợp, kèm chỗ phải nói "chưa đo";
3. manifest ghim đúng trường và chi phí thật lấy từ nhật ký, thiếu thì ghi `None`;
4. đường dry-run KHÔNG mở socket nào — chạy được khi `socket.socket` bị chặn;
5. `--execute` từ chối khi thiếu opt-in hoặc thiếu ngân sách, và dừng trước khi tiêu tiền;
6. 12 fixture Q1-Q12 nạp được, đúng luật mạng của kế hoạch §4;
7. bảng điểm tính lại được từ thư mục kết quả thô.

`scripts/eval` là các module phẳng cạnh nhau (không phải package) nên tệp này tự
thêm thư mục đó vào `sys.path`, giống cách chúng được chạy bằng `python scripts/eval/...`.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO / 'scripts' / 'eval'
sys.path.insert(0, str(EVAL_DIR))

import fixtureset  # noqa: E402
import guard  # noqa: E402
import judge  # noqa: E402
import logread  # noqa: E402
import manifest as manifest_mod  # noqa: E402
import rubric  # noqa: E402
import run_eval  # noqa: E402
import runner  # noqa: E402
import rushed_index  # noqa: E402
import scoreboard  # noqa: E402

ALL_TWO = {code: 2 for code in rubric.DIMENSION_CODES}


def _scores(**overrides):
    values = dict(ALL_TWO)
    values.update(overrides)
    return values


# --------------------------------------------------------------------------- rubric
def test_total_and_verdict_bands_match_the_plan():
    assert rubric.score_total(ALL_TWO) == 16 == rubric.MAX_TOTAL
    assert rubric.verdict(16) == 'đạt tốt'
    assert rubric.verdict(13) == 'đạt tốt'
    assert rubric.verdict(12) == 'đạt có điều kiện'
    assert rubric.verdict(9) == 'đạt có điều kiện'
    assert rubric.verdict(8) == 'chưa đạt'


def test_hard_gate_beats_a_high_total():
    scores = _scores(C2=0)
    assert rubric.score_total(scores) == 14
    assert rubric.hard_gate_ok(scores) is False
    assert rubric.passes(scores) is False
    assert rubric.evaluate(scores)['verdict'] == 'đạt tốt'  # thang báo cáo vẫn 14
    assert rubric.evaluate(_scores(C7=0))['pass'] is False


def test_a_middle_total_still_fails_the_pass_rule():
    scores = _scores(C1=1, C5=1, C6=1, C8=1)  # tổng 12 nhưng ≥ 9 nên vẫn pass
    assert rubric.passes(scores) is True
    weak = _scores(C4=0, C8=0, C1=1, C5=1, C6=1, C3=1)  # tổng 8
    assert rubric.score_total(weak) == 8
    assert rubric.passes(weak) is False


def test_scores_outside_the_scale_are_refused_not_clamped():
    with pytest.raises(ValueError):
        rubric.score_total(_scores(C1=3))
    with pytest.raises(ValueError):
        rubric.score_total(_scores(C1=-1))
    with pytest.raises(TypeError):
        rubric.score_total(_scores(C1='2'))
    with pytest.raises(KeyError):
        rubric.score_total({code: 2 for code in rubric.DIMENSION_CODES if code != 'C4'})


def test_infrastructure_rows_never_enter_the_quality_score():
    rows = [rubric.evaluate(ALL_TWO), rubric.evaluate(_scores(C2=0), outcome='rate_limited')]
    assert rows[1]['infrastructure'] is True and rows[1]['pass'] is False
    rate = rubric.pass_rate(rows)
    assert rate == {'passed': 1, 'total': 1, 'rate': 1.0, 'infrastructure': 1}
    stats = rubric.dimension_stats(rows)
    assert stats['C2']['n'] == 1 and stats['C2']['mean'] == 2.0


def test_empty_input_reports_unmeasured_instead_of_zero():
    stats = rubric.dimension_stats([])
    assert stats['C1']['mean'] is None
    assert rubric.pass_rate([])['rate'] is None
    agreement = rubric.judge_agreement([])
    assert agreement['rate'] is None and agreement['needsThirdPass'] == []


def test_judge_agreement_uses_the_two_point_rule():
    pairs = [{'first': ALL_TWO, 'second': _scores(C2=1)},
             {'first': _scores(C1=1, C2=1, C3=1, C4=1), 'second': _scores()}]
    result = rubric.judge_agreement(pairs)
    assert result['agree'] == 1 and result['total'] == 2 and result['rate'] == 0.5
    assert result['needsThirdPass'] == [1]


def test_stdev_needs_two_points():
    one = [rubric.evaluate(ALL_TWO)]
    two = one + [rubric.evaluate(_scores(**{'C1': 0}))]
    assert rubric.dimension_stats(one)['C1']['stdev'] is None
    assert rubric.dimension_stats(two)['C1']['stdev'] == pytest.approx(1.414, abs=1e-3)


def test_repetition_proxy_sees_duplicated_blocks():
    single = (''.join([
        'Bước một đọc mã nguồn trong thư mục gốc để hiểu luồng dữ liệu. ',
        'Bước hai chạy bộ test hiện có và ghi lại kết quả thật của lần chạy. ',
        'Bước ba sửa lỗi nhỏ nhất có thể rồi chạy lại đúng lệnh đó. ',
        'Bước bốn ghi lại phần chưa kiểm chứng được và lý do cụ thể. ',
    ]))
    doubled = single + single          # dạng BUG-26: đuôi dán lại nguyên đoạn đầu
    assert rubric.repetition_ratio(single) == 0.0
    assert rubric.repetition_ratio(doubled) > 0.3
    assert rubric.repeat_free(single) is True
    assert rubric.repeat_free(doubled) is False
    assert rubric.repetition_ratio('quá ngắn') == 0.0


def test_layer_split_matches_the_plan():
    assert rubric.LAYER1_DIMENSIONS == ('C1', 'C5', 'C6')
    assert rubric.LAYER2_DIMENSIONS == ('C2', 'C3', 'C4', 'C7', 'C8')
    assert set(rubric.DIMENSION_CODES) == set(rubric.LAYER1_DIMENSIONS) | set(rubric.LAYER2_DIMENSIONS)


# --------------------------------------------------------------------------- fixtures
def test_twelve_fixtures_load_and_match_the_plan_ids():
    fixtures = fixtureset.load_fixtures()
    assert list(fixtures) == [f'Q{index}' for index in range(1, 13)]
    for code, item in fixtures.items():
        assert item['id'] == code
        assert item['request'].strip()
        assert item['oracle_pass'] and item['bad_answer']
        assert set(item['rubric_dimensions']) <= set(rubric.DIMENSION_CODES)
        assert item['environment']['network'] in ('off', 'on')
        assert item['budget']['max_steps'] > 0


def test_only_q6_is_allowed_online():
    fixtures = fixtureset.load_fixtures()
    online = [code for code, item in fixtures.items() if item['environment']['network'] == 'on']
    assert online == ['Q6']
    assert fixtureset.set_issues(fixtures) == []


def test_a_broken_fixture_is_refused_with_a_reason(tmp_path):
    bad = json.loads((EVAL_DIR / 'fixtures' / 'Q1.json').read_text(encoding='utf-8'))
    bad['rubric_dimensions'] = ['C1', 'C9']
    bad['budget']['max_steps'] = 0
    (tmp_path / 'Q1.json').write_text(json.dumps(bad, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError) as excinfo:
        fixtureset.load_fixture(tmp_path / 'Q1.json')
    assert 'C9' in str(excinfo.value) and 'max_steps' in str(excinfo.value)


def test_unknown_fixture_id_is_refused_instead_of_skipped():
    fixtures = fixtureset.load_fixtures()
    assert list(fixtureset.select(fixtures, ['Q1', 'Q7'])) == ['Q1', 'Q7']
    with pytest.raises(KeyError):
        fixtureset.select(fixtures, ['Q99'])


# --------------------------------------------------------------------------- rushed index
def _entry(event, **fields):
    entry = {'ts': fields.pop('ts', '2026-09-20T00:00:00.000Z'), 'level': fields.pop('level', 'info'),
             'source': 'harness', 'event': event}
    entry.update(fields)
    return entry


def test_turn_pairing_keeps_tools_with_their_turn():
    entries = [
        _entry('turn.start', sessionId='s1', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('tool.end', sessionId='s1', data={'tool': 'file_write', 'isError': False}),
        _entry('turn.end', sessionId='s1', durationMs=1000, data={'status': 'completed', 'steps': 2,
                                                                  'textChars': 900}),
    ]
    turns = rushed_index.pair_turns(entries)
    assert len(turns) == 1
    assert [rushed_index._tool_name(item) for item in turns[0]['tools']] == ['file_write']
    assert turns[0]['end']['data']['steps'] == 2


def test_s2_flags_a_short_answer_only_after_work():
    entries = [
        _entry('turn.start', sessionId='s1', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('tool.end', sessionId='s1', data={'tool': 'file_read', 'isError': False}),
        _entry('turn.end', sessionId='s1', data={'status': 'completed', 'steps': 1, 'textChars': 12}),
        _entry('turn.start', sessionId='s2', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('turn.end', sessionId='s2', data={'status': 'completed', 'steps': 0, 'textChars': 5}),
    ]
    signal = rushed_index.compute(entries)['signals'][1]
    assert signal['code'] == 'S2' and signal['status'] == 'measured'
    assert signal['count'] == 1 and 's1' in signal['flagged'][0]['turn']
    assert 's2' not in signal['flagged'][0]['turn']


def test_s3_flags_a_write_that_was_never_checked():
    def turn(sid, tools):
        entries = [_entry('turn.start', sessionId=sid, data={'maxSteps': 8, 'deadlineSeconds': 60})]
        entries += [_entry('tool.end', sessionId=sid, data={'tool': name, 'isError': False})
                    for name in tools]
        entries.append(_entry('turn.end', sessionId=sid, data={'status': 'completed', 'steps': 2,
                                                              'textChars': 800}))
        return entries

    signals = rushed_index.compute(turn('a', ['file_write']) +
                                   turn('b', ['file_write', 'terminal_exec']) +
                                   turn('c', ['file_read']))
    s3 = signals['signals'][2]
    assert s3['code'] == 'S3' and s3['status'] == 'measured_proxy'
    assert s3['count'] == 1 and 'a' in s3['flagged'][0]['turn']


def test_s6_flags_three_identical_failing_calls():
    entries = [_entry('turn.start', sessionId='s1', data={'maxSteps': 8, 'deadlineSeconds': 60})]
    entries += [_entry('tool.end', sessionId='s1', data={'tool': 'terminal_exec', 'isError': True})
                for _ in range(3)]
    entries.append(_entry('turn.end', sessionId='s1', data={'status': 'completed', 'steps': 3,
                                                           'textChars': 500}))
    s6 = rushed_index.compute(entries)['signals'][5]
    assert s6['code'] == 'S6' and s6['count'] == 1 and s6['flagged'][0]['tool'] == 'terminal_exec'


def test_s7_flags_a_turn_that_swallowed_a_tool_error():
    entries = [
        _entry('turn.start', sessionId='s1', data={'maxSteps': 8, 'deadlineSeconds': 60}),
        _entry('tool.end', sessionId='s1', data={'tool': 'terminal_exec', 'isError': True}),
        _entry('turn.end', sessionId='s1', data={'status': 'completed', 'steps': 2, 'textChars': 1500}),
    ]
    signal = rushed_index.compute(entries)['signals'][6]
    assert signal['code'] == 'S7' and signal['severity'] == 'severe' and signal['count'] == 1
    assert signal['flagged'][0]['failedTools'] == ['terminal_exec']


def test_s8_flags_a_turn_over_eighty_percent_of_its_budget():
    entries = [
        _entry('turn.start', sessionId='s1', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('turn.end', sessionId='s1', durationMs=90000, data={'status': 'completed', 'steps': 9,
                                                                   'textChars': 900}),
        _entry('turn.start', sessionId='s2', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('turn.end', sessionId='s2', durationMs=1000, data={'status': 'completed', 'steps': 1,
                                                                  'textChars': 900}),
    ]
    signal = rushed_index.compute(entries)['signals'][7]
    assert signal['code'] == 'S8' and signal['count'] == 1
    assert signal['flagged'][0]['ratios'] == {'steps': 0.9, 'time': 0.9}


def test_s8_reads_the_turn_numbers_directly_when_the_log_has_them():
    entries = [
        _entry('turn.start', sessionId='s1', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        # Vòng 22 (B9): lượt mới ghi thẳng `stepsUsed`/`deadlineUsedMs`/`toolsRun`. `steps` và
        # `durationMs` ở đây cố tình nhỏ — nếu bài này đọc nhầm đường lùi thì tỉ lệ sẽ là
        # 0.1/0.01 và phép khẳng định dưới trượt.
        _entry('turn.end', sessionId='s1', durationMs=1000,
               data={'status': 'completed', 'steps': 1, 'textChars': 900,
                     'stepsUsed': 9, 'deadlineUsedMs': 90000, 'toolsRun': 7}),
        # Lượt cũ: chỉ có khoá cũ, và `toolsRun` phải suy từ số `tool.end` của lượt.
        _entry('turn.start', sessionId='s2', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('tool.end', sessionId='s2', data={'tool': 'file_read', 'isError': False}),
        _entry('turn.end', sessionId='s2', durationMs=90000,
               data={'status': 'completed', 'steps': 9, 'textChars': 900}),
    ]
    signal = rushed_index.compute(entries)['signals'][7]
    assert signal['code'] == 'S8' and signal['count'] == 2
    assert signal['flagged'][0]['ratios'] == {'steps': 0.9, 'time': 0.9}
    assert signal['flagged'][0]['toolsRun'] == 7
    assert signal['flagged'][1]['ratios'] == {'steps': 0.9, 'time': 0.9}
    assert signal['flagged'][1]['toolsRun'] == 1, 'lượt cũ suy từ số tool.end đã ghi'


def test_s9_and_s10_count_codes_and_missing_sections():
    entries = [
        _entry('turn.failed', sessionId='s1', level='error', code='UPSTREAM_HTTP_503',
               data={'errorCode': 'UPSTREAM_HTTP_503'}),
        _entry('model.error', sessionId='s1', level='warn', data={'errorCode': 'UPSTREAM_TIMEOUT'}),
        _entry('turn.failed', sessionId='s2', level='error',
               message='PLAN_QUALITY_REJECTED: the plan was not written: missing '
                       '(verification-section) name a command; (risks-section) state the risks.'),
    ]
    signals = rushed_index.compute(entries)['signals']
    s9 = signals[8]
    s10 = signals[9]
    assert s9['code'] == 'S9' and s9['count'] == 2 and s9['weight'] == 0.0
    assert s10['code'] == 'S10' and s10['count'] == 1
    assert s10['flagged'][0]['missing'] == ['risks-section', 'verification-section']


def test_signals_that_cannot_be_measured_say_so():
    report = rushed_index.compute([
        _entry('turn.start', sessionId='s1', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('turn.end', sessionId='s1', data={'status': 'completed', 'steps': 1, 'textChars': 900}),
    ])
    unmeasured = {signal['code']: signal for signal in report['signals'] if signal['status'] == 'not_measured'}
    assert set(unmeasured) == {'S1', 'S4', 'S5'}
    assert all(signal['value'] is None for signal in unmeasured.values())
    assert 'nội dung tin nhắn' in unmeasured['S4']['note']


def test_s4_measures_the_gate_numbers_when_the_log_has_them():
    """Đợt 3 vòng 22 (P5.1): cổng bằng chứng ghi số vào `turn.end` ⇒ S4 rời `not_measured`."""
    entries = [
        _entry('turn.start', sessionId='s1', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('turn.end', sessionId='s1',
               data={'status': 'completed', 'steps': 2, 'textChars': 900, 'gateMode': 'warn',
                     'evidenceVerdict': 'sufficient', 'evidenceMissing': 0}),
        _entry('turn.start', sessionId='s2', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('turn.end', sessionId='s2',
               data={'status': 'completed', 'steps': 2, 'textChars': 900, 'gateMode': 'warn',
                     'evidenceVerdict': 'insufficient', 'evidenceMissing': 2}),
    ]
    report = rushed_index.compute(entries)
    s4 = next(signal for signal in report['signals'] if signal['code'] == 'S4')
    assert s4['status'] == 'measured', 'có số của cổng trong log thì không được nói chưa đo'
    assert s4['value'] == 0.5, 'một nửa số lượt đo được bị gắn cờ'
    assert 'S4' not in report['unmeasured']
    assert s4['flagged'][0]['verdict'] == 'insufficient' and s4['flagged'][0]['missing'] == 2
    assert '20 PHIÊN' in s4['note'], 'ngưỡng nâng `enforce` của §6 phải nằm ngay trong note'


def test_s4_says_how_many_turns_it_measured_on_a_half_and_half_log():
    """Log nửa vời: lượt cũ (không khoá) KHÔNG được tính là sạch — nó không vào mẫu."""
    entries = [
        _entry('turn.start', sessionId='s1', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('turn.end', sessionId='s1',
               data={'status': 'completed', 'steps': 2, 'textChars': 900,
                     'evidenceVerdict': 'insufficient', 'evidenceMissing': 1}),
        _entry('turn.start', sessionId='s2', data={'maxSteps': 10, 'deadlineSeconds': 100}),
        _entry('turn.end', sessionId='s2', data={'status': 'completed', 'steps': 2, 'textChars': 900}),
    ]
    s4 = next(signal for signal in rushed_index.compute(entries)['signals'] if signal['code'] == 'S4')
    assert s4['status'] == 'measured' and s4['count'] == 1 and s4['value'] == 1.0
    assert '1 lượt đã đo' in s4['note'] and '2 lượt' in s4['note'], \
        'note phải nói rõ đã đo được bao nhiêu trên tổng bao nhiêu lượt trong cửa sổ'


def test_index_weights_only_warning_signals_and_is_capped_at_one():
    entries = [_entry('turn.start', sessionId='s1', data={'maxSteps': 4, 'deadlineSeconds': 10}),
               _entry('tool.end', sessionId='s1', data={'tool': 'terminal_exec', 'isError': True}),
               _entry('turn.end', sessionId='s1', durationMs=9000,
                      data={'status': 'completed', 'steps': 4, 'textChars': 900})]
    report = rushed_index.compute(entries)
    assert report['status'] == 'ok'
    assert report['evaluatedTurns'] == 1
    assert report['weightedFlags'] == 3.0 + 1.0  # S7 (lỗi nặng) + S8 (ngân sách)
    assert report['rawIndex'] == 4.0 and report['index'] == 1.0  # chặn trần theo hợp đồng 0-1


def test_no_log_means_no_data_never_a_zero():
    report = rushed_index.compute([])
    assert report['status'] == 'no_data' and report['index'] is None
    assert report['evaluatedTurns'] == 0
    window = logread.read_window(Path('/nonexistent/harness.jsonl'))
    assert window['state'] == logread.STATE_MISSING and window['entries'] == []
    text = rushed_index.render(report, rushed_index.summarize_log([], path=window['path'],
                                                                 state=window['state']))
    assert 'NO DATA' in text and '0.0' not in text.split('Kết luận')[1][:40]


def test_reader_reports_an_empty_file_as_empty_not_missing(tmp_path):
    empty = tmp_path / 'harness.jsonl'
    empty.write_text('', encoding='utf-8')
    window = logread.read_window(empty)
    assert window['state'] == logread.STATE_EMPTY and window['entries'] == []
    missing = logread.read_window(tmp_path / 'nope.jsonl')
    assert missing['state'] == logread.STATE_MISSING


def test_window_includes_the_previous_run_and_dedupes_across_files(tmp_path):
    """Nhật ký xoay vòng: tệp đang ghi + `harness.previous.jsonl` của lần chạy trước."""
    active = tmp_path / 'harness.jsonl'
    previous = tmp_path / 'harness.previous.jsonl'
    first = _entry('turn.start', sessionId='s1', data={'maxSteps': 4, 'deadlineSeconds': 10})
    second = _entry('turn.end', sessionId='s1', durationMs=500,
                    data={'status': 'completed', 'steps': 1, 'textChars': 700})
    previous.write_text(json.dumps(first) + '\n', encoding='utf-8')
    # dòng đầu bị dán lại ở tệp mới (bản xoay vòng kiểu copy, không phải rename)
    active.write_text(json.dumps(first) + '\n' + json.dumps(second) + '\n', encoding='utf-8')
    window = logread.read_window(active)
    assert window['state'] == logread.STATE_OK
    assert len(window['entries']) == 2          # không đếm hai lần dòng trùng
    assert window['duplicates'] == 1
    assert [Path(name).name for name in window['files']] == ['harness.previous.jsonl', 'harness.jsonl']
    assert logread.log_family(active)[0] == previous
    assert logread.previous_path(active) == previous
    # tệp .0-.3 chỉ đọc khi xin rõ
    assert len(logread.log_family(active, rotated=True)) == 6
    report = rushed_index.compute(window['entries'])
    text = rushed_index.render(report, rushed_index.summarize_log(
        window['entries'], path=window['path'], state=window['state'], files=window['files'],
        duplicates=window['duplicates']))
    assert 'harness.previous.jsonl' in text and 'trùng' in text


def test_previous_run_alone_is_still_a_window_not_no_data(tmp_path):
    """Sau khi restart, tệp đang ghi rỗng nhưng lần chạy trước vẫn còn dữ liệu."""
    active = tmp_path / 'harness.jsonl'
    active.write_text('', encoding='utf-8')
    (tmp_path / 'harness.previous.jsonl').write_text('\n'.join(json.dumps(item) for item in [
        _entry('turn.start', sessionId='s1', data={'maxSteps': 4, 'deadlineSeconds': 10}),
        _entry('turn.end', sessionId='s1', durationMs=500,
               data={'status': 'completed', 'steps': 1, 'textChars': 700}),
    ]) + '\n', encoding='utf-8')
    window = logread.read_window(active)
    assert window['state'] == logread.STATE_OK and len(window['entries']) == 2
    assert rushed_index.compute(window['entries'])['status'] == 'ok'


# --------------------------------------------------------------------------- manifest
def test_manifest_pins_every_field_the_plan_lists():
    manifest = manifest_mod.build_manifest(
        benchmark_name='quality-fixtures', benchmark_version='v1', repo_dir=REPO,
        fixture_ids=['Q1', 'Q2'], provider='antigravity', model='gemini-3.8-flash-high',
        seed=0, temperature=0.0, max_steps=16, deadline_seconds=180, network='off',
        firewall='off', judge_prompt=judge.prompt_info())
    pins = manifest['pins']
    for key in ('repo', 'image', 'provider', 'model', 'seed', 'temperature', 'maxSteps',
                'deadlineSeconds', 'network', 'firewall', 'prompts', 'toolSchema'):
        assert key in pins, key
    assert pins['repo']['commit'] and len(pins['repo']['commit']) >= 7
    # `dirty` phản ánh cây lúc chạy, nên ở đây chỉ khẳng định nó ĐƯỢC ĐO và có kiểu đúng —
    # khẳng định giá trị sẽ đỏ ngay khi cây sạch (đã xảy ra ở vòng soát mã đợt 10).
    assert isinstance(pins['repo']['dirty'], bool)
    assert pins['repo']['dirtyFileCount'] == 0 or pins['repo']['note']
    assert pins['prompts']['judge']['version'] == 'layer2-v1'
    assert len(pins['toolSchema']['sha256']) == 64
    assert manifest['cost']['tokensIn'] is None
    assert manifest['missingPins'] == []


def test_repo_state_sees_an_uncommitted_file_and_says_so(tmp_path):
    """Cây bẩn phải được ghi lại kèm số tệp — dựng bằng một repo tạm, không dựa vào repo thật."""
    import subprocess

    repo = tmp_path / 'repo'
    repo.mkdir()
    for command in (['git', 'init', '-q'], ['git', 'config', 'user.email', 'e@example.com'],
                    ['git', 'config', 'user.name', 'e']):
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    (repo / 'kept.txt').write_text('x')
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-qm', 'first'], cwd=repo, check=True, capture_output=True)

    clean = manifest_mod.repo_state(repo)
    assert clean['dirty'] is False and clean['dirtyFileCount'] == 0 and clean['note'] is None
    (repo / 'moi.txt').write_text('y')
    dirty = manifest_mod.repo_state(repo)
    assert dirty['dirty'] is True and dirty['dirtyFileCount'] == 1
    assert dirty['note'] and '1 tệp chưa commit' in dirty['note']


def test_manifest_names_what_is_missing_instead_of_inventing_it():
    manifest = manifest_mod.build_manifest(
        benchmark_name='bfcl', benchmark_version='v4', repo_dir=REPO, fixture_ids=[])
    assert set(manifest['missingPins']) == {'provider', 'model', 'seed', 'temperature', 'maxSteps',
                                            'network'}
    assert manifest['pins']['image']['missing'] == manifest_mod.UNMEASURED


def test_cost_fields_come_from_the_system_log_entries():
    entries = [
        {'ts': '2026-09-20T00:00:00Z', 'source': 'router', 'event': 'chat.end', 'sessionId': 's1',
         'data': {'inputTokens': 1200, 'outputTokens': 340}},
        {'ts': '2026-09-20T00:00:01Z', 'source': 'harness', 'event': 'turn.end', 'sessionId': 's1',
         'durationMs': 2500, 'data': {'status': 'completed', 'steps': 3, 'textChars': 400}},
        {'ts': '2026-09-20T00:00:02Z', 'source': 'harness', 'event': 'turn.failed', 'sessionId': 's1',
         'code': 'DEADLINE', 'data': {'errorCode': 'DEADLINE'}},
    ]
    cost = manifest_mod.cost_from_entries(entries)
    assert (cost['tokensIn'], cost['tokensOut'], cost['wallTimeMs'], cost['steps']) == (1200, 340, 2500, 3)
    assert cost['retries'] == 1 and cost['missing'] == []


def test_cost_fields_stay_unmeasured_when_the_log_has_no_tokens():
    cost = manifest_mod.cost_from_entries([])
    assert cost['tokensIn'] is None and cost['wallTimeMs'] is None
    assert set(cost['missing']) == {'tokensIn', 'tokensOut', 'wallTimeMs', 'steps'}


def test_real_log_window_is_readable_without_importing_the_harness(tmp_path):
    log = tmp_path / 'harness.jsonl'
    log.write_text('\n'.join(json.dumps(item) for item in [
        _entry('turn.start', sessionId='s1', data={'maxSteps': 4, 'deadlineSeconds': 10}),
        _entry('turn.end', sessionId='s1', durationMs=500, data={'status': 'completed', 'steps': 1,
                                                                 'textChars': 700}),
    ]) + '\n{not json}\n', encoding='utf-8')
    window = logread.read_window(log)
    assert window['state'] == logread.STATE_OK and len(window['entries']) == 2
    assert window['badLines'] == 1
    assert logread.session_ids(window['entries']) == ['s1']


# --------------------------------------------------------------------------- dry run is offline
def test_dry_run_writes_a_plan_and_refuses_to_touch_the_network(capsys, monkeypatch):
    class NoSockets:
        def __init__(self, *args, **kwargs):
            raise AssertionError('đường dry-run không được mở socket')

    monkeypatch.setattr(socket, 'socket', NoSockets)
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: (_ for _ in ()).throw(
        AssertionError('đường dry-run không được mở kết nối')))
    assert run_eval.main(['--dry-run', '--plan-tier', '0']) == run_eval.EXIT_OK
    out = capsys.readouterr().out
    assert 'DRY RUN' in out and 'không gọi model' in out
    assert 'bfcl-simple-subset' in out and '2.00-10.00 USD' in out
    assert 'CHƯA ĐO' in out


def test_dry_run_of_the_quality_track_uses_the_plan_numbers(capsys):
    assert run_eval.main(['--dry-run', '--fixture', 'Q1', '--fixture', 'Q2']) == run_eval.EXIT_OK
    out = capsys.readouterr().out
    assert '2 fixture chất lượng × 3 cấu hình × 1 lần lặp' in out
    assert 'lượt agent = 2 fixture × 3 cấu hình × 1 lần lặp = 6' in out
    assert 'lượt chấm lớp 2 = 12' in out
    assert '0.83-3.33 USD' in out  # 5-20 USD × (2/12)
    assert 'CHƯA ĐO' in out


def test_default_mode_is_dry_run_even_without_the_flag(capsys):
    assert run_eval.main([]) == run_eval.EXIT_OK
    assert 'DRY RUN' in capsys.readouterr().out


def test_list_prints_fixtures_and_tiers(capsys):
    assert run_eval.main(['--list']) == run_eval.EXIT_OK
    out = capsys.readouterr().out
    assert 'Q12' in out and 'Tầng 3' in out and 'Q6' in out


def test_plan_carries_no_model_call_budget_confusion():
    fixtures = fixtureset.load_fixtures()
    tiers = run_eval.load_tiers()
    plan = run_eval.build_plan(fixtures=fixtures, config_count=3, repeat=1, tiers=tiers,
                               tier_id='0')
    assert plan['qualityTrackIncluded'] is False
    assert plan['modelCalls'] == 200  # chỉ BFCL; bộ fixture không nằm trong tầng 0
    assert plan['costUsd'] == [2.0, 10.0]
    tier1 = run_eval.build_plan(fixtures=fixtures, config_count=3, repeat=1, tiers=tiers, tier_id='1')
    assert tier1['qualityTrackIncluded'] is True
    assert tier1['modelCalls'] == 100 + 30 + 30 + 108
    assert tier1['costUsd'] == [61.44, 213.6]


def test_execute_without_opt_in_or_budget_is_refused(capsys, monkeypatch):
    monkeypatch.delenv(guard.SPEND_ENV, raising=False)
    monkeypatch.delenv(guard.BUDGET_ENV, raising=False)
    assert run_eval.main(['--execute']) == run_eval.EXIT_SPEND
    out = capsys.readouterr().out
    assert 'TIÊU TIỀN' in out and guard.SPEND_ENV in out and guard.BUDGET_ENV in out
    assert '--dry-run' in out


def test_execute_refuses_when_only_the_opt_in_is_present(monkeypatch, capsys):
    monkeypatch.setenv(guard.SPEND_ENV, '1')
    monkeypatch.delenv(guard.BUDGET_ENV, raising=False)
    assert run_eval.main(['--execute']) == run_eval.EXIT_SPEND
    assert 'ngân sách' in capsys.readouterr().out


def test_execute_stops_before_spending_when_a_connection_is_missing(monkeypatch, capsys):
    monkeypatch.setenv(guard.SPEND_ENV, '1')
    monkeypatch.setenv(guard.BUDGET_ENV, '5')
    monkeypatch.delenv('BOXFOX_ROUTER_KEY', raising=False)
    monkeypatch.delenv('BOXFOX_HARNESS_ADMIN_TOKEN', raising=False)
    assert run_eval.main(['--execute']) == run_eval.EXIT_CONNECTION
    err = capsys.readouterr().err
    assert 'BOXFOX_ROUTER_KEY' in err


def test_execute_with_everything_set_reaches_the_runner(monkeypatch, capsys, tmp_path):
    """`--execute` nay gọi `runner.run_scenario` thật (P0a) — ở đây thay bằng hàm giả.

    Không có lượt mạng nào: bộ chạy giả trả một ô `infra-failed` để chứng minh ô chưa
    đo ghi `metrics: null`, không ghi 0.
    """
    monkeypatch.setenv(guard.SPEND_ENV, '1')
    monkeypatch.setenv(guard.BUDGET_ENV, '5')
    monkeypatch.setenv('BOXFOX_ROUTER_KEY', 'bf_not-a-real-key')
    monkeypatch.setenv('BOXFOX_HARNESS_ADMIN_TOKEN', 'not-a-real-token')
    monkeypatch.setattr(run_eval.runner, 'run_scenario', lambda *a, **k: {
        'scenarioId': 'Q1', 'configId': 'c1', 'repeat': 0, 'validity': runner.INFRA_FAILED,
        'measured': False, 'metrics': None, 'reruns': 2, 'infraFailureRate': 1.0,
        'infraErrorCodes': {'UPSTREAM_TIMEOUT': 3}, 'errorCode': 'UPSTREAM_TIMEOUT',
        'artifacts': {}})
    code = run_eval.main(['--execute', '--fixture', 'Q1', '--configs', '1',
                          '--budget-usd', '0.01', '--out', str(tmp_path)])
    assert code == run_eval.EXIT_CONNECTION  # không ô nào hợp lệ về chất lượng
    rows = [json.loads(line) for line in
            (tmp_path / 'scores.jsonl').read_text(encoding='utf-8').splitlines()]
    assert rows[0]['metrics'] is None and rows[0]['validity'] == 'infra-failed'
    assert 'TIÊU TIỀN' not in capsys.readouterr().out


def test_judge_execute_is_refused_without_the_opt_in(capsys, monkeypatch):
    monkeypatch.delenv(guard.SPEND_ENV, raising=False)
    monkeypatch.delenv(guard.BUDGET_ENV, raising=False)
    assert judge.main(['--execute', '--budget-usd', '3']) == run_eval.EXIT_SPEND
    assert 'TIÊU TIỀN' in capsys.readouterr().out


def test_eval_sources_import_no_network_library_except_net_py():
    """P0a nới bất biến cũ ĐÚNG một chỗ: chỉ `net.py` được import thư viện mạng.

    `net.py` là cửa duy nhất mở socket (chạy harness, gọi giám khảo, đo 8.7) và chỉ
    được gọi trong thân hàm của đường `--execute` / cổng chi tiền. Mọi mô-đun khác
    trong `scripts/eval/*.py` phải ở lại stdlib-không-mạng để `--dry-run` không mở socket.
    """
    forbidden = ('socket', 'urllib', 'requests', 'httpx', 'aiohttp', 'http', 'ssl', 'ftplib',
                 'smtplib', 'xmlrpc')
    allowed = {'net.py'}
    offenders: list[str] = []
    net_lines: list[str] = []
    for path in sorted(EVAL_DIR.glob('*.py')):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
            stripped = line.strip()
            if not (stripped.startswith('import ') or stripped.startswith('from ')):
                continue
            module = stripped.split()[1].split('.')[0]
            if module not in forbidden:
                continue
            if path.name in allowed:
                net_lines.append(f'{path.name}:{number}: {stripped}')
            else:
                offenders.append(f'{path.name}:{number}: {stripped}')
    assert offenders == [], ('chỉ net.py được dùng thư viện mạng trong scripts/eval: '
                             + '; '.join(offenders))
    # Whitelist phải có thật: net.py chính là chỗ import thư viện mạng.
    assert any('urllib' in line for line in net_lines), 'net.py phải import urllib'
    assert any(line.startswith('net.py') for line in net_lines)


# --------------------------------------------------------------------------- judge
def test_judge_prompt_is_versioned_and_frozen():
    info = judge.prompt_info()
    assert info['version'] == 'layer2-v1'
    assert len(info['sha256']) == 64
    assert judge.load_template(judge.LAYER2_TEMPLATE)['body'].startswith('<!-- version:')


def test_judge_prompt_never_shows_the_oracle_or_the_bad_answer():
    fixture = fixtureset.load_fixtures()['Q1']
    prompt = judge.render_layer2(fixture, 'Đây là câu trả lời thật của agent.')
    assert fixture['request'] in prompt
    assert 'Đây là câu trả lời thật của agent.' in prompt
    for item in fixture['oracle_pass'] + fixture['bad_answer']:
        assert item not in prompt
    assert fixture['case'] not in prompt


def test_judge_prompt_is_blind_to_the_label_by_default():
    answer = 'nội dung nào đó'
    prompt = judge.render_layer2(fixtureset.load_fixtures()['Q5'], answer)
    assert 'Q5' not in prompt
    assert judge.blind_label(answer) in prompt
    assert 'Q5' in judge.render_layer2(fixtureset.load_fixtures()['Q5'], 'x', label='Q5-run1')


def test_judge_layer1_has_no_prompt_and_layer3_is_a_form():
    with pytest.raises(ValueError):
        judge.render(1, fixtureset.load_fixtures()['Q1'], 'x')
    form = judge.render_layer3()
    assert 'Phiếu chấm tay' in form and 'C8' in form and '{{' not in form


def test_judge_answers_are_parsed_and_merged_by_layer():
    payload = json.dumps({'scores': {'C2': 2, 'C3': 1, 'C4': 2, 'C7': 2, 'C8': 1},
                          'why': {}, 'note': 'ok'})
    scores = judge.parse_scores(payload)
    assert scores == {'C2': 2, 'C3': 1, 'C4': 2, 'C7': 2, 'C8': 1}
    merged = judge.merge_layers({'C1': 2, 'C5': 2, 'C6': 2}, scores)
    assert rubric.score_total(merged) == 14
    assert rubric.passes(merged) is True
    with pytest.raises(ValueError):
        judge.parse_scores('không phải json')
    with pytest.raises(ValueError):
        judge.parse_scores(json.dumps({'scores': {'C2': 2}}))
    with pytest.raises(ValueError):
        judge.merge_layers({'C2': 2}, scores)


def test_selecting_configs_and_repeat_scales_the_estimate():
    tiers = run_eval.load_tiers()
    one = run_eval.quality_estimate(12, 3, 1, tiers)
    three = run_eval.quality_estimate(12, 3, 3, tiers)
    assert one['agentRuns'] == 36 and one['judgeCalls'] == 72
    assert three['agentRuns'] == 108 and three['judgeCalls'] == 216
    assert three['totalCostUsd'][1] > one['totalCostUsd'][1]
    assert one['agentCostUsd'] == [5.0, 20.0]


# --------------------------------------------------------------------------- scoreboard
def _raw_results(tmp_path: Path, *, cost: bool = False) -> Path:
    results = tmp_path / 'results'
    results.mkdir()
    (results / 'manifest.json').write_text(json.dumps({
        'manifestVersion': 'eval-manifest-v1',
        'benchmark': {'name': 'quality-fixtures', 'version': 'v1'},
        'fixtures': ['Q1', 'Q2'],
        'pins': {'repo': {'commit': 'a' * 40, 'commitShort': 'aaaaaaa', 'dirty': False},
                 'image': {'ref': 'agentbox-sandbox:latest', 'digest': None,
                           'missing': 'chưa đo'},
                 'provider': 'antigravity', 'model': 'gemini-3.8-flash-high', 'seed': 0,
                 'temperature': 0.0, 'maxSteps': 16, 'deadlineSeconds': 180, 'network': 'off',
                 'firewall': 'off',
                 'prompts': {'judge': {'version': 'layer2-v1', 'sha256': 'b' * 64}},
                 'toolSchema': {'path': 'backend/src/agentbox/agent_core/tool_contracts.py',
                                'sha256': 'c' * 64}},
        'cost': {'tokensIn': 1000 if cost else None, 'tokensOut': 200 if cost else None,
                 'wallTimeMs': None, 'steps': 4, 'retries': 0,
                 'source': 'nhật ký hệ thống'},
        'missingPins': ['image'], 'notes': [],
    }, ensure_ascii=False), encoding='utf-8')
    rows = [
        {'id': 'run-1', 'fixture': 'Q1', 'scores': _scores(), 'outcome': 'quality',
         'judge': {'first': ALL_TWO, 'second': _scores(C2=1)}},
        {'id': 'run-2', 'fixture': 'Q2', 'scores': _scores(C2=0), 'outcome': 'quality',
         'judge': {'first': ALL_TWO, 'second': _scores()}},
        {'id': 'run-3', 'fixture': 'Q2', 'scores': _scores(C8=0), 'outcome': 'rate_limited'},
    ]
    (results / 'scores.jsonl').write_text(
        '\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n', encoding='utf-8')
    return results


def test_scoreboard_is_recomputable_and_verify_catches_drift(tmp_path, capsys):
    results = _raw_results(tmp_path)
    out = tmp_path / 'docs' / 'eval-quality-fixtures.md'
    assert scoreboard.main(['--results', str(results), '--out', str(out)]) == 0
    text = out.read_text(encoding='utf-8')
    assert '| Pass rate (điều kiện cứng + tổng ≥ 9) | 1/2 = 0.5 |' in text
    assert '| Ca hỏng vì hạ tầng (ghi riêng, không vào điểm chất lượng) | 1 |' in text
    assert 'Đồng thuận giám khảo' in text and 'rate_limited' in text
    assert 'chưa đo' in text and 'layer2-v1' in text
    assert scoreboard.main(['--results', str(results), '--out', str(out), '--verify']) == 0
    out.write_text(text + 'sửa tay\n', encoding='utf-8')
    assert scoreboard.main(['--results', str(results), '--out', str(out), '--verify']) == 1
    capsys.readouterr()


def test_scoreboard_renders_a_regression_benchmark_from_cases(tmp_path):
    results = tmp_path / 'results'
    results.mkdir()
    (results / 'manifest.json').write_text(json.dumps(
        {'benchmark': {'name': 'tier0-regression', 'version': '2026-09-20'}, 'pins': {},
         'cost': {}, 'missingPins': ['provider']}, ensure_ascii=False), encoding='utf-8')
    (results / 'cases.jsonl').write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in [
        {'id': 'backend', 'command': '.venv/bin/python -m pytest backend/tests -q', 'status': 'pass',
         'passed': 400, 'failed': 0, 'skipped': 2, 'durationMs': 63630},
        {'id': 'router', 'command': 'cd router && node --test tests/*.test.mjs', 'status': 'fail',
         'passed': 80, 'failed': 5, 'note': 'lỗi tạm thời khi đo'},
    ]) + '\n', encoding='utf-8')
    text = scoreboard.build_document(scoreboard.read_results(results), benchmark='tier0-regression')
    assert 'CHƯA ĐO: chưa có dòng điểm nào' in text
    assert '| router |' in text and 'lỗi tạm thời khi đo' in text
    assert 'provider' in text


def test_scoreboard_refuses_rows_without_scores(tmp_path):
    results = tmp_path / 'results'
    results.mkdir()
    (results / 'scores.jsonl').write_text('{"id": "x"}\n', encoding='utf-8')
    with pytest.raises(ValueError):
        scoreboard.build_document(scoreboard.read_results(results), benchmark='broken')


def test_a_mixed_selection_prices_only_the_quality_fixtures():
    """Bộ chọn có cả Q lẫn R: khối chi phí chỉ tính ca Q, ca R nằm ở khối riêng, 0 lượt model.

    Trước bản sửa, `--plan --fixtures Q1 --fixtures R1` in "2 fixture chất lượng × 3 cấu hình …
    18 lượt model" — bịa ngân sách cho một tầng chỉ có một ca Q (vòng 27, đợt 8).
    """
    fixtures = {code: item for code, item in fixtureset.load_research_fixtures().items()}
    fixtures.update(fixtureset.load_fixtures())
    tiers = run_eval.load_tiers()
    plan = run_eval.build_plan(fixtures={code: fixtures[code] for code in ('Q1', 'R1')},
                               config_count=3, repeat=1, tiers=tiers)
    assert plan['estimate']['fixtures'] == 1, 'chỉ ca họ Q được nhân vào ngân sách'
    assert plan['modelCalls'] == 9, 'một ca Q × 3 cấu hình × 1 lần lặp'
    assert [row['id'] for row in plan['fixtures']] == ['Q1']
    assert [row['id'] for row in plan['researchFixtures']] == ['R1']


def test_the_quality_table_never_lists_a_research_row(capsys):
    """`--list` có cả hai họ: mỗi mã chỉ hiện MỘT lần, dưới đúng tiêu đề của họ nó."""
    assert run_eval.main(['--list', '--fixtures', 'Q1', '--fixtures', 'R1']) == run_eval.EXIT_OK
    out = capsys.readouterr().out
    quality_block, _, rest = out.partition('Fixture research')
    assert 'Q1' in quality_block and '| R1 |' not in quality_block
    assert '| R1 |' in rest
    assert out.count('| R1 |') == 1, 'R1 không được lặp ở hai bảng'
