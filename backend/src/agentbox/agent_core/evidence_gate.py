"""Evidence gate: the final answer must carry living proof of what the turn actually did.

Why this module exists
----------------------
Measured 2026-09-22 (BUG-44, D-8): the final answer was emitted under a single condition —
"there is text and it is not empty" (``agent_core/runtime.py``) — so "đã sửa xong" reached the user
with nothing machine-readable behind it. The UI painted the same green ``done`` badge on a turn that
only read two documents and on a turn that rewrote forty files, the ``E:`` (evidence) journal marker
had never once been written, and eval ``S4`` ("khẳng định không có bằng chứng") could not leave
``not_measured`` *because* no answer carried a machine-read trace of the work.

This module is that trace's judge, and it is deliberately PURE: no I/O, no model call, no session
state, no ``httpx``, no ``subprocess``. Everything it needs arrives as arguments — the tool calls the
turn already made, the box probe (when one was needed), the evidence fragments tools returned, and
the answer text. The runtime owns the impure half (one ``docker exec`` probe, at most one repair
model call); this file owns the rules, so the rules can be unit-tested without a box.

Contract
--------
``classify_turn(calls)`` -> ``TurnProfile``: what the turn did, from tool calls only (never from the
answer's wording — prose is used for cross-checking, never as evidence).

``assess(answer_text, profile, probe, artifacts)`` -> a verdict dict:
``{verdict, checked, missing[], artifacts[], changedFiles[], claims[], notes[]}`` where ``verdict``
is one of ``VERDICTS`` and every ``missing[].reason`` is a machine-readable member of ``REASONS``.

``repair_message(verdict, profile, probe)`` -> ONE ``{'role': 'user', 'content': …}`` message naming
the work done and the missing fragment, with file names and numbers only — never file contents.

Five rules, and the reasons they exist (R1-R5 in the construction plan):

* **R1** a turn that changed something with no matching evidence is ``insufficient``
  (``change_without_verification`` / ``ui_change_without_capture``);
* **R2** a read-only turn is ``sufficient`` — reading a document is a complete piece of work;
* **R3** a path or command the answer asserts but the turn never touched is ``insufficient``
  (``claim_path_not_in_turn`` / ``claim_path_missing`` / ``answer_references_unknown_command``);
* **R4** an answer past the D-4 ceiling is ``insufficient`` (``answer_too_long``);
* **R5** missing data (box down, probe failed, gate switched off, gate itself broken) is
  ``not_measurable`` — never downgraded to ``insufficient``. Saying "chưa đo được" beats a false
  accusation, and the gate must never be able to fail a turn.

Constants live here and only here (§2.2 of the plan). ``scripts/eval/rushed_index.py`` imports
``WRITE_TOOLS`` from this module when it can, so the "which tools write" rule has one home.

Two deliberate refinements of the written plan, recorded here so nobody has to guess later:

* ``delegate_task`` is neither a write nor an unknown tool. A turn that only delegated is judged on
  the child fragments it carries (kind ``child``); with a child still open it is ``not_measurable``
  — the work moved to another session, so this turn has no local proof yet, and a detached hand-off
  is not a lie. Claiming green here would be the BUG-44 pattern again, and calling it insufficient
  would punish the mesh this round just built.
* ``write_plan`` is left out of R1: ``plan_quality.py`` already gates plan content, and this gate
  must not fine the same turn twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .limits import ANSWER_MAX_CHARS, ANSWER_WARN_CHARS
# Một nguồn cho trần `caption` (hợp đồng công cụ), không chép lại con số.
from .tool_contracts import CAPTURE_CAPTION_MAX_CHARS as CAPTION_MAX_CHARS

__all__ = ['WRITE_TOOLS', 'PLAN_TOOLS', 'UI_TOOLS', 'READ_TOOLS', 'DELEGATE_TOOLS',
           'WRITE_CMD_RE', 'VERIFY_CMD_RE', 'READ_CMD_RE',
           'EVIDENCE_ROOT_REL', 'EVIDENCE_PROBE_COMMAND', 'EVIDENCE_KIND', 'EVIDENCE_ARTIFACT_RE',
           'CHANGE_ARTIFACT_KINDS',
           'CAPTURE_ARTIFACT_KINDS', 'VERDICTS', 'REASONS', 'REASON_TEXT', 'UNMEASURED_REASONS',
           'TurnProfile', 'classify_turn', 'artifacts_from_calls', 'claim_paths', 'assess',
           'missing_reason', 'repair_message', 'is_ui_path', 'verdict_label']

# ---------------------------------------------------------------------------------------------
# §2.2 — the frozen constant table. One home; a second copy is how two rules drift apart.
# ---------------------------------------------------------------------------------------------
WRITE_TOOLS = ('file_write', 'file_edit_block')
# Plans have their own gate (`plan_quality.py`) — this one must not punish the same turn twice.
PLAN_TOOLS = ('write_plan',)
UI_TOOLS = ('computer_use', 'browser_use', 'inspect_element', 'computer_screen_capture',
            'computer_screen_record')
# Tools known to touch nothing on disk. Anything outside this union and the three groups above is
# `uncertain` and forces the box probe: an unrecognised tool may have written something.
READ_TOOLS = ('file_read', 'codebase_glob', 'codebase_grep', 'skills_list', 'skill_view',
              'session_search', 'journal_brief', 'journal_write', 'peer_read', 'ask_user',
              'request_approval', 'web_search', 'web_fetch', 'await_children')
DELEGATE_TOOLS = ('delegate_task',)

# A shell command that writes: redirection, in-place editors, copy/move/remove, trees, permissions,
# package managers and build tools (they create `dist/`, `node_modules/`, `build/`).
WRITE_CMD_RE = re.compile(
    r'(?:^|[^\w])>>?\s*\S|\btee\b|\bsed\s+-i\b|\bpatch\b|\bcp\b|\bmv\b|\brm\b|\bmkdir\b|\bchmod\b'
    r'|\bchown\b|\btruncate\b|\bdd\b|\bln\b|\btouch\b|\bunzip\b|\btar\b\s+[^|]*-[xc]'
    r'|\b(?:npm|pnpm|yarn)\b[^|]*\b(?:install|ci|build|run\s+build)\b|\bpip3?\s+install\b'
    r'|\buv\s+(?:pip|sync|add)\b|\bmake\b|\bdocker\b|\bgit\s+(?:apply|commit|checkout|add)\b',
    re.IGNORECASE)
# A command that verifies: the test/type/lint runners, and the exit code is the point.
VERIFY_CMD_RE = re.compile(
    r'\bpytest\b|\bpy\.test\b|\bvitest\b|\bjest\b|\bnpm\s+(?:run\s+)?test\b|\bpnpm\s+test\b'
    r'|\byarn\s+test\b|\btsc\b|\beslint\b|\bruff\b|\bmypy\b|\bflake8\b|\bgo\s+test\b'
    r'|\bcargo\s+test\b|\bdotnet\s+test\b|\bgradle\s+test\b|\bmvn\s+test\b|\bphpunit\b',
    re.IGNORECASE)
# A command that only reads: safe to call "read-only", so no probe is needed.
READ_CMD_RE = re.compile(
    r'^\s*(?:sudo\s+)?(?:ls|cat|head|tail|less|more|grep|rg|find|fd|wc|stat|file|du|df|pwd|which'
    r'|whoami|git\s+(?:status|log|diff|show|branch)|python3?\s+-c|node\s+-e|jq|sort|uniq|cut|awk'
    r'|sed\s+-n|sha256sum|md5sum|echo|date|env|printenv|tree)\b',
    re.IGNORECASE)

# Evidence files sit under the workspace's capture root, so the box's own `retention()` sweeps them
# with every other capture (files-per-kind-per-session, MiB-per-session and MiB-per-box ceilings).
EVIDENCE_ROOT_REL = '.generated_artifacts/captures/evidence'
EVIDENCE_KIND = 'evidence'
EVIDENCE_ARTIFACT_RE = re.compile(r'\.(?:diff|patch|txt|log|md|json|png|mp4)$', re.IGNORECASE)

# Fragments that count as proof of a change, and fragments that count as proof of a UI change.
CHANGE_ARTIFACT_KINDS = ('diff', 'patch', 'file', 'command')
CAPTURE_ARTIFACT_KINDS = ('image', 'record')

VERDICTS = ('sufficient', 'insufficient', 'not_measurable')
# Machine-readable reason codes. `missing[]` in the verdict uses exactly these; the UI translates
# them, so they are part of the API surface and must not be renamed casually.
REASONS = ('no_change', 'change_without_verification', 'claim_path_not_in_turn', 'claim_path_missing',
           'ui_change_without_capture', 'answer_references_unknown_command', 'no_evidence_for_tools',
           'box_unreachable', 'box_probe_failed', 'gate_error', 'answer_too_long')
UNMEASURED_REASONS = ('box_unreachable', 'box_probe_failed', 'gate_error')

# One human Vietnamese sentence per code. The badge is a colour; this is what the reader gets.
REASON_TEXT = {
    'no_change': 'lượt này không đổi gì trên đĩa',
    'change_without_verification': 'lượt có đổi tệp nhưng không có diff/hash hay mã thoát để đối chiếu',
    'claim_path_not_in_turn': 'câu trả lời nêu tệp mà lượt này không hề đọc hay sửa',
    'claim_path_missing': 'câu trả lời nêu tệp không tồn tại trong box',
    'ui_change_without_capture': 'lượt đổi giao diện nhưng không có ảnh/ghi hình chụp SAU thay đổi',
    'answer_references_unknown_command': 'câu trả lời nêu lệnh mà lượt này không hề chạy',
    'no_evidence_for_tools': 'lượt có việc ghi nhưng không mảnh bằng chứng nào được sinh ra',
    'box_unreachable': 'không gọi được box để dò thay đổi',
    'box_probe_failed': 'phép dò box lỗi hoặc quá thời gian',
    'gate_error': 'cổng bằng chứng tự hỏng',
    'answer_too_long': 'câu trả lời vượt trần độ dài',
}

_LABELS = {'sufficient': 'đã kiểm chứng', 'insufficient': 'chưa kiểm chứng',
           'not_measurable': 'chưa đo được'}

# A line that asserts work was DONE (Vietnamese and English). Used only to decide whether a path or
# command mentioned in the answer is a *claim* worth checking — never as evidence itself.
# Only unambiguous done-markers. A bare Vietnamese verb is NOT one: "xem thêm docs/x.md" contains
# "thêm" but asserts nothing about this turn, and flagging it would teach readers to ignore the badge.
_ASSERT_RE = re.compile(
    r'(\bđã\b|\bxong\b|\bhoàn tất\b|\bdone\b|\bfixed\b|\bupdated\b|\bcreated\b|\bwrote\b'
    r'|\bwritten\b|\bchanged\b|\badded\b|\bran\b|\bpassed\b|\bverified\b|\btested\b|\bbuilt\b)',
    re.IGNORECASE)
# A path-looking token: something with a directory part, or a bare name with a known extension.
_PATH_RE = re.compile(
    r'(?<![\w./-])(?:\./|/home/agent/workspace/|[\w.@+-]+/)'
    r'[\w.@+-]+(?:/[\w.@+-]+)*\.(?:md|py|ts|tsx|js|jsx|json|css|scss|html|sh|ya?ml|toml|ini|txt|log'
    r'|diff|patch|sql|env|cfg|conf)\b')
_BARE_PATH_RE = re.compile(
    r'(?<![\w./-])[\w.@+-]+\.(?:md|py|ts|tsx|js|jsx|json|css|html|sh|ya?ml|diff|patch)\b')
# A command-looking token: a known runner plus an argument, as in `plan_quality._COMMAND_TOKEN_RE`.
_COMMAND_RE = re.compile(
    r'(?:^|[\s`>])(?:sudo\s+)?(?:[\w.~-]+/)*(?:python3?|pytest|py\.test|npm|npx|pnpm|yarn|node|bash'
    r'|sh|curl|docker|git|make|cargo|go|tsc|vitest|jest|eslint|ruff|mypy|sqlite3|find|grep|rg)'
    r'\s+[-\w./~"\'`]+', re.IGNORECASE)

# The probe (§3.2): ONE fixed command, only the turn's epoch and the file cap interpolated. The two
# excluded trees are what the harness itself writes during a turn — without them the scan reports
# "something changed" on every single turn, including read-only ones.
EVIDENCE_PROBE_COMMAND = (
    'cd /home/agent/workspace && find . -type f -newermt "@{epoch}" '
    "-not -path './.generated_artifacts/*' -not -path './.session-history/*' "
    "-printf '%T@ %s %p\\n' | sort -n | tail -{limit}")

_SEGMENT_RE = re.compile(r'[.;:!?]\s+')
MAX_CLAIM_LINES = 40
MAX_CLAIM_CHARS = 200
REPAIR_MAX_CHARS = 1200
REPAIR_MAX_ITEMS = 6


@dataclass(frozen=True)
class TurnProfile:
    """What a turn DID, read from its tool calls alone.

    ``writes``/``changes_commands``/``verify_commands``/``ui_tools`` are what the turn may claim;
    ``uncertain``/``needs_probe`` say the calls cannot settle it on their own (an unrecognised tool,
    or a shell command matching none of the three regexes) and the box must be scanned.
    ``kind`` is a coarse label for the reader: ``none``, ``code``, ``ui``, ``plan`` or ``mixed``.
    """
    writes: tuple = ()
    reads: tuple = ()
    changes_commands: tuple = ()
    verify_commands: tuple = ()
    read_commands: tuple = ()
    ui_tools: tuple = ()
    ui_paths: tuple = ()
    delegated: tuple = ()
    failed: tuple = ()
    read_only: bool = True
    uncertain: bool = False
    needs_probe: bool = False
    plan: bool = False
    kind: str = 'none'
    notes: tuple = field(default=())


def _segments(line):
    """Split one line into sentence-ish segments (the unit an assertive marker applies to)."""
    return [part for part in _SEGMENT_RE.split(str(line)) if part.strip()]


def _args_of(call):
    args = call.get('args') if isinstance(call, dict) else None
    return args if isinstance(args, dict) else {}


def _result_of(call):
    result = call.get('result') if isinstance(call, dict) else None
    return result if isinstance(result, dict) else {}


def _call_failed(call):
    """A call is failed when the tool said so, on either of the two shapes tools use."""
    result = _result_of(call)
    if result.get('is_error') or result.get('ok') is False or result.get('error'):
        return True
    if call.get('is_error') or call.get('ok') is False:
        return True
    return False


def _ref_numbers(ref):
    """Ref đủ hai con số để mảnh bằng chứng mang hash: thiếu `bytes` thì thôi, không đoán.

    Đọc `ref['bytes']` trần là KeyError ở giữa đường dựng bằng chứng — chỗ ấy không có ai bắt.
    """
    return isinstance(ref.get('contentHash'), str) and isinstance(ref.get('bytes'), int)


def _clean_path(value):
    text = str(value or '').strip().strip('\'"`')
    while text.startswith('./'):
        text = text[2:]
    return text.replace('/home/agent/workspace/', '').strip('/')


def _clean_command(value):
    """A command token as the answer wrote it, without markdown dressing or sentence punctuation.

    ``_COMMAND_RE``'s leading class eats the character before the runner (a space, ``>``, a backtick),
    and its argument class eats whatever follows the argument, so `` `git status --short` `` comes out
    as ``"`git status"``. Compared raw, that token can never match the command the turn really ran, so
    an honest answer that formats a real command as code would be charged with an invented one (§2.3,
    BUG-67). Dressing never belongs to the command; the words inside it do.
    """
    text = str(value or '').strip()
    while text[:1] in ('`', '"', "'"):
        text = text[1:].strip()
    while text[-1:] in ('`', '"', "'", '.', ',', ';', ':', '!', '?', ')'):
        text = text[:-1].strip()
    return text


def is_ui_path(path):
    """A workspace path that is part of the interface (so a UI change needs a capture)."""
    text = _clean_path(path).lower()
    return text.startswith(('frontend/', 'ui/', 'web/')) or '/components/' in text \
        or text.endswith(('.tsx', '.jsx', '.css', '.scss', '.html'))


def _append(store, value):
    text = str(value or '').strip()
    if text and text not in store:
        store.append(text)


def classify_turn(calls):
    """``tool_end`` payloads (or bare ``{'name','args','result'}`` dicts) -> :class:`TurnProfile`."""
    profile = {'writes': [], 'reads': [], 'changes_commands': [], 'verify_commands': [],
               'read_commands': [], 'ui_tools': [], 'ui_paths': [], 'delegated': [], 'failed': [],
               'notes': []}
    uncertain = False
    failed_writes = False
    plan = False
    for call in calls or ():
        if not isinstance(call, dict):
            continue
        name = str(call.get('name') or '').strip()
        args = _args_of(call)
        failed = _call_failed(call)
        if failed:
            _append(profile['failed'], name or 'unknown')
        if name in WRITE_TOOLS:
            if failed:
                # §2.5 — a write that failed did not change anything, but the answer may still say it
                # did; that is R3's job, not the profile's.
                failed_writes = True
                uncertain = True
                continue
            _append(profile['writes'], _clean_path(args.get('path')))
            if is_ui_path(args.get('path')):
                _append(profile['ui_paths'], _clean_path(args.get('path')))
        elif name in PLAN_TOOLS:
            plan = True
        elif name in UI_TOOLS:
            _append(profile['ui_tools'], name)
        elif name in DELEGATE_TOOLS:
            _append(profile['delegated'], str(args.get('role') or 'child'))
        elif name == 'terminal_exec':
            command = str(args.get('command') or '').strip()
            if not command:
                uncertain = True
            elif WRITE_CMD_RE.search(command):
                _append(profile['changes_commands'], command)
            elif VERIFY_CMD_RE.search(command):
                _append(profile['verify_commands'], command)
            elif READ_CMD_RE.search(command):
                _append(profile['read_commands'], command)
            else:
                # `python3 script.py`, `node deploy.js`, `./deploy.sh` — may well have written.
                uncertain = True
        elif name in READ_TOOLS:
            # R3 — a file the turn READ is a path the answer may legitimately name.
            if name in ('file_read', 'codebase_glob', 'codebase_grep'):
                for value in (args.get('path'), *(args.get('paths') or ())):
                    _append(profile['reads'], _clean_path(value))
        else:
            uncertain = True
            # A tool this build does not know may well have been given a path by the model; the
            # harness cannot read inside its args, so the path it named is a path the turn TOUCHED.
            # R3 exists to catch invented paths, not paths handed to a tool the classifier has not
            # learned yet.
            for value in (args.get('path'), *(args.get('paths') or ())):
                _append(profile['reads'], _clean_path(value))
    writes = tuple(profile['writes'])
    changes = tuple(profile['changes_commands'])
    ui_tools = tuple(profile['ui_tools'])
    ui_paths = tuple(profile['ui_paths'])
    delegated = tuple(profile['delegated'])
    # A write under `frontend/` is a UI change, so it counts as UI first: `mixed` means the turn
    # touched both faces, not "wrote a `.tsx` file and therefore also backend code".
    code_like = bool(changes or [p for p in writes if p not in ui_paths])
    ui_like = bool(ui_tools or ui_paths)
    if code_like and ui_like:
        kind = 'mixed'
    elif ui_like:
        kind = 'ui'
    elif code_like:
        kind = 'code'
    elif plan:
        kind = 'plan'
    else:
        kind = 'none'
    needs_probe = uncertain
    read_only = not (writes or changes or ui_tools or ui_paths or delegated)
    notes = []
    if failed_writes:
        notes.append('write_failed')
    if plan:
        notes.append('plan')
    return TurnProfile(writes=writes, reads=tuple(profile['reads']), changes_commands=changes,
                       verify_commands=tuple(profile['verify_commands']),
                       read_commands=tuple(profile['read_commands']), ui_tools=ui_tools,
                       ui_paths=ui_paths, delegated=delegated, failed=tuple(profile['failed']),
                       read_only=read_only, uncertain=uncertain, needs_probe=needs_probe,
                       plan=plan, kind=kind, notes=tuple(notes))


def _capture_target_label(value):
    """Nhãn đọc được của `target` một lần chụp (P3.1): ``tab:<url>`` / ``window:<title>`` / ``screen``.

    Vòng 23 (P2.1) mở `target` cho `computer_screen_capture`, nên mảnh ảnh phải nói được nó chụp
    CÁI GÌ. Trước đây mảnh chỉ đọc `args['url']` (khoá của `browser_use`), nên ảnh chụp tab không
    bao giờ có ngữ cảnh. Không đọc được gì thì trả `''` — không bịa.
    """
    if not isinstance(value, dict):
        return ''
    kind = str(value.get('kind') or '').strip()
    detail = ''
    for key in ('url', 'title', 'windowId', 'tabId'):
        detail = str(value.get(key) or '').strip()
        if detail:
            break
    return f'{kind}:{detail}' if kind and detail else kind


def _artifact_kind(path, name, result):
    """Classify one tool result into an evidence fragment kind (or ``None`` = no fragment)."""
    if result.get('record') or result.get('recording'):
        return 'record'
    if result.get('image') or result.get('screenshot'):
        return 'image'
    if path and name in UI_TOOLS:
        return 'image'
    suffix = str(path or '').lower().rsplit('.', 1)[-1] if path else ''
    if suffix in ('diff', 'patch'):
        return 'diff'
    if path and EVIDENCE_ARTIFACT_RE.search(str(path)):
        return 'file'
    return None


def box_exit_code(result):
    """Mã thoát của một lệnh trong box: worker trả ``exit_code`` (``sandbox/worker.py``).

    ``exitCode`` chỉ còn trong bài kiểm cũ. Đọc sai khoá thì mọi mảnh `command` mang `exit None`,
    và nhánh "lệnh + exit code + phép dò xác nhận" của R1 không bao giờ chạy được trên máy thật.
    """
    for key in ('exit_code', 'exitCode'):
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def box_output_tail(result, limit=200):
    """Văn đầu ra của một lệnh trong box: worker trả văn ở ``content`` (``stdout`` là tên cũ).

    ``limit=None`` trả nguyên văn — phép dò box đọc TỪNG DÒNG nên không được cắt đuôi.
    """
    for key in ('content', 'stdout'):
        value = result.get(key)
        if isinstance(value, str):
            return value if limit is None else value[-limit:]
    return ''


def artifacts_from_calls(calls):
    """Map ``tool_end`` payloads to evidence fragments — the bridge from work done to proof.

    A fragment is ``{kind, path, tool, step, ok}`` plus whatever the tool itself reported
    (``command``/``exitCode``/``sha256``/``bytes``/``target``/``role``/``status``). Nothing here
    reads a file: the fragment is a pointer, and the reader opens the pointer.
    """
    fragments = []
    for call in calls or ():
        if not isinstance(call, dict):
            continue
        name = str(call.get('name') or '').strip()
        args = _args_of(call)
        result = _result_of(call)
        step = call.get('step') if isinstance(call.get('step'), int) else None
        ok = not _call_failed(call)
        numbers = result.get('numbers') if isinstance(result.get('numbers'), dict) else {}
        base = {'tool': name, 'step': step, 'ok': ok}
        # F30: ref có cấu trúc (đường dẫn + hash nội dung) thắng đường dẫn trần khi cả hai cùng có.
        ref = result.get('outputRef') if isinstance(result.get('outputRef'), dict) else {}
        artifact = ref.get('path') or result.get('artifact') or result.get('path') or numbers.get('artifact')
        if name in ('terminal_exec', 'run_command'):
            # A command's evidence is the command and its exit code; its artifact is the OUTPUT
            # file (>20 000 chars of stdout), not a file the command changed.
            command = str(args.get('command') or '').strip()
            if command:
                fragments.append(dict(base, kind='command', command=command,
                                      exitCode=box_exit_code(result),
                                      artifact=_clean_path(artifact),
                                      **({'sha256': ref['contentHash'], 'bytes': ref['bytes']}
                                         if _ref_numbers(ref) else {}),
                                      stdoutTail=box_output_tail(result)))
            continue
        kind = _artifact_kind(artifact, name, result)
        if kind:
            # `path` is the evidence FILE the reader opens; `changed` is the workspace file the
            # evidence speaks about. Keeping both is what lets R1 ask "is there proof for THIS
            # change" without matching a diff file against a source file by name.
            # `numbers` KHÔNG mang `path` (worker giữ nó trong tệp bằng chứng, xem
            # `test_worker_evidence.py`), nên đường dẫn workspace phải lấy từ chính lời gọi ghi —
            # thiếu nó thì mảnh diff không bao giờ khớp tệp đã đổi, và R1 phạt oan mọi lượt ghi.
            written = _clean_path(args.get('path')) if name in WRITE_TOOLS else None
            fragment = dict(base, kind=kind, path=_clean_path(artifact),
                            changed=written or (_clean_path(numbers.get('path'))
                                                if numbers.get('path') else None),
                            sha256=numbers.get('sha256After') or numbers.get('sha256'),
                            bytes=numbers.get('bytes'))
            target = args.get('url') or args.get('selector')
            if not target:
                # P2.2 — ảnh chụp của một phiên có `target` (kind + url/title/…): mượn nhãn đọc
                # được của nó, ưu tiên `args` của model rồi tới `result` executor trả về.
                target = (_capture_target_label(args.get('target'))
                          or _capture_target_label(result.get('target')))
            if target:
                fragment['target'] = str(target)
            caption = str(args.get('caption') or result.get('caption') or '').strip()
            if caption:
                # `caption` là nhãn của CHÍNH lần chụp đó — chú thích ảnh đọc nó, nên nó đi cùng
                # mảnh. Executor đã cắt ở `CAPTURE_CAPTION_MAX_CHARS`, nhưng `args` của model thì
                # chưa ai chạm, nên cổng cắt lại.
                fragment['caption'] = caption[:CAPTION_MAX_CHARS]
            fragments.append(fragment)
        elif name in DELEGATE_TOOLS:
            status = result.get('status') or result.get('childStatus')
            if status:
                fragments.append(dict(base, kind='child', role=str(result.get('role') or 'child'),
                                      status=str(status), path=None))
    return fragments


def _claim_paths_in_line(line):
    found = []
    for match in _PATH_RE.finditer(line):
        found.append(_clean_path(match.group(0)))
    for match in _BARE_PATH_RE.finditer(line):
        path = _clean_path(match.group(0))
        if path not in found:
            found.append(path)
    return found


def claim_paths(text):
    """Paths and commands the answer asserts — the input to R3, not evidence of anything itself.

    Each claim carries ``assertive``: whether the LINE reads as a statement that work was done
    ("đã sửa", "created", "passed"). A path merely mentioned in passing (a file listing, a quote from
    a document) is reported but never held against the turn — the gate compares claims, it does not
    grade prose.
    """
    claims = []
    seen = set()
    own_prev = False
    for index, line in enumerate((text or '').splitlines()):
        if len(claims) >= MAX_CLAIM_LINES:
            break
        stripped = line.strip()
        if not stripped or stripped.startswith(('|', '>')):
            continue
        # Assertiveness is read per SEGMENT, and a segment inherits it from the marker immediately
        # before it — the "Đã sửa: <đường dẫn>" label chain. Inheritance is ONE hop, so the diagnosis
        # shape "… Còn lại: chưa chạy test. Thử gì tiếp: chạy `pytest …`" keeps its recommendation
        # out of R3: the turn is judged on what it did, not on what it suggests doing next.
        own = own_prev
        for segment in _segments(stripped):
            own_marker = bool(_ASSERT_RE.search(segment))
            assertive = own_marker or own
            if '`' not in segment and not re.search(r'[\w./-]{4,}', segment):
                own = own_marker
                continue
            found_paths = _claim_paths_in_line(segment) if (assertive or '`' in segment) else []
            for path in found_paths:
                key = ('path', path)
                if key in seen:
                    continue
                seen.add(key)
                claims.append({'text': stripped[:MAX_CLAIM_CHARS], 'line': index + 1, 'path': path,
                               'command': None, 'assertive': assertive})
            for match in _COMMAND_RE.finditer(segment):
                command = _clean_command(match.group(0))
                key = ('command', command)
                if key in seen:
                    continue
                seen.add(key)
                claims.append({'text': stripped[:MAX_CLAIM_CHARS], 'line': index + 1, 'path': None,
                               'command': command, 'assertive': assertive})
            own = own_marker
        own_prev = own
    return claims


def _path_backed(path, known):
    """Does ``known`` hold the same file as ``path``?"""
    candidate = _clean_path(path)
    if not candidate:
        return True
    for value in known:
        other = _clean_path(value)
        if not other:
            continue
        if candidate == other or other.endswith('/' + candidate) or candidate.endswith('/' + other):
            return True
    return False


def _command_backed(command, profile, fragments):
    text = _clean_command(command)
    if not text:
        return True
    head = text.split()[0] if text.split() else text
    for known in list(profile.changes_commands) + list(profile.verify_commands) \
            + list(profile.read_commands):
        if text in known or head in known:
            return True
    for fragment in fragments:
        if fragment.get('command') and (text in str(fragment['command'])
                                        or head in str(fragment['command'])):
            return True
    return False


def _fragment_targets(fragment):
    """Paths a fragment speaks about: the workspace file it changed, then the evidence file."""
    return [value for value in (fragment.get('changed'), fragment.get('path')) if value]


def _has_change_evidence(fragments, changed_paths, profile, probe_found=False):
    """Is there at least one fragment that proves a change these calls actually made?

    Three shapes count, matching §2.1's "minimal evidence" column: a diff/hash fragment for a file
    the turn wrote; the command itself plus its exit code (an in-place writer, or a runner whose
    files the box scan then confirmed — ``probe_found`` — with a clean exit and no read-only shape).
    """
    evidence = [f for f in fragments if f.get('kind') in CHANGE_ARTIFACT_KINDS and f.get('ok')]
    if not evidence:
        return False
    for fragment in evidence:
        if fragment.get('kind') in ('diff', 'patch', 'file'):
            for target in _fragment_targets(fragment):
                if not changed_paths or _path_backed(target, changed_paths):
                    return True
        if fragment.get('kind') == 'command':
            command = str(fragment.get('command') or '')
            if _command_backed(command, profile, []):
                return True
            if probe_found and fragment.get('exitCode') == 0 and command \
                    and not READ_CMD_RE.search(command):
                return True
    return False


def _capture_after_change(fragments, change_steps):
    """A capture counts only if it was taken AFTER the change (§2.4): a "before" shot proves nothing."""
    captures = [f for f in fragments if f.get('kind') in CAPTURE_ARTIFACT_KINDS and f.get('ok')]
    if not captures:
        return None
    if not change_steps:
        return captures[-1]
    latest_change = max(change_steps)
    return next((f for f in captures
                 if f.get('step') is None or f.get('step') >= latest_change), None)


def _fragment(value):
    fragment = dict(value)
    kind = str(fragment.get('kind') or '').strip()
    fragment['kind'] = kind
    fragment['path'] = _clean_path(fragment.get('path')) if fragment.get('path') else None
    fragment['ok'] = bool(fragment.get('ok', True))
    return fragment


def _verdict_dict(verdict, missing, fragments, changed_paths, claims, notes):
    return {
        'verdict': verdict,
        'checked': len(fragments),
        'missing': missing,
        'artifacts': fragments,
        'changedFiles': [{'path': path} if isinstance(path, str) else path
                         for path in changed_paths],
        'claims': claims,
        'notes': notes,
    }


def assess(answer_text, profile, probe, artifacts, *, mode='warn'):
    """Judge one finished turn. Pure: everything arrives as an argument, nothing is fetched.

    ``probe`` is the box scan (or ``None`` when no scan was needed or none could be made): a dict
    with ``ok``, ``files`` (changed since the turn began) and/or an ``error`` token. ``artifacts``
    are the fragments from :func:`artifacts_from_calls`.
    """
    text = answer_text or ''
    fragments = [_fragment(item) for item in (artifacts or []) if isinstance(item, dict)]
    probe = probe if isinstance(probe, dict) else None
    probe_error = str(probe.get('error') or '') if probe else ''
    probe_ok = bool(probe and probe.get('ok') is not False and not probe_error)
    probe_paths = tuple(_clean_path(item.get('path') if isinstance(item, dict) else item)
                        for item in (probe or {}).get('files') or ())
    if mode == 'off':
        # R5 — the gate was switched off: nothing was measured, so nothing is claimed.
        return _verdict_dict('not_measurable', [], fragments, (), [], ['gate_off'])
    changed = []
    for path in list(profile.writes) + list(probe_paths):
        path = _clean_path(path)
        if path and path not in changed:
            changed.append(path)
    ui_changed = [path for path in changed if is_ui_path(path)]
    code_changed = [path for path in changed if not is_ui_path(path)]
    missing = []
    unmeasured = []
    notes = []
    claim_list = claim_paths(text)

    # ---- R5 first: is there anything to judge at all? ------------------------------------------
    known_change = bool(profile.writes or profile.changes_commands)
    if profile.needs_probe and not probe_ok and not known_change:
        reason = 'box_unreachable' if probe is None else 'box_probe_failed'
        unmeasured.append({'reason': reason, 'detail': probe_error or 'no probe result'})
    # ---- R1: a change with no matching evidence ------------------------------------------------
    change_steps = [f['step'] for f in fragments
                    if f.get('kind') in ('diff', 'patch', 'file') and f.get('ok')
                    and isinstance(f.get('step'), int)]
    if code_changed or profile.changes_commands:
        if not _has_change_evidence(fragments, code_changed, profile, probe_found=bool(probe_paths)):
            # Two different silences: the box scan SAW files change and there is no proof for them
            # (`change_without_verification`), or a write-capable tool ran and left nothing at all
            # to read (`no_evidence_for_tools`).
            missing.append({'reason': 'change_without_verification'
                            if (probe_paths or fragments) else 'no_evidence_for_tools',
                            'detail': (code_changed or list(profile.changes_commands) or ['?'])[0]})
    if ui_changed or profile.ui_tools:
        capture = _capture_after_change(fragments, change_steps)
        if capture is None:
            missing.append({'reason': 'ui_change_without_capture',
                            'detail': (ui_changed or list(profile.ui_tools) or ['?'])[0]})
        else:
            notes.append('capture:%s' % capture.get('path'))
    # ---- R2: a read-only turn is complete work -------------------------------------------------
    if not code_changed and not ui_changed and not profile.changes_commands and not profile.ui_tools:
        if profile.delegated:
            if not any(f.get('kind') == 'child' for f in fragments):
                unmeasured.append({'reason': 'no_evidence_for_tools',
                                   'detail': 'đã giao cho phiên con nhưng chưa có kết quả con đóng'})
        else:
            notes.append('read_only')
    # ---- R3: claims the turn cannot back -------------------------------------------------------
    # R5 thắng R3 (§2.3): luật bắt bịa cần BIẾT đường dẫn có nằm trong box hay không, mà một phép
    # dò hỏng thì harness không còn dữ liệu nào về box — kết tội câu trả lời lúc đó đúng là thứ
    # R5 cấm, nên lượt chỉ được ghim `not_measurable`.
    claims_chargeable = probe_ok or not profile.needs_probe
    known_paths = list(profile.writes) + list(profile.reads) \
        + [value for f in fragments for value in _fragment_targets(f)] + list(probe_paths)
    claims = []
    for claim in claim_list:
        if claim.get('path'):
            backed = _path_backed(claim['path'], known_paths)
        else:
            backed = _command_backed(claim.get('command'), profile, fragments)
        claims.append(dict(claim, backed=backed))
        if backed or not claim.get('assertive') or not claims_chargeable:
            continue
        missing.append({'reason': 'claim_path_not_in_turn' if claim.get('path')
                        else 'answer_references_unknown_command',
                        'detail': claim.get('path') or claim.get('command')})
    # ---- R4: the D-4 ceiling ------------------------------------------------------------------
    long_answer = len(text) > ANSWER_WARN_CHARS
    if long_answer:
        notes.append('answer_long')
    if len(text) > ANSWER_MAX_CHARS:
        missing.append({'reason': 'answer_too_long', 'detail': '%d chars' % len(text)})
    blocking = [item for item in missing if item['reason'] not in UNMEASURED_REASONS]
    if blocking:
        verdict = 'insufficient'
    elif unmeasured:
        verdict = 'not_measurable'
        missing = unmeasured
    else:
        verdict = 'sufficient'
    return _verdict_dict(verdict, missing, fragments, changed, claims, notes)


def missing_reason(reason, detail=None):
    """Human Vietnamese text for one reason code (the badge colour is not an explanation)."""
    text = REASON_TEXT.get(str(reason or ''), str(reason or ''))
    detail = str(detail or '').strip()
    return f'{text} ({detail})' if detail else text


def repair_message(verdict, profile, probe):
    """ONE ``user`` message asking for the missing evidence — names and numbers only.

    The prompt never carries file contents or a diff: a repair round that leaks the diff would make
    the model's answer look verified on evidence the *prompt* supplied, which is exactly the
    self-praise the gate exists to stop.
    """
    missing = [item for item in (verdict or {}).get('missing') or [] if isinstance(item, dict)]
    lines = ['Bạn vừa kết thúc một lượt nhưng câu trả lời cuối chưa mang bằng chứng cho việc đã làm.',
             '', 'Việc đã làm trong lượt này:']
    worked = []
    if profile.writes:
        worked.append('ghi tệp: ' + ', '.join(list(profile.writes)[:REPAIR_MAX_ITEMS]))
    if profile.changes_commands:
        worked.append('lệnh có ghi: ' + '; '.join(list(profile.changes_commands)[:2])[:200])
    if profile.verify_commands:
        worked.append('lệnh kiểm chứng: ' + '; '.join(list(profile.verify_commands)[:2])[:200])
    if profile.ui_tools:
        worked.append('thao tác giao diện: ' + ', '.join(list(profile.ui_tools)[:REPAIR_MAX_ITEMS]))
    if profile.delegated:
        worked.append('đã giao cho phiên con: ' + ', '.join(list(profile.delegated)[:REPAIR_MAX_ITEMS]))
    lines.extend('- ' + item for item in (worked or ['chưa thấy việc ghi nào']))
    lines.extend(['', 'Còn thiếu:'])
    lines.extend('- ' + missing_reason(item.get('reason'), item.get('detail'))
                 for item in missing[:REPAIR_MAX_ITEMS])
    lines.extend(['', 'Hãy viết lại câu trả lời cuối bằng tiếng Việt, và trong đó:',
                  '- nêu đường dẫn tệp đã đổi kèm bằng chứng (tệp diff trong '
                  f'{EVIDENCE_ROOT_REL}, hoặc sha256/số dòng),',
                  '- nêu lệnh đã chạy kèm mã thoát và trích ngắn đầu ra,',
                  '- nếu lượt đổi giao diện: nêu đường dẫn ảnh/ghi hình chụp SAU thay đổi,',
                  '- nếu có phần chưa kiểm chứng được: nói rõ chưa kiểm chứng được và vì sao.',
                  'Không bịa đường dẫn hay lệnh; chỉ nêu thứ đã thật sự chạy trong lượt này.'])
    content = '\n'.join(lines)
    if len(content) > REPAIR_MAX_CHARS:
        content = content[:REPAIR_MAX_CHARS - 1].rstrip() + '…'
    return {'role': 'user', 'content': content}


def verdict_label(verdict):
    """Vietnamese label for one verdict — the same words the UI badge shows."""
    return _LABELS.get(str(verdict or ''), _LABELS['not_measurable'])
