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
import types
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


def test_every_fixture_declares_an_intent_with_a_reason():
    for scenario in bench.load_scenarios(with_v=True):
        intent = bench.scenario_intent(scenario)
        assert intent['command'] in bench.INTENT_COMMANDS
        assert len(intent['why']) >= 20, f'{scenario["id"]}: lý do chọn intent quá ngắn'


def test_fixture_validation_requires_a_usable_intent():
    good = bench.load_scenario(bench.scenario_path('S02'))
    broken = json.loads(json.dumps(good))
    broken.pop('intent')
    with pytest.raises(ValueError, match='intent là trường bắt buộc'):
        bench.validate_scenario(broken, 'S02.json')
    broken = json.loads(json.dumps(good))
    broken['intent'] = {'command': 'deploy', 'why': 'triển khai thẳng lên máy chủ thật luôn cho nhanh'}
    with pytest.raises(ValueError, match='phải thuộc'):
        bench.validate_scenario(broken, 'S02.json')
    broken = json.loads(json.dumps(good))
    broken['intent'] = {'command': 'mixed'}
    with pytest.raises(ValueError, match='why'):
        bench.validate_scenario(broken, 'S02.json')
    broken = json.loads(json.dumps(good))
    broken['intent'] = {'command': 'mixed', 'why': 'chủ nhà xin triển khai endpoint kèm test thật', 'extra': 1}
    with pytest.raises(ValueError, match='khóa lạ'):
        bench.validate_scenario(broken, 'S02.json')
    normalised = bench.normalize_intent({'command': 'FIX', 'why': 'ca sửa lỗi giữ nguyên hành vi khác'},
                                        'S12.json intent')
    assert normalised == {'command': 'fix', 'why': 'ca sửa lỗi giữ nguyên hành vi khác'}
    with pytest.raises(ValueError, match='object'):
        bench.normalize_intent(['mixed'], 'S02.intent')


def test_intent_commands_match_work_graph_flows():
    from agentbox.agent_core import work_graph  # noqa: PLC0415

    assert bench.INTENT_COMMANDS == work_graph.FLOWS


def test_code_cases_request_execution_and_tests_proof_cases_are_executable():
    """Lượt ở `legacy` (hoặc artifact-only) thì root tự sửa mã và không run nào ra đời.

    S02 với prompt cũ cho `work_runs=0` ⇒ oracle chấm `no_run` 0/1. Fixture phải chọn intent sao cho
    `execution_requested` trả True ở đúng những ca cần thi công thật.
    """
    from agentbox.agent_core import work_graph  # noqa: PLC0415

    for scenario in bench.load_scenarios(with_v=True):
        command = bench.intent_command(scenario)
        run = {'flow': command, 'intent': {'command': command}, 'goal': scenario['prompt']}
        session = {'messages': [{'role': 'user', 'content': scenario['prompt']}]}
        # Hàm thuần: `self` không được dùng, gọi không gắn instance cho khỏi dựng WorkGraph thật.
        executable = work_graph.WorkGraph.execution_requested(None, session, run)
        if command in ('fix', 'mixed'):
            assert executable is True, f'{scenario["id"]}: intent /{command} nhưng run bị xếp artifact-only'
        needs_tests = any(rule['kind'] == 'tests_proof'
                          for rules in scenario['oracle'].values() for rule in rules)
        if needs_tests:
            assert executable is True, f'{scenario["id"]}: oracle cần tests_proof nhưng run không được thi công'


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


# --------------------------------------------------------------------------- shard / gộp shard
def test_shards_cover_every_planned_cell_without_overlap(tmp_path):
    full = bench.build_plan(bench.load_scenarios(), out_root=tmp_path)
    keys = [(cell['caseId'], cell['repeat']) for cell in full['cells']]
    assert len(keys) == 24
    for count in (1, 2, 3, 5, 7):
        seen = []
        for index in range(1, count + 1):
            shard = bench.shard_cells(full['cells'], index, count)
            assert shard, f'shard {index}/{count} rỗng'
            seen += [(cell['caseId'], cell['repeat']) for cell in shard]
        assert sorted(seen) == sorted(keys), f'{count} shard không phủ đủ 24 lượt'
        assert len(seen) == len(set(seen)), f'{count} shard bị trùng lượt'
    assert bench.parse_shard('2/4') == (2, 4)
    for bad in ('0/4', '5/4', '4', 'a/b', '2/0', '1/65', '2/4/6'):
        with pytest.raises(ValueError):
            bench.parse_shard(bad)


def test_shard_dry_run_keeps_both_repeats_together(tmp_path):
    assert bench.main(['--out', str(tmp_path), '--shard', '2/3']) == bench.EXIT_OK
    plan = json.loads((tmp_path / 'plan.json').read_text(encoding='utf-8'))
    assert plan['cellCount'] == 8
    assert plan['shard'] == {'index': 2, 'count': 3, 'cellsTotal': 24}
    assert [cell['caseId'] for cell in plan['cells']] \
        == ['S05', 'S05', 'S06', 'S06', 'S07', 'S07', 'S08', 'S08']
    assert all(cell['intent'] in bench.INTENT_COMMANDS for cell in plan['cells'])
    assert bench.main(['--out', str(tmp_path), '--shard', '4/3']) == bench.EXIT_USAGE


def _observed_state(expected):
    if isinstance(expected, list):
        return expected[0]
    return 'needs_revision' if expected.startswith('!') else expected


