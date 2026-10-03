"""H8 — bộ soạn quyết định thích ứng cho main: thư viện thuần, không I/O.

Module trả lời đúng một câu: với `policy` của người gọi và dữ kiện quan sát được, bước
tiếp theo hợp lệ là `continue` / `branch` / `park` / `stop` / `blocked` — kèm lý do,
evidence refs, nhu cầu còn thiếu (`requires`) và ngân sách lấy từ policy. Nó KHÔNG cấp
quyền, không cấp ngân sách, không gọi model, không đọc store, không import `runtime.py`.

Quy tắc đã chốt (plan §3, §7, §8):

- Tiến triển chỉ tính khi có artifact/evidence mới, acceptance gap giảm, uncertainty
  được giải quyết hoặc checkpoint có kết quả quan sát được. Văn bản dài hơn, diễn giải
  lại, log lặp và số lần gọi tool KHÔNG phải tiến triển.
- Cùng failure signature với input/evidence không đổi: chặn lặp tự động, đòi checkpoint
  và đổi cách; signature đổi hoặc có evidence mới thì xoá chặn.
- Effort theo uncertainty × value, bị kẹp bởi capability (trần output công bố, mức
  reasoning công bố) và bởi trần trong policy. Capability không rõ ⇒ không phát minh số
  output token (`outputTokens=None` kèm lý do). Lịch sử reasoning token của lần trước
  không được ép hạ mức.
- Không tự đặt trần step/wall: chỉ tôn trọng `limits` do người gọi khai. Thiếu ngân sách
  cho khoản chi mới thì báo `requires=['consent']`, không suy là vô hạn.
- Stop/thu hồi epoch luôn thắng: không bao giờ mở nhánh mới sau đó.

Hình dạng dữ liệu (mọi khóa đều tùy chọn; thiếu thì module không tự suy ra quyền):

    policy = {'schema': 'boxfox-execution-policy/1', 'mode': 'adaptive',
              'ceilingRef': 'alloc-7', 'outputTokensCeiling': 16000, 'maxEffort': 'medium'}

    observation = {
        'stopRequested': bool | {'reason': str, 'evidenceRefs': [...]},
        'revoked': bool | 'capability' | {'kind': 'consent', 'evidenceRefs': [...]},
        'revokedEpoch': 3, 'epoch': 4,
        'goalMet': bool,
        'uncertainty': 'low|medium|high', 'value': 'low|medium|high',
        'capability': {'maxOutputTokens': 16000, 'thinkingLevels': ['low', 'medium']},
        'needs': ['consent', ...] | {'consent': True},
        'missingConsent': bool, 'missingCapability': [...], 'approvalPending': bool,
        'userDecisionPending': bool, 'needsBudget': bool,
        'spend': {'certainty': 'known|estimated|unknown', 'amount': 1.5, 'consentRef': ...},
        'budget': {'remaining': 12.0, 'ceilingRef': 'alloc-7'},
        'limits': {'steps': 40, 'deadlineSeconds': 600}, 'stepsTaken': 40, 'elapsedSeconds': 10,
        'branch': {'needed': True, 'reason': str, 'evidenceRefs': [...]},
        'park': bool | {'reason': str, 'waitFor': 'user'},
        'intent': 'analysis|plan|design|implementation', 'write': bool,
        'previous': {...}, 'current': {...},              # cho progress_signal
        'loop': {'history': [...], 'signature': ...} | {'repeat': bool, 'action': str},
        'evidenceRefs': [...],
    }

Mọi lý do trả về đều có mã `ADAPTIVE_*` ở đầu câu; `requires` chỉ chứa bốn giá trị
`consent`, `capability`, `approval`, `user_decision`. `budget` chỉ có
`{outputTokens, effort, ceilingRef}`, lấy từ policy/capability — không tự phát minh.
"""
import json

from .orchestration_contracts import ContractError, invalid
from .output_policy import DEFAULT_OUTPUT_TOKENS, REVIEW_OUTPUT_TOKENS, model_output_ceiling

DECISIONS = ('continue', 'branch', 'park', 'stop', 'blocked')
REQUIREMENTS = ('consent', 'capability', 'approval', 'user_decision')
EFFORT_LEVELS = ('low', 'medium', 'high')
PROGRESS_KINDS = ('artifact', 'evidence', 'acceptance_gap', 'uncertainty', 'checkpoint')

