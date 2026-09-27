"""The run manifest: everything a number has to be pinned to (benchmark plan §4.1).

§4.1 lists what must be pinned: "commit BoxFox, ảnh container (digest), phiên bản
benchmark, model + provider, prompt, schema công cụ, seed/temperature, trần bước,
điều kiện mạng, trạng thái firewall". §4.4 lists what a cost report must carry:
"token vào/ra, thời gian tường, số bước — lấy từ nhật ký hệ thống".

Field values this module cannot measure are written as `None` with a `missing`
entry naming the reason — never as a zero that could be mistaken for a
measurement.

`collect_docker_digest` talks to the Docker daemon (a unix socket). It is the
ONLY function here that does, and the dry-run path never calls it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

MANIFEST_VERSION = 'eval-manifest-v1'

#: Gốc kho: `scripts/eval/manifest.py` lùi ba cấp. Hai tệp dưới đây được băm bằng
#: đường dẫn TUYỆT ĐỐI so với gốc này — trước P0a chúng là đường dẫn tương đối nên
#: `sha256` thành `null` mỗi khi pytest chạy từ `backend/` thay vì gốc kho.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Files the plan calls "prompt" and "schema công cụ". Hashed as whole files; the
# label in the manifest says so instead of pretending it is a structural hash.
TOOL_SCHEMA_SOURCE = REPO_ROOT / 'backend/src/agentbox/agent_core/tool_contracts.py'
ROLES_PROMPT_SOURCE = REPO_ROOT / 'backend/src/agentbox/skills/roles.py'

UNMEASURED = 'chưa đo'


def _run(command: list[str], cwd: Path | None = None) -> str | None:
    try:
        done = subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True,
                              text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def repo_state(repo_dir: str | Path) -> dict:
    """Commit + dirty state. Read-only git commands only (`rev-parse`, `status`)."""
    repo_dir = Path(repo_dir)
    commit = _run(['git', 'rev-parse', 'HEAD'], cwd=repo_dir)
    porcelain = _run(['git', 'status', '--porcelain'], cwd=repo_dir)
    dirty_files = [line for line in (porcelain or '').splitlines() if line.strip()]
    return {
        'commit': commit,
        'commitShort': commit[:7] if commit else None,
        'dirty': bool(dirty_files),
        'dirtyFileCount': len(dirty_files),
        'note': (f'{len(dirty_files)} tệp chưa commit trong cây làm việc — số liệu này gắn với cây '
                 f'đang chạy, không chỉ với commit') if dirty_files else None,
    }


def file_hash(path: str | Path) -> dict:
    """sha256 of a source file, or `None` + reason when the file is gone."""
    path = Path(path)
    if not path.exists():
        return {'path': str(path), 'sha256': None, 'missing': 'không thấy tệp'}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'path': str(path), 'sha256': digest, 'kind': 'sha256-của-tệp-nguồn'}


def bench_version() -> dict:
    """Python/OS of the machine that produced the run."""
    return {
        'python': platform.python_version(),
        'system': platform.system(),
        'release': platform.release(),
    }


def collect_docker_digest(image: str = 'agentbox-sandbox:latest') -> dict:
    """Container image digest — REQUIRES the Docker daemon (a unix socket).

    Never call this from a dry run: the offline test patches `socket.socket` to
    raise, and this would (correctly) blow up.
    """
    digest = _run(['docker', 'image', 'inspect', '--format',
                   '{{index .RepoDigests 0}}', image])
    return {
        'ref': image,
        'digest': digest or None,
        'missing': None if digest else 'docker không trả digest (daemon tắt, hoặc ảnh chỉ có ID cục bộ)',
    }


def build_manifest(*, benchmark_name: str, benchmark_version: str, repo_dir: str | Path,
                   fixture_ids: list[str], provider: str | None = None, model: str | None = None,
                   seed: int | None = None, temperature: float | None = None,
                   max_steps: int | None = None, deadline_seconds: int | None = None,
                   network: str | None = None, firewall: str | None = None,
                   image_digest: dict | None = None, judge_prompt: dict | None = None,
                   created_at: str | None = None, extra: dict | None = None) -> dict:
    """The pinned block + placeholders for the real cost fields."""
    missing: list[str] = []
    if not provider:
        missing.append('provider')
    if not model:
        missing.append('model')
    if seed is None:
        missing.append('seed')
    if temperature is None:
        missing.append('temperature')
    if max_steps is None:
        missing.append('maxSteps')
    if network is None:
        missing.append('network')
    manifest = {
        'manifestVersion': MANIFEST_VERSION,
        'benchmark': {'name': benchmark_name, 'version': benchmark_version},
        'createdAt': created_at,
        'fixtures': list(fixture_ids),
        'pins': {
            'repo': repo_state(repo_dir),
            'image': image_digest or {'ref': None, 'digest': None, 'missing': UNMEASURED},
            'provider': provider,
            'model': model,
            'seed': seed,
            'temperature': temperature,
            'maxSteps': max_steps,
            'deadlineSeconds': deadline_seconds,
            'network': network,
            'firewall': firewall,
            'prompts': {
                'judge': judge_prompt or {'path': None, 'version': None, 'sha256': None,
                                          'missing': UNMEASURED},
                'agentRoles': file_hash(ROLES_PROMPT_SOURCE)
                if Path(ROLES_PROMPT_SOURCE).exists() else {'path': str(ROLES_PROMPT_SOURCE),
                                                            'sha256': None,
                                                            'missing': UNMEASURED},
            },
            'toolSchema': file_hash(TOOL_SCHEMA_SOURCE)
            if Path(TOOL_SCHEMA_SOURCE).exists() else {'path': str(TOOL_SCHEMA_SOURCE),
                                                       'sha256': None, 'missing': UNMEASURED},
            'runtime': bench_version(),
        },
        # Filled from the DEV system log after a real run (benchmark plan §4.4).
        'cost': empty_cost(),
        'missingPins': missing,
        'notes': [
            'chưa chạy: mọi số trong trường cost là null cho tới khi lượt chạy thật xong',
            'số liệu phải tính lại được từ thư mục kết quả thô (benchmark plan §6)',
        ],
    }
    if extra:
        manifest.update(extra)
    return manifest


def empty_cost() -> dict:
    """The §4.4 cost fields, all unmeasured until the system log has the run."""
    return {
        'tokensIn': None,
        'tokensOut': None,
        'wallTimeMs': None,
        'steps': None,
        'retries': None,
        'source': 'nhật ký hệ thống (~/BoxFox/logs/harness.jsonl + router.jsonl)',
        'missing': ['tokensIn', 'tokensOut', 'wallTimeMs', 'steps', 'retries'],
    }


def _data(entry: dict) -> dict:
    data = entry.get('data')
    return data if isinstance(data, dict) else {}


def _total(entries, keys) -> tuple[int | None, bool]:
    total = 0
    found = False
    for entry in entries:
        holder = {**entry, **_data(entry)}
        for key in keys:
            value = holder.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total += value
                found = True
                break
    return (total if found else None), found


def cost_from_entries(entries, *, session_id: str | None = None) -> dict:
    """Real cost fields from system-log entries (harness + router), §4.4.

    Router `chat.end` carries `inputTokens`/`outputTokens`; harness `turn.end`
    carries `steps`/`durationMs`; `model.error` and the UPSTREAM_* codes count
    retries. A field the log does not hold stays `None` and is listed in
    `missing` — the honest direction is "chưa đo", not 0.
    """
    entries = [entry for entry in entries
               if session_id is None or str(entry.get('sessionId', '')) == session_id]
    tokens_in, in_found = _total(entries, ('inputTokens', 'promptTokens', 'tokensIn'))
    tokens_out, out_found = _total(entries, ('outputTokens', 'completionTokens', 'tokensOut'))
    wall_time, wall_found = _total([entry for entry in entries if entry.get('event') == 'turn.end'],
                                   ('durationMs',))
    steps, steps_found = _total([entry for entry in entries if entry.get('event') == 'turn.end'],
                                ('steps',))
    retries = 0
    for entry in entries:
        code = str(entry.get('code') or _data(entry).get('errorCode') or '')
        if entry.get('event') == 'model.error' or code.startswith('UPSTREAM_') or code == 'DEADLINE':
            retries += 1
    cost = {
        'tokensIn': tokens_in if in_found else None,
        'tokensOut': tokens_out if out_found else None,
        'wallTimeMs': wall_time if wall_found else None,
        'steps': steps if steps_found else None,
        'retries': retries,
        'source': 'nhật ký hệ thống (~/BoxFox/logs/harness.jsonl + router.jsonl)',
    }
    cost['missing'] = [key for key, found in (('tokensIn', in_found), ('tokensOut', out_found),
                                              ('wallTimeMs', wall_found), ('steps', steps_found))
                       if not found]
    return cost


def write_manifest(path: str | Path, manifest: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def load_manifest(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def env_network_state() -> str:
    """Firewall/network state as configured, not as guessed."""
    return os.environ.get('BOX_DEFAULT_NETWORK', 'unknown')