def _shard_docs(tmp_path, *, shards=3, bad=(), hard=None):
    """results.json giả cho từng shard: đủ trường `merge_results` cần, không dựng bundle."""
    scenarios = bench.load_scenarios()
    docs, paths = [], []
    for index in range(1, shards + 1):
        plan = bench.build_plan(scenarios, out_root=tmp_path / f'shard{index}', shard=(index, shards))
        cells = []
        for cell in plan['cells']:
            key = (cell['caseId'], cell['repeat'])
            failed = {role: [] for role in bench.RUBRIC_ROLES}
            if hard and key == (hard[0], hard[1]):
                failed[hard[2]].append(hard[3])
            observed = 'no_run' if key in bad else _observed_state(cell['expectedState'])
            state_ok = bench.state_matches(observed, cell['expectedState'])
            cells.append({'caseId': cell['caseId'], 'repeat': cell['repeat'], 'intent': cell['intent'],
                          'expectedState': cell['expectedState'], 'observedState': observed,
                          'passed': state_ok and not any(failed.values()),
                          'score': 100.0 if state_ok else 0.0, 'failedRules': failed,
                          'validity': 'quality-valid', 'error': None, 'runStatus': observed,
                          'wallTimeMs': 1000, 'tokensIn': 10, 'tokensOut': 5, 'modelCalls': 1,
                          'roleLatency': {}, 'steps': 3, 'children': 1})
        roles = {role: {'rules': 4, 'passed': 4, 'rate': 1.0, 'calls': 2, 'tokensIn': 20,
                        'tokensOut': 10, 'wallMs': 2000} for role in bench.RUBRIC_ROLES}
        doc = {'schema': bench.RESULTS_SCHEMA, 'plan': plan, 'route': {'providerId': 'opencode'},
               'configHash': plan['configHash'], 'cells': cells, 'roles': roles, 'gate': {},
               'failures': [], 'tokens': {'in': 240, 'out': 120}, 'wallTimeMs': 24000,
               'cost': {}, 'attempts': len(cells), 'manifest': {'benchmark': 'work-acceptance'}}
        path = bench._write_json(tmp_path / f'shard{index}' / 'results.json', doc)
        docs.append(doc)
        paths.append(path)
    return docs, paths


def test_merge_of_three_shards_rebuilds_the_full_gate(tmp_path):
    docs, paths = _shard_docs(tmp_path)
    merged = bench.merge_results(docs, paths=paths)
    assert [cell['caseId'] for cell in merged['cells']] == sorted(cell['caseId'] for cell in merged['cells'])
    assert [(cell['caseId'], cell['repeat']) for cell in merged['cells']][:2] == [('S01', 1), ('S01', 2)]
    assert merged['attempts'] == 24 and merged['plan']['cellCount'] == 24
    assert 'shard' not in merged['plan'] and merged['plan']['shards'] == [str(path) for path in paths]
    assert merged['mergedFrom'] == [str(path) for path in paths]
    assert merged['manifest']['shards'] == 3
    assert merged['roles']['main'] == {'rules': 12, 'passed': 12, 'rate': 1.0, 'calls': 6,
                                       'tokensIn': 60, 'tokensOut': 30, 'wallMs': 6000}
    assert merged['tokens'] == {'in': 240, 'out': 120}
    assert merged['gate']['denominator'] == 24 and merged['gate']['statePassed'] == 24
    assert merged['gate']['ok'] is True and merged['failures'] == []


def test_merged_gate_fails_on_two_misses_or_any_hard_counter(tmp_path):
    docs, paths = _shard_docs(tmp_path, bad={('S07', 1), ('S12', 2)})
    merged = bench.merge_results(docs, paths=paths)
    assert merged['gate']['statePassed'] == 22 and merged['gate']['ok'] is True
    assert {item['caseId'] for item in merged['failures']} == {'S07', 'S12'}
    docs, paths = _shard_docs(tmp_path, bad={('S07', 1), ('S12', 2), ('S02', 1)})
    assert bench.merge_results(docs, paths=paths)['gate']['ok'] is False
    for role, kind, field in (('flow', 'no_duplicate_continuation', 'duplicateContinuation'),
                              ('main', 'no_auto_pass', 'autoPass'),
                              ('research', 'no_fabricated_url', 'fabricatedUrlOrDiagnostic'),
                              ('reviewer', 'same_child_continuation', 'sameChild'),
                              ('testing', 'provider_unchanged', 'providerSwitches')):
        docs, paths = _shard_docs(tmp_path, shards=1, hard=('S02', 1, role, kind))
        merged = bench.merge_results(docs, paths=paths)
        assert merged['gate'][field] == 1 and merged['gate']['ok'] is False, kind
        assert merged['gate']['statePassed'] == 24, kind


def test_merge_refuses_duplicates_missing_shards_and_stale_results(tmp_path):
    docs, paths = _shard_docs(tmp_path)
    with pytest.raises(ValueError, match='trùng lượt S01 r1'):
        bench.merge_results([docs[0], docs[0]], paths=paths[:2])
    with pytest.raises(ValueError, match='gộp thiếu/lạ lượt'):
        bench.merge_results(docs[:2], paths=paths[:2])
    stale = json.loads(json.dumps(docs[0]))
    for cell in stale['cells']:
        cell.pop('failedRules')
    with pytest.raises(ValueError, match='thiếu `failedRules`'):
        bench.merge_results([stale, docs[1], docs[2]], paths=paths)
    drifted = json.loads(json.dumps(docs[1]))
    drifted['plan']['configHash'] = {'policyVersion': 'work-checks/11', 'combined': 'x' * 64}
    with pytest.raises(ValueError, match='khác cấu hình'):
        bench.merge_results([docs[0], drifted, docs[2]], paths=paths)
    relabelled = json.loads(json.dumps(docs[1]))
    relabelled['cells'][0]['intent'] = 'research'
    with pytest.raises(ValueError, match='intent lệch'):
        bench.merge_results([docs[0], relabelled, docs[2]], paths=paths)
    with pytest.raises(ValueError, match='schema'):
        bench.merge_results([{'schema': 'khác'}, docs[1]], paths=paths[:2])


def test_merge_cli_writes_the_merged_results(tmp_path, capsys):
    docs, paths = _shard_docs(tmp_path)
    code = bench.main(['--merge', ','.join(str(path.parent) for path in paths),
                       '--out', str(tmp_path / 'merged')])
    assert code == bench.EXIT_OK
    out = capsys.readouterr().out
    assert 'gộp 3 shard → 24 lượt' in out and 'cổng đạt: ĐẠT' in out
    merged = json.loads((tmp_path / 'merged' / 'results.json').read_text(encoding='utf-8'))
    assert merged['attempts'] == 24 and merged['gate']['ok'] is True
    assert bench.main(['--merge', str(paths[0].parent)]) == bench.EXIT_USAGE
    assert bench.main(['--merge', str(paths[0].parent), '--out', str(paths[0].parent)]) == bench.EXIT_USAGE
    assert bench.main(['--merge', str(paths[0].parent), '--out', str(tmp_path / 'x'),
                       '--shard', '1/2']) == bench.EXIT_USAGE


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
        {'kind': 'tool_end', 'sessionId': 'root', 'data': {'id': 'call_414', 'name': 'terminal_exec', 'args': {'command': 'python -m pytest -q'}, 'result': {'exit_code': 0, 'is_error': False, 'content': 'ok'}}},
    ], checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'execute', 'status': 'pass'}],
        artifacts=_plan_artifact())
    scored = bench.score_bundle(passing['scenario'], rubric, passing['bundle'])
    assert scored['observedState'] == 'verified'
    assert scored['stateMatched'] is True
    assert scored['passed'] is True, scored['roles']

    failing = _cell('S02', run_status='execute_failed', events=[
        {'kind': 'tool_end', 'sessionId': 'root', 'data': {'id': 'call_414', 'name': 'terminal_exec', 'args': {'command': 'python -m pytest -q'}, 'result': {'exit_code': 1, 'is_error': True, 'content': 'ok'}}},
    ], checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'execute', 'status': 'revise'}])
    scored = bench.score_bundle(failing['scenario'], rubric, failing['bundle'])
    assert scored['stateMatched'] is False
    assert scored['passed'] is False
    assert 'tests_proof' in scored['roles']['testing']['failed']