#: Yêu cầu output nền theo mức effort. Đây là REQUEST, luôn bị kẹp bởi trần công bố của
#: model và trần trong policy; capability không rõ thì không trả số nào (None).
#: 4096/16000 lấy từ `output_policy` (default/review), 8192 nằm trong dải lựa chọn hiện có.
EFFORT_OUTPUT_TOKENS = {'low': DEFAULT_OUTPUT_TOKENS, 'medium': 8192, 'high': REVIEW_OUTPUT_TOKENS}
EFFORT_WEIGHT = {'low': 0, 'medium': 1, 'high': 2}

# Mã lý do (đặt ở đầu `reason` để bên gọi so khớp ổn định).
STOP_REQUESTED = 'ADAPTIVE_STOP_REQUESTED'
EPOCH_REVOKED = 'ADAPTIVE_EPOCH_REVOKED'
LEGACY_POLICY = 'ADAPTIVE_LEGACY'
LOOP_REPEAT = 'ADAPTIVE_LOOP_REPEAT'
GOAL_MET = 'ADAPTIVE_GOAL_MET'
LIMIT_REACHED = 'ADAPTIVE_LIMIT_REACHED'
NEEDS_CONSENT = 'ADAPTIVE_NEEDS_CONSENT'
NEEDS_CAPABILITY = 'ADAPTIVE_NEEDS_CAPABILITY'
NEEDS_APPROVAL = 'ADAPTIVE_NEEDS_APPROVAL'
NEEDS_USER_DECISION = 'ADAPTIVE_NEEDS_USER_DECISION'
NEED_UNSUPPORTED = 'ADAPTIVE_NEED_UNSUPPORTED'
PARK_REQUESTED = 'ADAPTIVE_PARK_REQUESTED'
BRANCH_BENEFICIAL = 'ADAPTIVE_BRANCH_BENEFICIAL'
CONTINUE_DIRECT = 'ADAPTIVE_CONTINUE'
INTENT_WRITE_BLOCKED = 'ADAPTIVE_INTENT_WRITE_BLOCKED'

NEED_CODES = {'consent': NEEDS_CONSENT, 'capability': NEEDS_CAPABILITY,
              'approval': NEEDS_APPROVAL, 'user_decision': NEEDS_USER_DECISION}
WRITE_INTENTS = ('analysis', 'plan', 'design')


# --------------------------------------------------------------------------- #
# Chuẩn hoá dữ liệu đầu vào (khoan dung với dữ liệu thiếu, không nới quyền)
# --------------------------------------------------------------------------- #

def _mapping(value):
    return value if isinstance(value, dict) else {}


def _flag(value):
    """Đọc cờ cần/thiếu; dict có `needed`/`required`/`pending` thì đọc khóa đó trước."""
    if isinstance(value, dict):
        for key in ('needed', 'required', 'pending', 'missing', 'blocked'):
            if key in value:
                return bool(value[key])
        return bool(value)
    return bool(value)


