#!/usr/bin/env python3
"""W10 — benchmark nghiệm thu Work Graph: 12 kịch bản S01–S12 × 2 lượt, chấm bằng oracle tất định.

Mặc định là **dry-run**: đọc fixture + rubric, in kế hoạch 24 lượt và thoát, không mở socket,
không gọi model (cùng kỷ luật với `run_eval.py`). `--execute` là đường DUY NHẤT có thể tiêu tiền:
cần `BOXFOX_EVAL_ALLOW_SPEND=1` + ngân sách + biến kết nối của `run_eval.py`, và cổng provider
chỉ cho `opencode` / `space-bunny-free` — không có thay thế provider nào (§10).

Mỗi lượt chạy trong session/DB/workspace riêng; ngân sách, commit, config hash, token và
latency theo lượt/theo vai được ghi vào `results.json`; chấm bằng oracle tất định trên
event/artifact/report (không LLM judge). Mọi lượt lỗi vẫn nằm trong mẫu số của cổng đạt.
"""
from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402
import manifest as manifest_mod  # noqa: E402
import net  # noqa: E402
import runner  # noqa: E402

REPO_DIR = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = EVAL_DIR / 'fixtures' / 'work_acceptance'
RUBRIC_PATH = EVAL_DIR / 'work_acceptance_rubric.json'
DEFAULT_OUT_ROOT = Path.home() / 'BoxFox' / 'eval-runs' / 'work-acceptance'

RESULTS_SCHEMA = 'work-acceptance-v1'
SCENARIO_IDS = tuple(f'S{index:02d}' for index in range(1, 13))
V_CASE_IDS = ('V06', 'V07', 'V10', 'V13', 'V14')
ALL_CASE_IDS = SCENARIO_IDS + V_CASE_IDS
# Ý định của chủ nhà (`config.workIntent`) — bản sao của `work_graph.FLOWS`. Thiếu ý định thì lượt
# root ở `legacy`, root tự sửa mã và KHÔNG run nào được dựng (bằng chứng S02: work_runs=0 → oracle
# `no_run`). Test `test_intent_commands_match_work_graph_flows` ghim hai bên khớp nhau.
INTENT_COMMANDS = ('plan', 'research', 'design', 'fix', 'mixed')
REPEATS = 2
DEADLINE_SECONDS = 45 * 60            # §10: mỗi lượt có deadline wall-clock (ví dụ 45 phút)
GATE_MIN_PASSED = 22                  # §10: ≥ 22/24 lượt đạt expectedState
PROVIDER_ID = 'opencode'
MODEL_ID = 'space-bunny-free'
PROVIDER_GUARD_MESSAGE = 'OpenCode space-bunny-free unavailable; no provider substitution'

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SPEND = 3
EXIT_CONNECTION = 4
EXIT_PROVIDER = 6

DEFAULT_MAX_STEPS = 80
DEFAULT_RUN_DEADLINE = 45 * 60
DRIVE_POLL_SECONDS = 2.0
DRIVE_SETTLE_SECONDS = 6.0

# Sau restart, lượt main cũ mất theo tiến trình: benchmark mô phỏng lượt kế tiếp của người dùng.
RESTART_RESUME_PROMPT = ('Harness vừa khởi động lại khi run đang chờ câu trả lời. '
                         'Tiếp tục run đang dở từ trạng thái bền trong DB — không làm lại từ đầu, '
                         'và giữ nguyên child đã hỏi.')

TERMINAL_RUN_STATUSES = ('shipped', 'cancelled', 'rejected')


# --------------------------------------------------------------------------- cổng provider
class ProviderUnavailable(Exception):
    """Route không phải opencode/space-bunny-free: dừng trước khi tiêu bất kỳ token nào."""

    def __init__(self, message=PROVIDER_GUARD_MESSAGE):
        super().__init__(message)
        self.message = message


def select_route(state, *, provider_id=PROVIDER_ID, model_id=MODEL_ID):
    """Chọn route opencode/space-bunny-free từ snapshot router; không bao giờ thay provider."""
    connections = state.get('connections') if isinstance(state, dict) else None
    if not connections:
        raise ProviderUnavailable(f'{PROVIDER_GUARD_MESSAGE} (router state has no connections)')
    providers = {item.get('providerId') for item in connections if isinstance(item, dict)}
    models = {model.get('id') for item in connections if isinstance(item, dict)
              for model in (item.get('models') or []) if isinstance(model, dict)}
    if provider_id not in providers or model_id not in models:
        raise ProviderUnavailable(f'{PROVIDER_GUARD_MESSAGE} (router state offers '
                                  f'providers={sorted(x for x in providers if x)} '
                                  f'models={sorted(x for x in models if x)})')
    for connection in connections:
        if connection.get('providerId') != provider_id or not connection.get('enabled'):
            continue
        for model in connection.get('models') or []:
            if model.get('id') == model_id and model.get('enabled'):
                return {'connectionId': connection['id'], 'modelId': model['id'],
                        'providerId': provider_id}
    raise ProviderUnavailable(f'{PROVIDER_GUARD_MESSAGE} (connection disabled)')


# --------------------------------------------------------------------------- fixture
def scenario_path(code, directory=None):
    return Path(directory or FIXTURE_DIR) / f'{code}.json'


def normalize_intent(value, field):
    """Chuẩn hoá `intent` của fixture: `{"command": "mixed", "why": "..."}`.

    `why` là bắt buộc: mỗi ca phải nói được vì sao chọn luồng ấy, để lượt chạy thật không bị
    đọc như một lựa chọn tuỳ tiện.
    """
    if not isinstance(value, dict):
        raise ValueError(f'{field}: phải là object {{"command": ..., "why": ...}}')
    command = str(value.get('command') or '').strip().lower()
    if command not in INTENT_COMMANDS:
        raise ValueError(f'{field}.command: phải thuộc {list(INTENT_COMMANDS)} (nhận {command!r})')
    unknown = set(value) - {'command', 'why'}
    if unknown:
        raise ValueError(f'{field}: có khóa lạ {sorted(unknown)}')
    why = str(value.get('why') or '').strip()
    if len(why) < 20:
        raise ValueError(f'{field}.why: phải nêu vì sao chọn luồng này (≥ 20 ký tự)')
    return {'command': command, 'why': why}


def scenario_intent(scenario):
    """Intent đã chuẩn hoá của fixture; thiếu là lỗi fixture, không im lặng lấy mặc định."""
    intent = scenario.get('intent')
    if not isinstance(intent, dict) or intent.get('command') not in INTENT_COMMANDS:
        raise ValueError(f"{scenario.get('id')}: fixture thiếu `intent` hợp lệ — xem validate_scenario")
    return intent


def intent_command(scenario):
    return scenario_intent(scenario)['command']


def validate_scenario(doc, stem='<memory>'):
    """Kiểm schema fixture; ném ValueError với đường dẫn trường cụ thể khi sai."""
    where = str(stem)

    def bad(field, why):
        raise ValueError(f'{where}: {field} {why}')

    if not isinstance(doc, dict):
        bad('<root>', 'phải là object JSON')
    for field in ('id', 'prompt', 'oracle'):
        if not doc.get(field):
            bad(field, 'là trường bắt buộc')
    if stem != '<memory>' and doc['id'] != Path(stem).stem:
        bad('id', f"phải khớp tên file ({Path(stem).stem})")
    if not isinstance(doc['prompt'], str) or len(doc['prompt'].strip()) < 20:
        bad('prompt', 'phải là chuỗi ≥ 20 ký tự')
    expected = doc.get('expectedState')
    if isinstance(expected, str):
        if not expected.strip():
            bad('expectedState', 'không được rỗng')
    elif isinstance(expected, list):
        if not expected or any(not isinstance(item, str) or not item.strip() for item in expected):
            bad('expectedState', 'list phải không rỗng và toàn chuỗi')
    else:
        bad('expectedState', 'phải là chuỗi (tiền tố ! = phải khác) hoặc list chuỗi')
    if doc.get('expectedStateSource') not in (None, 'run', 'turn', 'check'):
        bad('expectedStateSource', "phải là 'run', 'turn' hoặc 'check'")
    for field in ('title', 'goal', 'ownerLanguage'):
        if field in doc and not isinstance(doc[field], str):
            bad(field, 'phải là chuỗi')
    if 'notes' in doc and not isinstance(doc['notes'], str):
        bad('notes', 'phải là chuỗi')
    if doc.get('ownerLanguage') not in (None, 'vi', 'en'):
        bad('ownerLanguage', "phải là 'vi' hoặc 'en'")
    if doc.get('autopilot') is False:
        bad('autopilot', 'W10 chỉ chạy kịch bản autopilot (bỏ trường nếu muốn mặc định true)')
    if 'intent' not in doc:
        bad('intent', 'là trường bắt buộc — thiếu ý định thì lượt root ở `legacy` và mọi ca thành `no_run`')
    doc['intent'] = normalize_intent(doc.get('intent'), f'{where}.intent')

    answers = doc.get('interviewAnswers', [])
    if not isinstance(answers, list):
        bad('interviewAnswers', 'phải là list')
    for index, answer in enumerate(answers):
        if not isinstance(answer, dict):
            bad(f'interviewAnswers[{index}]', 'phải là object')
        if not str(answer.get('text') or '').strip() and not answer.get('optionId'):
            bad(f'interviewAnswers[{index}]', 'cần text hoặc optionId')
        unknown = set(answer) - {'questionId', 'text', 'optionId'}
        if unknown:
            bad(f'interviewAnswers[{index}]', f'có khóa lạ {sorted(unknown)}')

    workspace = doc.get('workspace', {'files': []})
    if not isinstance(workspace, dict) or not isinstance(workspace.get('files', []), list):
        bad('workspace', 'phải là object với files là list')
    for index, entry in enumerate(workspace.get('files', [])):
        if not isinstance(entry, dict) or not entry.get('path'):
            bad(f'workspace.files[{index}]', 'cần path')
        _relative(entry['path'], f'workspace.files[{index}].path')

    faults = doc.get('faults', [])
    if not isinstance(faults, list):
        bad('faults', 'phải là list')
    for index, fault in enumerate(faults):
        if not isinstance(fault, dict) or not fault.get('kind'):
            bad(f'faults[{index}]', 'cần kind')
        spec = FAULT_KINDS.get(fault['kind'])
        if spec is None:
            bad(f'faults[{index}].kind', f'không thuộc {sorted(FAULT_KINDS)}')
        missing = [key for key in spec['required'] if key not in fault]
        if missing:
            bad(f'faults[{index}]', f'thiếu {missing}')
        unknown = set(fault) - {'kind'} - set(spec['required']) - set(spec['optional'])
        if unknown:
            bad(f'faults[{index}]', f'có khóa lạ {sorted(unknown)}')
        if fault['kind'] in ('dirty_foreign_file', 'long_document'):
            _relative(fault['path'], f'faults[{index}].path')
        for key in ('calls', 'maxChars', 'chars'):
            if key in fault and (not isinstance(fault[key], int) or fault[key] <= 0):
                bad(f'faults[{index}].{key}', 'phải là số nguyên dương')
        if fault['kind'] == 'answer_revision' and not isinstance(fault.get('answers'), list):
            bad(f'faults[{index}].answers', 'phải là list')

    sources = doc.get('sources', [])
    if not isinstance(sources, list):
        bad('sources', 'phải là list')
    for index, source in enumerate(sources):
        if not isinstance(source, dict) or not (source.get('path') or source.get('url')):
            bad(f'sources[{index}]', 'cần path hoặc url')
        if source.get('path'):
            _relative(source['path'], f'sources[{index}].path')
        if not isinstance(source.get('content', ''), str):
            bad(f'sources[{index}].content', 'phải là chuỗi')

    results = doc.get('searchResults', [])
    if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
        bad('searchResults', 'phải là list object')

    budget = doc.get('budget', {})
    if not isinstance(budget, dict):
        bad('budget', 'phải là object')
    for key in ('maxSteps', 'deadlineSeconds'):
        if key in budget and (not isinstance(budget[key], (int, float)) or budget[key] <= 0):
            bad(f'budget.{key}', 'phải là số dương')

    oracle = doc['oracle']
    if not isinstance(oracle, dict):
        bad('oracle', 'phải là object')
    for role, rules in oracle.items():
        if role not in RUBRIC_ROLES:
            bad(f'oracle.{role}', f'không thuộc {sorted(RUBRIC_ROLES)}')
        if not isinstance(rules, list) or not rules:
            bad(f'oracle.{role}', 'phải là list không rỗng')
        for index, rule in enumerate(rules):
            validate_rule(rule, f'oracle.{role}[{index}]')
    return doc


def _relative(value, field):
    text = str(value)
    if Path(text).is_absolute() or text.startswith('~') or '..' in Path(text).parts:
        raise ValueError(f'{field}: phải là đường dẫn tương đối trong workspace ({text!r})')
    return text