def test_failures_stay_in_the_denominator_and_the_gate_counts_them():
    rubric = bench.load_rubric()
    cells = [
        _cell('S02', events=[{'kind': 'tool_end', 'sessionId': 'root',
                              'data': {'id': 'call_472', 'name': 'terminal_exec', 'args': {'command': 'python -m pytest'}, 'result': {'exit_code': 0, 'is_error': False, 'content': 'ok'}}}], artifacts=_plan_artifact(),
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
                                    'data': {'id': 'call_472', 'name': 'terminal_exec', 'args': {'command': 'python -m pytest'}, 'result': {'exit_code': 0, 'is_error': False, 'content': 'ok'}}}], artifacts=_plan_artifact(),
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
         'data': {'id': 'call_472', 'name': 'terminal_exec', 'args': {'command': 'python -m pytest'}, 'result': {'exit_code': 0, 'is_error': False, 'content': 'ok'}}},
        {'kind': 'assistant', 'sessionId': 'root',
         'data': {'final': True, 'text': 'Lỗi WORK_CHECK_UNAVAILABLE khi chạy.'}},
    ])
    switched = _cell('S02', calls=[{'providerId': 'anthropic', 'modelId': 'claude-sonnet'}],
                     events=[{'kind': 'tool_end', 'sessionId': 'root',
                              'data': {'id': 'call_472', 'name': 'terminal_exec', 'args': {'command': 'python -m pytest'}, 'result': {'exit_code': 0, 'is_error': False, 'content': 'ok'}}}])
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
                 'data': {'id': 'call_472', 'name': 'terminal_exec', 'args': {'command': 'python -m pytest'}, 'result': {'exit_code': 0, 'is_error': False, 'content': 'ok'}}}],
        run={'status': 'verified'},
        checks=[{'checkId': 'c1', 'kind': 'tests', 'stage': 'execute', 'status': 'pass'}],
        artifacts=_plan_artifact(),
        child_sessions={'root': 'orchestrator', 'child-1': 'research'},
        calls=[{'providerId': 'opencode', 'modelId': 'space-bunny-free', 'sessionId': 'root',
                'tokensIn': 100, 'tokensOut': 20, 'wallMs': 900},
               {'providerId': 'opencode', 'modelId': 'space-bunny-free', 'sessionId': 'child-1',
                'tokensIn': 40, 'tokensOut': 10, 'wallMs': 300},
               # W10.M2 (soát vòng 2): lượt gọi không rõ phiên gọi phải vào rổ `unknown`,
               # không được thổi vào `main`.
               {'providerId': 'opencode', 'modelId': 'space-bunny-free', 'sessionId': None,
                'tokensIn': 7, 'tokensOut': 0, 'wallMs': 50}],
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
    assert results['attempts'] == 1 and results['tokens'] == {'in': 147, 'out': 30}
    assert results['cells'][0]['callsWithoutSessionId'] == 1
    assert results['roles']['unknown']['calls'] == 1
    # Vòng soát 2 — metadata từng ô phải đi qua `write_results`, không chỉ nằm trong bundle.
    row = results['cells'][0]
    assert row['stateMatched'] is True and row['measurementInvalid'] is False
    assert row['phaseNotReached'] == [] and 'budget' in row
    assert results['gate']['measurementInvalid'] == 0
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


def test_run_cell_sets_the_intent_before_the_turn(tmp_path, monkeypatch):
    """`set_intent` phải chạy trước `rt.start`: `work_scope.begin_turn` mới thấy `config.workIntent`."""
    order = []

    class FakeGraph:
        @staticmethod
        def enabled():
            return True

        @staticmethod
        def service(rt):
            return FakeGraph()

        @staticmethod
        def set_intent(rt, session, command, text):
            order.append(('set_intent', command, text))
            rt.store.update_config(session['id'], {'workIntent': {'command': command}})
            return {'command': command, 'flow': command, 'text': text}

    class FakeStore:
        def __init__(self, path):
            self.path = path
            self.config = {}
            self.db = types.SimpleNamespace(close=lambda: order.append(('close',)))

        def update_config(self, sid, config):
            order.append(('update_config', sid))
            self.config = dict(config)

    class FakeRuntime:
        def __init__(self, store, executor, client):
            self.store, self.executor, self.client = store, executor, client

        def create(self, config):
            order.append(('create',))
            return {'id': 'sess-1', 'config': dict(config)}

    class FakeRouter:
        def __init__(self, url):
            self.url = url

    async def fake_drive(rt, graph, work_feedback, sid, scenario, *, deadline_seconds, handles=None):
        order.append(('drive', rt.store.config.get('workIntent', {}).get('command')))
        assert handles is not None and handles['store'] is rt.store, \
            'run_cell phải truyền handles sống để sau restart còn gom bundle đúng bộ mới'
        order.append(('handles', id(handles['store'])))
        return ['ghi chú từ lượt chạy']

    def fake_bundle(store, graph, sid, scenario, client, *, error=None, notes=None, workspace=None,
                    budget=None):
        order.append(('bundle', list(notes or []), id(store)))
        return {'run': {'status': 'verified'}, 'notes': list(notes or []), 'budget': budget}

    monkeypatch.setattr(bench, '_live_imports', lambda: (
        types.SimpleNamespace(HarnessRuntime=FakeRuntime, RouterClient=FakeRouter), FakeGraph,
        types.SimpleNamespace(), types.SimpleNamespace(SessionStore=FakeStore)))
    monkeypatch.setattr(bench, 'seed_workspace', lambda *args, **kwargs: None)
    monkeypatch.setattr(bench, 'RecordingClient', lambda *args, **kwargs: types.SimpleNamespace(calls=[]))
    monkeypatch.setattr(bench, 'WorkspaceExecutor', lambda *args, **kwargs: None)
    monkeypatch.setattr(bench, 'drive_session', fake_drive)
    monkeypatch.setattr(bench, 'collect_bundle', fake_bundle)
    monkeypatch.setattr(bench.runner, 'classify_validity', lambda *args, **kwargs: 'invalid')
    scenario = bench.load_scenario(bench.scenario_path('S02'))
    cell = asyncio.run(bench.run_cell(scenario, 2, out_dir=tmp_path,
                                      route={'connectionId': 'conn-1', 'providerId': 'opencode'},
                                      router_url='http://127.0.0.1:1', deadline_seconds=30))
    steps = [item[0] for item in order if item[0] in ('set_intent', 'drive')]
    assert steps == ['set_intent', 'drive'], 'intent phải được đặt TRƯỚC lượt chạy'
    assert len([item for item in order if item[0] == 'set_intent']) == 1
    intent_call = next(item for item in order if item[0] == 'set_intent')
    assert (intent_call[1], intent_call[2]) == ('mixed', scenario['prompt'])
    assert next(item for item in order if item[0] == 'drive')[1] == 'mixed'
    assert cell['intent'] == {'command': 'mixed', 'flow': 'mixed', 'text': scenario['prompt']}
    assert cell['bundle']['notes'][0].startswith('intent: /mixed')
    handles_id = next(item for item in order if item[0] == 'handles')[1]
    bundle_store_id = next(item for item in order if item[0] == 'bundle')[2]
    assert bundle_store_id == handles_id, 'collect_bundle phải nhận store trong handles (W10.M2)'
    # Fixture S02 không khai budget riêng: yêu cầu = mặc định 80 bước + hạn driver 30 s; hạn
    # driver ngoài được ghi riêng để oracle tách requested/effective/driver (H5.3).
    assert cell['bundle']['budget'] == {'maxSteps': 80, 'deadlineSeconds': 30,
                                        'driverDeadlineSeconds': 30}


