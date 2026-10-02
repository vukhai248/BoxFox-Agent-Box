"""W10 — benchmark nghiệm thu Work Graph: fixture, rubric, cổng provider, dry-run và oracle.

Kiểm những điều dễ nói suông nhất:

1. 12 fixture S01–S12 (+V06/V07/V10/V13/V14 khi bật `--with-v`) nạp được và đúng schema;
2. rubric theo vai nạp được, baseline hợp lệ, catalog đúng luật đã cài;
3. cổng provider chỉ nhận `opencode`/`space-bunny-free` và từ chối bằng ĐÚNG câu bắt buộc;
4. dry-run in kế hoạch 24 lượt mà KHÔNG mở socket nào (chạy được khi `socket.socket` bị chặn);
5. `--execute` từ chối khi thiếu opt-in/ngân sách/kết nối, và dừng trước khi tiêu tiền;
6. oracle tất định chấm được một lượt đạt và một lượt hỏng, lượt hỏng vẫn nằm trong mẫu số;
7. cổng đạt (≥ 22/24, 0 auto-pass, 0 continuation trùng, 0 URL bịa/diagnostic, 0 đổi provider)
   tính đúng từ transcript tổng hợp.

`scripts/eval` là các module phẳng cạnh nhau (không phải package) nên tệp này tự thêm thư mục
đó vào `sys.path`, giống cách chúng được chạy bằng `python scripts/eval/...`.
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO / 'scripts' / 'eval'
sys.path.insert(0, str(EVAL_DIR))

import work_acceptance_bench as bench  # noqa: E402


# --------------------------------------------------------------------------- fixture + rubric
def test_every_scenario_loads_with_schema_and_oracle_rules():
    scenarios = bench.load_scenarios()
    assert [item['id'] for item in scenarios] == list(bench.SCENARIO_IDS)
    for scenario in scenarios:
        assert scenario['prompt'].strip()
        assert set(scenario['oracle']) <= set(bench.RUBRIC_ROLES)
        for role, rules in scenario['oracle'].items():
            assert rules, f'{scenario["id"]}.{role} phải có ít nhất một luật'
            for rule in rules:
                bench.validate_rule(rule)


def test_v_cases_load_only_with_the_switch():
    with pytest.raises(ValueError, match='thiếu fixture'):
        bench.load_scenarios(directory=str(REPO / 'scripts' / 'eval' / 'fixtures' / 'missing'))
    scenarios = bench.load_scenarios(with_v=True)
    ids = [item['id'] for item in scenarios]
    assert ids[:12] == list(bench.SCENARIO_IDS)
    assert ids[12:] == list(bench.V_CASE_IDS)


def test_fixture_validation_rejects_malformed_documents(tmp_path):
    good = bench.load_scenario(bench.scenario_path('S02'))
    broken = json.loads(json.dumps(good))
    broken['oracle']['main'][0] = {'kind': 'không-có-luật-này'}
    with pytest.raises(ValueError, match='không thuộc'):
        bench.validate_scenario(broken, 'S02.json')
    broken = json.loads(json.dumps(good))
    broken['faults'] = [{'kind': 'output_length', 'unknownKey': 1}]
    with pytest.raises(ValueError, match='có khóa lạ'):
        bench.validate_scenario(broken, 'S02.json')
    broken = json.loads(json.dumps(good))
    broken['faults'] = [{'kind': 'output_length', 'maxChars': -1}]
    with pytest.raises(ValueError, match='số nguyên dương'):
        bench.validate_scenario(broken, 'S02.json')
    broken = json.loads(json.dumps(good))
    broken['workspace']['files'] = [{'path': '../escape.py', 'content': 'x'}]
    with pytest.raises(ValueError, match='tương đối'):
        bench.validate_scenario(broken, 'S02.json')
    broken = json.loads(json.dumps(good))
    broken['expectedState'] = 7
    with pytest.raises(ValueError, match='expectedState'):
        bench.validate_scenario(broken, 'S02.json')


def test_rubric_loads_with_baseline_and_catalog():
    rubric = bench.load_rubric()
    assert set(rubric['roles']) == set(bench.RUBRIC_ROLES)
    assert rubric['baseline']['main'], 'rubric nền của main phải có luật thật'
    for role, rules in rubric['baseline'].items():
        for rule in rules:
            bench.validate_rule(rule)
    for rule in rubric['catalog']:
        bench.validate_rule(rule)
    assert bench.RUBRIC_WEIGHTS == {role: rubric['weights'][role] for role in bench.RUBRIC_ROLES}


# --------------------------------------------------------------------------- cổng provider
def _router_state(provider='opencode', model='space-bunny-free', enabled=True):
    return {'connections': [{'id': 'conn-1', 'providerId': provider, 'enabled': enabled,
                             'models': [{'id': model, 'enabled': enabled}]}]}


def test_provider_guard_accepts_only_opencode_space_bunny():
    route = bench.select_route(_router_state())
    assert route == {'connectionId': 'conn-1', 'modelId': 'space-bunny-free',
                     'providerId': 'opencode'}


@pytest.mark.parametrize('state', [
    _router_state(provider='anthropic'),
    _router_state(model='claude-sonnet'),
    _router_state(enabled=False),
    {'connections': []},
    {},
])
def test_provider_guard_refuses_substitution_with_the_exact_message(state):
    with pytest.raises(bench.ProviderUnavailable) as excinfo:
        bench.select_route(state)
    assert str(excinfo.value).startswith(bench.PROVIDER_GUARD_MESSAGE)
    assert bench.PROVIDER_GUARD_MESSAGE == 'OpenCode space-bunny-free unavailable; no provider substitution'


# --------------------------------------------------------------------------- dry-run / chi tiền
def test_dry_run_lists_24_runs_without_spend(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):  # pragma: no cover - chỉ chạy khi có lỗi
        raise AssertionError('dry-run không được mở socket')

    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(bench.net, 'request_json', forbidden)
    monkeypatch.delenv('BOXFOX_EVAL_ALLOW_SPEND', raising=False)
    monkeypatch.delenv('BOXFOX_EVAL_BUDGET_USD', raising=False)
    code = bench.main(['--out', str(tmp_path)])
    assert code == bench.EXIT_OK
    plan = json.loads((tmp_path / 'plan.json').read_text(encoding='utf-8'))
    assert plan['cellCount'] == 24
    assert len(plan['cells']) == 24
    assert {cell['caseId'] for cell in plan['cells']} == set(bench.SCENARIO_IDS)
    assert plan['provider'] == 'opencode' and plan['model'] == 'space-bunny-free'
    assert plan['configHash']['policyVersion'], 'phải đọc work_policy.VERSION từ repo'
    assert len(plan['configHash']['combined']) == 64
    assert all(cell['deadlineSeconds'] > 0 for cell in plan['cells'])
    out = capsys.readouterr().out
    assert 'dry-run' in out and '24' in out


def test_with_v_adds_the_five_optional_cases(tmp_path):
    code = bench.main(['--out', str(tmp_path), '--with-v'])
    assert code == bench.EXIT_OK
    plan = json.loads((tmp_path / 'plan.json').read_text(encoding='utf-8'))
    assert plan['cellCount'] == 34
    assert plan['withV'] is True


def test_unknown_case_id_is_a_usage_error(tmp_path, capsys):
    assert bench.main(['--out', str(tmp_path), '--cases', 'S01,S99']) == bench.EXIT_USAGE
    assert 'S99' in capsys.readouterr().err
    assert not (tmp_path / 'plan.json').exists()


def test_case_subset_keeps_two_repeats_each(tmp_path):
    assert bench.main(['--out', str(tmp_path), '--cases', 's03,s11']) == bench.EXIT_OK
    plan = json.loads((tmp_path / 'plan.json').read_text(encoding='utf-8'))
    assert plan['cellCount'] == 4
    assert [cell['caseId'] for cell in plan['cells']] == ['S03', 'S03', 'S11', 'S11']


def test_execute_refuses_without_opt_in_and_budget(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('BOXFOX_EVAL_ALLOW_SPEND', raising=False)
    monkeypatch.delenv('BOXFOX_EVAL_BUDGET_USD', raising=False)
    assert bench.main(['--execute', '--out', str(tmp_path)]) == bench.EXIT_SPEND
    assert 'ALLOW_SPEND' in capsys.readouterr().err
    monkeypatch.setenv('BOXFOX_EVAL_ALLOW_SPEND', '1')
    assert bench.main(['--execute', '--out', str(tmp_path)]) == bench.EXIT_SPEND


def test_execute_stops_before_spending_when_connection_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('BOXFOX_EVAL_ALLOW_SPEND', '1')
    monkeypatch.delenv('BOXFOX_ROUTER_KEY', raising=False)
    monkeypatch.delenv('BOXFOX_HARNESS_ADMIN_TOKEN', raising=False)

    def forbidden(*args, **kwargs):  # pragma: no cover - chỉ chạy khi có lỗi
        raise AssertionError('thiếu kết nối thì không được gọi router')

    monkeypatch.setattr(bench.net, 'request_json', forbidden)
    assert bench.main(['--execute', '--budget-usd', '1', '--out', str(tmp_path)]) \
        == bench.EXIT_CONNECTION
    assert 'BOXFOX_ROUTER_KEY' in capsys.readouterr().err


def test_execute_refuses_a_substituted_provider_before_any_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('BOXFOX_EVAL_ALLOW_SPEND', '1')
    monkeypatch.setenv('BOXFOX_ROUTER_KEY', 'bf_test')
    monkeypatch.setenv('BOXFOX_HARNESS_ADMIN_TOKEN', 'test')
    monkeypatch.setattr(bench.net, 'request_json',
                        lambda *args, **kwargs: _router_state(provider='anthropic'))
    monkeypatch.setattr(bench, 'run_cell', lambda *args, **kwargs: pytest.fail('không được chạy lượt nào'))
    code = bench.main(['--execute', '--budget-usd', '1', '--out', str(tmp_path)])
    assert code == bench.EXIT_PROVIDER
    assert bench.PROVIDER_GUARD_MESSAGE in capsys.readouterr().err
    assert not (tmp_path / 'results.json').exists()


# --------------------------------------------------------------------------- oracle tất định
def _cell(case_id, *, run_status='verified', events=None, checks=None, feedback=None, calls=None,
          artifacts=None, children=None, turns=None, faults=None, ship=None):
    scenario = bench.load_scenario(bench.scenario_path(case_id))
    bundle = bench.build_bundle(
        events=events or [], run={'status': run_status}, checks=checks or [],
        feedback=feedback or [], turns=turns or [], children=children or [],
        artifacts=artifacts or [], calls=calls or [{'providerId': 'opencode',
                                                    'modelId': 'space-bunny-free'}],
        config={'session': 'root', 'faults': faults or [], 'ship': ship or {}},
        expected_state=scenario['expectedState'])
    return {'scenario': scenario, 'repeat': 1, 'bundle': bundle, 'validity': 'quality-valid'}


def _plan_artifact():
    return [{'artifactId': 'a-1', 'schema': 'plan', 'text': 'Sửa src/appointments.py:12, chạy python -m pytest -q.'}]


def test_oracle_scores_a_passing_transcript_and_a_failing_one():
    rubric = bench.load_rubric()
    passing = _cell('S02', events=[
        {'kind': 'tool_end', 'sessionId': 'root',
         'data': {'name': 'terminal_exec', 'command': 'python -m pytest -q', 'exitCode': 0}},
    ], checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'execute', 'status': 'pass'}],
        artifacts=_plan_artifact())
    scored = bench.score_bundle(passing['scenario'], rubric, passing['bundle'])
    assert scored['observedState'] == 'verified'
    assert scored['stateMatched'] is True
    assert scored['passed'] is True, scored['roles']

    failing = _cell('S02', run_status='execute_failed', events=[
        {'kind': 'tool_end', 'sessionId': 'root',
         'data': {'name': 'terminal_exec', 'command': 'python -m pytest -q', 'exitCode': 1}},
    ], checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'execute', 'status': 'revise'}])
    scored = bench.score_bundle(failing['scenario'], rubric, failing['bundle'])
    assert scored['stateMatched'] is False
    assert scored['passed'] is False
    assert 'tests_proof' in scored['roles']['testing']['failed']


def test_failures_stay_in_the_denominator_and_the_gate_counts_them():
    rubric = bench.load_rubric()
    cells = [
        _cell('S02', events=[{'kind': 'tool_end', 'sessionId': 'root',
                              'data': {'name': 'terminal_exec', 'command': 'python -m pytest',
                                       'exitCode': 0}}], artifacts=_plan_artifact(),
              checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'execute', 'status': 'pass'}]),
        _cell('S02', run_status='execute_failed'),
    ]
    scoring = bench.evaluate_run(cells, rubric)
    assert scoring['gate']['denominator'] == 2
    assert scoring['gate']['statePassed'] == 1
    assert scoring['gate']['ok'] is False
    assert [item['caseId'] for item in scoring['failures']] == ['S02']
    assert scoring['gate']['passed'] == 1


def test_gate_requires_22_of_24_and_zero_auto_pass_duplicates_leaks_and_provider_switches():
    rubric = bench.load_rubric()
    ok_cell = _cell('S02', events=[{'kind': 'tool_end', 'sessionId': 'root',
                                    'data': {'name': 'terminal_exec', 'command': 'python -m pytest',
                                             'exitCode': 0}}], artifacts=_plan_artifact(),
                    checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'execute', 'status': 'pass'}])
    bad_state = _cell('S02', run_status='needs_revision')
    auto_pass = _cell('S02', checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'tests',
                                      'status': 'pass'}])
    duplicate = _cell('S07', feedback=[{'requestId': 'wr-1', 'childId': 'child-1', 'kind': 'child_interview',
                                        'status': 'ready', 'revision': 1, 'answers': []}],
                      children=[{'id': 'child-1'}], events=[
                          {'kind': 'turn_start', 'sessionId': 'child-1', 'created': 5},
                          {'kind': 'work_notice', 'sessionId': 'root',
                           'data': {'event': 'continuation_completed', 'requestId': 'wr-1',
                                    'childId': 'child-1', 'requestRevision': 1}},
                          {'kind': 'work_notice', 'sessionId': 'root',
                           'data': {'event': 'continuation_completed', 'requestId': 'wr-1',
                                    'childId': 'child-1', 'requestRevision': 1}}])
    leaked = _cell('S02', events=[
        {'kind': 'tool_end', 'sessionId': 'root',
         'data': {'name': 'terminal_exec', 'command': 'python -m pytest', 'exitCode': 0}},
        {'kind': 'assistant', 'sessionId': 'root',
         'data': {'final': True, 'text': 'Lỗi WORK_CHECK_UNAVAILABLE khi chạy.'}},
    ])
    switched = _cell('S02', calls=[{'providerId': 'anthropic', 'modelId': 'claude-sonnet'}],
                     events=[{'kind': 'tool_end', 'sessionId': 'root',
                              'data': {'name': 'terminal_exec', 'command': 'python -m pytest',
                                       'exitCode': 0}}])
    cells = ([ok_cell] * 21 + [bad_state, auto_pass, duplicate, leaked, switched])
    scoring = bench.evaluate_run(cells, rubric)
    gate = scoring['gate']
    assert gate['denominator'] == 26
    assert gate['statePassed'] == 25, 'chỉ lượt sai trạng thái làm giảm statePassed'
    assert gate['passed'] == 21, 'passed đòi hỏi mọi luật của mọi vai trò đều đạt'
    assert gate['autoPass'] == 1
    assert gate['duplicateContinuation'] == 1
    assert gate['fabricatedUrlOrDiagnostic'] == 1
    assert gate['providerSwitches'] == 1
    assert gate['ok'] is False


# --------------------------------------------------------------------------- luật lẻ
def test_evidence_rules_are_deterministic():
    rubric = bench.load_rubric()
    bundle = bench.build_bundle(
        events=[
            {'kind': 'tool_end', 'sessionId': 'root',
             'data': {'name': 'web_fetch', 'result': 'nguồn thật https://example.org/a'}},
            {'kind': 'assistant', 'sessionId': 'root',
             'data': {'final': True, 'text': 'Theo https://example.org/a và https://bịa.example/x.'}},
        ],
        turns=[{'role': 'assistant', 'sessionId': 'root', 'status': 'partial'}],
        config={'session': 'root'})
    ok, detail = bench.score_rule({'kind': 'no_fabricated_url'}, bundle)
    assert ok is False and 'bịa.example' in detail
    ok, _ = bench.score_rule({'kind': 'turn_status_any', 'status_in': ['partial']}, bundle)
    assert ok is True
    assert bench.observe_state(bundle, 'turn') == 'partial'


def test_word_count_no_misdiagnosis_and_claim_labelling_rules():
    long_review = ' '.join(f'từ{index}' for index in range(700))
    bundle = bench.build_bundle(
        events=[
            {'kind': 'notice', 'sessionId': 'root',
             'data': {'code': 'WORK_CHECK_UNAVAILABLE', 'message': 'role plan-review bị tắt'}},
            {'kind': 'assistant', 'sessionId': 'root',
             'data': {'final': True, 'text': 'Lỗi ACL: không có quyền truy cập role này.'}},
        ],
        turns=[{'role': 'research', 'sessionId': 'child-1', 'text': ' '.join(['từ'] * 140)},
               {'role': 'assistant', 'sessionId': 'root', 'text': 'Lỗi ACL: không có quyền.'}],
        checks=[{'checkId': 'c1', 'kind': 'code_review', 'stage': 'review', 'status': 'revise',
                 'output': long_review}],
        artifacts=[{'artifactId': 'a-1', 'schema': 'plan',
                     'text': '```code\n' + ' '.join(['x'] * 900) + '\n```\nngắn gọn.'}],
        config={'session': 'root'})

    ok, detail = bench.score_rule({'kind': 'word_count_max', 'source': 'turn', 'role': 'research',
                                   'max': 120}, bundle)
    assert ok is False and '=140' in detail
    ok, detail = bench.score_rule({'kind': 'word_count_max', 'source': 'check', 'checkId': 'code_review',
                                   'max': 600}, bundle)
    assert ok is False and '=700' in detail
    ok, detail = bench.score_rule({'kind': 'word_count_max', 'source': 'artifact', 'schema': 'plan',
                                   'max': 10}, bundle)
    assert ok is True, 'khối ``` không tính vào prose'
    ok, _ = bench.score_rule({'kind': 'word_count_max', 'source': 'turn', 'role': 'không-có',
                              'max': 10, 'min_sources': 1}, bundle)
    assert ok is False, 'thiếu nguồn văn bản mà luật đòi min_sources thì phải hỏng'

    ok, detail = bench.score_rule({'kind': 'no_misdiagnosis', 'code': 'WORK_CHECK_UNAVAILABLE',
                                   'patterns': ['\\bACL\\b', 'không có quyền']}, bundle)
    assert ok is False and 'code_seen=True' in detail
    ok, _ = bench.score_rule({'kind': 'no_misdiagnosis', 'code': 'WORK_ARTIFACT_UNKNOWN',
                              'patterns': ['\\bACL\\b']}, bundle)
    assert ok is True, 'mã chưa từng xuất hiện thì không kết luận quy sai nguyên nhân'

    labelled = bench.build_bundle(
        events=[
            {'kind': 'notice', 'sessionId': 'root',
             'data': {'type': 'unreviewed_claims', 'tokens': ['src/ghost.py:42']}},
            {'kind': 'assistant', 'sessionId': 'root',
             'data': {'final': True, 'text': 'src/ghost.py:42 chưa kiểm — cần mở file trước.'}},
        ],
        config={'session': 'root'})
    ok, detail = bench.score_rule({'kind': 'unreviewed_claims_labelled'}, labelled)
    assert ok is True, detail
    bare = bench.build_bundle(
        events=[
            {'kind': 'notice', 'sessionId': 'root',
             'data': {'type': 'unreviewed_claims', 'tokens': ['src/ghost.py:42']}},
            {'kind': 'assistant', 'sessionId': 'root',
             'data': {'final': True, 'text': 'src/ghost.py:42 hoạt động đúng.'}},
        ],
        config={'session': 'root'})
    ok, detail = bench.score_rule({'kind': 'unreviewed_claims_labelled'}, bare)
    assert ok is False and 'src/ghost.py:42' in detail
    ok, detail = bench.score_rule({'kind': 'unreviewed_claims_labelled'},
                                  bench.build_bundle(config={'session': 'root'}))
    assert ok is True and 'no unreviewed_claims' in detail


def test_pending_continuations_probe_never_raises():
    class Broken:
        @property
        def continuations(self):
            raise RuntimeError('chưa có bảng outbox')

    assert bench._pending_continuations(Broken()) is False

    class WithRows:
        class continuations:  # noqa: N801 - giả lập service của work_graph
            @staticmethod
            def rows():
                return [{'id': 'o-1'}]

    assert bench._pending_continuations(WithRows()) is True
    assert 'khởi động lại' in bench.RESTART_RESUME_PROMPT


def test_expected_state_matches_lists_and_negation():
    assert bench.state_matches('verified', 'verified') is True
    assert bench.state_matches('needs_revision', 'verified') is False
    assert bench.state_matches('needs_revision', '!verified') is True
    assert bench.state_matches('verified', '!verified') is False
    assert bench.state_matches('drafting', ['drafting', 'discovering']) is True
    assert bench.state_matches('shipped', ['drafting', 'discovering']) is False


def test_same_child_continuation_needs_a_real_resumed_child():
    feedback = [{'requestId': 'wr-1', 'childId': 'child-1', 'kind': 'child_interview',
                 'status': 'ready', 'revision': 2,
                 'answers': [{'confirmedAt': 100.0}]}]
    same = bench.build_bundle(
        feedback=feedback, children=[{'id': 'child-1'}],
        events=[{'kind': 'turn_start', 'sessionId': 'child-1', 'created': 120.0},
                {'kind': 'work_notice', 'sessionId': 'root',
                 'data': {'event': 'continuation_completed', 'requestId': 'wr-1'}}],
        config={'session': 'root'})
    ok, detail = bench.score_rule({'kind': 'same_child_continuation'}, same)
    assert ok is True, detail
    ok, _ = bench.score_rule({'kind': 'no_duplicate_continuation'}, same)
    assert ok is True

    replaced = bench.build_bundle(
        feedback=feedback, children=[{'id': 'child-2'}],
        events=[{'kind': 'turn_start', 'sessionId': 'child-2', 'created': 120.0},
                {'kind': 'work_notice', 'sessionId': 'root',
                 'data': {'event': 'continuation_completed', 'requestId': 'wr-1',
                          'childId': 'child-2'}}],
        config={'session': 'root'})
    ok, detail = bench.score_rule({'kind': 'same_child_continuation'}, replaced)
    assert ok is False and 'bad=' in detail


def test_extra_ship_paths_and_converged_review_rules():
    bundle = bench.build_bundle(
        config={'session': 'root',
                'faults': [{'kind': 'dirty_foreign_file', 'path': 'notes/foreign.md'}],
                'ship': {'commit': 'abc123', 'files': ['src/export.py', 'notes/foreign.md']}},
        checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'execute', 'status': 'pass',
                 'binding': {'codeSnapshot': {'schema': 'work-code/1', 'hash': 'h1'}}}])
    ok, detail = bench.score_rule({'kind': 'no_extra_ship_paths'}, bundle)
    assert ok is False and 'notes/foreign.md' in detail
    ok, detail = bench.score_rule({'kind': 'converged_review', 'checkId': 'tests',
                                   'requireHash': True}, bundle)
    assert ok is True, detail
    clean = bench.build_bundle(
        config={'session': 'root', 'ship': {'files': ['src/export.py']}},
        checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'execute', 'status': 'pass',
                 'binding': {'codeSnapshot': {'schema': 'work-code/1', 'hash': 'h1'}}}])
    ok, _ = bench.score_rule({'kind': 'no_extra_ship_paths'}, clean)
    assert ok is True


def test_finding_and_artifact_rules_read_the_real_check_documents():
    bundle = bench.build_bundle(
        checks=[{'checkId': 'c1', 'kind': 'plan_review', 'stage': 'produce', 'status': 'revise',
                 'findings': [{'id': 'F1', 'claim': 'thiếu hợp đồng dữ liệu'},
                              {'id': 'F2', 'claim': 'thiếu tiêu chí nghiệm thu'}],
                 'blocking': ['F1'], 'downgraded': [{'findingId': 'F2', 'reason': 'NO_RECEIPT'}],
                 'output': 'VERDICT: revise'}],
        artifacts=[{'artifactId': 'a-1', 'schema': 'plan',
                    'text': 'Kế hoạch: sửa src/reports.py:12 và chạy python -m pytest -q.'}],
        config={'session': 'root'})
    ok, detail = bench.score_rule({'kind': 'finding_kept_min', 'min': 1}, bundle)
    assert ok is True and 'kept=2' in detail
    ok, _ = bench.score_rule({'kind': 'finding_cited_min', 'min': 1}, bundle)
    assert ok is True
    ok, detail = bench.score_rule({'kind': 'finding_downgrade_rate_max', 'max': 0.2}, bundle)
    assert ok is False and 'rate=0.33' in detail
    ok, detail = bench.score_rule({'kind': 'artifact_regex_any',
                                   'patterns': ['src/[\\w./-]+\\.py:\\d+']}, bundle)
    assert ok is True, detail
    ok, _ = bench.score_rule({'kind': 'check_status_any', 'checkId': 'plan_review',
                              'status_in': ['revise']}, bundle)
    assert ok is True


# --------------------------------------------------------------------------- live helpers
def test_seed_workspace_writes_long_document_tail_and_dirty_foreign_file(tmp_path):
    scenario = bench.load_scenario(bench.scenario_path('S12'))
    bench.seed_workspace(tmp_path, scenario)
    assert (tmp_path / 'src' / 'export.py').is_file()
    assert (tmp_path / 'notes' / 'foreign.md').is_file()
    long_scenario = bench.load_scenario(bench.scenario_path('S11'))
    other = tmp_path / 'long'
    bench.seed_workspace(other, long_scenario)
    text = (other / 'docs' / 'design-long.md').read_text(encoding='utf-8')
    assert len(text) >= 15000
    assert text.rstrip().endswith('không có result_url.')


def test_config_hash_reads_the_policy_version_instead_of_hardcoding_it():
    info = bench.config_hash()
    assert info['policyVersion'] == bench.policy_version()
    assert len(info['sources']) >= 3
    assert all(len(value) == 64 for value in info['sources'].values())
    assert info['combined'] == bench.config_hash()['combined']


def test_results_json_carries_gate_failures_and_per_role_latency(tmp_path):
    rubric = bench.load_rubric()
    scenario = bench.load_scenario(bench.scenario_path('S02'))
    bundle = bench.build_bundle(
        events=[{'kind': 'tool_end', 'sessionId': 'root',
                 'data': {'name': 'terminal_exec', 'command': 'python -m pytest', 'exitCode': 0}}],
        run={'status': 'verified'},
        checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'execute', 'status': 'pass'}],
        artifacts=_plan_artifact(),
        child_sessions={'root': 'orchestrator', 'child-1': 'research'},
        calls=[{'providerId': 'opencode', 'modelId': 'space-bunny-free', 'sessionId': 'root',
                'tokensIn': 100, 'tokensOut': 20, 'wallMs': 900},
               {'providerId': 'opencode', 'modelId': 'space-bunny-free', 'sessionId': 'child-1',
                'tokensIn': 40, 'tokensOut': 10, 'wallMs': 300}],
        config={'session': 'root'}, expected_state=scenario['expectedState'])
    cell = {'scenario': scenario, 'repeat': 1, 'bundle': bundle, 'validity': 'quality-valid',
            'wallTimeMs': 1500, 'calls': bundle['calls'], 'error': None}
    scoring = bench.evaluate_run([cell], rubric)
    plan = bench.build_plan([scenario], repeats=1, out_root=tmp_path, repo_dir=bench.REPO_DIR,
                            budget_usd=None, with_v=False)
    path = bench.write_results(tmp_path, plan, [cell], scoring, route={'providerId': 'opencode'},
                               extra={'manifest': {'commit': 'abc'}})
    results = json.loads(Path(path).read_text(encoding='utf-8'))
    assert results['schema'] == bench.RESULTS_SCHEMA
    assert results['attempts'] == 1 and results['tokens'] == {'in': 140, 'out': 30}
    assert results['cells'][0]['roleLatency']['research'] == {'calls': 1, 'tokensIn': 40,
                                                              'tokensOut': 10, 'wallMs': 300}
    assert results['roles']['research']['calls'] == 1
    assert results['roles']['main']['calls'] == 1
    assert results['roles']['main']['wallMs'] == 900
    assert results['gate']['denominator'] == 1 and results['failures'] == []
    assert results['configHash']['policyVersion'] == bench.policy_version()
    assert results['manifest']['commit'] == 'abc'


def test_executor_snapshot_runs_and_other_commands_are_blocked(tmp_path):
    from agentbox.agent_core import work_checks  # noqa: PLC0415 - chỉ có ở đường chạy thật

    scenario = bench.load_scenario(bench.scenario_path('S12'))
    bench.seed_workspace(tmp_path, scenario)
    executor = bench.WorkspaceExecutor(tmp_path, scenario)

    async def run(command):
        return await executor.execute('terminal_exec', {'command': command, 'timeout': 90}, 'sid')

    snapshot = asyncio.run(run(work_checks.SNAPSHOT_COMMAND))
    assert snapshot['is_error'] is False and snapshot['exit_code'] == 0
    doc = json.loads(snapshot['content'])
    assert doc['schema'] == 'work-code/1' and len(doc['hash']) == 64

    blocked = asyncio.run(run('rm -rf /'))
    assert blocked['is_error'] is True and 'không chạy' in blocked['error']
    pytest_run = asyncio.run(run('python -m pytest -q'))
    assert pytest_run['exit_code'] == 1, 'workspace S12 cố ý đỏ trước khi repair'


def test_ship_report_reads_the_commit_and_dirty_state(tmp_path):
    scenario = bench.load_scenario(bench.scenario_path('S12'))
    bench.seed_workspace(tmp_path, scenario)
    report = bench.ship_report(tmp_path, {'ship': {}})
    assert report['branch']
    assert 'notes/foreign.md' in report['dirty']