FAULT_KINDS = {
    'search_error': {'required': (), 'optional': ('tool', 'message')},
    'output_length': {'required': (), 'optional': ('calls', 'maxChars')},
    'dirty_foreign_file': {'required': ('path',), 'optional': ('content',)},
    'missing_role': {'required': ('role',), 'optional': ()},
    'restart_while_waiting': {'required': (), 'optional': ()},
    'answer_revision': {'required': ('answers',), 'optional': ()},
    'long_document': {'required': ('path',), 'optional': ('chars',)},
    'claim_unsourced': {'required': (), 'optional': ('text', 'calls')},
}


def load_scenario(path):
    path = Path(path)
    doc = json.loads(path.read_text(encoding='utf-8'))
    return validate_scenario(doc, path.name)


def load_scenarios(directory=None, *, with_v=False):
    """Nạp S01–S12 (+V khi `with_v`); thứ tự cố định, thiếu file nào là lỗi ngay."""
    codes = ALL_CASE_IDS if with_v else SCENARIO_IDS
    scenarios = []
    for code in codes:
        path = scenario_path(code, directory)
        if not path.exists():
            raise ValueError(f'thiếu fixture {path}')
        scenarios.append(load_scenario(path))
    return scenarios


def load_rubric(path=None):
    doc = json.loads(Path(path or RUBRIC_PATH).read_text(encoding='utf-8'))
    if doc.get('schema') != 'work-acceptance-rubric/1':
        raise ValueError('rubric sai schema')
    roles = doc.get('roles')
    if not isinstance(roles, dict) or set(roles) != set(RUBRIC_ROLES):
        raise ValueError(f'rubric phải có đúng các vai {sorted(RUBRIC_ROLES)}')
    for role, value in roles.items():
        if not isinstance(value, dict) or not value.get('title'):
            raise ValueError(f'rubric.roles.{role} phải là object có title')
    for role, rules in (doc.get('baseline') or {}).items():
        if role not in RUBRIC_ROLES:
            raise ValueError(f'rubric.baseline.{role} không thuộc {sorted(RUBRIC_ROLES)}')
        for index, rule in enumerate(rules):
            validate_rule(rule, f'rubric.baseline.{role}[{index}]')
    for index, rule in enumerate(doc.get('catalog') or []):
        validate_rule(rule, f'rubric.catalog[{index}]')
    return doc


RUBRIC_ROLES = ('main', 'producer', 'research', 'reviewer', 'testing', 'flow')
RUBRIC_WEIGHTS = {'main': 3, 'producer': 3, 'research': 2, 'reviewer': 3, 'testing': 3, 'flow': 2}


# --------------------------------------------------------------------------- luật oracle
RULE_SPECS = {
    'run_state_in': {'required': ('states',), 'optional': ()},
    'run_state_not_in': {'required': ('states',), 'optional': ()},
    'stage_status_any': {'required': ('stage', 'status_in'), 'optional': ('nodeId',)},
    'stage_status_all': {'required': ('stage', 'status_in'), 'optional': ('nodeId',)},
    'no_execute_stage': {'required': (), 'optional': ()},
    'event_code_seen': {'required': ('code',), 'optional': ('min',)},
    'event_code_absent': {'required': ('code',), 'optional': ()},
    'event_kind_seen': {'required': ('eventKind',), 'optional': ('min',)},
    'turn_status_any': {'required': ('status_in',), 'optional': ()},
    'check_status_any': {'required': ('status_in',), 'optional': ('checkId',)},
    'check_count_max': {'required': ('max',), 'optional': ('checkId',)},
    'check_count_min': {'required': ('min',), 'optional': ('checkId',)},
    'interview_questions_max': {'required': ('max',), 'optional': ()},
    'interview_answered': {'required': (), 'optional': ()},
    'same_child_continuation': {'required': (), 'optional': ()},
    'no_duplicate_continuation': {'required': (), 'optional': ()},
    'feedback_revision_min': {'required': ('min',), 'optional': ()},
    'no_fabricated_url': {'required': (), 'optional': ()},
    'no_diagnostic_leak': {'required': (), 'optional': ()},
    'artifact_regex_any': {'required': ('patterns',), 'optional': ('min_matches',)},
    'artifact_excludes': {'required': ('patterns',), 'optional': ()},
    'artifact_schema_seen': {'required': ('schema',), 'optional': ()},
    'report_regex_any': {'required': ('patterns',), 'optional': ('min_matches',)},
    'finding_kept_min': {'required': ('min',), 'optional': ()},
    'finding_cited_min': {'required': ('min',), 'optional': ()},
    'finding_downgrade_rate_max': {'required': ('max',), 'optional': ()},
    'tests_proof': {'required': (), 'optional': ('commands',)},
    'child_count_max': {'required': ('max',), 'optional': ()},
    'no_auto_pass': {'required': (), 'optional': ()},
    'provider_unchanged': {'required': (), 'optional': ('providerId', 'modelId')},
    'converged_review': {'required': (), 'optional': ('checkId', 'requireHash')},
    'no_extra_ship_paths': {'required': (), 'optional': ()},
    'user_output_excludes': {'required': ('patterns',), 'optional': ()},
    'word_count_max': {'required': ('max',), 'optional': ('source', 'schema', 'role', 'checkId',
                                                          'mode', 'min_sources')},
    'no_misdiagnosis': {'required': ('code', 'patterns'), 'optional': ()},
    'unreviewed_claims_labelled': {'required': (), 'optional': ('labels',)},
    'any_of': {'required': ('rules',), 'optional': ()},
    'all_of': {'required': ('rules',), 'optional': ()},
}

_WORD_SOURCES = ('artifact', 'turn', 'check', 'report')
# Nhãn "chưa kiểm" cho claim không nằm trong tài liệu đã phản biện (W6.2.BIND) — chấm chữ, không LLM.
_LABEL_MARKERS = ('chưa kiểm', 'chưa xác minh', 'chưa xác thực', 'chưa phản biện', 'chưa review',
                  'unverified', 'not reviewed')

_NESTED_RULE_KINDS = ('any_of', 'all_of')


def validate_rule(rule, where='<rule>'):
    if not isinstance(rule, dict):
        raise ValueError(f'{where}: phải là object')
    kind = rule.get('kind')
    spec = RULE_SPECS.get(kind)
    if spec is None:
        raise ValueError(f'{where}: kind {kind!r} không thuộc {sorted(RULE_SPECS)}')
    missing = [key for key in spec['required'] if key not in rule]
    if missing:
        raise ValueError(f'{where}: {kind} thiếu {missing}')
    unknown = set(rule) - {'kind', 'why'} - set(spec['required']) - set(spec['optional'])
    if unknown:
        raise ValueError(f'{where}: {kind} có khóa lạ {sorted(unknown)}')
    if kind in _NESTED_RULE_KINDS:
        if not isinstance(rule['rules'], list) or not rule['rules']:
            raise ValueError(f'{where}: {kind}.rules phải là list không rỗng')
        for index, nested in enumerate(rule['rules']):
            validate_rule(nested, f'{where}.{kind}[{index}]')
    if kind == 'word_count_max':
        if not isinstance(rule['max'], int) or rule['max'] <= 0:
            raise ValueError(f'{where}: word_count_max.max phải là số nguyên dương')
        source = rule.get('source', 'artifact')
        if source not in _WORD_SOURCES:
            raise ValueError(f'{where}: word_count_max.source phải thuộc {list(_WORD_SOURCES)}')
        if rule.get('mode', 'prose') not in ('prose', 'all'):
            raise ValueError(f"{where}: word_count_max.mode phải là 'prose' hoặc 'all'")
    if kind == 'no_misdiagnosis':
        if not isinstance(rule['patterns'], list) or not rule['patterns']:
            raise ValueError(f'{where}: no_misdiagnosis.patterns phải là list không rỗng')
    return rule


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _match_patterns(texts, patterns):
    blob = '\n'.join(str(item or '') for item in texts)
    hits = set()
    for pattern in patterns:
        if re.search(pattern, blob, re.I | re.S):
            hits.add(pattern)
    return hits


def _check_matches(doc, rule):
    """`checkId` trong luật là LOẠI check (tests/plan_review/evidence/…), khớp `kind` của doc."""
    wanted = rule.get('checkId')
    return not wanted or wanted in (doc.get('kind'), doc.get('checkId'))


def _code_seen(events, code):
    pattern = re.compile(r'(?<![A-Z0-9_])' + re.escape(code) + r'(?![A-Z0-9_])')
    for event in events:
        blob = json.dumps(event.get('data'), ensure_ascii=False)
        if pattern.search(blob) or event.get('kind') == code:
            return True
    return False


# --------------------------------------------------------------------------- bundle (đầu vào chấm)
def build_bundle(*, events=None, run=None, checks=None, feedback=None, turns=None,
                 children=None, child_sessions=None, artifacts=None, calls=None, config=None,
                 expected_state=None, missing=None, continuations=None):
    """Gom mọi thứ oracle được phép nhìn vào một object thuần JSON (test được bằng fixture)."""
    feedback = list(feedback or [])
    return {
        'events': list(events or []),
        'run': run or {},
        'checks': list(checks or []),
        'feedback': feedback,
        'turns': list(turns or []),
        'children': list(children or []),
        'childSessions': dict(child_sessions or {}),
        'artifacts': list(artifacts or []),
        'calls': list(calls or []),
        'config': dict(config or {}),
        'expectedState': expected_state,
        'missing': list(missing or []),
        'derived': _derive(events or [], run or {}, checks or [], feedback, turns or [],
                           continuations or []),
    }


def _derive(events, run, checks, feedback, turns, continuations=None):
    latest = {}
    for doc in checks:
        if doc.get('status') == 'superseded':
            continue
        key = (doc.get('nodeId'), doc.get('stage'), doc.get('checkId'))
        latest[key] = doc
    current = list(latest.values())
    rows = [item for item in (continuations or []) if isinstance(item, dict)]
    for event in events:
        kind = str(event.get('kind') or '')
        data = event.get('data') or {}
        marker = str(data.get('event') or '') if isinstance(data, dict) else ''
        if kind.startswith('continuation_') or marker.startswith('continuation_'):
            rows.append({'event': kind, 'data': data})
    return {
        'latestChecks': current,
        'continuations': rows,
        'feedback': list(feedback),
    }


def observe_state(bundle, source='run'):
    """Trạng thái quan sát được: run (mặc định), turn cuối của phiên gốc, hay check tệ nhất.

    `expectedState` so với nguồn này; `!X` nghĩa là "phải KHÁC X" (kịch bản chỉ cấm một trạng thái).
    """
    root = (bundle.get('config') or {}).get('session')
    run = bundle.get('run') or {}
    if source == 'turn':
        order = {'error': 0, 'deadline': 1, 'budget_exhausted': 2, 'partial': 3,
                 'tool_calls': 4, 'completed': 5, 'ok': 5}
        statuses = [str(turn['status']) for turn in (bundle.get('turns') or []) if turn.get('status')]
        if not statuses:
            return 'no_turn'
        return min(statuses, key=lambda value: order.get(value, 3))
    if source == 'check':
        order = {'error': 3, 'unverified': 2, 'revise': 1, 'pass': 0}
        statuses = [doc.get('status') for doc in bundle['derived']['latestChecks']]
        if statuses:
            return max(statuses, key=lambda value: order.get(value, 2))
        return run.get('status') or 'no_check'
    state = run.get('status')
    if state:
        return state
    statuses = {doc.get('status') for doc in bundle['derived']['latestChecks']}
    if 'revise' in statuses:
        return 'needs_revision'
    if 'unverified' in statuses:
        return 'unverified'
    if statuses:
        return 'verified'
    return 'no_run'


def state_matches(observed, expected):
    if isinstance(expected, (list, tuple)):
        return observed in expected
    text = str(expected)
    if text.startswith('!'):
        return observed != text[1:]
    return observed == text


def _missing_bundle(bundle):
    for item in bundle.get('missing') or []:
        if not str(item).startswith('run:'):
            return True
    return not (bundle.get('run') or {})