def test_run_cell_refuses_when_work_graph_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, '_live_imports', lambda: (
        types.SimpleNamespace(), types.SimpleNamespace(enabled=lambda: False),
        types.SimpleNamespace(), types.SimpleNamespace()))
    scenario = bench.load_scenario(bench.scenario_path('S02'))
    with pytest.raises(ValueError, match='BOXFOX_WORK_GRAPH=off'):
        asyncio.run(bench.run_cell(scenario, 1, out_dir=tmp_path, route={'connectionId': 'c'},
                                   router_url='http://127.0.0.1:1', deadline_seconds=30))


def test_require_work_graph_stops_the_execute_path(monkeypatch, capsys):
    monkeypatch.setattr(bench, '_live_imports', lambda: (
        types.SimpleNamespace(), types.SimpleNamespace(enabled=lambda: False),
        types.SimpleNamespace(), types.SimpleNamespace()))
    with pytest.raises(ValueError, match='no_run'):
        bench.require_work_graph()


# --- review vòng 2 (oracle): ba lỗ hổng đã bịt ---------------------------------------------------
def _real_event(command, exit_code, name='terminal_exec'):
    return {'kind': 'tool_end', 'sessionId': 'root',
            'data': {'id': 'call_1', 'name': name, 'args': {'command': command},
                     'result': {'exit_code': exit_code, 'is_error': exit_code != 0, 'content': 'out'}}}


def test_tests_proof_reads_the_real_tool_end_payload():
    """Finding 1: mã thoát nằm trong `result.exit_code`, lệnh nằm trong `args.command`."""
    bundle = bench.build_bundle(events=[_real_event('python -m pytest -q', 0)])
    assert bench._tests_proof(bundle, ['python -m pytest'])[0] is True
    flat = bench.build_bundle(events=[{'kind': 'tool_end', 'data': {
        'name': 'terminal_exec', 'command': 'python -m pytest -q', 'exitCode': 0}}])
    assert bench._tests_proof(flat, ['python -m pytest'])[0] is False, 'dạng cũ không phải bằng chứng'
    assert bench._tests_proof(bundle, ['vitest'])[0] is False, 'lệnh khác không tính'


def test_no_auto_pass_fires_on_a_real_check_document():
    """Finding 2: check doc thật có `kind == 'tests'` và `stage` ∈ {produce, execute}."""
    scenario = bench.load_scenario(bench.scenario_path('S11'))
    check = {'checkId': 'c1', 'nodeId': 'R1', 'kind': 'tests', 'stage': 'execute', 'status': 'pass'}
    without = bench.build_bundle(events=[], checks=[check])
    ok, detail = bench.score_rule({'kind': 'no_auto_pass'}, without)
    assert ok is False and 'c1' in detail
    with_proof = bench.build_bundle(events=[_real_event('python -m pytest -q', 0)], checks=[check])
    assert bench.score_rule({'kind': 'no_auto_pass'}, with_proof)[0] is True
    assert scenario['id'] == 'S11'


def test_a_cell_without_a_run_can_never_match_a_negative_state():
    """Finding 3: `no_run` từng khớp `!verified` và được tính là đạt trạng thái."""
    rubric = bench.load_rubric()
    scenario = bench.load_scenario(bench.scenario_path('S11'))
    assert scenario['expectedState'] == '!verified'
    empty = bench.build_bundle(events=[], run={}, expected_state='!verified')
    scored = bench.score_bundle(scenario, rubric, empty)
    assert scored['observedState'] == 'no_run'
    assert scored['stateMatched'] is False and scored['passed'] is False
    assert scored['missing'] == []

    incomplete = bench.build_bundle(events=[], run={'status': 'verified'}, expected_state='!verified',
                                    missing=['run: boom'])
    assert bench.score_bundle(scenario, rubric, incomplete)['stateMatched'] is False