def _ref(item):
    """Một evidence/artifact ref → chuỗi chuẩn tắc, ổn định để so sánh."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ('ref', 'artifactId', 'id', 'taskKey', 'jobId', 'callKey', 'receiptId',
                    'checkpointId'):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                version = item.get('version')
                return f'{value.strip()}@{version}' if version is not None else value.strip()
        return json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
    if item is None:
        return ''
    return str(item)


def _refs(value):
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for item in value:
        ref = _ref(item)
        if ref and ref not in result:
            result.append(ref)
    return result


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _count(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return None


def _level(value):
    if isinstance(value, str) and value.strip().lower() in EFFORT_LEVELS:
        return value.strip().lower()
    return None


def _canonical(value):
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), sort_keys=True, ensure_ascii=False, default=str)
    return value


def _source_refs(source):
    if isinstance(source, dict):
        return _refs(source.get('evidenceRefs', source.get('evidence')))
    return []


def _evidence(observation, *extras):
    refs = _refs(observation.get('evidenceRefs'))
    for extra in extras:
        for ref in _refs(extra):
            if ref not in refs:
                refs.append(ref)
    return refs


# --------------------------------------------------------------------------- #
# 1. Progress signal
# --------------------------------------------------------------------------- #

def _checkpoint_observed(checkpoint):
    for key in ('result', 'observedResult', 'outcome', 'output'):
        if _flag(checkpoint.get(key)):
            return True
    if checkpoint.get('observed') is True:
        return True
    return checkpoint.get('status') in ('observed', 'completed', 'passed', 'failed')


def _text(snapshot):
    for key in ('text', 'summary', 'message', 'report', 'output'):
        value = snapshot.get(key)
        if isinstance(value, str):
            return value
    return ''


def progress_signal(previous, current):
    """So hai ảnh chụp trạng thái; chỉ năm loại tiến triển thật mới trả `progress=True`."""
    before, after = _mapping(previous), _mapping(current)
    kinds, reasons = [], []

    fresh_artifacts = [ref for ref in _refs(after.get('artifacts'))
                       if ref not in set(_refs(before.get('artifacts')))]
    if fresh_artifacts:
        kinds.append('artifact')
        reasons.append('new artifact refs: ' + ', '.join(fresh_artifacts))

    fresh_evidence = [ref for ref in _refs(after.get('evidenceRefs', after.get('evidence')))
                      if ref not in set(_refs(before.get('evidenceRefs', before.get('evidence'))))]
    if fresh_evidence:
        kinds.append('evidence')
        reasons.append('new evidence refs: ' + ', '.join(fresh_evidence))

    gap_before, gap_after = _number(before.get('acceptanceGap')), _number(after.get('acceptanceGap'))
    if gap_before is not None and gap_after is not None and gap_after < gap_before:
        kinds.append('acceptance_gap')
        reasons.append(f'acceptance gap shrank {gap_before} -> {gap_after}')

    open_before, open_after = set(_refs(before.get('openCriteria'))), set(_refs(after.get('openCriteria')))
    if open_after and open_after < open_before:
        kinds.append('acceptance_gap')
        reasons.append('open acceptance criteria shrank: ' + ', '.join(sorted(open_before - open_after)))

    resolved = [ref for ref in _refs(before.get('uncertainties'))
                if ref not in set(_refs(after.get('uncertainties')))]
    if resolved:
        kinds.append('uncertainty')
        reasons.append('uncertainties resolved: ' + ', '.join(resolved))
    level_before, level_after = _level(before.get('uncertainty')), _level(after.get('uncertainty'))
    if level_before and level_after and EFFORT_WEIGHT[level_after] < EFFORT_WEIGHT[level_before]:
        kinds.append('uncertainty')
        reasons.append(f'uncertainty level dropped {level_before} -> {level_after}')

    checkpoint_before, checkpoint_after = before.get('checkpoint'), after.get('checkpoint')
    if (isinstance(checkpoint_after, dict) and _checkpoint_observed(checkpoint_after)
            and _canonical(checkpoint_after) != _canonical(checkpoint_before)):
        kinds.append('checkpoint')
        reasons.append('checkpoint recorded an observed result')

    kinds = list(dict.fromkeys(kinds))
    if not kinds:
        text_before, text_after = _text(before), _text(after)
        if text_after and len(text_after) > len(text_before):
            reasons.append('longer text or paraphrase is not progress')
        calls_before, calls_after = _count(before.get('toolCalls')), _count(after.get('toolCalls'))
        if calls_before is not None and calls_after is not None and calls_after > calls_before:
            reasons.append('a higher tool-call count is not progress')
        logs_before = _count(before.get('logs', before.get('log')))
        logs_after = _count(after.get('logs', after.get('log')))
        if logs_before is not None and logs_after is not None and logs_after > logs_before:
            reasons.append('repeated or longer logs are not progress')
        if not reasons:
            reasons.append('no new artifact, evidence, reduced acceptance gap, resolved '
                           'uncertainty, or observed checkpoint')
    return {'progress': bool(kinds), 'kind': kinds[0] if kinds else None, 'reasons': reasons}


# --------------------------------------------------------------------------- #
# 2. Loop guard
# --------------------------------------------------------------------------- #

def _loop_entry(value):
    if isinstance(value, str):
        return {'signature': value.strip(), 'inputs': None, 'evidence': set()}
    if isinstance(value, dict):
        signature = value.get('signature', value.get('failure', value.get('failureSignature',
                                                                          value.get('code'))))
        if isinstance(signature, dict):
            signature = _canonical(signature)
        elif signature is not None and not isinstance(signature, str):
            signature = str(signature)
        signature = signature.strip() if isinstance(signature, str) else None
        inputs = value.get('inputs', value.get('inputHash', value.get('argsHash')))
        evidence = set(_refs(value.get('evidenceRefs', value.get('evidence'))))
        return {'signature': signature, 'inputs': _canonical(inputs), 'evidence': evidence}
    return {'signature': None, 'inputs': None, 'evidence': set()}


def _loop_entries(history):
    if isinstance(history, dict):
        history = history.get('entries', history.get('history'))
    if not isinstance(history, (list, tuple)):
        return []
    return [_loop_entry(item) for item in history]


def _loop_action(history, signature):
    """`blocked` mặc định; policy có thể chọn `stop` qua `loopAction`/`onRepeat`."""
    candidates = []
    if isinstance(signature, dict):
        candidates += [signature.get('loopAction'), signature.get('repeatAction'),
                       signature.get('onRepeat')]
        policy = _mapping(signature.get('policy'))
        candidates += [policy.get('loopAction'), policy.get('onRepeat')]
    if isinstance(history, dict):
        candidates += [history.get('loopAction'), history.get('onRepeat')]
        policy = _mapping(history.get('policy'))
        candidates += [policy.get('loopAction'), policy.get('onRepeat')]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip().lower() in ('blocked', 'stop'):
            return candidate.strip().lower()
    return None


def loop_guard(history, signature):
    """Cùng signature + input/evidence không đổi ⇒ chặn lặp tự động (đòi checkpoint/đổi cách)."""
    current = _loop_entry(signature)
    entries = _loop_entries(history)
    action = _loop_action(history, signature) or 'blocked'
    repeat = False
    if current['signature'] is not None:
        for entry in reversed(entries):
            if entry['signature'] != current['signature']:
                continue
            if entry['inputs'] != current['inputs']:
                break  # input đổi ⇒ lần thử này không còn là bản lặp
            if current['evidence'] - entry['evidence']:
                break  # evidence mới ⇒ xoá chặn
            repeat = True
            break
    return {'repeat': repeat, 'code': LOOP_REPEAT if repeat else None,
            'action': action if repeat else 'continue'}


# --------------------------------------------------------------------------- #
# 3. Effort
# --------------------------------------------------------------------------- #

def _effort_level(uncertainty, value, reasons):
    levels = []
    for raw, field in ((uncertainty, 'uncertainty'), (value, 'value')):
        if raw is None:
            levels.append('medium')
            reasons.append(f'{field} was not declared; medium baseline')
            continue
        level = _level(raw)
        if level is None and isinstance(raw, str) and raw.strip().lower() == 'unknown':
            level = 'medium'
            reasons.append(f'{field} is unknown; medium baseline, never low')
        if level is None:
            invalid(field, 'expected one of low, medium, high', code='ADAPTIVE_EFFORT_INPUT')
        levels.append(level)
    score = EFFORT_WEIGHT[levels[0]] + EFFORT_WEIGHT[levels[1]]
    level = 'low' if score <= 1 else ('high' if score >= 4 else 'medium')
    reasons.insert(0, f'effort {level} from uncertainty={levels[0]} x value={levels[1]}')
    return level


def _clamp_level(level, supported, reasons, source):
    allowed = [item for item in EFFORT_LEVELS if item in supported]
    if not allowed or level in allowed:
        return level
    lower = [item for item in allowed if EFFORT_WEIGHT[item] < EFFORT_WEIGHT[level]]
    chosen = lower[-1] if lower else allowed[0]
    reasons.append(f'effort {level} -> {chosen} clamped by {source}')
    return chosen


def _published_levels(capability):
    """Mức reasoning model công bố; `None` = không có dữ liệu, `[]` = công bố là không hỗ trợ."""
    raw = None
    for key in ('thinkingLevels', 'reasoningEfforts', 'supportedEfforts', 'effortLevels',
                'thinking_levels', 'supported_efforts'):
        if isinstance(capability.get(key), list):
            raw = capability[key]
            break
    if raw is None:
        reasoning = capability.get('reasoning')
        if isinstance(reasoning, dict):
            for key in ('supported_efforts', 'supportedEfforts', 'efforts', 'levels'):
                if isinstance(reasoning.get(key), list):
                    raw = reasoning[key]
                    break
        elif isinstance(reasoning, list):
            raw = reasoning
    if raw is None:
        ceiling_level = _level(capability.get('maxReasoningEffort', capability.get('effortCeiling')))
        if ceiling_level:
            raw = [item for item in EFFORT_LEVELS
                   if EFFORT_WEIGHT[item] <= EFFORT_WEIGHT[ceiling_level]]
    if raw is None:
        if (capability.get('reasoning') is False or capability.get('reasoningSupported') is False
                or capability.get('thinkingType') in ('none', 'fixed')):
            return []
        return None
    levels = []
    for item in raw:
        level = _level(item)
        if level and level not in levels:
            levels.append(level)
    return levels


def _capability(value):
    if isinstance(value, dict):
        return {'maxOutputTokens': model_output_ceiling(value),
                'levels': _published_levels(value)}
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return {'maxOutputTokens': value, 'levels': None}
    if isinstance(value, str) and value.strip().isdigit() and int(value) > 0:
        return {'maxOutputTokens': int(value), 'levels': None}
    return {'maxOutputTokens': None, 'levels': None}


def _policy_output_ceiling(policy):
    if not isinstance(policy, dict):
        return None
    values = []
    for source in (policy, _mapping(policy.get('budget'))):
        for key in ('outputTokensCeiling', 'outputTokenCeiling', 'maxOutputTokens', 'ceiling',
                    'outputCeiling', 'outputTokens'):
            value = source.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                values.append(value)
    return min(values) if values else None


def _policy_effort_ceiling(policy):
    if not isinstance(policy, dict):
        return None
    for source in (policy, _mapping(policy.get('budget'))):
        for key in ('maxEffort', 'effortCeiling', 'reasoningEffortCeiling', 'maxReasoningEffort'):
            level = _level(source.get(key))
            if level:
                return level
    return None


def effort(uncertainty, value, capability, policy=None):
    """Mức effort theo uncertainty × value, kẹp bởi capability và trần policy.

    Không bao giờ nâng trần, không phát minh số token khi capability không rõ, và không
    đọc lịch sử reasoning token để ép hạ mức.
    """
    reasons = []
    level = _effort_level(uncertainty, value, reasons)
    cap = _capability(capability)
    if cap['levels'] is not None:
        if cap['levels']:
            level = _clamp_level(level, cap['levels'], reasons, 'published model levels')
        else:
            reasons.append('model publishes no reasoning levels; the level stays a request only')
    policy_level = _policy_effort_ceiling(policy)
    if policy_level:
        level = _clamp_level(level, [policy_level], reasons, 'policy effort ceiling')

    tokens = None
    base = EFFORT_OUTPUT_TOKENS[level]
    if cap['maxOutputTokens'] is None:
        reasons.append('provider/model max output is unknown; no output-token number is invented')
    else:
        tokens = min(base, cap['maxOutputTokens'])
        if tokens != base:
            reasons.append(f'output request clamped to the published model max {cap["maxOutputTokens"]}')
        ceiling = _policy_output_ceiling(policy)
        if ceiling is not None:
            if ceiling == 0:
                tokens = None
                reasons.append('policy output ceiling is 0; no new output budget without consent')
            elif tokens > ceiling:
                tokens = ceiling
                reasons.append(f'output request clamped to the policy ceiling {ceiling}')
    return {'level': level, 'outputTokens': tokens, 'reasons': reasons}


# --------------------------------------------------------------------------- #
# 4. plan_step / compose
# --------------------------------------------------------------------------- #

def _policy_on(policy):
    if not isinstance(policy, dict):
        return False
    if policy.get('enabled') is False:
        return False
    mode = policy.get('mode')
    mode = mode.strip().lower() if isinstance(mode, str) else None
    if mode in ('legacy', 'off', 'disabled'):
        return False
    return policy.get('enabled') is True or mode == 'adaptive'


def _policy_ceiling_ref(policy):
    if not isinstance(policy, dict):
        return None
    for source in (policy, _mapping(policy.get('budget'))):
        for key in ('ceilingRef', 'allocationRef', 'budgetRef'):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _budget(policy, observation):
    """Ngân sách báo cáo: chỉ lấy từ policy/capability, không tự đặt số."""
    empty = {'outputTokens': None, 'effort': None, 'ceilingRef': None}
    if not _policy_on(policy):
        return empty
    try:
        result = effort(observation.get('uncertainty'), observation.get('value'),
                        observation.get('capability'), policy)
    except ContractError:
        return empty
    return {'outputTokens': result['outputTokens'], 'effort': result['level'],
            'ceilingRef': _policy_ceiling_ref(policy)}


def _progress_result(observation):
    provided = observation.get('progress')
    if isinstance(provided, dict) and 'progress' in provided:
        reasons = [str(item) for item in provided.get('reasons') or []]
        return {'progress': bool(provided['progress']), 'kind': provided.get('kind'),
                'reasons': reasons or ['progress signal supplied by the caller']}
    if 'previous' in observation or 'current' in observation:
        return progress_signal(observation.get('previous'), observation.get('current'))
    return {'progress': False, 'kind': None,
            'reasons': ['no previous/current snapshot was supplied']}


def _loop_result(observation, history):
    loop = _mapping(observation.get('loop'))
    if history is None and {'repeat', 'action'} <= set(loop):
        repeat = bool(loop['repeat'])
        action = loop.get('action') if loop.get('action') in ('blocked', 'stop') else 'blocked'
        code = loop.get('code') or LOOP_REPEAT
        return {'repeat': repeat, 'code': code if repeat else None,
                'action': action if repeat else 'continue'}
    entries = history if history is not None else (loop.get('history') or observation.get('history'))
    signature = observation.get('signature')
    if signature is None:
        signature = loop.get('signature')
    return loop_guard(entries, signature)


def _signature_refs(observation):
    loop = _mapping(observation.get('loop'))
    signature = observation.get('signature')
    if signature is None:
        signature = loop.get('signature')
    return _source_refs(signature)


def _revocation(observation):
    revoked = observation.get('revoked')
    epoch_revoked = False
    if observation.get('revokedEpoch') is not None:
        current = observation.get('epoch', observation.get('currentEpoch'))
        epoch_revoked = current is None or observation['revokedEpoch'] != current
    if not _flag(revoked) and not epoch_revoked:
        return None
    kind = None
    if isinstance(revoked, str):
        kind = revoked.strip().lower()
    if isinstance(revoked, dict):
        kind = revoked.get('kind') or revoked.get('require')
    if kind not in REQUIREMENTS:
        kind = 'capability'
    return {'require': kind, 'refs': _source_refs(revoked)}


def _missing(observation):
    """Trả (needs theo thứ tự chuẩn, notes, needs không nhận diện được)."""
    declared = observation.get('needs', observation.get('requires'))
    names = []
    if isinstance(declared, str):
        names = [declared]
    elif isinstance(declared, list):
        names = [item for item in declared if isinstance(item, str)]
    elif isinstance(declared, dict):
        names = [key for key, value in declared.items() if _flag(value)]
    unsupported = [name for name in names if name not in REQUIREMENTS]
    found = {}
    for name in names:
        if name in REQUIREMENTS:
            found.setdefault(name, f'the caller declared missing {name}')

    flags = (
        ('consent', ('missingConsent', 'consentMissing', 'needsConsent'),
         'consent for new spend or scope is missing'),
        ('capability', ('missingCapability', 'capabilityMissing', 'needsCapability'),
         'a required capability is not currently held'),
        ('approval', ('approvalRequired', 'approvalPending', 'needsApproval'),
         'owner approval is required first'),
        ('user_decision', ('userDecisionRequired', 'userDecisionPending', 'needsUserDecision',
                           'pendingQuestion'),
         'a user decision is required first'),
    )
    for name, keys, note in flags:
        for key in keys:
            if key in observation and _flag(observation[key]):
                found.setdefault(name, note)
                break

    spend = observation.get('spend', observation.get('cost'))
    budget = _mapping(observation.get('budget'))
    branch = _mapping(observation.get('branch'))
    proposal_spends = (_flag(observation.get('needsBudget')) or _flag(observation.get('budgetRequested'))
                       or _flag(branch.get('spend')))
    basis = bool(observation.get('consentRef'))
    if isinstance(spend, dict):
        proposal_spends = proposal_spends or any(
            key in spend for key in ('amount', 'certainty', 'estimated', 'needed'))
        certainty = spend.get('certainty')
        amount = spend.get('amount')
        if certainty == 'unknown' or (certainty is None and _number(amount) is None):
            found.setdefault('consent', 'cost is unknown (not zero); new spend needs consent')
        elif certainty == 'estimated' and not (spend.get('consentRef') or _flag(spend.get('accepted'))):
            found.setdefault('consent', 'cost is only an estimate with no accepted upper bound')
        if spend.get('consentRef') or _flag(spend.get('accepted')):
            basis = True
        if certainty == 'known' and _number(amount) is not None:
            basis = True
    elif _number(spend) is not None:
        proposal_spends = True
        basis = True
    remaining = _number(budget.get('remaining'))
    if remaining is not None and remaining > 0:
        basis = True
    if proposal_spends and 'remaining' in budget and remaining is None:
        found.setdefault('consent', 'remaining budget is unknown; it is neither zero nor unlimited')
    if 'remaining' in budget and remaining is not None and remaining <= 0:
        # Ngân sách người gọi khai đã hết: mọi bước còn tốn chi tiêu đều cần consent mới.
        found.setdefault('consent', 'the declared budget is exhausted; extension needs consent')
    if proposal_spends and not basis:
        found.setdefault('consent', 'a new spend/budget has no caller-declared basis; consent is required')

    write = _flag(observation.get('write')) or _flag(observation.get('writeRequested')) \
        or _flag(branch.get('write'))
    intent = observation.get('intent')
    if write and isinstance(intent, str) and intent.strip().lower() in WRITE_INTENTS:
        found.setdefault('approval', 'analysis/plan/design intent cannot write; owner approval for '
                                     'an implementation intent is required first')
    change = observation.get('intentChange') or observation.get('scopeChange')
    if _flag(change):
        receipt = change.get('receiptRef') if isinstance(change, dict) else None
        if not receipt and not _flag(change.get('approved')):
            found.setdefault('approval', 'an intent/scope change has no admission receipt')

    needs = [name for name in REQUIREMENTS if name in found]
    return needs, found, unsupported


def _limit_reached(observation):
    limits = _mapping(observation.get('limits'))
    steps = _number(limits.get('steps', limits.get('maxSteps')))
    taken = _number(observation.get('stepsTaken'))
    if steps is not None and taken is not None and taken >= steps:
        return f'caller-declared step limit reached ({taken}/{steps})'
    deadline = _number(limits.get('deadlineSeconds', limits.get('seconds')))
    elapsed = _number(observation.get('elapsedSeconds'))
    if deadline is not None and elapsed is not None and elapsed >= deadline:
        return f'caller-declared deadline reached ({elapsed}/{deadline}s)'
    if _flag(observation.get('deadlineExceeded')):
        return 'the caller reported its own deadline as exceeded'
    if _flag(observation.get('budgetExhausted')):
        return 'the caller reported its budget as exhausted'
    return None


def _branch_proposal(branch):
    if isinstance(branch, dict):
        return (_flag(branch.get('needed')) or _flag(branch.get('beneficial'))
                or bool(branch.get('taskKey')))
    if isinstance(branch, (list, tuple)):
        return bool(branch)
    return _flag(branch)


def _park_proposal(park):
    if isinstance(park, dict):
        return bool(park['needed']) if 'needed' in park else _flag(park)
    return _flag(park)


def _why_not(candidate, chosen, observation, code, requires):
    refs = _refs(observation.get('evidenceRefs'))
    missing = ', '.join(requires) if requires else 'mandatory conditions'
    if code == LEGACY_POLICY:
        return (f'{candidate} not available: the adaptive policy is missing or off', [])
    if chosen == 'stop':
        return (f'{candidate} rejected: stop wins; no new work is opened', [])
    if chosen == 'blocked':
        if candidate in ('continue', 'branch'):
            return (f'{candidate} rejected: {missing} must be satisfied first', refs)
        if candidate == 'park':
            return ('park rejected: this is a missing authority/capability, not a wait condition', refs)
        return ('stop rejected: no stop request and the goal is not satisfied', [])
    if chosen == 'park':
        if candidate in ('continue', 'branch'):
            return (f'{candidate} rejected: waiting on {missing} before acting', refs)
        if candidate == 'blocked':
            return ('blocked rejected: this is a wait condition, not a missing authority', [])
        return ('stop rejected: no stop request and the goal is not satisfied', [])
    if chosen == 'branch':
        if candidate == 'continue':
            return ('continue rejected: independent work with a separate owner is beneficial', refs)
        if candidate == 'park':
            return ('park rejected: no wait condition was declared', [])
        if candidate == 'stop':
            return ('stop rejected: no stop request and the goal is not satisfied', [])
        return ('blocked rejected: no missing consent, capability, approval, or user decision', refs)
    if candidate == 'branch':
        return ('branch rejected: no independent work with a separate owner was declared', [])
    if candidate == 'park':
        return ('park rejected: no wait condition was declared', [])
    if candidate == 'stop':
        return ('stop rejected: no stop request and the goal is not satisfied', [])
    return ('blocked rejected: no missing consent, capability, approval, or user decision', [])


def _alternatives(action, observation, code, requires):
    alternatives = []
    for candidate in DECISIONS:
        if candidate == action:
            continue
        reason, refs = _why_not(candidate, action, observation, code, requires)
        alternatives.append({'action': candidate, 'reason': reason, 'evidenceRefs': refs})
    return alternatives


def _decision(action, code, detail, observation, policy, loop, progress, requires=(), evidence=()):
    return {
        'action': action,
        'reason': f'{code}: {detail}' if detail else code,
        'evidenceRefs': _evidence(observation, evidence),
        'requires': list(requires),
        'budget': _budget(policy, observation),
        'alternatives': _alternatives(action, observation, code, requires),
        'loop': dict(loop),
        'progress': dict(progress),
    }


def _decide(policy, observation, history):
    observation = _mapping(observation)
    loop = _loop_result(observation, history)
    progress = _progress_result(observation)

    # Stop/thu hồi luôn thắng, kể cả khi policy tắt.
    if _flag(observation.get('stopRequested')):
        return _decision('stop', STOP_REQUESTED, 'stop wins; no new branch, spend, or retry',
                         observation, policy, loop, progress,
                         evidence=_source_refs(observation.get('stopRequested')))
    revoked = _revocation(observation)
    if revoked:
        return _decision('blocked', EPOCH_REVOKED,
                         'a revoked epoch/authority must be re-admitted before any effect',
                         observation, policy, loop, progress,
                         requires=[revoked['require']], evidence=revoked['refs'])

    if not _policy_on(policy):
        return _decision('continue', LEGACY_POLICY,
                         'policy is missing or off; the composer defers to the legacy path '
                         'and grants nothing', observation, policy, loop, progress)

    if loop['repeat']:
        action = loop['action'] if loop['action'] in ('blocked', 'stop') else 'blocked'
        return _decision(action, LOOP_REPEAT,
                         'the same failure signature repeated with unchanged inputs and evidence; '
                         'automatic repeat is blocked — save a checkpoint and change approach '
                         'before any new attempt', observation, policy, loop, progress,
                         evidence=_signature_refs(observation))

    if _flag(observation.get('goalMet')):
        return _decision('stop', GOAL_MET, 'the goal is satisfied; stop instead of opening new work',
                         observation, policy, loop, progress)

    needs, notes, unsupported = _missing(observation)
    if unsupported:
        return _decision('blocked', NEED_UNSUPPORTED,
                         'unsupported need(s) ' + ', '.join(unsupported)
                         + '; the composer refuses to proceed', observation, policy, loop, progress)
    if needs:
        detail = '; '.join(notes[name] for name in needs if name in notes)
        if needs == ['user_decision']:
            return _decision('park', NEEDS_USER_DECISION,
                             detail + '; park and checkpoint until the decision arrives',
                             observation, policy, loop, progress, requires=needs)
        return _decision('blocked', NEED_CODES[needs[0]], detail + '; nothing is granted',
                         observation, policy, loop, progress, requires=needs)

    limit = _limit_reached(observation)
    if limit:
        return _decision('blocked', LIMIT_REACHED,
                         limit + '; a new budget requires explicit consent',
                         observation, policy, loop, progress, requires=['consent'])

    park = observation.get('park', observation.get('waitFor'))
    if _park_proposal(park):
        if isinstance(park, dict):
            wait = park.get('waitFor')
            detail = park.get('reason') if isinstance(park.get('reason'), str) else 'a wait condition was declared'
        else:
            wait = park if isinstance(park, str) else None
            detail = 'a wait condition was declared'
        requires = ['user_decision'] if wait in ('user', 'decision', 'user_decision') else []
        return _decision('park', PARK_REQUESTED, str(detail) + '; checkpoint and wait',
                         observation, policy, loop, progress, requires=requires,
                         evidence=_source_refs(park))

    branch = observation.get('branch')
    if _branch_proposal(branch):
        detail = (branch.get('reason') if isinstance(branch, dict)
                  and isinstance(branch.get('reason'), str) else
                  'independent work with a separate owner was declared')
        return _decision('branch', BRANCH_BENEFICIAL, detail, observation, policy, loop, progress,
                         evidence=_source_refs(branch))

    return _decision('continue', CONTINUE_DIRECT,
                     'no blocker and no branch or wait proposal; main continues directly',
                     observation, policy, loop, progress)


def plan_step(policy, observation):
    """Một bước quyết định từ policy + observation (không history)."""
    return _decide(policy, observation, None)


def compose(policy, observation, history=None):
    """Như `plan_step` nhưng nhận thêm `history` của loop guard.

    Trả về đúng một quyết định đã chọn kèm `alternatives` (các lựa chọn bị từ chối, mỗi
    lựa chọn có lý do và evidence refs), `requires`, `budget` và hai tín hiệu `loop`/`progress`.
    """
    return _decide(policy, observation, history)