# --------------------------------------------------------------------------- chấm điểm
def score_rule(rule, bundle):
    """Trả (passed, detail). Mọi luật đều tất định; không gọi model, không đọc mạng."""
    kind = rule['kind']
    run = bundle.get('run') or {}
    derived = bundle['derived']
    events = bundle['events']
    checks = bundle['derived']['latestChecks']

    if kind == 'run_state_in':
        return state_matches(observe_state(bundle), rule['states']), f'state={observe_state(bundle)}'
    if kind == 'run_state_not_in':
        return not state_matches(observe_state(bundle), rule['states']), f'state={observe_state(bundle)}'
    if kind in ('stage_status_any', 'stage_status_all'):
        picked = [doc for doc in checks if doc.get('stage') == rule['stage']
                  and (not rule.get('nodeId') or doc.get('nodeId') == rule['nodeId'])]
        statuses = [doc.get('status') for doc in picked]
        if kind == 'stage_status_any':
            ok = any(status in rule['status_in'] for status in statuses)
        else:
            ok = bool(statuses) and all(status in rule['status_in'] for status in statuses)
        return ok, f"stage={rule['stage']} statuses={statuses}"
    if kind == 'no_execute_stage':
        stages = sorted({str(doc.get('stage')) for doc in checks})
        ok = not any('execute' in stage for stage in stages)
        return ok, f'stages={stages}'
    if kind == 'event_code_seen':
        hits = sum(1 for event in events
                   if re.search(r'(?<![A-Z0-9_])' + re.escape(rule['code']) + r'(?![A-Z0-9_])',
                                json.dumps(event.get('data'), ensure_ascii=False)))
        return hits >= _int(rule.get('min'), 1), f"{rule['code']}×{hits}"
    if kind == 'event_code_absent':
        seen = _code_seen(events, rule['code'])
        return not seen, f"{rule['code']} seen={seen}"
    if kind == 'event_kind_seen':
        hits = sum(1 for event in events if event.get('kind') == rule['eventKind'])
        return hits >= _int(rule.get('min'), 1), f"{rule['eventKind']}×{hits}"
    if kind == 'turn_status_any':
        statuses = [doc.get('status') for doc in bundle['turns']]
        return any(status in rule['status_in'] for status in statuses), f'turn statuses={statuses}'
    if kind == 'check_status_any':
        picked = [doc for doc in checks if _check_matches(doc, rule)]
        statuses = [doc.get('status') for doc in picked]
        return any(status in rule['status_in'] for status in statuses), f'check statuses={statuses}'
    if kind in ('check_count_max', 'check_count_min'):
        picked = [doc for doc in checks if _check_matches(doc, rule)]
        count = len(picked)
        if kind == 'check_count_max':
            return count <= _int(rule['max']), f'checks={count}'
        return count >= _int(rule['min']), f'checks={count}'
    if kind == 'interview_questions_max':
        total = sum(len(doc.get('questions') or []) for doc in derived['feedback'])
        return total <= _int(rule['max']), f'questions={total}'
    if kind == 'interview_answered':
        docs = [doc for doc in derived['feedback'] if doc.get('kind') != 'main_interview']
        ok = bool(docs) and all(doc.get('status') in ('answered', 'ready', 'consumed')
                                or _int(doc.get('revision')) >= 1 for doc in docs)
        return ok, f"statuses={[doc.get('status') for doc in docs]}"
    if kind == 'same_child_continuation':
        rows = _continuation_rows(bundle)
        bad_rows = [row for row in rows if not row['same']]
        return bool(rows) and not bad_rows, f'rows={len(rows)} bad={bad_rows[:3]}'
    if kind == 'no_duplicate_continuation':
        rows = _continuation_rows(bundle)
        seen = set()
        duplicates = 0
        for row in rows:
            key = (row['requestId'], row['revision'], row['childId'])
            if key in seen:
                duplicates += 1
            seen.add(key)
        return duplicates == 0, f'duplicates={duplicates} rows={len(rows)}'
    if kind == 'feedback_revision_min':
        revisions = [max(_int(doc.get('revision')), len(doc.get('answers') or []))
                     for doc in derived['feedback']]
        top = max(revisions) if revisions else 0
        return top >= _int(rule['min']), f'revision={top}'
    if kind == 'no_fabricated_url':
        return _no_fabricated_url(bundle)
    if kind == 'no_diagnostic_leak':
        patterns = (r'WORK_[A-Z_]{3,}', r'\b[A-Z][A-Z0-9_]*_UNAVAILABLE\b')
        return _no_leak(bundle, patterns)
    if kind in ('artifact_regex_any', 'report_regex_any'):
        texts = _artifact_texts(bundle) if kind == 'artifact_regex_any' else _report_texts(bundle)
        hits = _match_patterns(texts, rule['patterns'])
        need = _int(rule.get('min_matches'), 1)
        return len(hits) >= need, f'hits={sorted(hits)} need={need}'
    if kind == 'artifact_excludes':
        texts = _artifact_texts(bundle)
        hits = _match_patterns(texts, rule['patterns'])
        return not hits, f'unexpected={sorted(hits)}'
    if kind == 'artifact_schema_seen':
        schemas = set()
        for doc in bundle['artifacts']:
            schemas |= {str(doc.get('schema')), str((doc.get('meta') or {}).get('schema'))}
        for doc in bundle['checks']:
            snapshot = (doc.get('binding') or {}).get('codeSnapshot') or {}
            schemas |= {str(snapshot.get('schema'))}
        schemas.discard('None')
        return rule['schema'] in schemas, f'schemas={sorted(schemas)}'
    if kind == 'finding_kept_min':
        return _finding_counts(bundle)[0] >= _int(rule['min']), _finding_detail(bundle)
    if kind == 'finding_cited_min':
        return _finding_counts(bundle)[1] >= _int(rule['min']), _finding_detail(bundle)
    if kind == 'finding_downgrade_rate_max':
        kept, cited, downgraded = _finding_counts(bundle)
        total = kept + downgraded
        rate = (downgraded / total) if total else 0.0
        return rate <= float(rule['max']), f'rate={rate:.2f} ({downgraded}/{total})'
    if kind == 'tests_proof':
        return _tests_proof(bundle, rule.get('commands'))
    if kind == 'child_count_max':
        count = len(bundle['children'])
        return count <= _int(rule['max']), f'children={count}'
    if kind == 'no_auto_pass':
        # Review vòng 2 (finding 2): check doc thật mang `stage` ∈ {produce, execute} và `kind`
        # ∈ {tests, code_review, …}; lọc theo `stage == 'tests'` nên bộ đếm không bao giờ bật.
        auto = [doc.get('checkId') for doc in checks if doc.get('status') == 'pass'
                and str(doc.get('kind')) == 'tests' and not _tests_proof(bundle, None)[0]]
        return not auto, f'auto-passed tests={auto}'
    if kind == 'provider_unchanged':
        return _provider_unchanged(bundle, rule)
    if kind == 'converged_review':
        return _converged_review(bundle, rule)
    if kind == 'no_extra_ship_paths':
        return _no_extra_ship_paths(bundle)
    if kind == 'user_output_excludes':
        texts = [doc.get('text') for doc in bundle['turns'] if doc.get('role') == 'assistant']
        hits = _match_patterns(texts, rule['patterns'])
        return not hits, f'leaked={sorted(hits)}'
    if kind == 'word_count_max':
        sources = _word_sources(bundle, rule)
        minimum = _int(rule.get('min_sources'), 0)
        if len(sources) < minimum:
            return False, f'sources={len(sources)} need≥{minimum}'
        if not sources:
            return True, 'sources=0'
        mode = rule.get('mode', 'prose')
        counted = [(label, _prose_words(text) if mode == 'prose' else len(re.findall(r'\S+', str(text))))
                   for label, text in sources]
        worst = max(counted, key=lambda item: item[1])
        return worst[1] <= _int(rule['max']), \
            f'{worst[0]}={worst[1]} từ (max={rule["max"]}, nguồn={len(sources)})'
    if kind == 'no_misdiagnosis':
        return _no_misdiagnosis(bundle, rule)
    if kind == 'unreviewed_claims_labelled':
        return _unreviewed_claims_labelled(bundle, rule.get('labels'))
    if kind == 'any_of':
        results = [score_rule(nested, bundle) for nested in rule['rules']]
        ok = any(item[0] for item in results)
        return ok, 'any_of[' + '; '.join(f'{item[0]}:{item[1]}' for item in results) + ']'
    if kind == 'all_of':
        results = [score_rule(nested, bundle) for nested in rule['rules']]
        ok = all(item[0] for item in results)
        return ok, 'all_of[' + '; '.join(f'{item[0]}:{item[1]}' for item in results) + ']'
    raise ValueError(f'luật chưa cài: {kind}')


def _continuation_rows(bundle):
    """Mỗi continuation phải resume ĐÚNG child đã hỏi, không tạo child thay thế (W7.1).

    Cùng child = (a) childId nằm trong danh sách phiên con, và (b) child đó có lượt mới SAU khi
    owner trả lời (`turn_start` sau `confirmedAt`), tức nó thật sự chạy tiếp — không phải một
    child mới được sinh ra để làm lại việc.
    """
    by_request = {}
    for doc in bundle['derived']['feedback']:
        by_request[doc.get('requestId')] = doc
    children = {item.get('id') for item in bundle.get('children') or []}
    starts = {}
    for event in bundle['events']:
        if event.get('kind') == 'turn_start':
            starts.setdefault(event.get('sessionId'), []).append(event.get('created') or 0)
    rows = []
    for item in bundle['derived']['continuations']:
        data = item.get('data') if isinstance(item.get('data'), dict) else item
        if not isinstance(data, dict):
            continue
        request_id = data.get('requestId')
        doc = by_request.get(request_id) or {}
        request_child = doc.get('childId')
        explicit = data.get('childId')
        child_id = explicit or request_child
        revision = _int(data.get('revision') or data.get('requestRevision'), _int(doc.get('revision')))
        answered_at = max((float(answer.get('confirmedAt') or 0)
                           for answer in (doc.get('answers') or []) if isinstance(answer, dict)),
                          default=0.0)
        marks = starts.get(child_id) or []
        resumed = any(mark >= answered_at for mark in marks) if answered_at else bool(marks)
        same_request_child = not (explicit and request_child) or explicit == request_child
        rows.append({'event': item.get('event'), 'requestId': request_id, 'revision': revision,
                     'childId': child_id, 'exists': child_id in children, 'resumed': resumed,
                     'sameRequestChild': same_request_child,
                     'same': bool(child_id) and child_id in children and resumed and same_request_child})
    return rows


def _artifact_texts(bundle):
    texts = []
    for doc in bundle['artifacts']:
        for key in ('content', 'text', 'body'):
            if isinstance(doc.get(key), str):
                texts.append(doc[key])
    return texts


def _prose_words(raw):
    """Đếm từ ngoài khối ``` và dòng VERDICT — cùng định nghĩa với `work_checks.prose_words`."""
    text = re.sub(r'```.*?```', ' ', str(raw or ''), flags=re.S)
    text = re.sub(r'^\s*VERDICT: (?:ok|revise)\s*$', ' ', text, flags=re.M)
    return len(re.findall(r'\S+', text))


def _word_sources(bundle, rule):
    """[(nhãn, text)] theo `source` của luật; rỗng nghĩa là lượt này không có văn bản để đo."""
    source = rule.get('source', 'artifact')
    if source == 'artifact':
        picked = []
        for doc in bundle['artifacts']:
            schema = str(doc.get('schema') or (doc.get('meta') or {}).get('schema') or '')
            if rule.get('schema') and schema != rule['schema']:
                continue
            text = next((doc[key] for key in ('content', 'text', 'body')
                         if isinstance(doc.get(key), str)), None)
            if text is not None:
                picked.append((f"artifact:{doc.get('artifactId')}", text))
        return picked
    if source == 'turn':
        return [(f"turn:{doc.get('sessionId')}", doc.get('text')) for doc in bundle['turns']
                if doc.get('text') and (not rule.get('role') or doc.get('role') == rule['role'])]
    if source == 'check':
        picked = [doc for doc in bundle['derived']['latestChecks'] if _check_matches(doc, rule)]
        rows = []
        for doc in picked:
            text = next((doc[key] for key in ('output', 'report', 'text', 'summary')
                         if isinstance(doc.get(key), str)), None)
            if text is not None:
                rows.append((f"check:{doc.get('checkId')}", text))
        return rows
    return [(f'report:{index}', text) for index, text in enumerate(_report_texts(bundle))]


def _unreviewed_claim_tokens(bundle):
    """Token của mọi notice `unreviewed_claims` (W6.2.BIND) trong transcript."""
    rows = []
    for event in bundle['events']:
        data = event.get('data') or {}
        if not isinstance(data, dict):
            continue
        blob = f"{event.get('kind') or ''} {data.get('type') or ''} {data.get('event') or ''}"
        if 'unreviewed_claims' not in blob:
            continue
        tokens = [str(token) for token in (data.get('tokens') or []) if str(token).strip()]
        if tokens:
            rows.append(tokens)
    return rows


def _unreviewed_claims_labelled(bundle, labels):
    """Claim ngoài tập đã phản biện: phải gắn nhãn chưa-kiểm, hoặc nằm trong artifact chính thức."""
    notices = _unreviewed_claim_tokens(bundle)
    if not notices:
        return True, 'no unreviewed_claims notice'
    markers = [str(item).lower() for item in (labels or _LABEL_MARKERS)]
    answer = '\n'.join(str(text) for text in _user_visible_texts(bundle)).lower()
    artifacts = '\n'.join(_artifact_texts(bundle)).lower()
    unlabelled = []
    for tokens in notices:
        for token in tokens:
            if token.lower() in artifacts:
                continue
            lines = [line for line in answer.splitlines() if token.lower() in line]
            if not lines:
                continue
            if any(any(marker in line for marker in markers) for line in lines):
                continue
            unlabelled.append(token)
    return not unlabelled, f'notices={len(notices)} unlabelled={sorted(set(unlabelled))[:5]}'


def _no_misdiagnosis(bundle, rule):
    """Mã lỗi nội bộ đã thấy thì câu trả lời cho user không được quy sai nguyên nhân."""
    seen = _code_seen(bundle['events'], rule['code'])
    hits = _match_patterns(_user_visible_texts(bundle), rule['patterns']) if seen else set()
    return not hits, f"code_seen={seen} wrong={sorted(hits)}"


