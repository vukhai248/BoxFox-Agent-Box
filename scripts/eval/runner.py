#!/usr/bin/env python3
"""Bộ chạy ca thật + phân loại tính hợp lệ của một lần chạy (kế hoạch v2 §8.5 / #6079).

Một lần chạy chỉ được **chấm** khi nó `quality-valid`. Ba nhãn, đúng định nghĩa #6079:

* `quality-valid` — lượt tới trạng thái kết thúc (kể cả `partial` / hết ngân sách **do agent**);
* `infra-failed` — lượt chết với mã `UPSTREAM_*`, `DEADLINE_EXCEEDED` do nhà cung cấp chậm, hoặc
  lỗi tìm kiếm/gói nguồn **của bộ chạy**;
* `harness-bug` — chính bộ chạy/session của mình hỏng.

Lỗi **của agent** (vượt trần, cổng từ chối, hồ sơ sai) là lỗi **chất lượng**: nó vẫn
`quality-valid` và vẫn được chấm. Lần `infra-failed` được chạy lại từ đầu tối đa
`max_reruns` lần, cùng gói nguồn và cùng hạt giống; vẫn hỏng thì ghi `null` (chưa đo),
**không bao giờ ghi 0**.

Mọi lời gọi mạng đi qua `net.py` và chỉ xảy ra trong `run_once` — hàm này chỉ được
gọi khi đã qua cổng chi tiền.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402
import net  # noqa: E402

QUALITY_VALID = 'quality-valid'
INFRA_FAILED = 'infra-failed'
HARNESS_BUG = 'harness-bug'

#: Mã lỗi của nhà cung cấp/hạ tầng ⇒ `infra-failed`. `UPSTREAM_*` phủ hết các mã
#: `UPSTREAM_HTTP_<status>`/`UPSTREAM_TIMEOUT`/`UPSTREAM_UNREACHABLE`.
INFRA_ERROR_CODES = ('DEADLINE', 'DEADLINE_EXCEEDED')
#: Mã lỗi của bộ chạy tìm kiếm/gói nguồn (§8.5) ⇒ cũng là hạ tầng. `POLL_EXHAUSTED` là lượt
#: không bao giờ tới trạng thái kết thúc trong hạn chờ của bộ chạy — KHÔNG phải chất lượng (H4).
TOOLING_ERROR_CODES = ('SEARCH_TOOLING_FAILED', 'PACK_TOOLING_FAILED', 'POLL_EXHAUSTED')
#: Nguồn của mã `DEADLINE_EXCEEDED`: `provider` (chậm) = hạ tầng; `agent` = chất lượng.
DEADLINE_SOURCE_AGENT = 'agent'
#: Trạng thái kết thúc coi là "chạy xong, kể cả partial/hết ngân sách do agent".
TERMINAL_STATUSES = ('completed', 'partial', 'budget_exhausted', 'cancelled', 'failed')

PACK_ENV = 'BOXFOX_WEB_PACK'
HARNESS_ENV = 'BOXFOX_HARNESS_BASE_URL'
DEFAULT_HARNESS_URL = 'http://127.0.0.1:3102'
AGENT_MODEL_ENV = 'BOXFOX_EVAL_AGENT_MODEL'
DEFAULT_AGENT_MODEL = 'muse-spark-1.3-contributor-free'
ROUTE_ENV = 'BOXFOX_ROUTER_BASE_URL'
DEFAULT_ROUTE = 'http://127.0.0.1:3101'
POLL_SECONDS = 2.0

_CODE_RE = re.compile(r'^([A-Z][A-Z0-9_]+)\b')


class SpendRefused(RuntimeError):
    """Cổng chi tiền chưa mở: thiếu opt-in hoặc thiếu ngân sách."""


class _HarnessUnreachable(RuntimeError):
    """Không gọi được harness (transport) — hạ tầng, không phải bug của bộ chạy."""


def classify_validity(result: dict) -> str:
    """Phân loại một kết quả chạy thành một trong ba nhãn #6079.

    Thứ tự kiểm quan trọng: bug của bộ chạy trước, sau đó hạ tầng, còn lại là chất lượng.
    """
    result = result or {}
    if result.get('harnessBug') or result.get('sessionError'):
        return HARNESS_BUG
    # Lượt cạn hạn chờ mà chưa tới trạng thái kết thúc là lỗi bộ chạy/hạ tầng, KHÔNG phải chất
    # lượng (H4): một `awaiting_decision` chưa từng chạy xong không được chấm như dữ liệu chất lượng.
    if result.get('pollExhausted'):
        return INFRA_FAILED
    # Vòng soát 2 phát hiện lỗ còn lại của H4: harness trả NGAY một trạng thái không kết thúc
    # (`paused`, `pending`, `error`) thì vòng dò thoát trước khi cạn poll, nên `pollExhausted`
    # không bật mà `terminal` vẫn False — lượt ấy cũng KHÔNG được chấm như dữ liệu chất lượng.
    if result.get('terminal') is False:
        return INFRA_FAILED
    if result.get('toolingFailed'):
        return INFRA_FAILED
    code = str(result.get('errorCode') or '').strip().upper()
    if code.startswith('UPSTREAM_') or code in TOOLING_ERROR_CODES:
        return INFRA_FAILED
    if code in INFRA_ERROR_CODES:
        # `DEADLINE` là mã cũ luôn là hạ tầng; `DEADLINE_EXCEEDED` là hạ tầng trừ khi
        # kết quả nói rõ hạn chót do chính agent tiêu hết (`deadlineSource='agent'`).
        if code == 'DEADLINE_EXCEEDED' and str(result.get('deadlineSource') or '').lower() \
                == DEADLINE_SOURCE_AGENT:
            return QUALITY_VALID
        return INFRA_FAILED
    return QUALITY_VALID


def infra_failure_rate(attempts: list[dict]) -> float | None:
    """Tỉ lệ lần `infra-failed` trên tổng số lần đã thử; `None` khi chưa thử lần nào."""
    if not attempts:
        return None
    failed = sum(1 for item in attempts if item.get('validity') == INFRA_FAILED)
    return round(failed / len(attempts), 4)


def infra_error_codes(attempts: list[dict]) -> dict:
    """Đếm mã lỗi hạ tầng trên các lần `infra-failed`."""
    counts: dict[str, int] = {}
    for item in attempts:
        if item.get('validity') != INFRA_FAILED:
            continue
        code = str(item.get('errorCode') or 'UNKNOWN')
        counts[code] = counts.get(code, 0) + 1
    return counts


def summarize_infra(rows: list[dict]) -> dict:
    """Tỉ lệ lỗi hạ tầng **theo cấu hình** và **theo mã lỗi** trên nhiều lần chạy (§8.5)."""
    by_config: dict[str, float | None] = {}
    buckets: dict[str, list[dict]] = {}
    error_counts: dict[str, int] = {}
    for row in rows:
        config_id = str(row.get('configId') or 'unknown')
        buckets.setdefault(config_id, []).extend(row.get('runs') or [])
        for code, count in (row.get('infraErrorCodes') or {}).items():
            error_counts[code] = error_counts.get(code, 0) + count
    for config_id, attempts in buckets.items():
        by_config[config_id] = infra_failure_rate(attempts)
    return {'byConfig': by_config, 'byErrorCode': error_counts}


def flag_rate_divergence(by_config: dict[str, float | None], *, threshold: float = 0.10) -> dict:
    """Gắn cờ so sánh khi hai cấu hình lệch tỉ lệ lỗi hạ tầng > `threshold` (§8.5)."""
    names = [name for name, rate in by_config.items() if rate is not None]
    pairs = []
    for index, first in enumerate(names):
        for second in names[index + 1:]:
            delta = abs(float(by_config[first]) - float(by_config[second]))
            if delta > threshold:
                pairs.append({'configs': [first, second], 'delta': round(delta, 4)})
    return {'flagged': bool(pairs), 'threshold': threshold, 'pairs': pairs}


def pack_hash(pack_dir: str | Path | None) -> dict:
    """Băm gói nguồn để ghim vào manifest; gói thiếu ⇒ `None` + lý do (không bịa)."""
    if not pack_dir:
        return {'path': None, 'sha256': None, 'missing': 'không có gói nguồn'}
    path = Path(pack_dir)
    if not path.is_dir():
        return {'path': str(path), 'sha256': None, 'missing': 'không thấy thư mục gói nguồn'}
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob('*') if item.is_file())
    for item in files:
        digest.update(str(item.relative_to(path)).replace(os.sep, '/').encode('utf-8'))
        digest.update(b'\0')
        digest.update(item.read_bytes())
    return {'path': str(path), 'sha256': digest.hexdigest(), 'files': len(files)}


def run_scenario(scenario: dict, config: dict, *, repeat: int, allow_spend: bool,
                 budget_usd: float, max_reruns: int = 2) -> dict:
    """Chạy một ca dưới một cấu hình, tự chạy lại lần `infra-failed`, trả kết quả có cấu trúc.

    Trả `{'runs', 'infraFailureRate', 'validity', 'reruns', …}`. Nếu mọi lần đều
    `infra-failed` thì `metrics` là `None` (chưa đo) — không bao giờ 0.
    """
    verdict = guard.check(budget_usd)
    if not allow_spend:
        raise SpendRefused('chưa có opt-in: đặt ' + guard.SPEND_ENV + '=1')
    if not verdict['allowed']:
        raise SpendRefused(verdict['reason'] or 'cổng chi tiền chưa mở')

    seed = scenario.get('seed', 0)
    attempts: list[dict] = []
    reruns = 0
    for attempt in range(max_reruns + 1):
        raw = run_once(scenario, config, allow_spend=allow_spend, budget_usd=budget_usd,
                       seed=seed, attempt=attempt)
        record = {**raw, 'attempt': attempt, 'validity': classify_validity(raw)}
        attempts.append(record)
        if record['validity'] != INFRA_FAILED:
            break
        if attempt < max_reruns:
            reruns += 1

    final = attempts[-1] if attempts else {'validity': INFRA_FAILED, 'errorCode': 'NOT_RUN'}
    quality_valid = final['validity'] == QUALITY_VALID
    metrics = final.get('metrics')
    if metrics is None and quality_valid:
        # H3 — chỉ số thật, tất định, suy từ hồ sơ/thẻ phạm vi/nguồn đã thu được. Không có mảnh
        # nào ⇒ `None`, và ô đó KHÔNG được đánh dấu `measured`.
        metrics = artifact_metrics(final.get('artifacts'))
    measured = bool(quality_valid and metrics is not None)
    return {
        'scenarioId': scenario.get('id'),
        'configId': config.get('id'),
        'repeat': repeat,
        'runs': attempts,
        'reruns': reruns,
        'validity': final['validity'],
        'measured': measured,
        'infraFailureRate': infra_failure_rate(attempts),
        'infraErrorCodes': infra_error_codes(attempts),
        'errorCode': final.get('errorCode'),
        'artifacts': final.get('artifacts') or {},
        'metrics': metrics if measured else None,
    }


def artifact_metrics(artifacts: dict | None) -> dict | None:
    """Khối chỉ số tất định từ hồ sơ/thẻ phạm vi/nguồn (H3). `None` khi chưa có mảnh nào.

    Không gọi model, không bịa: chỉ đếm thứ có trong tệp thu được. `measured: true` chỉ được đặt
    khi khối này (hoặc chỉ số do harness trả) tồn tại.
    """
    artifacts = artifacts or {}
    report = str(artifacts.get('report') or '')
    scope = str(artifacts.get('scope') or '')
    sources = str(artifacts.get('sources') or '')
    if not (report.strip() or scope.strip() or sources.strip()):
        return None
    source_lines = {line.strip() for line in sources.splitlines() if line.strip()}
    return {
        'reportChars': len(report),
        'reportHeadings': sum(1 for line in report.splitlines() if line.lstrip().startswith('#')),
        'scopeChars': len(scope),
        'sourceCount': len(source_lines),
        'hasReport': bool(report.strip()),
        'hasScope': bool(scope.strip()),
        'hasSources': bool(sources.strip()),
    }


# ------------------------------------------------------------------ đường chạy thật
def run_once(scenario: dict, config: dict, *, allow_spend: bool, budget_usd: float,
             seed: int = 0, attempt: int = 0) -> dict:
    """MỘT lần chạy thật qua harness (mạng). Chỉ gọi khi đã qua cổng chi tiền.

    Mở phiên harness với `BOXFOX_WEB_PACK` của gói nguồn, gửi lời nhắc của ca, chờ
    lượt kết thúc, rồi gom hồ sơ/thẻ phạm vi/nguồn. Mọi lỗi transport ⇒ `infra-failed`;
    lỗi trong chính bộ chạy ⇒ `harness-bug`.
    """
    if not allow_spend:
        raise SpendRefused('run_once cần allow_spend')
    pack = scenario.get('pack')
    previous_pack = os.environ.get(PACK_ENV)
    if pack:
        os.environ[PACK_ENV] = str(pack)
    elif PACK_ENV in os.environ:
        os.environ.pop(PACK_ENV, None)
    try:
        return _drive_session(scenario, config, seed=seed, attempt=attempt)
    except _HarnessUnreachable as exc:
        return {'status': 'failed', 'errorCode': 'UPSTREAM_UNREACHABLE', 'toolingFailed': True,
                'harnessBug': False, 'detail': str(exc), 'artifacts': {}}
    except Exception as exc:  # pragma: no cover - đường sống, cần xác minh thủ công
        return {'status': 'failed', 'errorCode': f'TURN_FAILED_{type(exc).__name__.upper()}',
                'harnessBug': True, 'detail': str(exc), 'artifacts': {}}
    finally:
        if previous_pack is None:
            os.environ.pop(PACK_ENV, None)
        else:
            os.environ[PACK_ENV] = previous_pack


def _drive_session(scenario: dict, config: dict, *, seed: int, attempt: int) -> dict:
    harness = (os.environ.get(HARNESS_ENV) or DEFAULT_HARNESS_URL).rstrip('/')
    headers = {'X-BoxFox-Admin': '1', 'Origin': 'http://localhost:3100',
               'Content-Type': 'application/json'}
    payload = {'skills': [], 'modelId': os.environ.get(AGENT_MODEL_ENV) or DEFAULT_AGENT_MODEL}
    budget = scenario.get('budget') or {}
    if budget.get('deadline_seconds'):
        payload['deadlineSeconds'] = int(budget['deadline_seconds'])
    try:
        created = net.request_json(f'{harness}/api/agent/sessions', method='POST',
                                   payload=payload, headers=headers, timeout=30)
    except net.NetError as exc:
        raise _HarnessUnreachable(str(exc)) from exc
    session_id = created.get('id')
    if not session_id:
        return {'status': 'failed', 'errorCode': 'SESSION_NOT_CREATED', 'harnessBug': True,
                'detail': f'harness không trả id phiên: {created!r}', 'artifacts': {}}
    try:
        net.request_json(f'{harness}/api/agent/sessions/{session_id}/turns',
                         method='POST', payload={'prompt': scenario.get('prompt') or ''},
                         headers=headers, timeout=60)
    except net.NetError as exc:
        raise _HarnessUnreachable(str(exc)) from exc
    deadline = time.monotonic() + float(budget.get('wall_seconds') or 1800)
    session: dict = {'status': 'running'}
    exhausted = False
    while time.monotonic() < deadline:
        session = net.request_json(f'{harness}/api/agent/sessions/{session_id}',
                                   headers=headers, timeout=30)
        status = str(session.get('status') or '')
        if status not in ('running', 'awaiting_decision'):
            break
        time.sleep(POLL_SECONDS)
    else:
        # Hết hạn chờ mà chưa tới trạng thái kết thúc ⇒ cạn poll (H4), KHÔNG ép thành 'partial'.
        exhausted = True
    status = str(session.get('status') or 'failed')
    terminal = status in TERMINAL_STATUSES
    error_code = _error_code(session)
    if exhausted and not terminal:
        error_code = error_code or 'POLL_EXHAUSTED'
    result = {
        'sessionId': session_id,
        # Giữ NGUYÊN trạng thái cuối của harness (kể cả `awaiting_decision` khi cạn poll).
        'status': status,
        'terminal': terminal,
        'pollExhausted': bool(exhausted and not terminal),
        'errorCode': error_code,
        'deadlineSource': 'agent' if status == 'budget_exhausted' else 'provider',
        'harnessBug': False,
        'artifacts': _collect_artifacts(session, scenario),
    }
    return result


def _error_code(session: dict) -> str | None:
    """Mã lỗi máy của phiên: khoá `errorCode`, hoặc tiền tố `CODE:` của trường `error`."""
    explicit = session.get('errorCode')
    if explicit:
        return str(explicit)
    for key in ('error', 'failure', 'reason'):
        value = str(session.get(key) or '').strip()
        match = _CODE_RE.match(value)
        if match:
            return match.group(1)
    return None


def _collect_artifacts(session: dict, scenario: dict) -> dict:
    """Gom hồ sơ/thẻ phạm vi/nguồn — `None` khi chưa có, không bịa."""
    artifacts: dict[str, str | None] = {'report': None, 'scope': None, 'sources': None}
    config = session.get('config') or {}
    scope = config.get('researchMode') or config.get('researchScope')
    if scope:
        artifacts['scope'] = json.dumps(scope, ensure_ascii=False)
    workspace = scenario.get('workspace')
    if workspace:
        research_dir = Path(workspace) / '.research'
        if research_dir.is_dir():
            reports = sorted(research_dir.glob('**/v*-*.md'))
            if reports:
                artifacts['report'] = reports[-1].read_text(encoding='utf-8', errors='replace')
            sources = sorted(research_dir.glob('**/sources.md'))
            if sources:
                artifacts['sources'] = sources[-1].read_text(encoding='utf-8', errors='replace')
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Phân loại một kết quả chạy (offline).')
    parser.add_argument('--result', required=True, help='tệp JSON kết quả một lần chạy')
    args = parser.parse_args(argv)
    result = json.loads(Path(args.result).read_text(encoding='utf-8'))
    print(classify_validity(result))
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