def test_rescore_rebuilds_scores_from_saved_bundles(tmp_path):
    """Oracle đổi thì chấm lại từ bundle: lượt `no_run` không còn được tính là đạt trạng thái."""
    docs, paths = _shard_docs(tmp_path, shards=1, bad={('S11', 1)})
    doc = docs[0]
    runs = tmp_path / 'shard1' / 'runs'
    for cell in doc['cells']:
        directory = runs / f"{cell['caseId']}-r{cell['repeat']}"
        directory.mkdir(parents=True, exist_ok=True)
        events = []
        if cell['caseId'] == 'S02':
            events = [{'kind': 'tool_end', 'sessionId': 'root',
                       'data': {'id': 'call_1', 'name': 'terminal_exec', 'args': {'command': 'python -m pytest -q'},
                                'result': {'exit_code': 0, 'is_error': False, 'content': 'ok'}}}]
        run = {} if cell['caseId'] == 'S11' else {'status': _observed_state(cell['expectedState'])}
        bundle = bench.build_bundle(events=events, run=run, checks=[], calls=[])
        bench._write_json(directory / 'bundle.json', {'bundle': bundle, 'validity': 'quality-valid', 'error': None})
    merged = bench.merge_results(docs, paths=paths, rescore=True)
    by_key = {(cell['caseId'], cell['repeat']): cell for cell in merged['cells']}
    assert merged['plan']['rescored']['cells'] == 24
    assert all(cell['rescored'] is True for cell in merged['cells'])
    assert by_key[('S11', 1)]['observedState'] == 'no_run'
    assert by_key[('S11', 1)]['passed'] is False, 'no_run không được đạt'
    # 20 = 24 − S05 r1/r2 (kỳ vọng theo `turn`, bundle giả không có turn) − S11 r1/r2 (`no_run`:
    # trước đây `no_run` khớp `!verified` nên hai ô này bị tính là đạt trạng thái → 22 sai).
    assert merged['gate']['statePassed'] == 20
    assert merged['gate']['stateObserved'] == 22, 'stateObserved là số thô để đối chiếu, không dùng làm cổng'
    assert merged['gate']['ok'] is False
    # Vòng soát 2 — `rescore_cells` cũng phải giữ metadata phép đo của từng ô.
    for cell in merged['cells']:
        assert cell['measurementInvalid'] is False and 'budget' in cell
        assert isinstance(cell['phaseNotReached'], list)


def test_rescore_requires_the_saved_bundles(tmp_path):
    docs, paths = _shard_docs(tmp_path, shards=1)
    with pytest.raises(ValueError, match='thiếu bundle.json'):
        bench.merge_results(docs, paths=paths, rescore=True)


# --- W10.M1/M2/M3 (audit H1–H5): phép đo và oracle sau đối chiếu -------------------------------


def test_safe_events_reads_every_page_and_marks_read_errors():
    """H1 — `store.events()` chỉ trả một trang: export phải đọc hết, không cắt ở 500."""

    class FakeStore:
        EVENTS_PAGE = 500

        def __init__(self, total, fail=False):
            self.fail = fail
            self.rows = [{'seq': index, 'type': 'assistant', 'data': {'text': str(index)},
                          'created': float(index)} for index in range(1, total + 1)]

        def events(self, sid, after=0, limit=None):
            if self.fail:
                raise RuntimeError('Cannot operate on a closed database')
            return [row for row in self.rows if row['seq'] > after][:self.EVENTS_PAGE]

        def events_page(self, sid, after=0, limit=None):
            """Cùng hợp đồng con trỏ với `SessionStore.events_page()` thật."""
            rows = self.events(sid, after, limit)
            return {'events': rows, 'hasMore': len(rows) == self.EVENTS_PAGE and bool(rows),
                    'nextAfter': rows[-1]['seq'] if rows else int(after or 0)}

    rows = bench._safe_events(FakeStore(1200), 'root')
    assert [row['seq'] for row in rows][:2] == [1, 2]
    assert len(rows) == 1200, 'phải đọc hết mọi trang, không dừng ở 500'
    assert rows[-1]['data'] == {'text': '1200'}, 'marker cuối lượt phải còn'
    assert all(row['sessionId'] == 'root' for row in rows)

    boundary = bench._safe_events(FakeStore(500), 'root')
    assert len(boundary) == 500, 'đúng 500 (đúng biên một trang) vẫn phải thoát vòng lặp'

    broken = bench._safe_events(FakeStore(0, fail=True), 'root')
    assert len(broken) == 1 and broken[0]['kind'] == 'events_read_error'
    assert 'closed database' in broken[0]['data']['error']


def test_drive_session_swaps_handles_after_restart(monkeypatch):
    """H2 — sau restart, caller phải gom bundle từ store/runtime MỚI, không đọc DB đã đóng."""
    order = []
    new_store, new_graph = object(), object()

    class FakeRt:
        def __init__(self, cards=True):
            self.store = object()
            self.tasks = {}
            self.cards = cards

        def start(self, sid, prompt):
            order.append(('start', prompt))
            return asyncio.get_event_loop().create_future()

        def pending_for(self, sid):
            if not self.cards:
                return []
            return [{'kind': 'interview', 'decisionId': 'd1-r1', 'requestId': 'd1', 'revision': 1,
                     'questions': []}]

        @staticmethod
        def resolve_decision(*args, **kwargs):
            order.append(('resolve', args))

    new_rt = FakeRt(cards=False)

    class FakeFeedback:
        @staticmethod
        async def pump(rt):
            return []

    class FakeGraph:
        @staticmethod
        def runs(sid, limit=20):
            return [{'status': 'verified'}]

        class continuations:
            @staticmethod
            def rows():
                return []

    new_graph = FakeGraph()

    def fake_restart(rt, sid, notes):
        order.append(('restart', sid))
        return new_store, new_rt, new_graph

    monkeypatch.setattr(bench, '_restart_session', fake_restart)
    handles = {'store': object(), 'graph': object(), 'rt': FakeRt()}
    scenario = {'id': 'S09', 'prompt': 'p', 'faults': [{'kind': 'restart_while_waiting'}]}
    notes = asyncio.run(bench.drive_session(handles['rt'], FakeGraph(), FakeFeedback(), 'sid-1',
                                            scenario, deadline_seconds=1, handles=handles))
    assert ('restart', 'sid-1') in order
    assert handles['store'] is new_store and handles['graph'] is new_graph \
        and handles['rt'] is new_rt, 'handles phải trỏ bộ mới để collect_bundle đọc DB đang mở'
    assert any('khởi động lại harness' in note for note in notes)