def _report_texts(bundle):
    texts = []
    for doc in bundle['checks']:
        for key in ('output', 'report', 'text', 'summary'):
            if isinstance(doc.get(key), str):
                texts.append(doc[key])
        for entry in doc.get('attempts') or []:
            if isinstance(entry, dict) and isinstance(entry.get('text'), str):
                texts.append(entry['text'])
    return texts


def _finding_counts(bundle):
    """(số finding được giữ, số finding có căn cứ được giữ, số finding bị hạ)."""
    kept = cited = downgraded = 0
    for doc in bundle['checks']:
        items = [item for item in (doc.get('findings') or []) if isinstance(item, dict)]
        blocking = set(doc.get('blocking') or [])
        kept += len(items)
        cited += len([item for item in items
                      if (item.get('id') or item.get('findingId')) in blocking])
        downgraded += len(doc.get('downgraded') or [])
    return kept, cited, downgraded


def _finding_detail(bundle):
    kept, cited, downgraded = _finding_counts(bundle)
    return f'kept={kept} cited={cited} downgraded={downgraded}'


def _tool_names(bundle):
    names = []
    for event in bundle['events']:
        if event.get('kind') != 'tool_end':
            continue
        data = event.get('data') or {}
        name = data.get('name') or data.get('tool')
        if name:
            names.append(str(name))
    return names


def _opened_texts(bundle):
    """Nội dung đã mở qua tool (read/web_fetch/terminal) — căn cứ hợp lệ cho claim/URL."""
    texts = []
    for event in bundle['events']:
        if event.get('kind') not in ('tool_end', 'tool_start'):
            continue
        data = event.get('data') or {}
        for key in ('result', 'output', 'content', 'text', 'stdout'):
            value = data.get(key)
            if isinstance(value, str):
                texts.append(value)
    return texts


def _user_visible_texts(bundle):
    """Chỉ câu trả lời của phiên gốc mới là output cho user — không tính câu của child."""
    root = (bundle.get('config') or {}).get('session')
    texts = []
    for turn in bundle['turns']:
        if turn.get('role') != 'assistant' or not turn.get('text'):
            continue
        if root and turn.get('sessionId') not in (None, root):
            continue
        texts.append(turn['text'])
    for event in bundle['events']:
        if root and event.get('sessionId') != root:
            continue
        if event.get('kind') in ('assistant', 'notice'):
            data = event.get('data') or {}
            if data.get('final') and isinstance(data.get('text'), str):
                texts.append(data['text'])
    return texts


def _no_fabricated_url(bundle):
    opened = '\n'.join(_opened_texts(bundle))
    flagged = []
    for text in _user_visible_texts(bundle):
        for url in re.findall(r'https?://[^\s`)\]\'"]+', text):
            clean = url.rstrip('.,;:')
            if clean not in opened:
                flagged.append(clean)
    return not flagged, f'fabricated={sorted(set(flagged))[:5]}'


def _no_leak(bundle, patterns):
    leaked = []
    for text in _user_visible_texts(bundle):
        for pattern in patterns:
            leaked += re.findall(pattern, text)
    return not leaked, f'leaked={sorted(set(leaked))[:5]}'


def tool_call(data):
    """`tool_end.data` thật là `{id, name, args, result}` — mã thoát nằm trong `result`.

    Review vòng 2 (finding 1): oracle đọc `data['exitCode']`/`data['command']` ở tầng ngoài nên
    không bao giờ thấy một `terminal_exec` thật, và mọi lượt cần `tests_proof` bị chấm hỏng.
    """
    data = data if isinstance(data, dict) else {}
    args = data.get('args') if isinstance(data.get('args'), dict) else {}
    result = data.get('result') if isinstance(data.get('result'), dict) else {}
    return {'id': data.get('id'), 'name': str(data.get('name') or ''),
            'command': str(args.get('command') or data.get('command') or ''),
            'exit_code': result.get('exit_code', result.get('exitCode')),
            'is_error': bool(result.get('is_error')), 'result': result, 'args': args}


def _tests_proof(bundle, commands):
    """Lệnh test yêu cầu phải có tool_end thật với exit_code=0 (không tin lời khai)."""
    wanted = [str(command) for command in (commands or [])]
    proven = []
    for event in bundle['events']:
        if event.get('kind') != 'tool_end':
            continue
        call = tool_call(event.get('data'))
        if call['exit_code'] != 0 or call['is_error']:
            continue
        blob = json.dumps(event.get('data') or {}, ensure_ascii=False)
        if wanted and not any(command in call['command'] or command in blob for command in wanted):
            continue
        proven.append(call['command'] or call['name'] or 'tool')
    return bool(proven), f'proven={proven[:5]}'


def _provider_unchanged(bundle, rule):
    provider = rule.get('providerId', PROVIDER_ID)
    model = rule.get('modelId', MODEL_ID)
    calls = bundle['calls'] or []
    used = {(call.get('providerId'), call.get('modelId')) for call in calls}
    wrong = sorted({item for item in used if item[0] and item[0] != provider})
    wrong += sorted({(item[0], item[1]) for item in used if item[1] and item[1] != model})
    return not wrong and bool(calls), f'used={sorted(item for item in used if item[0] or item[1])} wrong={wrong}'


def _converged_review(bundle, rule):
    """Review một lần trên hash đã hội tụ: mọi check được chọn pass, không pass hai lần một hash."""
    all_docs = [doc for doc in bundle['checks'] if _check_matches(doc, rule)]
    latest = [doc for doc in all_docs if doc.get('status') != 'superseded']
    passing = [doc for doc in latest if doc.get('status') == 'pass']

    def code_hash(doc):
        return ((doc.get('binding') or {}).get('codeSnapshot') or {}).get('hash') \
            or doc.get('codeHash') or doc.get('sourceHash')

    reviewed = {code_hash(doc) for doc in passing}
    reviewed.discard(None)
    final = set()
    for doc in bundle['artifacts']:
        final |= {doc.get('hash'), (doc.get('meta') or {}).get('hash')}
    for doc in bundle['checks']:
        final |= {((doc.get('binding') or {}).get('codeSnapshot') or {}).get('hash')}
    final.discard(None)
    passes_per_hash = {}
    for doc in passing:
        key = code_hash(doc) or 'unknown'
        passes_per_hash[key] = passes_per_hash.get(key, 0) + 1
    repeated = sorted(key for key, count in passes_per_hash.items() if count > 1)
    ok = bool(passing) and len(latest) == len(passing) and not repeated
    if rule.get('requireHash', True):
        ok = ok and bool(reviewed) and bool(final) and reviewed <= final
    return ok, (f'checks={len(latest)} passed={len(passing)} reviewed={sorted(reviewed)[:3]} '
                f'final={sorted(final)[:3]} repeated={repeated}')


def _no_extra_ship_paths(bundle):
    """File ngoài run (dirty foreign) không được nằm trong commit ship."""
    foreign = {str(fault.get('path')) for fault in (bundle['config'].get('faults') or [])
               if fault.get('kind') == 'dirty_foreign_file'}
    ship = bundle['config'].get('ship') or {}
    files = {str(item) for item in ship.get('files') or []}
    extra = sorted(path for path in foreign if any(path == item or item.endswith('/' + path)
                                                   for item in files))
    return not extra, f'foreign={sorted(foreign)} shipped={sorted(files)[:8]} extra={extra}'


def score_bundle(scenario, rubric, bundle):
    """Chấm một lượt: rubric nền theo vai + oracle riêng của kịch bản; lượt lỗi vẫn vào mẫu số."""
    by_role = {}
    passed_total = weight_total = 0
    for role in RUBRIC_ROLES:
        rules = list(((rubric.get('baseline') or {}).get(role) or [])) \
            + list((scenario.get('oracle') or {}).get(role) or [])
        results = []
        for rule in rules:
            ok, detail = score_rule(rule, bundle)
            results.append({'kind': rule['kind'], 'passed': bool(ok), 'detail': detail,
                            'why': rule.get('why', '')})
        weight = RUBRIC_WEIGHTS[role]
        if results:
            passed_total += sum(1 for item in results if item['passed']) * weight
            weight_total += len(results) * weight
        by_role[role] = {'rules': results, 'passed': all(item['passed'] for item in results),
                         'count': len(results),
                         'failed': [item['kind'] for item in results if not item['passed']]}
    observed = observe_state(bundle, scenario.get('expectedStateSource', 'run'))
    expected = scenario['expectedState']
    missing = _missing_bundle(bundle)
    state_ok = state_matches(observed, expected)
    if missing:
        # Không có run thì không lượt nào chứng minh được điều gì — kể cả `!verified`
        # (review vòng 2, finding 3: `no_run` từng khớp `!verified` và được tính là đạt).
        state_ok = False
    elif observed == 'no_run' and str(expected).startswith('!'):
        state_ok = False
    score = round(100.0 * passed_total / weight_total, 2) if weight_total else 0.0
    return {'role': None, 'observedState': observed, 'expectedState': expected,
            'expectedStateSource': scenario.get('expectedStateSource', 'run'),
            'missing': bundle.get('missing') or [], 'stateMatched': state_ok,
            'passed': bool(state_ok and weight_total and passed_total == weight_total),
            'score': score, 'roles': by_role}


def evaluate_run(cell, rubric):
    """Chấm cả benchmark: 24 lượt, mọi lượt lỗi vẫn nằm trong mẫu số."""
    cells = []
    for item in cell:
        scenario = item['scenario']
        bundle = item['bundle']
        scored = score_bundle(scenario, rubric, bundle)
        scored.update(caseId=scenario['id'], repeat=item.get('repeat'),
                      validity=item.get('validity'), error=item.get('error'))
        cells.append(scored)
    denominator = len(cells)
    passed = [item for item in cells if item['passed']]
    state_passed = [item for item in cells if item['stateMatched']]
    roles = {}
    for role in RUBRIC_ROLES:
        rules = [(item, rule) for item in cells for rule in item['roles'][role]['rules']]
        failed = [(item['caseId'], item['repeat'], rule['kind'], rule['detail'])
                  for item, rule in rules if not rule['passed']]
        roles[role] = {'rules': len(rules),
                       'passed': len(rules) - len(failed),
                       'rate': round((len(rules) - len(failed)) / len(rules), 4) if rules else 1.0,
                       'failures': failed[:20]}
    gate = {
        'minPassed': GATE_MIN_PASSED,
        'denominator': denominator,
        'passed': len(passed),
        'statePassed': len(state_passed),
        'stateRate': round(len(state_passed) / denominator, 4) if denominator else 0.0,
        'autoPass': _count_rule_failures(cells, 'no_auto_pass'),
        'sameChild': _count_rule_failures(cells, 'same_child_continuation'),
        'duplicateContinuation': _count_rule_failures(cells, 'no_duplicate_continuation'),
        'fabricatedUrlOrDiagnostic': (_count_rule_failures(cells, 'no_fabricated_url')
                                      + _count_rule_failures(cells, 'no_diagnostic_leak')),
        'providerSwitches': _count_rule_failures(cells, 'provider_unchanged'),
    }
    gate['ok'] = (denominator > 0 and gate['statePassed'] >= GATE_MIN_PASSED
                  and gate['autoPass'] == 0 and gate['sameChild'] == 0
                  and gate['duplicateContinuation'] == 0
                  and gate['fabricatedUrlOrDiagnostic'] == 0
                  and gate['providerSwitches'] == 0)
    failures = [{'caseId': item['caseId'], 'repeat': item['repeat'], 'observedState': item['observedState'],
                 'expectedState': item['expectedState'], 'score': item['score'],
                 'error': item.get('error')} for item in cells if not item['passed']]
    return {'schema': RESULTS_SCHEMA + '/scoring', 'gate': gate, 'roles': roles,
            'cells': cells, 'failures': failures}


def _count_rule_failures(cells, kind):
    count = 0
    for item in cells:
        for role in item['roles'].values():
            for rule in role['rules']:
                if rule['kind'] == kind and not rule['passed']:
                    count += 1
    return count


# --------------------------------------------------------------------------- config hash
CONFIG_SOURCE_FILES = (
    'backend/src/agentbox/agent_core/work_policy.py',
    'backend/src/agentbox/agent_core/work_checks.py',
    'backend/src/agentbox/agent_core/work_graph.py',
    'backend/src/agentbox/agent_core/runtime.py',
)
CONFIG_ENV_KNOBS = ('BOXFOX_WORK_HELPER_OUTPUT_TOKENS', 'BOXFOX_WORK_ISOLATION',
                    'BOXFOX_WORK_GRAPH', 'BOXFOX_WORK_CHECK_OUTPUT_TOKENS')


def policy_version(repo_dir=REPO_DIR):
    """Đọc `work_policy.VERSION` từ chính repo đang chạy (W8 bump /11 — KHÔNG hardcode)."""
    path = Path(repo_dir) / 'backend/src/agentbox/agent_core/work_policy.py'
    if path.exists():
        match = re.search(r"^VERSION\s*=\s*'([^']+)'", path.read_text(encoding='utf-8'), re.M)
        if match:
            return match.group(1)
    return None


def config_hash(repo_dir=REPO_DIR, env=None):
    env = env if env is not None else os.environ
    digests, missing = {}, []
    for relative in CONFIG_SOURCE_FILES:
        path = Path(repo_dir) / relative
        if path.exists():
            digests[relative] = manifest_mod.file_hash(path)['sha256']
        else:
            missing.append(relative)
    knobs = {name: env.get(name) for name in CONFIG_ENV_KNOBS}
    payload = json.dumps({'policyVersion': policy_version(repo_dir), 'sources': digests,
                          'knobs': knobs}, sort_keys=True)
    return {'policyVersion': policy_version(repo_dir), 'sources': digests, 'knobs': knobs,
            'missing': missing, 'combined': hashlib.sha256(payload.encode('utf-8')).hexdigest()}


# --------------------------------------------------------------------------- kế hoạch / dry-run
def scenario_budget(scenario, *, deadline_seconds=DEADLINE_SECONDS, max_steps=DEFAULT_MAX_STEPS):
    budget = scenario.get('budget') or {}
    return {'maxSteps': int(budget.get('maxSteps') or max_steps),
            'deadlineSeconds': int(budget.get('deadlineSeconds') or deadline_seconds)}


def parse_shard(value):
    """`--shard I/N` → `(I, N)`; sai định dạng là lỗi cách dùng."""
    parts = str(value or '').strip().split('/')
    if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
        raise ValueError(f'--shard phải có dạng I/N (nhận {value!r})')
    index, count = (int(part) for part in parts)
    if not 1 <= count <= 64:
        raise ValueError(f'--shard: N phải trong 1..64 (nhận {count})')
    if not 1 <= index <= count:
        raise ValueError(f'--shard: I phải trong 1..{count} (nhận {index})')
    return index, count


def shard_cells(cells, index, count):
    """Chia `cells` thành `count` shard LIÊN TIẾP (không có shard rỗng).

    Hai lần lặp của cùng ca nằm cạnh nhau trong kế hoạch nên thường chung một shard, nhưng điều đó
    không được bảo đảm với mọi N (ví dụ N=5, 7, 8, 24): độ phủ thì luôn đúng và đủ.
    """
    if count < 1 or not 1 <= index <= count:
        raise ValueError(f'shard {index}/{count} không hợp lệ')
    size, extra = divmod(len(cells), count)
    start = (index - 1) * size + min(index - 1, extra)
    end = start + size + (1 if index <= extra else 0)
    return list(cells[start:end])


def build_plan(scenarios, *, repeats=REPEATS, out_root=DEFAULT_OUT_ROOT, repo_dir=REPO_DIR,
               budget_usd=None, with_v=False, env=None, shard=None):
    """Kế hoạch bất biến trước khi chạy: 24 lượt (+V), deadline từng lượt, không quét mở."""
    cells = []
    for scenario in scenarios:
        budget = scenario_budget(scenario)
        for repeat in range(1, repeats + 1):
            cells.append({
                'caseId': scenario['id'], 'repeat': repeat, 'title': scenario.get('title', ''),
                'expectedState': scenario['expectedState'], 'goal': scenario.get('goal', ''),
                'expectedStateSource': scenario.get('expectedStateSource', 'run'),
                'ownerLanguage': scenario.get('ownerLanguage', 'vi'),
                'intent': intent_command(scenario),
                'maxSteps': budget['maxSteps'], 'deadlineSeconds': budget['deadlineSeconds'],
                'isolation': 'session mới + DB riêng + workspace riêng',
                'workspace': [entry['path'] for entry in (scenario.get('workspace') or {}).get('files', [])],
                'faults': [fault['kind'] for fault in scenario.get('faults') or []],
                'oracleRules': sum(len(rules) for rules in (scenario.get('oracle') or {}).values()),
            })
    total = len(cells)
    if shard:
        cells = shard_cells(cells, shard[0], shard[1])
    plan = {'schema': RESULTS_SCHEMA + '/plan', 'mode': 'execute' if _execute_requested() else 'dry-run',
            'createdAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'repo': str(repo_dir), 'commit': manifest_mod.repo_state(repo_dir).get('commit'),
            'configHash': config_hash(repo_dir, env), 'provider': PROVIDER_ID, 'model': MODEL_ID,
            'repeats': repeats, 'cellCount': len(cells), 'withV': bool(with_v),
            'cases': [scenario['id'] for scenario in scenarios],
            'budgetUsd': budget_usd, 'outRoot': str(out_root), 'cells': cells}
    if shard:
        plan['shard'] = {'index': shard[0], 'count': shard[1], 'cellsTotal': total}
    return plan


def _execute_requested():
    return '--execute' in sys.argv


def render_plan(plan):
    lines = [f"W10 benchmark nghiệm thu Work Graph — {plan['mode']}",
             f"  repo      : {plan['repo']} @ {plan['commit']}",
             f"  policy    : {plan['configHash']['policyVersion']} "
             f"(combined {plan['configHash']['combined'][:12]})",
             f"  provider  : {plan['provider']} / {plan['model']} (không thay thế)",
             f"  lượt      : {plan['cellCount']} = {len(plan['cases'])} kịch bản × {plan['repeats']} lần"]
    if plan.get('shard'):
        shard = plan['shard']
        lines.append(f"  shard     : {shard['index']}/{shard['count']} "
                     f"({plan['cellCount']}/{shard['cellsTotal']} lượt của kế hoạch đầy đủ)")
    lines += [f"  ngân sách : {plan['budgetUsd'] if plan['budgetUsd'] is not None else '(chưa đặt)'} USD",
              f"  kết quả   : {plan['outRoot']}",
              '  kịch bản  :']
    for cell in plan['cells']:
        faults = ','.join(cell['faults']) or '-'
        expected = cell['expectedState']
        expected = '|'.join(expected) if isinstance(expected, list) else expected
        lines.append(f"    {cell['caseId']} r{cell['repeat']}: intent=/{cell['intent']:<8}"
                     f" expected={expected:<24}"
                     f" src={cell['expectedStateSource']:<5} steps≤{cell['maxSteps']:<4}"
                     f" deadline={cell['deadlineSeconds']}s faults={faults} rules={cell['oracleRules']}")
    lines.append('  chế độ dry-run: không mở socket, không gọi model. '
                 'Chạy thật: BOXFOX_EVAL_ALLOW_SPEND=1 python3 scripts/eval/work_acceptance_bench.py '
                 '--execute --budget-usd <N> [--out DIR] [--shard I/N]')
    lines.append('  cảnh báo  : thiếu `intent` (hoặc BOXFOX_WORK_GRAPH=off) thì root ở `legacy`, '
                 'không run nào được dựng và mọi lượt thành `no_run`.')
    return '\n'.join(lines)


# --------------------------------------------------------------------------- executor/workspace
def long_document_text(chars=15000):
    """Tài liệu dài tất định: mâu thuẫn nằm ở CUỐI file (reviewer phải đọc hết mới thấy)."""
    chars = max(200, int(chars))
    head = '# Thiết kế job API (bản dài)\n\n'
    block = ('## Phần tham chiếu\nTrạng thái DONE trả result_url; FAILED không có result_url.\n'
             'Phần này lặp lại để đo khả năng đọc hết tài liệu; nội dung không đổi.\n\n')
    tail = ('\n## Hợp đồng cuối (mâu thuẫn)\nKhi FAILED phải trả result_url bắt buộc; khi DONE '
            'tuyệt đối không có result_url.\n')
    body = head
    while len(body) < max(0, chars - len(tail)):
        body += block
    return body[:max(0, chars - len(tail))] + tail