def test_recording_client_resolves_the_caller_session():
    """H3 — danh tính phiên gọi đọc từ `runtime.tasks` theo task hiện tại, không từ route."""

    class Inner:
        @staticmethod
        async def complete(messages, tools, route, **kwargs):
            return {'choices': [{'message': {'content': 'x'}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}

    async def drive():
        runtime = types.SimpleNamespace(tasks={})
        client = bench.RecordingClient(Inner(), {'id': 'S06', 'faults': []})
        client.runtime = runtime
        runtime.tasks['child-1'] = asyncio.current_task()
        caller = client.caller_session()
        await client.complete([], [], {'connectionId': 'c', 'modelId': 'space-bunny-free'})
        client.runtime = None
        unknown = client.caller_session()
        await client.complete([], [], {'connectionId': 'c', 'modelId': 'space-bunny-free'})
        return caller, unknown, client.calls

    caller, unknown, calls = asyncio.run(drive())
    assert caller == 'child-1'
    assert unknown is None, 'không tra được thì trả None (unknown), không mặc định về main'
    assert [call['sessionId'] for call in calls] == ['child-1', None]


def test_claim_fault_never_targets_main_and_is_recorded_when_unknown():
    """H3 — fault claim_unsourced chỉ bắn vào helper child; thiếu danh tính thì ghi lỗi đo."""

    class Inner:
        @staticmethod
        async def complete(messages, tools, route, **kwargs):
            return {'choices': [{'message': {'content': 'đã kiểm src/ghost.py:42'},
                                 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}

    async def drive():
        client = bench.RecordingClient(Inner(), {'id': 'S06', 'faults': [
            {'kind': 'claim_unsourced', 'calls': 1, 'text': 'ghost-sentinel-7f3a'}]})
        client.root_session_id = 'root'
        client.runtime = types.SimpleNamespace(tasks={})
        first = await client.complete([], [], {'connectionId': 'c'})   # caller None (main bị cấm)
        assert 'ghost-sentinel-7f3a' not in str(first['choices'][0]['message']['content'])
        assert 'fault' not in client.calls[-1]
        assert client.claim_left == 1 and client.fault_notes, 'phải ghi lỗi đo khi không rõ caller'
        client.runtime.tasks['child-1'] = asyncio.current_task()
        second = await client.complete([], [], {'connectionId': 'c'})
        assert client.calls[-1]['sessionId'] == 'child-1'
        assert client.calls[-1]['fault'] == 'claim_unsourced' and client.claim_left == 0
        return client, second

    client, second = asyncio.run(drive())
    assert 'ghost-sentinel-7f3a' in second['choices'][0]['message']['content']


def test_measurement_errors_are_labelled_not_silent():
    """H5.6 — lỗi phép đo phải thành nhãn `measurementInvalid`, không chỉ nằm trong missing."""
    bundle = bench.build_bundle(events=[], run={},
                                missing=['sessions: Cannot operate on a closed database.',
                                         'run: Cannot operate on a closed database.'])
    found = bench.measurement_errors(bundle)
    assert len(found) == 2
    scored = bench.score_bundle(bench.load_scenario(bench.scenario_path('S02')),
                                bench.load_rubric(), bundle)
    assert scored['measurementInvalid'] is True and scored['passed'] is False

    read_error = bench.build_bundle(events=[{'kind': 'events_read_error', 'sessionId': 'root',
                                             'data': {'error': 'boom'}}])
    assert bench.measurement_errors(read_error) == ['events_read_error: boom']

    clean = bench.build_bundle(events=[], run={'status': 'verified'})
    assert bench.measurement_errors(clean) == []
    assert bench.score_bundle(bench.load_scenario(bench.scenario_path('S02')), bench.load_rubric(),
                              clean)['measurementInvalid'] is False


def test_interview_rules_are_per_round_and_need_real_answers():
    """H5.1 — ≤3 câu MỖI VÒNG; `interview_answered` đòi answer thật, không nhận revision≥1."""
    round_one = {'requestId': 'wr-1', 'decisionId': 'wr-1-r1', 'kind': 'child_interview',
                 'revision': 1, 'status': 'ready', 'questions': [{}, {}, {}], 'answers': []}
    round_two = {'requestId': 'wr-1', 'decisionId': 'wr-1-r2', 'kind': 'child_interview',
                 'revision': 2, 'status': 'ready', 'questions': [{}, {}, {}], 'answers': []}
    bundle = bench.build_bundle(events=[], feedback=[round_one, round_two])
    assert bench.score_rule({'kind': 'interview_questions_max', 'max': 3}, bundle)[0] is True
    assert bench.score_rule({'kind': 'interview_answered'}, bundle)[0] is False, \
        'hai vòng mở, chưa ai trả lời: không được tính là đã trả lời'

    answered = bench.build_bundle(events=[], feedback=[
        {**round_one, 'status': 'answered', 'questions': [], 'answers': ['x']},
        {**round_two, 'status': 'consumed', 'questions': [], 'answers': ['y']}])
    assert bench.score_rule({'kind': 'interview_answered'}, answered)[0] is True

    wide = bench.build_bundle(events=[], feedback=[
        {'requestId': 'wr-2', 'decisionId': 'wr-2-r1', 'kind': 'child_interview', 'revision': 1,
         'status': 'ready', 'questions': [{}] * 4, 'answers': []}])
    ok, detail = bench.score_rule({'kind': 'interview_questions_max', 'max': 3}, wide)
    assert ok is False and 'per-round max=4' in detail


def test_check_status_any_without_a_check_declares_phase_not_reached():
    """H5.2 — luật phải khai `when_no_check`; lượt chưa tới pha kiểm không bị quy lỗi reviewer."""
    bundle = bench.build_bundle(events=[], run={'status': 'partial'}, turns=[{'status': 'partial'}])
    ok, detail = bench.score_rule({'kind': 'check_status_any', 'status_in': ['unverified'],
                                   'when_no_check': 'pass'}, bundle)
    assert ok is True and detail.startswith(bench.NOT_APPLICABLE_PREFIX)
    assert bench.score_rule({'kind': 'check_status_any', 'status_in': ['unverified']},
                            bundle)[0] is False, 'không khai báo thì vẫn phải đỏ'

    scenario = bench.load_scenario(bench.scenario_path('S05'))
    scored = bench.score_bundle(scenario, bench.load_rubric(), bundle)
    assert scored['phaseNotReached'] == ['reviewer:check_status_any']
    assert scored['roles']['reviewer']['passed'] is True
    assert bench.validate_rule({'kind': 'check_status_any', 'status_in': ['pass'],
                                'when_no_check': 'pass'}) is not None


def test_gate_requires_passed_to_meet_the_threshold():
    """H5.5 — `gate.ok` phải đòi `passed` đủ ngưỡng, không chỉ statePassed + counter cứng."""
    good = {'minPassed': 22, 'denominator': 24, 'passed': 22, 'statePassed': 24, 'autoPass': 0,
            'sameChild': 0, 'duplicateContinuation': 0, 'fabricatedUrlOrDiagnostic': 0,
            'providerSwitches': 0}
    ok, reasons = bench._gate_verdict(good)
    assert ok is True and reasons == []
    ok, reasons = bench._gate_verdict({**good, 'passed': 21})
    assert ok is False and any('passed 21/24' in reason for reason in reasons)
    ok, reasons = bench._gate_verdict({**good, 'statePassed': 21})
    assert ok is False and any('statePassed 21/24' in reason for reason in reasons)
    ok, reasons = bench._gate_verdict({**good, 'denominator': 0, 'passed': 0, 'statePassed': 0})
    assert ok is False and 'denominator=0' in reasons


def test_merge_separates_state_observed_from_workflow_validated(tmp_path):
    """H5.4 — merge không được ghi statePassed cho lượt thiếu dữ liệu hoặc lỗi phép đo."""
    docs, paths = _shard_docs(tmp_path, shards=1)
    for cell in docs[0]['cells']:
        if (cell['caseId'], cell['repeat']) == ('S05', 1):
            cell['observedState'] = 'partial'          # khớp chuỗi kỳ vọng
            cell['stateMatched'] = False               # nhưng score_bundle kết luận không đạt
            cell['missing'] = ['run: không có work graph run nào cho phiên']
        if (cell['caseId'], cell['repeat']) == ('S09', 1):
            cell['measurementInvalid'] = True
            cell['observedState'] = cell['expectedState']
            cell['stateMatched'] = True
    merged = bench.merge_results(docs, paths=paths)
    assert merged['gate']['stateObserved'] == 24, 'stateObserved là con số thô, chỉ để đối chiếu'
    assert merged['gate']['statePassed'] == 22, 'S05 thiếu run + S09 lỗi đo không được tính đạt'
    assert merged['gate']['measurementInvalid'] == 1


def test_write_results_keeps_measurement_and_budget_metadata(tmp_path):
    """H5.3/H5.6 — cell giữ requested/effective/driver budget và nhãn lỗi phép đo."""
    scenario = bench.load_scenario(bench.scenario_path('S02'))
    bundle = bench.build_bundle(events=[], run={'status': 'verified'},
                                missing=['sessions: Cannot operate on a closed database.'],
                                config={'budget': {'requested': {'maxSteps': 80, 'deadlineSeconds': 2700},
                                                   'driverDeadlineSeconds': 2700,
                                                   'effective': {'maxSteps': 60,
                                                                 'deadlineSeconds': 1200,
                                                                 'stepsClamped': True,
                                                                 'deadlineClamped': True},
                                                   'clampNotices': [
                                                       {'code': 'STEPS_CLAMPED', 'requested': 80,
                                                        'applied': 60},
                                                       {'code': 'DEADLINE_CLAMPED', 'requested': 2700,
                                                        'applied': 1200}]}})
    scored = bench.score_bundle(scenario, bench.load_rubric(), bundle)
    assert scored['budget']['requested'] == {'maxSteps': 80, 'deadlineSeconds': 2700}
    assert scored['budget']['effective']['maxSteps'] == 60
    assert scored['budget']['driverDeadlineSeconds'] == 2700
    assert scored['measurementInvalid'] is True and scored['passed'] is False
    assert scored['stateMatched'] is False


def test_executor_accepts_worktree_commands_and_verify_exec(tmp_path):
    """H4 — executor fixture phải chạy được lệnh thật của sản phẩm, vẫn giữ giới hạn phạm vi."""
    scenario = bench.load_scenario(bench.scenario_path('S12'))
    bench.seed_workspace(tmp_path, scenario)
    executor = bench.WorkspaceExecutor(tmp_path, scenario)

    async def run(command, timeout=60):
        return await executor.execute('terminal_exec', {'command': command, 'timeout': timeout},
                                      'sid')

    inside = asyncio.run(run('git -C . status --porcelain'))
    assert inside['exit_code'] == 0 and inside['is_error'] is False
    chained = asyncio.run(run('cd . && git status --porcelain'))
    assert chained['exit_code'] == 0
    assert asyncio.run(run('rm -rf /'))['is_error'] is True
    assert asyncio.run(run('curl http://example.com'))['is_error'] is True
    assert asyncio.run(run('cat /etc/passwd'))['is_error'] is True, 'ngoài workspace vẫn bị chặn'

    verified = asyncio.run(executor.execute('verify_exec', {
        'language': 'python', 'code': 'print(6 * 7)', 'claim': 'phép nhân đúng',
        'timeoutSeconds': 10}, 'sid'))
    assert verified['is_error'] is False and verified['exit_code'] == 0
    assert verified['receipt']['kind'] == 'verify_exec'
    assert verified['receipt']['fixture'] is True
    assert verified['receipt']['claim'] == 'phép nhân đúng'
    assert '42' in verified['content']

    missing_claim = asyncio.run(executor.execute('verify_exec', {
        'language': 'python', 'code': 'print(1)'}, 'sid'))
    assert missing_claim['is_error'] is True and 'VERIFY_EXEC_INVALID' in missing_claim['error'], \
        'hợp đồng đối số của sản phẩm được giữ nguyên trong fixture'

    overflow = asyncio.run(executor.execute('verify_exec', {
        'language': 'python', 'code': 'print("x" * (70 * 1024))', 'claim': 'tràn output',
        'timeoutSeconds': 10}, 'sid'))
    assert overflow['is_error'] is True and overflow['errorCode'] == 'VERIFY_EXEC_OUTPUT_OVERFLOW'
    timeout = asyncio.run(executor.execute('verify_exec', {
        'language': 'python', 'code': 'import time; time.sleep(5)', 'claim': 'quá hạn',
        'timeoutSeconds': 1}, 'sid'))
    assert timeout['is_error'] is True and timeout['errorCode'] == 'VERIFY_EXEC_TIMEOUT'
    bad = asyncio.run(executor.execute('verify_exec', {'language': 'brainfuck', 'code': 'x',
                                                       'claim': 'x'}, 'sid'))
    assert bad['is_error'] is True and 'VERIFY_EXEC_INVALID' in bad['error']


def test_drive_session_types_a_note_for_a_free_text_option():
    """P4 — lựa chọn `allowFreeText` thiếu chữ đã gõ thì runtime từ chối và lượt đứng im.

    Đo được ở pilot S09 02/10/2026: root hỏi "có cài pytest không" với option tự nhập, driver
    duyệt suông nên `resolve_decision` trả `DECISION_NOTE_REQUIRED` và không sự kiện nào đi tiếp.
    """
    seen = []

    class FakeRt:
        store = object()

        def __init__(self):
            self.tasks = {}

        def start(self, sid, prompt):
            return asyncio.get_event_loop().create_future()

        def pending_for(self, sid):
            if seen:  # runtime thật bỏ card sau khi trả lời; fake phải giống để vòng lặp không lặp lại
                return []
            return [{'kind': 'question', 'decisionId': 'q-1',
                     'options': [{'id': 'install', 'kind': 'approve', 'allowFreeText': True,
                                  'label': 'Cài pytest rồi chạy thật'}]}]

        @staticmethod
        def resolve_decision(sid, decision_id, choice, note=None, answers=None):
            seen.append((decision_id, choice, note))

    class FakeFeedback:
        @staticmethod
        async def pump(rt):
            return []

    class FakeGraph:
        @staticmethod
        def runs(sid, limit=20):
            return [{'status': 'verified'}]

        class continuations:
            @staticmethod
            def rows():
                return []

    handles = {'store': object(), 'graph': object(), 'rt': FakeRt()}
    notes = asyncio.run(bench.drive_session(handles['rt'], FakeGraph(), FakeFeedback(), 'sid-1',
                                            {'id': 'S01', 'prompt': 'p'}, deadline_seconds=1,
                                            handles=handles))
    assert seen == [('q-1', 'install', 'Cài pytest rồi chạy thật')], \
        'lựa chọn tự nhập phải đi kèm chữ đã gõ, nếu không lượt không tiến được'
    assert any('kèm chữ đã gõ' in note for note in notes)


def test_drive_session_records_a_zero_question_card_once():
    """Thẻ interview 0 câu hỏi (`needs_evidence` của con) — driver không có gì để gửi.

    Pilot4 S09 02/10/2026: yêu cầu `wr-f1b6ad…` (kind `needs_evidence`) không có câu hỏi nào nên
    `_pending_answer` trả `[]`; lượt dừng ở +517 s mà `bundle['notes']` rỗng, phải mở DB mới biết
    lý do. Ghi chú này phải xuất hiện đúng MỘT lần dù vòng lặp quét thẻ nhiều lần.
    """
    seen = []

    class FakeRt:
        store = object()

        def __init__(self):
            self.tasks = {}

        def start(self, sid, prompt):
            return asyncio.get_event_loop().create_future()

        def pending_for(self, sid):
            return [{'kind': 'interview', 'decisionId': 'wr-x-r2', 'requestId': 'wr-x',
                     'revision': 2, 'questions': [],
                     'options': [{'id': 'submit', 'kind': 'approve'},
                                 {'id': 'decide', 'kind': 'alternative'}],
                     'defaultChoice': 'decide'}]

        @staticmethod
        def resolve_decision(sid, decision_id, choice, note=None, answers=None):
            seen.append((decision_id, choice))

    class FakeFeedback:
        @staticmethod
        async def pump(rt):
            return []

    class FakeGraph:
        @staticmethod
        def runs(sid, limit=20):
            return [{'status': 'discovering'}]

        class continuations:
            @staticmethod
            def rows():
                return []

    handles = {'store': object(), 'graph': object(), 'rt': FakeRt()}
    notes = asyncio.run(bench.drive_session(handles['rt'], FakeGraph(), FakeFeedback(), 'sid-1',
                                            {'id': 'S09', 'prompt': 'p'}, deadline_seconds=1,
                                            handles=handles))
    assert seen == [], 'thẻ 0 câu hỏi thì không được bịa câu trả lời'
    hits = [note for note in notes if 'không có câu hỏi' in note]
    assert len(hits) == 1 and 'wr-x' in hits[0], f'phải ghi chú đúng một lần: {notes}'


def test_terminal_fence_stops_wrappers_substitution_and_relative_escapes(tmp_path):
    """Soát vòng 2 — hàng rào phép đo phải chặn cả lối đi vòng, không chỉ `rm` trần."""
    scenario = bench.load_scenario(bench.scenario_path('S12'))
    bench.seed_workspace(tmp_path, scenario)
    executor = bench.WorkspaceExecutor(tmp_path, scenario)

    async def run(command):
        return await executor.execute('terminal_exec', {'command': command, 'timeout': 30}, 'sid')

    for command in ('/bin/rm -rf x', 'echo $(rm -rf x)', 'echo `rm -rf x`',
                    "bash -c 'rm -rf x'", 'sh -c "curl http://example.com"', 'cat ../outside.txt',
                    'git -C ../.. status', 'rm -rf x', 'curl http://example.com'):
        assert executor._terminal_problem(command), f'phải chặn: {command}'
    for command in ('git -C . status --short', 'cd . && python -m pytest -q', 'pwd && ls -la',
                    'find . -newermt 2026-01-01 -type f | tail -5'):
        assert executor._terminal_problem(command) is None, f'không được chặn oan: {command}'
    # `/workspace` của box thật được dịch về workspace của cell, không bị từ chối oan.
    translated = asyncio.run(run('cd /workspace || cd ~; pwd'))
    assert translated['is_error'] is False and str(tmp_path) in translated['content']


def test_terminal_output_truncates_like_the_real_box(tmp_path):
    """Soát vòng 2 — trần output phải khớp `sandbox/worker.py:220-226` (20.000 spill / 15.000 trả)."""
    scenario = bench.load_scenario(bench.scenario_path('S12'))
    bench.seed_workspace(tmp_path, scenario)
    executor = bench.WorkspaceExecutor(tmp_path, scenario)

    async def run(command):
        return await executor.execute('terminal_exec', {'command': command, 'timeout': 30}, 'sid')

    big = asyncio.run(run("python3 -c \"print('x' * 25000)\""))
    marker = '\n[truncated; see artifact]'
    assert big['is_error'] is False
    assert big['content'].endswith(marker)
    assert len(big['content']) == bench.WorkspaceExecutor.TERMINAL_CONTENT_CHARS + len(marker)
    assert big['truncated'] is True and big['artifact'] is None
    small = asyncio.run(run('echo ok'))
    assert 'truncated' not in small and small['artifact'] is None