def seed_workspace(workspace, scenario):
    """Tạo workspace riêng của lượt: file seed + git commit mốc, rồi mới thả file ngoài run."""
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / 'README.md').write_text(
        '# W10 workspace\n\nWorkspace dùng một lần cho một lượt benchmark.\n', encoding='utf-8')
    (workspace / 'conftest.py').write_text(
        '# Giữ rootdir trên sys.path để `from src.… import …` chạy được trong pytest.\n',
        encoding='utf-8')
    for entry in (scenario.get('workspace') or {}).get('files', []):
        path = workspace / _relative(entry['path'], 'workspace.files.path')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(entry.get('content', '')), encoding='utf-8')
    for source in scenario.get('sources') or []:
        raw = source.get('path')
        if not raw:
            continue
        path = workspace / _relative(raw, 'sources.path')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(source.get('content', '')), encoding='utf-8')
    for fault in scenario.get('faults') or []:
        if fault['kind'] == 'long_document':
            path = workspace / fault['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(long_document_text(fault.get('chars', 15000)), encoding='utf-8')
    git = shutil.which('git')
    if not git:
        return {'git': False, 'note': 'không có git trong PATH'}
    subprocess.run([git, 'init', '-q'], cwd=workspace, capture_output=True, check=False)
    subprocess.run([git, 'add', '-A'], cwd=workspace, capture_output=True, check=False)
    subprocess.run([git, '-c', 'user.email=w10@bench', '-c', 'user.name=W10', 'commit', '-qm', 'seed'],
                   cwd=workspace, capture_output=True, check=False)
    # File ngoài run được thả SAU commit để worktree dirty đúng nghĩa "thay đổi ngoài run".
    for fault in scenario.get('faults') or []:
        if fault['kind'] == 'dirty_foreign_file':
            path = workspace / fault['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(fault.get('content', '')), encoding='utf-8')
    return {'git': True}


class WorkspaceExecutor:
    """Executor của lượt: chạy thật trong workspace riêng, không chạm repo chính, không ra mạng."""

    def __init__(self, workspace, scenario):
        self.workspace = Path(workspace).resolve()
        self.scenario = scenario

    def path(self, raw):
        target = (self.workspace / str(raw or '.')).resolve()
        if target != self.workspace and self.workspace not in target.parents:
            raise PermissionError(f'W10 workspace: từ chối đường dẫn ngoài workspace: {raw}')
        return target

    async def execute(self, name, args, sid, **identity):
        if name == 'write_plan':
            raw = '.plans/' + str(args.get('directory', 'work')) + '/v1-' + str(args.get('slug', 'plan')) + '.md'
            path = self.path(raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(args.get('markdown', '')), encoding='utf-8')
            return {'relativePath': raw, 'version': 1, 'fixture': True}
        if name == 'file_write':
            path = self.path(args.get('path'))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(str(args.get('content', '')).encode('utf-8'))
            return {'path': args.get('path'), 'bytes': path.stat().st_size}
        if name == 'file_read':
            path = self.path(args.get('path'))
            if not path.is_file():
                return {'is_error': True, 'error': 'WORK_ARTIFACT_UNKNOWN: không thấy tệp ' + str(args.get('path'))}
            return {'content': path.read_text(encoding='utf-8', errors='replace'),
                    'path': args.get('path')}
        if name in ('codebase_glob', 'codebase_grep'):
            pattern = str(args.get('pattern') or args.get('query') or '**/*')
            query = str(args.get('query') or '')
            matches = []
            for path in sorted(self.workspace.rglob('*')):
                if not path.is_file() or '.git' in path.parts:
                    continue
                relative = path.relative_to(self.workspace).as_posix()
                if name == 'codebase_glob':
                    if fnmatch.fnmatch(relative, pattern):
                        matches.append(relative)
                else:
                    for number, line in enumerate(path.read_text(encoding='utf-8',
                                                                 errors='replace').splitlines(), 1):
                        if query and query in line:
                            matches.append(f'{relative}:{number}: {line}')
            return {'content': '\n'.join(matches), 'matches': matches[:200]}
        if name == 'terminal_exec':
            return await self.terminal(args)
        return {'is_error': True, 'error': 'W10 fixture: công cụ không thuộc lượt: ' + str(name)}

    async def terminal(self, args):
        command = str(args.get('command') or '').strip()
        allowed = command == work_checks_snapshot_command() or command.startswith('python -m pytest') \
            or command.startswith('python3 -m pytest') or command.startswith('git status') \
            or command.startswith('git diff')
        if not allowed:
            return {'is_error': True, 'error': 'W10 fixture: chỉ cho phép lệnh test/snapshot/git đọc; '
                                               'không chạy: ' + command}
        # `shlex` để lệnh snapshot (`python3 -c "import base64;exec(...)"`) không bị cắt sai chỗ trắng.
        argv = [sys.executable, '-m', 'pytest', '-q'] if command.endswith('pytest -q') \
            else shlex.split(command)
        proc = await asyncio.create_subprocess_exec(*argv, cwd=self.workspace,
                                                    stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        return {'content': (out + err).decode('utf-8', errors='replace'),
                'exit_code': proc.returncode, 'is_error': proc.returncode != 0}

    async def cleanup(self, sid):
        return None


def work_checks_snapshot_command():
    """Đọc `SNAPSHOT_COMMAND` từ work_checks mà không import agentbox ở đường dry-run."""
    try:
        from agentbox.agent_core import work_checks  # noqa: PLC0415 — chỉ trong execute
    except Exception:
        return 'W10:snapshot-unavailable'
    return work_checks.SNAPSHOT_COMMAND


class FixtureWeb:
    """Web host-side của lượt: canned theo fixture hoặc lỗi cố ý; không bao giờ ra Internet."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = []
        self.fault = next((fault for fault in scenario.get('faults') or []
                           if fault['kind'] == 'search_error'), None)

    async def run(self, name, args, sid, scope_id=None):
        self.calls.append({'name': name, 'args': args, 'sessionId': sid})
        if name == 'web_search' and self.fault:
            return {'is_error': True, 'code': 'SEARCH_PROVIDER_ERROR',
                    'error': self.fault.get('message', 'SEARCH_PROVIDER_ERROR: nhà cung cấp tìm kiếm lỗi')}
        if name == 'web_search':
            return {'content': json.dumps(self.scenario.get('searchResults') or [], ensure_ascii=False),
                    'results': self.scenario.get('searchResults') or [], 'fixture': True}
        if name in ('web_fetch', 'read_source'):
            raw = str(args.get('url') or args.get('path') or '')
            for source in self.scenario.get('sources') or []:
                if raw and raw in {str(source.get('url')), str(source.get('path'))}:
                    return {'content': str(source.get('content', '')), 'url': raw, 'fixture': True}
            return {'is_error': True, 'code': 'SOURCE_UNAVAILABLE',
                    'error': 'SOURCE_UNAVAILABLE: fixture không có nguồn này'}
        return {'is_error': True, 'code': 'TOOL_UNAVAILABLE',
                'error': 'W10 fixture: công cụ web không thuộc lượt: ' + str(name)}


class RecordingClient:
    """Bọc RouterClient của lượt: ghi route/usage, áp fault output_length/claim_unsourced."""

    def __init__(self, inner, scenario, providers=None):
        self.inner = inner
        self.scenario = scenario
        self.providers = dict(providers or {})
        self.calls = []
        self.root_session_id = None
        self.length_fault = next((fault for fault in scenario.get('faults') or []
                                  if fault['kind'] == 'output_length'), None)
        self.length_left = int((self.length_fault or {}).get('calls', 1))
        self.claim_fault = next((fault for fault in scenario.get('faults') or []
                                 if fault['kind'] == 'claim_unsourced'), None)
        self.claim_left = int((self.claim_fault or {}).get('calls', 1))

    async def complete(self, messages, tools, route, **kwargs):
        started = time.monotonic()
        response = await self.inner.complete(messages, tools, route, **kwargs)
        usage = response.get('usage') or {}
        call = {'providerId': self.providers.get(route.get('connectionId')),
                'modelId': route.get('modelId'), 'connectionId': route.get('connectionId'),
                'sessionId': route.get('sessionId'),
                'tokensIn': usage.get('prompt_tokens'), 'tokensOut': usage.get('completion_tokens'),
                'wallMs': int((time.monotonic() - started) * 1000)}
        if self.length_fault and self.length_left > 0:
            self.length_left -= 1
            choices = response.get('choices') or [{}]
            message = choices[0].setdefault('message', {})
            limit = int(self.length_fault.get('maxChars', 240))
            message['content'] = str(message.get('content') or '')[:limit]
            message['tool_calls'] = []
            choices[0]['finish_reason'] = 'length'
            call['fault'] = 'output_length'
        if self.claim_fault and self.claim_left > 0 and route.get('sessionId') != self.root_session_id:
            choices = response.get('choices') or [{}]
            message = choices[0].setdefault('message', {})
            if not message.get('tool_calls') and message.get('content'):
                # Helper trả "path đã kiểm" nhưng chưa hề mở nó: W6.2 phải gắn WORK_CLAIM_UNSOURCED
                # và main không được dùng câu trả lời này (marker dưới đây không được xuất hiện lại).
                self.claim_left -= 1
                message['content'] = str(message['content']) + '\n\n' + str(
                    self.claim_fault.get('text')
                    or 'Đã xác minh src/ghost.py:42 — mã ghost-sentinel-7f3a hoạt động đúng.')
                call['fault'] = 'claim_unsourced'
        call['finishReason'] = ((response.get('choices') or [{}])[0]).get('finish_reason')
        self.calls.append(call)
        return response

    def __getattr__(self, name):
        return getattr(self.inner, name)


# --------------------------------------------------------------------------- chạy thật
def apply_config_faults(config, scenario):
    """Fault mức config: bỏ một role khỏi `subagents` (W1.P) — preflight phải chặn trước producer."""
    roles = _role_ids()
    if roles:
        config['subagents'] = [{'id': role, 'enabled': True, 'model': 'inherit'} for role in roles]
    for fault in scenario.get('faults') or []:
        if fault['kind'] == 'missing_role' and config.get('subagents'):
            kept = [item for item in config['subagents'] if item['id'] != fault['role']]
            config['subagents'] = kept or config['subagents']
    return config


def _role_ids():
    try:
        from agentbox.agent_core import roles as roles_mod  # noqa: PLC0415 — chỉ trong execute
    except Exception:
        return ()
    return tuple(roles_mod.ROLES)


def _live_imports():
    """Import agentbox chỉ trong đường execute — dry-run phải ở lại stdlib-không-mạng."""
    sys.path.insert(0, str(REPO_DIR / 'backend/src'))
    os.environ.setdefault('BOXFOX_SYSTEM_LOG_DIR', str(REPO_DIR / '.tmp/work-acceptance/logs'))
    from agentbox.agent_core import runtime as runtime_mod  # noqa: PLC0415
    from agentbox.agent_core import work_feedback, work_graph  # noqa: PLC0415
    from agentbox.memory import session_store  # noqa: PLC0415
    return runtime_mod, work_graph, work_feedback, session_store


def require_work_graph():
    """Bench chỉ có nghĩa khi Work Graph bật: `BOXFOX_WORK_GRAPH=off` trả mọi lượt về `legacy`."""
    _, work_graph, _, _ = _live_imports()
    if not work_graph.enabled():
        raise ValueError('BOXFOX_WORK_GRAPH=off: mọi lượt sẽ là `no_run` — bật Work Graph trước khi chạy bench')
    return work_graph


def _descendants(store, root):
    rows = [dict(row) for row in store.db.execute('SELECT id, parent_id, role, config FROM sessions')]
    by_parent = {}
    for row in rows:
        by_parent.setdefault(row['parent_id'], []).append(row)
    found, stack = [], [root]
    while stack:
        for row in by_parent.get(stack.pop(), []):
            found.append(row)
            stack.append(row['id'])
    return found


def _safe_events(store, sid):
    try:
        return [{'seq': row.get('seq'), 'kind': row.get('type'), 'data': row.get('data'),
                 'created': row.get('created'), 'sessionId': sid}
                for row in store.events(sid) or []]
    except Exception:
        return []


def collect_bundle(store, graph, sid, scenario, client, *, error=None, notes=None, workspace=None):
    """Đọc sự thật của lượt từ DB/run/check/feedback — đầu vào duy nhất của oracle."""
    missing = []
    try:
        sessions = [{'id': sid, 'role': 'orchestrator', 'parent_id': None, 'config': {}}] \
            + _descendants(store, sid)
    except Exception as exc:
        sessions, _ = [{'id': sid, 'role': 'orchestrator'}], missing.append(f'sessions: {exc}')
    events = []
    for session in sessions:
        events += _safe_events(store, session['id'])
    events.sort(key=lambda item: (item.get('created') or 0, item.get('seq') or 0))
    roles = {session['id']: session.get('role') for session in sessions}
    turns = []
    for event in events:
        data = event.get('data') or {}
        if event.get('kind') == 'turn_end':
            turns.append({'role': roles.get(event.get('sessionId')), 'sessionId': event.get('sessionId'),
                          'status': data.get('status'), 'stepsUsed': data.get('stepsUsed'),
                          'outputTokens': data.get('outputTokens')})
        if event.get('kind') == 'assistant' and data.get('final'):
            turns.append({'role': 'assistant', 'sessionId': event.get('sessionId'),
                          'text': data.get('text')})
    runs = []
    try:
        runs = graph.runs(sid, limit=20) or []
    except Exception as exc:
        missing.append(f'run: {exc}')
    run = next((item for item in runs if item.get('status') not in TERMINAL_RUN_STATUSES), None) or \
        (runs[0] if runs else None)
    if run is None:
        missing.append('run: không có work graph run nào cho phiên')
    checks = []
    if run:
        try:
            checks = graph.checks.records(run['runId']) or []
        except Exception as exc:
            missing.append(f'checks: {exc}')
    feedback = []
    if run:
        try:
            feedback = [graph.feedback.card(doc) for doc in graph.feedback.records(run['runId'])]
        except Exception as exc:
            missing.append(f'feedback: {exc}')
    outbox = []
    if run:
        try:
            outbox = [json.loads(row['doc']) | {'outboxId': row['id'], 'outboxStatus': row['status']}
                      for row in graph.continuations.rows(run['runId'])]
        except Exception as exc:
            missing.append(f'outbox: {exc}')
    artifacts = []
    if run:
        try:
            for row in store.db.execute('SELECT * FROM work_artifacts WHERE run_id=?', (run['runId'],)):
                meta = json.loads(row['metadata'])
                artifacts.append(dict(meta) | {'artifactId': row['id'], 'runId': row['run_id'],
                                               'sessionId': row['session_id'], 'text': row['content']})
        except Exception as exc:
            missing.append(f'artifacts: {exc}')
    children = [{'id': session['id'], 'role': session.get('role'), 'parentId': session.get('parent_id')}
                for session in sessions if session['id'] != sid]
    ship = ship_report(workspace, run) if workspace else {}
    bundle = build_bundle(events=events, run=run, checks=checks, feedback=feedback, turns=turns,
                          children=children, artifacts=artifacts, calls=client.calls,
                          child_sessions={session['id']: session.get('role') for session in sessions},
                          config={'faults': scenario.get('faults') or [], 'session': sid,
                                  'ship': ship},
                          expected_state=scenario['expectedState'], missing=missing,
                          continuations=outbox)
    if error:
        bundle['missing'].append(f'turn: {error}')
    bundle['notes'] = list(notes or [])
    return bundle


def ship_report(workspace, run):
    """Tập file thật sự vào commit ship + trạng thái dirty của workspace (kiểm 'file ngoài run')."""
    workspace = Path(workspace)
    commit = ((run or {}).get('ship') or {}).get('commit')
    report = {'commit': commit, 'files': [], 'dirty': [], 'branch': None}
    if not shutil.which('git') or not (workspace / '.git').exists():
        return report
    if commit:
        out = subprocess.run(['git', '-C', str(workspace), 'show', '--pretty=format:', '--name-only',
                              str(commit)], capture_output=True, text=True, check=False)
        report['files'] = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    status = subprocess.run(['git', '-C', str(workspace), 'status', '--porcelain',
                             '--untracked-files=all'],
                            capture_output=True, text=True, check=False)
    report['dirty'] = [line[3:].strip() for line in status.stdout.splitlines() if line.strip()]
    branch = subprocess.run(['git', '-C', str(workspace), 'rev-parse', '--abbrev-ref', 'HEAD'],
                            capture_output=True, text=True, check=False)
    report['branch'] = branch.stdout.strip() or None
    return report


def _pending_answer(card, pool):
    supplied = []
    for index, question in enumerate(card.get('questions') or []):
        item = dict(pool[index]) if index < len(pool) else {'optionId': 'decide'}
        supplied.append({'questionId': question['id'], **item})
    return supplied


async def drive_session(rt, graph, work_feedback, sid, scenario, *, deadline_seconds):
    """Vòng đời một lượt: chạy tới trạng thái cuối, trả lời interview, chịu fault, không tự bịa."""
    deadline = time.monotonic() + float(scenario_budget(scenario, deadline_seconds=deadline_seconds)
                                        ['deadlineSeconds'])
    answers = list(scenario.get('interviewAnswers') or [])
    revision_answers = next((fault.get('answers') or [] for fault in scenario.get('faults') or []
                             if fault['kind'] == 'answer_revision'), [])
    restart_fault = next((fault for fault in scenario.get('faults') or []
                          if fault['kind'] == 'restart_while_waiting'), None)
    answered_by_request, revision_done, restarted, resumed_main = {}, False, False, False
    notes = []
    task = rt.start(sid, scenario['prompt'])
    idle_since = None
    while time.monotonic() < deadline:
        live = [item for item in rt.tasks.values() if not item.done()]
        if live:
            await asyncio.wait(live, timeout=min(DRIVE_POLL_SECONDS * 2,
                                                 max(0.1, deadline - time.monotonic())))
        else:
            await asyncio.sleep(0.05)
        try:
            await work_feedback.pump(rt)
        except Exception as exc:  # pump hỏng không được giết lượt; oracle vẫn thấy sự thật
            notes.append(f'pump: {type(exc).__name__}: {exc}')
        cards = rt.pending_for(sid) or []
        interviews = [card for card in cards if card.get('kind') == 'interview']
        if restart_fault and not restarted and interviews:
            store, rt, graph = _restart_session(rt, sid, notes)
            restarted = True
            notes.append('restart_while_waiting: đã khởi động lại harness giữa lúc chờ trả lời')
            continue
        for card in cards:
            if card.get('kind') == 'interview':
                continue
            options = card.get('options') or []
            choice = next((option['id'] for option in options if option.get('kind') == 'approve'), None) \
                or next((option['id'] for option in options
                         if option.get('id') in ('approve', 'submit', 'accept', 'yes')), None) \
                or card.get('defaultChoice')
            if not choice:
                continue
            try:
                rt.resolve_decision(sid, card['decisionId'], choice)
                notes.append(f"autopilot: duyệt {card['decisionId']} → {choice}")
            except Exception as exc:
                notes.append(f'settle {card["decisionId"]}: {type(exc).__name__}: {exc}')
        for card in interviews:
            request_id = card.get('requestId') or str(card.get('decisionId', '')).rsplit('-r', 1)[0]
            revision = int(card.get('revision') or 0)
            if answered_by_request.get(request_id) == revision:
                continue
            first_round = request_id not in answered_by_request
            pool = answers if first_round else (revision_answers or answers)
            if not first_round and revision_answers:
                revision_done = True
            supplied = _pending_answer(card, pool)
            if not supplied:
                continue
            try:
                rt.resolve_decision(sid, card['decisionId'], 'submit', answers=supplied)
                answered_by_request[request_id] = revision
                notes.append(f"interview {request_id} r{revision}: trả lời {len(supplied)} câu")
            except Exception as exc:
                notes.append(f'answer {card["decisionId"]}: {type(exc).__name__}: {exc}')
        live = [item for item in rt.tasks.values() if not item.done()]
        # W7.1 sau restart: card sống sót nhưng lượt main cũ đã mất theo tiến trình, nên
        # người dùng gửi một lượt mới để run đi tiếp — đúng thao tác thật sau khi khởi động lại.
        if restarted and not resumed_main and not live and not cards \
                and not _pending_continuations(graph):
            try:
                task = rt.start(sid, RESTART_RESUME_PROMPT)
                notes.append('restart_while_waiting: mở lượt main mới để run đi tiếp')
            except Exception as exc:
                notes.append(f'resume sau restart: {type(exc).__name__}: {exc}')
            resumed_main = True
            live = [item for item in rt.tasks.values() if not item.done()]
        run = _current_run(graph, sid)
        status = (run or {}).get('status')
        if not live and not cards and (task.done() or status in TERMINAL_RUN_STATUSES
                                       or status in ('verified', 'executed', 'execute_failed')):
            if idle_since is None:
                idle_since = time.monotonic()
            elif time.monotonic() - idle_since >= DRIVE_SETTLE_SECONDS:
                break
        else:
            idle_since = None
    else:
        notes.append('deadline: lượt chạm hạn wall-clock')
    for item in list(rt.tasks.values()):
        if not item.done():
            item.cancel()
    await asyncio.gather(*rt.tasks.values(), return_exceptions=True)
    return notes


def _current_run(graph, sid):
    runs = graph.runs(sid, limit=20) or []
    return next((item for item in runs if item.get('status') not in TERMINAL_RUN_STATUSES), None) \
        or (runs[0] if runs else None)


def _pending_continuations(graph):
    """Còn job resume_child nào đang chờ không — dùng để không mở lượt main quá sớm."""
    try:
        return bool(graph.continuations.rows())
    except Exception:
        return False


def _restart_session(rt, sid, notes):
    """Khởi động lại harness trên cùng DB/workspace (W7.1) — thẻ còn, child phải giữ nguyên."""
    runtime_mod, work_graph, _, _ = _live_imports()
    store = rt.store
    path = getattr(store, 'w10_path', None)
    executor, client = rt.executor, rt.client
    try:
        store.db.close()
    except Exception as exc:
        notes.append(f'restart close: {type(exc).__name__}: {exc}')
    if path is None:
        raise RuntimeError('W10 restart: không biết đường dẫn DB của phiên')
    fresh_store = type(store)(Path(path))
    fresh_store.w10_path = Path(path)
    fresh = runtime_mod.HarnessRuntime(fresh_store, executor, client)
    fresh.web = rt.web
    return fresh_store, fresh, work_graph.service(fresh)


async def run_cell(scenario, repeat, *, out_dir, route, router_url, deadline_seconds):
    """Một lượt: workspace riêng + DB riêng + session riêng; trả bundle đã gom để chấm."""
    runtime_mod, work_graph, work_feedback, session_store = _live_imports()
    if not work_graph.enabled():
        raise ValueError('BOXFOX_WORK_GRAPH=off: mọi lượt sẽ là `no_run` — bật Work Graph trước khi chạy bench')
    cell_dir = Path(out_dir) / 'runs' / f"{scenario['id']}-r{repeat}"
    cell_dir.mkdir(parents=True, exist_ok=True)
    workspace = cell_dir / 'workspace'
    seed_workspace(workspace, scenario)
    store = session_store.SessionStore(cell_dir / 'sessions.db')
    store.w10_path = cell_dir / 'sessions.db'
    client = RecordingClient(runtime_mod.RouterClient(router_url), scenario,
                             providers={route['connectionId']: route['providerId']})
    rt = runtime_mod.HarnessRuntime(store, WorkspaceExecutor(workspace, scenario), client)
    rt.web = FixtureWeb(scenario)
    graph = work_graph.service(rt)
    budget = scenario_budget(scenario, deadline_seconds=deadline_seconds)
    config = {'skills': [], 'autopilot': True, 'maxSteps': budget['maxSteps'],
              'deadlineSeconds': budget['deadlineSeconds'], **route}
    config = apply_config_faults(config, scenario)
    session = rt.create(config)
    sid = session['id']
    client.root_session_id = sid
    # Đường chạy thật: chủ nhà PHẢI yêu cầu việc trước lượt (`/plan|/research|/design <text>` ghi
    # `config.workIntent`; harness mô phỏng bằng chính `work_graph.set_intent`). Thiếu ý định thì
    # `work_scope` giữ root ở `legacy`, root tự sửa mã và không run nào ra đời (S02: work_runs=0).
    intent = work_graph.set_intent(rt, session, intent_command(scenario), scenario['prompt'])
    started = time.time()
    error = None
    try:
        notes = await drive_session(rt, graph, work_feedback, sid, scenario,
                                    deadline_seconds=deadline_seconds)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        notes = []
    notes = [f"intent: /{intent['command']} → flow {intent['flow']} (chủ nhà yêu cầu việc)"] + list(notes)
    bundle = collect_bundle(store, graph, sid, scenario, client, error=error, notes=notes,
                            workspace=workspace)
    try:
        store.db.close()
    except Exception:
        pass
    wall_ms = int((time.time() - started) * 1000)
    validity = runner.classify_validity({'status': bundle['run'].get('status'),
                                         'errorCode': None if bundle['run'] else 'NO_RUN'})
    return {'scenario': scenario, 'repeat': repeat, 'bundle': bundle, 'error': error,
            'startedAt': started, 'wallTimeMs': wall_ms, 'validity': validity,
            'calls': client.calls, 'cellDir': str(cell_dir), 'intent': intent}


# --------------------------------------------------------------------------- main
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='W10 — benchmark nghiệm thu Work Graph')
    parser.add_argument('--execute', action='store_true',
                        help='chạy thật (cần BOXFOX_EVAL_ALLOW_SPEND=1 + ngân sách + biến kết nối)')
    parser.add_argument('--budget-usd', type=float, default=None,
                        help='trần chi phí cho cả benchmark (hoặc BOXFOX_EVAL_BUDGET_USD)')
    parser.add_argument('--out', default=None, help='thư mục kết quả (mặc định ~/BoxFox/eval-runs/...)')
    parser.add_argument('--repeats', type=int, default=REPEATS)
    parser.add_argument('--cases', default=None, help='danh sách id, ví dụ S01,S02 (mặc định S01–S12)')
    parser.add_argument('--shard', default=None,
                        help='chỉ chạy một phần của kế hoạch: I/N (1-based), ví dụ 2/4 cho tiến trình song song')
    parser.add_argument('--merge', default=None,
                        help='gộp results.json của các shard: danh sách thư mục/tệp, ví dụ s1,s2,s3 '
                             '(cần --out; không chạy model)')
    parser.add_argument('--with-v', action='store_true', help='thêm V06/V07/V10/V13/V14 (§9.2)')
    parser.add_argument('--deadline-seconds', type=int, default=DEADLINE_SECONDS)
    parser.add_argument('--max-steps', type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument('--fixtures', default=None, help='thư mục fixture khác (test/dev)')
    parser.add_argument('--rubric', default=None)
    parser.add_argument('--repo-dir', default=str(REPO_DIR))
    parser.add_argument('--router-url', default=None)
    parser.add_argument('--plan-only', action='store_true', help='chỉ ghi plan.json rồi thoát')
    return parser.parse_args(argv)


def selected_scenarios(args):
    directory = args.fixtures
    if args.cases:
        wanted = [item.strip().upper() for item in args.cases.split(',') if item.strip()]
        unknown = [item for item in wanted if item not in ALL_CASE_IDS]
        if unknown:
            raise ValueError(f'id kịch bản lạ: {unknown}')
        return [load_scenario(scenario_path(code, directory)) for code in wanted]
    return load_scenarios(directory, with_v=args.with_v)


def _write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def _rubric_role(role):
    """Vai của phiên → vai của rubric: phiên gốc (orchestrator) tính là `main`."""
    return role if role in RUBRIC_ROLES else 'main'


def write_results(out_dir, plan, cells, scoring, *, route, extra=None):
    """results.json: model, commit, config hash, attempts, budget, token/latency theo lượt và vai."""
    per_cell = []
    per_role = {}
    role_totals = {}
    for index, item in enumerate(cells):
        scenario, bundle = item['scenario'], item['bundle']
        run = bundle.get('run') or {}
        calls = item.get('calls') or []
        scored = scoring['cells'][index]
        by_role = {}
        for call in calls:
            role = _rubric_role((bundle.get('childSessions') or {}).get(call.get('sessionId')))
            row = by_role.setdefault(role, {'calls': 0, 'tokensIn': 0, 'tokensOut': 0, 'wallMs': 0})
            total = role_totals.setdefault(role, {'calls': 0, 'tokensIn': 0, 'tokensOut': 0, 'wallMs': 0})
            for key, value in (('tokensIn', call.get('tokensIn')), ('tokensOut', call.get('tokensOut')),
                               ('wallMs', call.get('wallMs'))):
                row[key] += int(value or 0)
                total[key] += int(value or 0)
            row['calls'] += 1
            total['calls'] += 1
        per_cell.append({'caseId': scenario['id'], 'repeat': item['repeat'],
                         'intent': intent_command(scenario),
                         'expectedState': scenario['expectedState'],
                         'observedState': scored['observedState'],
                         'passed': scored['passed'], 'score': scored['score'],
                         'failedRules': {role: list((scored['roles'].get(role) or {}).get('failed') or [])
                                         for role in RUBRIC_ROLES},
                         'validity': item.get('validity'), 'error': item.get('error'),
                         'runStatus': run.get('status'), 'wallTimeMs': item.get('wallTimeMs'),
                         'tokensIn': sum(call.get('tokensIn') or 0 for call in calls),
                         'tokensOut': sum(call.get('tokensOut') or 0 for call in calls),
                         'modelCalls': len(calls), 'roleLatency': by_role,
                         'steps': len([turn for turn in bundle.get('turns') or [] if turn.get('status')]),
                         'children': len(bundle.get('children') or [])})
    for role in RUBRIC_ROLES:
        per_role[role] = {'rules': scoring['roles'][role]['rules'],
                          'passed': scoring['roles'][role]['passed'],
                          'rate': scoring['roles'][role]['rate']}
        per_role[role].update(role_totals.get(role) or {'calls': 0, 'tokensIn': 0, 'tokensOut': 0,
                                                        'wallMs': 0})
    results = {'schema': RESULTS_SCHEMA, 'plan': plan, 'route': route,
               'configHash': plan['configHash'],
               'cells': per_cell, 'roles': per_role, 'gate': scoring['gate'],
               'failures': scoring['failures'],
               'tokens': {'in': sum(cell['tokensIn'] for cell in per_cell),
                          'out': sum(cell['tokensOut'] for cell in per_cell)},
               'wallTimeMs': sum(cell['wallTimeMs'] or 0 for cell in per_cell),
               'cost': manifest_mod.cost_from_entries(
                   [{'tokensIn': cell['tokensIn'], 'tokensOut': cell['tokensOut'],
                     'wallTimeMs': cell['wallTimeMs'], 'steps': cell['steps']}
                    for cell in per_cell]),
               'attempts': len(cells)}
    results.update(extra or {})
    return _write_json(Path(out_dir) / 'results.json', results)


# --------------------------------------------------------------------------- gộp shard
def results_path(directory):
    """`results.json` của một shard: nhận cả thư mục shard lẫn đường dẫn tệp."""
    path = Path(directory)
    if path.is_dir():
        path = path / 'results.json'
    if not path.is_file():
        raise ValueError(f'không thấy results.json: {path}')
    return path


def load_results(directories):
    """Đọc results.json của từng shard; trả cả đường dẫn để báo lỗi và ghi vết gộp."""
    docs, paths = [], []
    for directory in directories:
        path = results_path(directory)
        try:
            doc = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise ValueError(f'{path}: JSON hỏng ({exc})') from exc
        docs.append(doc)
        paths.append(path)
    return docs, paths


def _plan_identity(plan):
    return {'commit': plan.get('commit'), 'provider': plan.get('provider'), 'model': plan.get('model'),
            'repeats': plan.get('repeats'), 'cases': plan.get('cases'),
            'configHash': (plan.get('configHash') or {}).get('combined')}


def merge_results(docs, *, paths=None):
    """Gộp results.json của các shard: từ chối trùng/thiếu/khác cấu hình, cộng token, tính lại cổng."""
    if not docs:
        raise ValueError('cần ít nhất một results.json để gộp')
    labels = [str(path) for path in (paths or [])] or [str(index) for index in range(len(docs))]
    for label, doc in zip(labels, docs):
        if not isinstance(doc, dict) or doc.get('schema') != RESULTS_SCHEMA:
            raise ValueError(f'{label}: schema phải là {RESULTS_SCHEMA}')
    first = docs[0]
    identity = _plan_identity(first.get('plan') or {})
    if not identity['cases']:
        raise ValueError(f'{labels[0]}: plan thiếu `cases` — chạy lại shard bằng harness hiện tại')
    for label, doc in zip(labels[1:], docs[1:]):
        other = _plan_identity(doc.get('plan') or {})
        if other != identity:
            raise ValueError(f'{label}: khác cấu hình với shard đầu ({other} != {identity}) — không gộp được')
    cells, seen = [], {}
    for label, doc in zip(labels, docs):
        for cell in doc.get('cells') or []:
            if 'failedRules' not in cell:
                raise ValueError(f'{label}: results.json cũ thiếu `failedRules` — chạy lại shard bằng '
                                 'harness hiện tại rồi mới gộp')
            key = (str(cell.get('caseId')), int(cell.get('repeat') or 0))
            if key in seen:
                raise ValueError(f'trùng lượt {key[0]} r{key[1]} ({seen[key]} và {label})')
            seen[key] = label
            cells.append(cell)
    plan = dict(first.get('plan') or {})
    plan_cells = {}
    for doc in docs:
        for cell in (doc.get('plan') or {}).get('cells') or []:
            plan_cells[(str(cell.get('caseId')), int(cell.get('repeat') or 0))] = cell
    expected = {(case, repeat) for case in plan['cases']
                for repeat in range(1, int(plan.get('repeats') or REPEATS) + 1)}
    missing = sorted(expected - set(seen))
    extra = sorted(set(seen) - expected)
    if missing or extra:
        raise ValueError(f'gộp thiếu/lạ lượt: thiếu={missing} lạ={extra}')
    cells.sort(key=lambda cell: (str(cell.get('caseId')), int(cell.get('repeat') or 0)))
    order = [(str(cell.get('caseId')), int(cell.get('repeat') or 0)) for cell in cells]
    absent = [key for key in order if key not in plan_cells]
    if absent:
        raise ValueError(f'plan của shard thiếu lượt {absent}')
    for cell in cells:
        key = (str(cell.get('caseId')), int(cell.get('repeat') or 0))
        if cell.get('intent') != plan_cells[key].get('intent'):
            raise ValueError(f"{key[0]} r{key[1]}: intent lệch giữa kết quả ({cell.get('intent')}) và "
                             f"plan ({plan_cells[key].get('intent')}) — fixture đã đổi giữa các shard")
    plan['cells'] = [plan_cells[key] for key in order]
    plan['cellCount'] = len(plan['cells'])
    plan.pop('shard', None)
    plan['shards'] = labels
    roles = {}
    for role in RUBRIC_ROLES:
        rules = passed = 0
        totals = {'calls': 0, 'tokensIn': 0, 'tokensOut': 0, 'wallMs': 0}
        for doc in docs:
            row = (doc.get('roles') or {}).get(role) or {}
            rules += int(row.get('rules') or 0)
            passed += int(row.get('passed') or 0)
            for key in totals:
                totals[key] += int(row.get(key) or 0)
        roles[role] = {'rules': rules, 'passed': passed,
                       'rate': round(passed / rules, 4) if rules else 1.0, **totals}

    def hard(kind):
        return sum(list(kinds).count(kind) for cell in cells
                   for kinds in (cell.get('failedRules') or {}).values())

    state_passed = sum(1 for cell in cells
                       if state_matches(cell.get('observedState'), cell.get('expectedState')))
    gate = {'minPassed': GATE_MIN_PASSED, 'denominator': len(cells),
            'passed': sum(1 for cell in cells if cell.get('passed')),
            'statePassed': state_passed,
            'stateRate': round(state_passed / len(cells), 4) if cells else 0.0,
            'autoPass': hard('no_auto_pass'), 'sameChild': hard('same_child_continuation'),
            'duplicateContinuation': hard('no_duplicate_continuation'),
            'fabricatedUrlOrDiagnostic': hard('no_fabricated_url') + hard('no_diagnostic_leak'),
            'providerSwitches': hard('provider_unchanged')}
    gate['ok'] = (gate['denominator'] > 0 and gate['statePassed'] >= GATE_MIN_PASSED
                  and gate['autoPass'] == 0 and gate['sameChild'] == 0
                  and gate['duplicateContinuation'] == 0
                  and gate['fabricatedUrlOrDiagnostic'] == 0
                  and gate['providerSwitches'] == 0)
    failures = [{'caseId': cell.get('caseId'), 'repeat': cell.get('repeat'),
                 'observedState': cell.get('observedState'), 'expectedState': cell.get('expectedState'),
                 'score': cell.get('score'), 'error': cell.get('error')}
                for cell in cells if not cell.get('passed')]
    manifest = dict(first.get('manifest') or {})
    manifest.update(mergedFrom=labels, shards=len(docs))
    return {'schema': RESULTS_SCHEMA, 'plan': plan, 'route': first.get('route'),
            'configHash': first.get('configHash'), 'cells': cells, 'roles': roles, 'gate': gate,
            'failures': failures,
            'tokens': {'in': sum(int(cell.get('tokensIn') or 0) for cell in cells),
                       'out': sum(int(cell.get('tokensOut') or 0) for cell in cells)},
            'wallTimeMs': sum(int(cell.get('wallTimeMs') or 0) for cell in cells),
            'cost': manifest_mod.cost_from_entries(
                [{'tokensIn': int(cell.get('tokensIn') or 0), 'tokensOut': int(cell.get('tokensOut') or 0),
                  'wallTimeMs': cell.get('wallTimeMs'), 'steps': cell.get('steps')} for cell in cells]),
            'attempts': len(cells), 'manifest': manifest, 'mergedFrom': labels}


def merge_main(args):
    """`--merge`: gộp results.json của các shard thành kết quả cuối + cổng; không gọi model."""
    if not args.out:
        print('lỗi cách dùng: --merge cần --out DIR để ghi results.json đã gộp', file=sys.stderr)
        return EXIT_USAGE
    directories = [item.strip() for item in str(args.merge).split(',') if item.strip()]
    if not directories:
        print('lỗi cách dùng: --merge cần danh sách thư mục shard', file=sys.stderr)
        return EXIT_USAGE
    out_root = Path(args.out)
    try:
        docs, paths = load_results(directories)
        for path in paths:
            if out_root == path.parent or out_root in path.parents:
                raise ValueError(f'--out {out_root} nằm trong chính shard {path.parent} — chọn thư mục khác')
        merged = merge_results(docs, paths=paths)
    except ValueError as exc:
        print(f'lỗi cách dùng: {exc}', file=sys.stderr)
        return EXIT_USAGE
    path = _write_json(out_root / 'results.json', merged)
    print(f'gộp {len(docs)} shard → {len(merged["cells"])} lượt')
    print(render_gate(merged))
    print('results.json (gộp) →', path)
    return EXIT_OK if merged['gate']['ok'] else 1


def main(argv=None):
    args = parse_args(argv)
    if args.merge:
        if args.execute or args.shard or args.cases or args.with_v:
            print('lỗi cách dùng: --merge không đi cùng --execute/--shard/--cases/--with-v', file=sys.stderr)
            return EXIT_USAGE
        return merge_main(args)
    try:
        scenarios = selected_scenarios(args)
        shard = parse_shard(args.shard) if args.shard else None
    except ValueError as exc:
        print(f'lỗi cách dùng: {exc}', file=sys.stderr)
        return EXIT_USAGE
    out_root = Path(args.out) if args.out else DEFAULT_OUT_ROOT / time.strftime('%Y%m%d-%H%M%S')
    plan = build_plan(scenarios, repeats=args.repeats, out_root=out_root,
                      repo_dir=Path(args.repo_dir), budget_usd=args.budget_usd,
                      with_v=args.with_v, shard=shard)
    print(render_plan(plan))
    if not args.execute:
        if args.out or args.plan_only:
            print('plan.json →', _write_json(out_root / 'plan.json', plan))
        return EXIT_OK
    decision = guard.check(args.budget_usd)
    missing = guard.missing_connection()
    if not decision['allowed']:
        print(guard.rendered_refusal(decision, missing), file=sys.stderr)
        return EXIT_SPEND
    if missing:
        print('Thiếu biến kết nối: ' + ', '.join(item['name'] for item in missing)
              + ' — không chạy benchmark.', file=sys.stderr)
        return EXIT_CONNECTION
    try:
        require_work_graph()
    except ValueError as exc:
        print(f'lỗi cách dùng: {exc}', file=sys.stderr)
        return EXIT_USAGE
    router_url = args.router_url or os.environ.get('BOXFOX_ROUTER_BASE_URL', 'http://127.0.0.1:3101')
    try:
        state = net.request_json(router_url.rstrip('/') + '/api/router/state',
                                 headers={'x-boxfox-admin': '1'})
        route = select_route(state)
    except ProviderUnavailable as exc:
        print(exc.message, file=sys.stderr)
        return EXIT_PROVIDER
    print(f"route: {route['providerId']}/{route['modelId']} connection={route['connectionId']}")
    _write_json(out_root / 'plan.json', plan)
    by_id = {scenario['id']: scenario for scenario in scenarios}
    cells = []
    for planned in plan['cells']:
        scenario, repeat = by_id[planned['caseId']], planned['repeat']
        cell = asyncio.run(run_cell(scenario, repeat, out_dir=out_root, route=route,
                                    router_url=router_url,
                                    deadline_seconds=args.deadline_seconds))
        cells.append(cell)
        print(f"  {scenario['id']} r{repeat}: intent=/{cell['intent']['command']}"
              f" state={(cell['bundle'].get('run') or {}).get('status')}"
              f" validity={cell['validity']} {cell['wallTimeMs']}ms")
        _write_json(out_root / 'runs' / f"{scenario['id']}-r{repeat}" / 'bundle.json',
                    {'bundle': cell['bundle'], 'validity': cell['validity'],
                     'error': cell['error'], 'intent': cell['intent']})
    rubric = load_rubric(args.rubric)
    scoring = evaluate_run(cells, rubric)
    path = write_results(out_root, plan, cells, scoring, route=route,
                         extra={'shard': plan.get('shard'),
                                'manifest': manifest_mod.build_manifest(
                             benchmark_name='work-acceptance', benchmark_version=RESULTS_SCHEMA,
                             repo_dir=Path(args.repo_dir),
                             fixture_ids=[scenario['id'] for scenario in scenarios],
                             provider=PROVIDER_ID, model=MODEL_ID, seed=None, temperature=None,
                             max_steps=args.max_steps, deadline_seconds=args.deadline_seconds,
                             network='off', firewall='box', image_digest=None, judge_prompt=None,
                             created_at=None,
                             extra={'configHash': plan['configHash'], 'withV': args.with_v})})
    print(render_gate(scoring))
    print('results.json →', path)
    if plan.get('shard'):
        print(f"shard {plan['shard']['index']}/{plan['shard']['count']} — gộp bằng: "
              f"python3 scripts/eval/work_acceptance_bench.py --merge <dir1,dir2,...> --out <dir-gộp>")
    return EXIT_OK if scoring['gate']['ok'] else 1


def render_gate(scoring):
    gate = scoring['gate']
    lines = [f"cổng đạt: {'ĐẠT' if gate['ok'] else 'CHƯA ĐẠT'}",
             f"  expectedState : {gate['statePassed']}/{gate['denominator']} (cần ≥ {gate['minPassed']})",
             f"  auto-pass     : {gate['autoPass']} (cần 0)",
             f"  same-child    : {gate['sameChild']} lỗi (cần 0)",
             f"  trùng continuation: {gate['duplicateContinuation']} (cần 0)",
             f"  URL bịa/diagnostic: {gate['fabricatedUrlOrDiagnostic']} (cần 0)",
             f"  đổi provider  : {gate['providerSwitches']} (cần 0)"]
    for role, row in scoring['roles'].items():
        lines.append(f"  {role:<9}: {row['passed']}/{row['rules']} luật ({row['rate']:.0%})")
    if scoring['failures']:
        lines.append('  lượt chưa đạt:')
        for item in scoring['failures']:
            lines.append(f"    {item['caseId']} r{item['repeat']}: {item['observedState']}"
                         f" (expected {item['expectedState']}) score={item['score']}")
    return '\n'.join(lines)


if __name__ == '__main__':
    sys.exit(main())
