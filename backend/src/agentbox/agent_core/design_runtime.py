"""Chế độ `/design` của P1 — vỏ mode, Design Lead, phỏng vấn có điều kiện, danh sách chạm.

Khuôn mẫu là chế độ `/research` (`research_runtime.py`): mọi hàm ở đây nhận `rt` (`HarnessRuntime`)
làm tham số đầu và chỉ nói LUẬT — việc ghi đĩa/mở mạng đi qua `rt.store`/`rt.executor` như mọi công
cụ khác. Không import `agent_core.runtime` ở cấp mô-đun (vòng import chạy ngược): chỗ nào cần thì
nạp lười qua `_mode_mod()`.

P1 dựng nền: bật/tắt chế độ (`apply_design_mode`), run (`new_design_job`), phỏng vấn
(`design_confirm_interview_required` + `design_interview_questions`), thẻ brief/danh sách chạm
(`design_touch_list_store`/`design_touch_list_approve`) và CỔNG từ chối ghi khi danh sách chưa được
duyệt (`design_write`). Đường ghi thật, canvas, soát độc lập và bàn giao thuộc P2–P4.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid

from . import journal
from .limits import (
    DESIGN_ACTIVE_STATUSES, DESIGN_ERROR_TEXT, DESIGN_EXIT_CHOICE_REQUIRED_CODE,
    DESIGN_HANDOFF_BLOCK_END, DESIGN_HANDOFF_BLOCK_MARKER, DESIGN_HARD_FORBIDDEN,
    DESIGN_BRANCH_REQUIRED_CODE, DESIGN_CANVAS_PROTOCOL_INVALID_CODE,
    DESIGN_DIFF_DIRTY_BASE_CODE, DESIGN_INTERVIEW_IDS, DESIGN_INTERVIEW_MAX_QUESTIONS,
    DESIGN_MODE_EVENT_CODE, DESIGN_OWNED_PREFIX, DESIGN_PATH_NOT_APPROVED_CODE,
    DESIGN_PROMPT_KINDS, DESIGN_STEPS, DESIGN_TOUCH_KINDS, DESIGN_TOUCH_LIST_REQUIRED_CODE,
    DESIGN_TOUCH_LIST_REVISION_STALE_CODE, DESIGN_TOUCH_STATUSES, DESIGN_WRITE_STALE_CODE,
)

# Bảy bước và tám pha được hợp đồng §2 đặt trong mô-đun này; `limits` là nguồn duy nhất, ở đây chỉ
# tái xuất cho `design_runtime.PHASE_STEP`/`DESIGN_STEPS` khớp hợp đồng.
from .limits import DESIGN_PHASES, DESIGN_STATUSES, DESIGN_TERMINAL_STATUSES  # noqa: E402

#: Bảy bước hiển thị của một run, và pha → bước (hợp đồng design-interfaces §2).
PHASE_STEP = {'interviewing': 'clarify', 'briefing': 'brief', 'touch-list': 'approve',
              'drawing': 'draw', 'scaffolding': 'write', 'reviewing': 'review', 'handoff': 'handoff',
              'done': 'handoff'}

#: Pha ĐÓNG của một run (`done` ⇔ `completed`/`partial`/`cancelled`). Run đã đóng thì không mở lại.
PHASE_DONE = 'done'

#: Bốn kỹ năng của lượt design (§7.9) — tên khớp `limits.DESIGN_SKILLS`.
DESIGN_SKILL_NAMES = ('claude-design', 'design-md', 'popular-web-designs', 'architecture-diagram')

#: Công cụ design ĐÃ nối vào `dispatch`. P1 nối `design_scope`/`design_write`; P2/P3 nối thêm đường
#: canvas và bốn công cụ đường ghi. P4–P5 (soát độc lập, báo cáo) thêm tên vào ĐÚNG danh sách này
#: khi nối phần của chúng: chưa nối thì không được quảng cáo cho mô hình.
WIRED_DESIGN_TOOLS = ('design_scope', 'design_branch_create', 'design_write', 'design_diff',
                      'design_revert', 'canvas_draw')

#: `origin` của một run: `mode` = run của chế độ (được bơm khi mode bật hoặc đang chạy nền),
#: `delegate` = run mở bởi `delegate_task(role='design')` từ ngoài mode (không bao giờ bơm).
DESIGN_JOB_ORIGIN = 'mode'
DESIGN_DELEGATE_ORIGIN = 'delegate'

#: Câu hỏi phỏng vấn → trường của brief mà câu trả lời ghi vào (`design_prompt_answer`).
QUESTION_FIELD = {'dq-screen': 'screen', 'dq-platform': 'platform', 'dq-project': 'project',
                  'dq-scope': 'mode', 'dq-style': 'style', 'dq-entry': 'entry',
                  'dq-constraints': 'constraints'}

#: Lựa chọn gợi ý của từng câu hỏi (§7.8: mỗi câu 2–5 lựa chọn + ô tự luận).
QUESTION_OPTIONS = {
    'dq-screen': [('chat', 'Màn hình chat'), ('settings', 'Màn hình cài đặt'),
                  ('dashboard', 'Bảng điều khiển'), ('other', 'Màn hình khác')],
    'dq-platform': [('web', 'Web (trình duyệt)'), ('desktop', 'Ứng dụng desktop'),
                    ('mobile', 'Ứng dụng di động')],
    'dq-project': [('current', 'Dự án đang mở trong workspace'), ('other', 'Dự án khác (ghi rõ)')],
    'dq-scope': [('new-screen', 'Màn hình/tính năng mới'), ('redesign', 'Thiết kế lại màn hình có sẵn'),
                 ('new-feature', 'Tính năng mới trong luồng có sẵn')],
    'dq-style': [('follow-existing', 'Theo phong cách hiện có của dự án'),
                 ('reference', 'Có tham chiếu phong cách riêng (ghi rõ)'),
                 ('not-sure', 'Chưa rõ — cứ đề xuất rồi tôi góp ý')],
    'dq-entry': [('existing-route', 'Điểm vào là một tuyến/route có sẵn'),
                 ('new-route', 'Mở tuyến mới'), ('unknown', 'Chưa rõ điểm vào')],
    'dq-constraints': [('none', 'Không có ràng buộc đặc biệt'), ('other', 'Có (ghi rõ)')],
}

#: Nhãn tiếng Việt của từng câu hỏi phỏng vấn.
QUESTION_TEXT = {
    'dq-screen': 'Thiết kế cho màn hình hay bề mặt nào?',
    'dq-platform': 'Chạy trên nền tảng nào?',
    'dq-project': 'Dự án đích trong workspace là dự án nào?',
    'dq-scope': 'Đây là màn hình mới, thiết kế lại, hay tính năng mới trong luồng có sẵn?',
    'dq-style': 'Phong cách tham chiếu là gì?',
    'dq-entry': 'Điểm vào của màn hình này ở đâu?',
    'dq-constraints': 'Có điều gì tuyệt đối không được phá không?',
}

#: Token cho thấy brief ĐÃ nói rõ một BỀ MẶT CỤ THỂ. "giao diện chat" KHÔNG tính: nó vẫn là một
#: lời yêu cầu mơ hồ ("thiết kế một giao diện chat" ⇒ còn phải hỏi là màn hình nào).
_SCREEN_TOKENS = ('màn hình', 'trang ', 'panel', 'modal', 'hộp thoại', 'biểu mẫu', 'form ')
_PLATFORM_TOKENS = {'web': ('web', 'trình duyệt', 'browser', 'responsive'),
                    'desktop': ('desktop', 'máy tính', 'electron', 'tauri'),
                    'mobile': ('mobile', 'di động', 'ios', 'android', 'điện thoại')}
_REDESIGN_TOKENS = ('thiết kế lại', 'redesign', 'làm lại', 'cải tạo', 'sửa giao diện')
_NEW_TOKENS = ('màn hình mới', 'tính năng mới', 'giao diện mới', 'new screen', 'new feature')
_FOLLOW_STYLE_TOKENS = ('theo phong cách hiện có', 'theo phong cách hiện tại', 'giống hiện có',
                        'follow existing', 'đồng bộ phong cách', 'theo ui hiện có')
#: Đường dẫn tệp đích nói trong `goal` (§7.8: thiết kế lại + đường dẫn ⇒ bỏ qua phỏng vấn).
_PATH_RE = re.compile(r'[\w./-]+\.[A-Za-z]{1,6}\b')


def _mode_mod():
    """Nạp lười `agent_core.runtime` — tránh vòng import (runtime ⇒ design_runtime)."""
    from . import runtime as runtime_module
    return runtime_module


def _error(code):
    """`ValueError` mang mã hợp đồng: `CODE: câu tiếng Việt` (khuôn research)."""
    return ValueError(f'{code}: {DESIGN_ERROR_TEXT.get(code, code)}')


def _slug(value):
    """Slug an toàn cho `design_id` và tên thư mục `.design/<slug>/`."""
    text = re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')
    return text[:48] or 'run'


def _revision_arg(value, code):
    """`revision` nhận từ thân HTTP → `int`; giá trị không phải số ⇒ `ValueError(code)`."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise _error(code) from None


# ── Vỏ chế độ (§7.4) ────────────────────────────────────────────────────────


def design_mode_available(env=None):
    """Công tắc giết `BOXFOX_DESIGN_MODE` — mặc định `on` nghĩa là tính năng CÓ MẶT.

    Có mặt KHÔNG có nghĩa là bật: mọi phiên khởi đầu với `designMode.on = False` cho tới khi người
    dùng bấm nút hoặc gõ `/design`.
    """
    from .limits import design_mode_enabled
    return design_mode_enabled(env)


def design_mode_state(rt, session_id):
    """`session.config.designMode` đã chuẩn hoá — ảnh chụp trạng thái mode của phiên."""
    session = rt.store.get(session_id)
    return _mode_mod().design_mode(session)


def apply_design_mode(rt, session_id, on, by='toggle', active_run=None):
    """Bật/tắt chế độ (§7.3) — logic thuần, route HTTP chỉ gọi hàm này.

    Tắt chế độ khi một run còn hoạt động mà THIẾU lựa chọn ⇒ `DESIGN_EXIT_CHOICE_REQUIRED` kèm một
    lời hỏi `exit-choice`; chế độ KHÔNG đổi cho tới khi người dùng chọn.
    """
    runtime_module = _mode_mod()
    session = rt.store.get(session_id)
    if session.get('role') != 'orchestrator' or session.get('parent_id'):
        raise PermissionError('design mode belongs to the conversation, not to a child session')
    want_on = bool(on)
    mode = dict(runtime_module.design_mode(session))
    run_id = str(mode.get('activeRunId') or '')
    job = rt.store.design_job(run_id) if run_id else None
    if job is not None and job['session_id'] != session_id:
        job = None
    active = job is not None and job['status'] in set(DESIGN_ACTIVE_STATUSES) | {
        'needs_user', 'paused', 'partial'}
    if want_on:
        config = dict(session.get('config') or {})
        entered = str(by or 'toggle')
        mode = {**mode, 'on': True,
                'since': mode.get('since') or journal.utc_now_iso(),
                'enteredBy': entered if not mode.get('on') else mode.get('enteredBy') or entered,
                'revision': int(mode.get('revision') or 0) + 1}
        if job is not None:
            mode['activeRunId'] = job['design_id']
            state = dict(job['state'] or {})
            if state.get('background'):
                state['background'] = False
                rt.store.design_job_save(job['design_id'], session_id, state)
        config[runtime_module.DESIGN_MODE_CONFIG_KEY] = mode
        rt.store.update_config(session_id, config)
        rt.store.emit(session_id, DESIGN_MODE_EVENT_CODE,
                      {'on': True, 'by': mode['enteredBy'],
                       'activeRunId': mode.get('activeRunId'), 'revision': mode['revision']})
        return {'on': True, 'mode': mode, 'activeRunId': mode.get('activeRunId'), 'prompt': None}
    # Tắt chế độ.
    if active:
        choice = str(active_run or '').strip().lower()
        if choice not in ('pause', 'background'):
            prompt = design_prompt_new(rt, session_id, job, 'exit-choice',
                                       questions=[{'id': 'exit',
                                                   'text': f'Run {job["design_id"]} đang chạy. Bạn muốn '
                                                           'tạm dừng hay để nó chạy nền?',
                                                   'options': [{'id': 'pause', 'label': 'Tạm dừng run'},
                                                               {'id': 'background',
                                                                'label': 'Tiếp tục chạy nền'}],
                                                   'allowFreeText': False, 'required': True}])
            error = _error(DESIGN_EXIT_CHOICE_REQUIRED_CODE)
            error.payload = {'code': DESIGN_EXIT_CHOICE_REQUIRED_CODE, 'status': 409,
                             'prompt': {**prompt, 'kind': 'exit-choice'}}
            raise error
        state = dict(job['state'] or {})
        if choice == 'pause':
            state['background'] = False
            rt.store.design_job_save(job['design_id'], session_id, state, 'paused')
            rt.store.emit(session_id, 'design_run', design_job_event(
                rt.store.design_job(job['design_id'])))
        else:
            state['background'] = True
            rt.store.design_job_save(job['design_id'], session_id, state)
            rt.store.emit(session_id, 'design_run', design_job_event(
                rt.store.design_job(job['design_id'])))
    config = dict(session.get('config') or {})
    mode = {**mode, 'on': False, 'activeRunId': run_id if active else mode.get('activeRunId'),
            'revision': int(mode.get('revision') or 0) + 1}
    config[runtime_module.DESIGN_MODE_CONFIG_KEY] = mode
    rt.store.update_config(session_id, config)
    rt.store.emit(session_id, DESIGN_MODE_EVENT_CODE,
                  {'on': False, 'by': str(by or 'toggle'), 'revision': mode['revision']})
    return {'on': False, 'mode': mode, 'activeRunId': mode.get('activeRunId'), 'prompt': None,
            'exitChoice': str(active_run or '') or None}


# ── Run (§7.7) ──────────────────────────────────────────────────────────────


def new_design_job(rt, session_id, goal, *, origin='mode', entered_by=None):
    """Mở một run thiết kế mới trong pha `interviewing` và phát `design_run`."""
    goal = str(goal or '').strip()
    design_id = f'd-{_slug(goal)}-{uuid.uuid4().hex[:6]}'
    state = {'origin': str(origin), 'phase': 'interviewing',
             'phaseHistory': [{'phase': 'interviewing', 'at': journal.utc_now_iso(),
                               'reason': 'run-opened'}],
             'goal': goal, 'brief': brief_from_goal(goal), 'touchList': None, 'prompts': [],
             'actions': [], 'enteredBy': entered_by, 'background': False}
    job = rt.store.design_job_save(design_id, session_id, state, status='scoping')
    rt.store.emit(session_id, 'design_run', design_job_event(job))
    # Phỏng vấn có ĐIỀU KIỆN (§7.8): brief mơ hồ thì mở lời hỏi ngay, không phải chờ mô hình gọi
    # `design_scope(action="ask")`. Brief đã đủ bốn mục thì KHÔNG có lời hỏi nào (D-06).
    if design_confirm_interview_required(state['brief']):
        design_prompt_new(rt, session_id, job, 'interview',
                          questions=design_interview_questions(state['brief']))
    return job


def design_job_event(job):
    """Payload `design_run` (§7.2) — một chỗ dựng để mọi đường phát nói cùng một câu."""
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    phase = str(state.get('phase') or '')
    return {'designId': job.get('design_id'), 'status': job.get('status'), 'phase': phase,
            'background': bool(state.get('background')), 'revision': int(job.get('revision') or 0),
            'origin': str(state.get('origin') or ''), 'step': PHASE_STEP.get(phase, 'clarify')}


def design_run_payload(job):
    """Bản camelCase của một hàng `design_jobs` cho API (hợp đồng §5, §6)."""
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    touch_list = state.get('touchList') if isinstance(state.get('touchList'), dict) else None
    return {'designId': job.get('design_id'), 'sessionId': job.get('session_id'),
            'status': job.get('status'), 'revision': int(job.get('revision') or 0),
            'phase': state.get('phase'), 'origin': state.get('origin'),
            'background': bool(state.get('background')),
            'step': PHASE_STEP.get(str(state.get('phase') or ''), 'clarify'),
            'goal': state.get('goal'), 'brief': state.get('brief') or {},
            'touchList': touch_list, 'prompts': state.get('prompts') or [],
            'phaseHistory': state.get('phaseHistory') or [], 'actions': state.get('actions') or [],
            'touchListRevision': int((touch_list or {}).get('revision') or 0)}


def set_phase(rt, session_id, job, phase, reason, *, force=False):
    """Đẩy một run sang pha mới: ghi `state.phase` + `phaseHistory[]` rồi PHÁT đúng MỘT `design_run`.

    Luật "có gì để ghi không" nằm trong `store.design_job_phase` (nó đọc hàng TƯƠI): pha đang đứng
    thì không ghi, run đã ở pha `done` thì không lùi khỏi đó — trừ `force`. Nhích pha KHÔNG nhích
    `revision`. Trả về hàng job sau khi ghi, hoặc `None` khi không có gì để ghi.
    """
    if job is None:
        return None
    updated = rt.store.design_job_phase(job['design_id'], session_id, str(phase), reason,
                                       journal.utc_now_iso(), force=force)
    if updated is None:
        return None
    rt.store.emit(session_id, 'design_run', design_job_event(updated))
    return updated


def close_run(rt, session_id, job, status, reason, *, revision=None):
    """Đóng một run: ghim `status` + pha `done`, phát `design_run` và `design_notice`."""
    state = dict(job['state'] or {})
    state['stopReason'] = str(reason or '')
    updated = rt.store.design_job_save(job['design_id'], session_id, state, status=status,
                                       revision=revision)
    updated = set_phase(rt, session_id, updated, PHASE_DONE, reason, force=True) or updated
    rt.store.emit(session_id, 'design_notice',
                  {'designId': job['design_id'],
                   'kind': 'background-done' if state.get('background') else 'blocked'})
    return updated


def background_design_run(rt, session_id, design_id, reason):
    """Đánh dấu một run là CHẠY NỀN (mode có thể tắt mà run vẫn tiếp tục) và phát `design_run`."""
    job = rt.store.design_job(design_id)
    if job is None or job['session_id'] != session_id:
        raise ValueError('DESIGN_JOB_UNKNOWN: no such run on this session')
    state = dict(job['state'] or {})
    state['background'] = True
    state['backgroundReason'] = str(reason or '')
    updated = rt.store.design_job_save(design_id, session_id, state, revision=job.get('revision'))
    rt.store.emit(session_id, 'design_run', design_job_event(updated))
    return updated


# ── Brief + phỏng vấn (§7.8) ────────────────────────────────────────────────


def brief_from_goal(goal):
    """Đọc một `goal` tự do thành brief — chỉ để QUYẾT ĐỊNH có hỏi hay không (§7.8).

    Đây là suy đoán thô, không phải dữ liệu chốt: brief thật do mô hình ghi qua `design_scope`.
    """
    text = str(goal or '')
    low = text.lower()
    brief = {'goal': text}
    if any(token in low for token in _SCREEN_TOKENS):
        brief['screen'] = text
    found = _PATH_RE.search(text)
    if found:
        brief['path'] = found.group(0)
    for platform, tokens in _PLATFORM_TOKENS.items():
        if any(token in low for token in tokens):
            brief['platform'] = platform
            break
    for token in _FOLLOW_STYLE_TOKENS:
        if token in low:
            brief['style'] = 'follow-existing'
            break
    redesign = any(token in low for token in _REDESIGN_TOKENS)
    new_scope = any(token in low for token in _NEW_TOKENS)
    if redesign and not new_scope:
        brief['mode'] = 'redesign'
    elif new_scope and not redesign:
        brief['mode'] = 'new'
    return brief


def _merge_brief(brief, patch):
    """Ghép `patch` vào brief; mục dạng chuỗi được ghi thẳng, mục dạng dict giữ nguyên."""
    merged = dict(brief or {})
    for key, value in (patch or {}).items():
        if key == 'revision' or value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = value if isinstance(value, (dict, list)) else str(value).strip()
    return merged


def design_confirm_interview_required(brief):
    """Id các luật kích hoạt phỏng vấn mà brief ĐÃ CHẠM (§7.8); `[]` ⇒ bỏ qua phỏng vấn."""
    brief = brief if isinstance(brief, dict) else {}

    def has(key):
        value = brief.get(key)
        if isinstance(value, dict):
            return bool(str(value.get('text') or value.get('value') or '').strip())
        if isinstance(value, list):
            return len(value) > 0
        return bool(str(value or '').strip())

    mode = str(brief.get('mode') or '').strip()
    screen, platform, project, style = has('screen'), has('platform'), has('project'), has('style')
    path = str(brief.get('path') or '').strip()
    # Bỏ qua phỏng vấn: brief đã có màn hình + nền tảng + dự án đích + (tham chiếu phong cách hoặc
    # lệnh "theo phong cách hiện có"), HOẶC thiết kế lại đã có đường dẫn tệp đích (§7.8).
    if screen and platform and project and (style or mode == 'follow-existing'):
        return []
    if mode == 'redesign' and path:
        return []
    rules = []
    if not screen:
        rules.append('dq-screen')
    if not platform:
        rules.append('dq-platform')
    if not project:
        rules.append('dq-project')
    if not style and mode != 'redesign':
        rules.append('dq-style')
    if mode and mode not in ('new', 'redesign') and not screen:
        # Mơ hồ giữa "tính năng mới" và "thiết kế lại" chỉ đáng hỏi khi chưa rõ bề mặt.
        rules.append('dq-scope')
    if mode == 'redesign' and not has('entry'):
        rules.append('dq-entry')
    # Giữ đúng thứ tự canonical và không trùng.
    ordered = [item for item in DESIGN_INTERVIEW_IDS if item in set(rules)]
    return ordered


def design_interview_questions(brief):
    """≤3 câu hỏi phỏng vấn cho brief này, mỗi câu 2–5 lựa chọn + ô tự luận (§7.8)."""
    ids = design_confirm_interview_required(brief)[:DESIGN_INTERVIEW_MAX_QUESTIONS]
    questions = []
    for qid in ids:
        options = [{'id': oid, 'label': label} for oid, label in QUESTION_OPTIONS.get(qid, [])]
        questions.append({'id': qid, 'text': QUESTION_TEXT.get(qid, qid),
                          'why': 'câu trả lời đổi hướng thiết kế', 'options': options,
                          'allowFreeText': True, 'required': True})
    return questions


# ── Thẻ brief + danh sách chạm (§7.10) ──────────────────────────────────────


def _normalize_touch_item(item, index):
    """Một mục danh sách chạm theo lược đồ §7.10; mục thiếu trường nhận mặc định an toàn."""
    item = item if isinstance(item, dict) else {}
    kind = str(item.get('kind') or 'new').strip().lower()
    if kind not in DESIGN_TOUCH_KINDS:
        raise ValueError(f'DESIGN_TOUCH_KIND_INVALID: kind ∈ {DESIGN_TOUCH_KINDS}, nhận {kind!r}')
    status = str(item.get('status') or 'proposed').strip().lower()
    if status not in DESIGN_TOUCH_STATUSES:
        status = 'proposed'
    return {'id': str(item.get('id') or f't{index + 1}'), 'kind': kind,
            'path': str(item.get('path') or '').strip(), 'reason': str(item.get('reason') or ''),
            'risk': str(item.get('risk') or 'low'), 'status': status,
            'sha256': item.get('sha256')}


def design_scope(rt, session_id, job, action, patch=None, questions=None):
    """`design_scope` (§7.1): `propose`/`update` ghép brief, `ask` mở một lời hỏi phỏng vấn.

    `update` với `patch.revision` là khoá lạc quan so với `design_jobs.revision` SỐNG: lệch ⇒
    `DESIGN_TOUCH_LIST_REVISION_STALE` (không ghi gì).
    """
    action = str(action or '').strip().lower()
    if action not in ('propose', 'ask', 'update'):
        raise ValueError(f'DESIGN_SCOPE_ACTION_INVALID: action ∈ (propose, ask, update), '
                         f'nhận {action!r}')
    state = dict(job['state'] or {})
    if action == 'ask':
        prompt = design_prompt_new(rt, session_id, job, 'interview',
                                   questions=questions or design_interview_questions(
                                       state.get('brief') or {}))
        return {'designId': job['design_id'], 'revision': prompt['revision'],
                'phase': state.get('phase'), 'promptId': prompt['promptId']}
    patch = patch if isinstance(patch, dict) else {}
    # Danh sách chạm đi qua CÙNG công cụ với brief (§7.1): một `patch` mang `touchList`/`items` là
    # một lần ĐỀ XUẤT danh sách, không phải một lần sửa brief.
    if isinstance(patch.get('touchList'), dict) or isinstance(patch.get('items'), list):
        proposed = patch.get('touchList') if isinstance(patch.get('touchList'), dict) else patch
        return design_touch_list_store(rt, session_id, job, proposed.get('items') or [],
                                       proposed.get('forbidden'), proposed.get('revision'))
    if action == 'update':
        expected = _revision_arg(patch.get('revision'), DESIGN_TOUCH_LIST_REVISION_STALE_CODE)
        if expected is not None and expected != int(job['revision'] or 0):
            raise _error(DESIGN_TOUCH_LIST_REVISION_STALE_CODE)
    state['brief'] = _merge_brief(state.get('brief') or {}, patch)
    updated = rt.store.design_job_save(job['design_id'], session_id, state,
                                       revision=job.get('revision'))
    rt.store.emit(session_id, 'design_scope',
                  {'designId': job['design_id'], 'revision': updated['revision']})
    return {'designId': job['design_id'], 'revision': updated['revision'],
            'phase': state.get('phase')}


def design_touch_list_store(rt, session_id, job, items, forbidden=None, revision=None):
    """Ghi danh sách chạm (§7.10) — mỗi lần ghi tăng `touchList.revision` của chính danh sách.

    `revision` (nếu có) là khoá lạc quan so với `touchList.revision` sống: lệch ⇒ từ chối. Danh
    sách đen cứng `DESIGN_HARD_FORBIDDEN` luôn được gộp vào `forbidden`.
    """
    state = dict(job['state'] or {})
    current = state.get('touchList') if isinstance(state.get('touchList'), dict) else {}
    if revision is not None:
        expected = _revision_arg(revision, DESIGN_TOUCH_LIST_REVISION_STALE_CODE)
        if int(current.get('revision') or 0) != (expected or 0):
            raise _error(DESIGN_TOUCH_LIST_REVISION_STALE_CODE)
    normalized = [_normalize_touch_item(item, index) for index, item in enumerate(items or [])]
    blocked = list(current.get('forbidden') or DESIGN_HARD_FORBIDDEN)
    for path in (forbidden or []):
        text = str(path or '').strip()
        if text and text not in blocked:
            blocked.append(text)
    for path in DESIGN_HARD_FORBIDDEN:
        if path not in blocked:
            blocked.append(path)
    state['touchList'] = {'revision': int(current.get('revision') or 0) + 1,
                          'designId': job['design_id'],
                          'branch': current.get('branch') or {'name': None, 'base': None,
                                                              'status': 'proposed'},
                          'items': normalized, 'forbidden': blocked, 'approvedAt': None}
    updated = rt.store.design_job_save(job['design_id'], session_id, state,
                                       revision=job.get('revision'))
    rt.store.emit(session_id, 'design_scope',
                  {'designId': job['design_id'], 'revision': updated['revision']})
    return {'designId': job['design_id'], 'revision': state['touchList']['revision'],
            'items': len(normalized), 'forbidden': blocked}


def design_touch_list_approve(rt, session_id, job, revision, answers=None):
    """Duyệt CẢ danh sách chạm (§7.3): mọi mục `proposed` thành `approved`, ghim `approvedAt`."""
    state = dict(job['state'] or {})
    touch_list = state.get('touchList') if isinstance(state.get('touchList'), dict) else None
    if not touch_list:
        raise _error(DESIGN_TOUCH_LIST_REQUIRED_CODE)
    expected = _revision_arg(revision, DESIGN_TOUCH_LIST_REVISION_STALE_CODE)
    if expected is not None and expected != int(touch_list.get('revision') or 0):
        raise _error(DESIGN_TOUCH_LIST_REVISION_STALE_CODE)
    approved = 0
    for item in touch_list.get('items') or []:
        if item.get('status') == 'proposed':
            item['status'] = 'approved'
            approved += 1
    touch_list['approvedAt'] = journal.utc_now_iso()
    state['touchList'] = touch_list
    updated = rt.store.design_job_save(job['design_id'], session_id, state,
                                       revision=job.get('revision'))
    rt.store.emit(session_id, 'design_scope',
                  {'designId': job['design_id'], 'revision': updated['revision']})
    set_phase(rt, session_id, updated, 'drawing', 'touch-list-approved')
    return {'designId': job['design_id'], 'revision': touch_list['revision'],
            'approved': approved, 'approvedAt': touch_list['approvedAt']}


# ── Đường ghi có gác (§6.5) ─────────────────────────────────────────────────


def design_dir(job):
    """`.design/<slug>/` — thư mục do run tự sở hữu."""
    return f'{DESIGN_OWNED_PREFIX}{_slug(job["design_id"])}/'


def design_canvas_path(job):
    """Đường dẫn ảnh chụp cảnh của run (hợp đồng §7.5)."""
    return f'{design_dir(job)}canvas.v1.json'


def _sha256_text(text):
    return hashlib.sha256(str(text).encode('utf-8')).hexdigest()


async def _read_box_text(rt, session_id, path):
    """Nội dung tệp trong box, hoặc `None` khi chưa có/không đọc được (không ném)."""
    try:
        result = await rt.executor.execute('file_read', {'path': path}, session_id)
    except (ValueError, OSError):
        return None
    content = result.get('content') if isinstance(result, dict) else None
    return content if isinstance(content, str) else None


async def _write_box_text(rt, session_id, path, content):
    """Ghi một tệp trong box qua op `file_write` (đường `.design/**` do run sở hữu)."""
    return await rt.executor.execute('file_write', {'path': path, 'content': content}, session_id)


def _branch_state(state):
    branch = state.get('branch') if isinstance(state.get('branch'), dict) else {}
    return branch if str(branch.get('base') or '').strip() else {}


def _approved_items(touch_list):
    return {item.get('path') for item in (touch_list or {}).get('items') or []
            if item.get('status') in ('approved', 'written')}


async def design_branch_create(rt, session_id, job, name):
    """`design_branch_create` (§6.5): tạo nhánh thiết kế từ `HEAD` và ghim `base` sha vào run.

    Cây làm việc còn thay đổi chưa lưu của chủ nhà ⇒ `DESIGN_DIFF_DIRTY_BASE` (không tạo nhánh trên
    một nền bẩn). Việc dựng lệnh git nằm trong worker; lỗi worker (`DESIGN_MAIN_BRANCH_FORBIDDEN`,
    `DESIGN_BRANCH_EXISTS`, `DESIGN_WORKSPACE_NOT_REPO`) đi thẳng ra ngoài.
    """
    dirty = await rt.executor.execute('design_diff', {'base': 'HEAD', 'paths': None}, session_id)
    if (dirty.get('files') if isinstance(dirty, dict) else None):
        raise _error(DESIGN_DIFF_DIRTY_BASE_CODE)
    result = await rt.executor.execute('design_branch_create', {'name': str(name or '')},
                                       session_id)
    state = dict(job['state'] or {})
    branch = {'name': result['branch'], 'base': result['base'], 'head': result['head'],
              'status': 'active'}
    state['branch'] = branch
    touch_list = state.get('touchList') if isinstance(state.get('touchList'), dict) else None
    if touch_list is not None:
        touch_list = dict(touch_list)
        touch_list['branch'] = {'name': branch['name'], 'base': branch['base'], 'status': 'active'}
        state['touchList'] = touch_list
    updated = rt.store.design_job_save(job['design_id'], session_id, state, revision=job.get('revision'))
    rt.store.emit(session_id, 'design_run', design_job_event(updated))
    set_phase(rt, session_id, updated, 'scaffolding', 'branch-created')
    return {'branch': result['branch'], 'base': result['base'], 'head': result['head']}


async def design_write(rt, session_id, job, path, content, mode, anchor=None, position=None):
    """`design_write` (§6.5): ghi MỘT tệp DỰ ÁN sau khi danh sách chạm được duyệt.

    Lớp gác của HARNESS chạy trước khi chạm box: danh sách chạm phải được duyệt
    (`DESIGN_TOUCH_LIST_REQUIRED`), đường dẫn phải nằm trong danh sách đã duyệt hoặc thuộc
    `.design/**` (`DESIGN_PATH_NOT_APPROVED`), danh sách đen cứng luôn bị chối, run phải có nhánh
    thiết kế (`DESIGN_BRANCH_REQUIRED`), và tệp `insert` đã ghim băm mà nay đổi ⇒ `DESIGN_WRITE_STALE`.
    Việc ghi thật đi qua op `design_write` của worker (chỉ `git` với tham số đã kiểm, không shell).
    """
    state = dict(job['state'] or {})
    touch_list = state.get('touchList') if isinstance(state.get('touchList'), dict) else None
    if not touch_list or not touch_list.get('approvedAt'):
        raise _error(DESIGN_TOUCH_LIST_REQUIRED_CODE)
    normalized = str(path or '').strip()
    owned = normalized.startswith(DESIGN_OWNED_PREFIX)
    entry = next((item for item in touch_list.get('items') or []
                  if item.get('path') == normalized), None)
    if normalized in DESIGN_HARD_FORBIDDEN:
        raise _error(DESIGN_PATH_NOT_APPROVED_CODE)
    if not owned and (entry is None or entry.get('status') not in ('approved', 'written')):
        raise _error(DESIGN_PATH_NOT_APPROVED_CODE)
    if not owned and not _branch_state(state):
        raise _error(DESIGN_BRANCH_REQUIRED_CODE)

    before_text = await _read_box_text(rt, session_id, normalized)
    if (entry is not None and entry.get('sha256') and mode == 'insert'
            and (before_text is None or _sha256_text(before_text) != entry['sha256'])):
        raise _error(DESIGN_WRITE_STALE_CODE)

    write_args = {'path': normalized, 'content': content, 'mode': mode}
    if anchor is not None:
        write_args['anchor'] = anchor
    if position is not None:
        write_args['position'] = position
    result = await rt.executor.execute('design_write', write_args, session_id)

    live = rt.store.design_job(job['design_id'])
    state = dict(live['state'] or {})
    touch_list = state.get('touchList') if isinstance(state.get('touchList'), dict) else None
    reason = ''
    if touch_list is not None:
        for item in touch_list.get('items') or []:
            if item.get('path') == result['path']:
                item['status'] = 'written'
                item['sha256'] = result['sha256']
                reason = str(item.get('reason') or '')
                break
        state['touchList'] = touch_list
    log_path = f'{design_dir(job)}actions.jsonl'
    action = {'at': journal.utc_now_iso(), 'path': result['path'], 'mode': result['mode'],
              'sha256Before': _sha256_text(before_text) if before_text is not None else None,
              'sha256After': result['sha256'], 'bytes': result.get('bytes'), 'reason': reason,
              'logPath': log_path, 'author': 'agent'}
    state['actions'] = (state.get('actions') or []) + [action]
    updated = rt.store.design_job_save(job['design_id'], session_id, state, revision=live.get('revision'))
    lines = [json.dumps(row, ensure_ascii=False) for row in state['actions']]
    await _write_box_text(rt, session_id, log_path, '\n'.join(lines) + '\n')
    rt.store.emit(session_id, 'design_run', design_job_event(updated))
    return {'path': result['path'], 'mode': result['mode'], 'sha256': result['sha256'],
            'bytes': result.get('bytes'), 'revision': updated['revision']}


async def design_diff(rt, session_id, job, paths=None):
    """`design_diff` (§6.5): so nhánh thiết kế với `base`, ghim `diff.patch`, trả `patchPath`."""
    state = dict(job['state'] or {})
    branch = _branch_state(state)
    if not branch:
        raise _error(DESIGN_BRANCH_REQUIRED_CODE)
    diff = await rt.executor.execute('design_diff', {'base': branch['base'], 'paths': paths or None},
                                     session_id)
    files = diff.get('files') or []
    patch_path = f'{design_dir(job)}diff.patch'
    await _write_box_text(rt, session_id, patch_path, diff.get('patch') or '')
    live = rt.store.design_job(job['design_id'])
    state = dict(live['state'] or {})
    state['diff'] = {'files': files, 'patchPath': patch_path, 'at': journal.utc_now_iso()}
    updated = rt.store.design_job_save(job['design_id'], session_id, state, revision=live.get('revision'))
    return {'designId': job['design_id'], 'revision': updated['revision'], 'files': files,
            'patchPath': patch_path}


async def design_revert(rt, session_id, job, paths=None, mode='file'):
    """`design_revert` (§6.5): khôi phục tệp `insert` về `base`, xoá tệp `new`; `HEAD` không nhích.

    Chỉ những đường dẫn trong danh sách chạm đã duyệt (hoặc `.design/**`) mới được hoàn tác khi
    `mode='file'`; `mode='batch'` hoàn tác cả lô vừa ghi. Kết quả trả về gộp cả tệp khôi phục lẫn
    tệp bị xoá vào một danh sách `reverted` theo hợp đồng §6.
    """
    mode = str(mode or 'file')
    if mode not in ('file', 'batch'):
        raise ValueError("DESIGN_REVERT_INVALID: kiểu hoàn tác phải là 'file' hoặc 'batch'.")
    state = dict(job['state'] or {})
    branch = _branch_state(state)
    base = branch['base'] if branch else 'HEAD'
    scope = None
    if mode == 'file':
        scope = [str(item).strip() for item in (paths or []) if str(item).strip()]
        allowed = _approved_items(state.get('touchList'))
        for path in scope:
            if path not in allowed and not path.startswith(DESIGN_OWNED_PREFIX):
                raise _error(DESIGN_PATH_NOT_APPROVED_CODE)
        if not scope:
            return {'reverted': []}
    result = await rt.executor.execute('design_revert',
                                       {'base': base, 'paths': scope, 'mode': mode}, session_id)
    reverted = list(result.get('reverted') or []) + list(result.get('deleted') or [])
    live = rt.store.design_job(job['design_id'])
    state = dict(live['state'] or {})
    touch_list = state.get('touchList') if isinstance(state.get('touchList'), dict) else None
    if touch_list is not None:
        for item in touch_list.get('items') or []:
            if item.get('path') in set(reverted) and item.get('status') == 'written':
                item['status'] = 'approved'
                item['sha256'] = None
        state['touchList'] = touch_list
    undone = set(reverted)
    state['actions'] = [row for row in (state.get('actions') or [])
                        if row.get('path') not in undone]
    state['revert'] = {'paths': reverted, 'mode': mode, 'at': journal.utc_now_iso()}
    rt.store.design_job_save(job['design_id'], session_id, state, revision=live.get('revision'))
    return {'reverted': reverted}


# ── Canvas hai chiều (§6.4) ─────────────────────────────────────────────────


CANVAS_PROTOCOL = 'boxfox.canvas.v1'
CANVAS_NODE_KINDS = ('shape', 'card', 'webview')
CANVAS_SHAPES = ('rect', 'ellipse', 'triangle', 'diamond')
CANVAS_CARDS = ('ui-mockup', 'agent-reasoning-flow', 'directive-annotation')
CANVAS_ANCHORS = ('top', 'right', 'bottom', 'left', 'center')


def _canvas_number(value, default):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        else float(default)


def _canvas_node(value):
    """Chuẩn hoá MỘT node theo `CanvasNode` (types.ts); thiếu `id` ⇒ `None` (op sai)."""
    if not isinstance(value, dict):
        return None
    node_id = value.get('id')
    if not isinstance(node_id, str) or not node_id.strip():
        return None
    style = value.get('style') if isinstance(value.get('style'), dict) else {}
    return {'id': node_id,
            'kind': value['kind'] if value.get('kind') in CANVAS_NODE_KINDS else 'shape',
            'shape': value.get('shape') if value.get('shape') in CANVAS_SHAPES else None,
            'card': value.get('card') if value.get('card') in CANVAS_CARDS else None,
            'x': _canvas_number(value.get('x'), 0), 'y': _canvas_number(value.get('y'), 0),
            'width': _canvas_number(value.get('width'), 160),
            'height': _canvas_number(value.get('height'), 100),
            'title': str(value.get('title') or ''), 'body': str(value.get('body') or ''),
            'url': value.get('url') if isinstance(value.get('url'), str) else None,
            'style': {'fill': str(style.get('fill') or '#ffffff'),
                      'stroke': str(style.get('stroke') or '#111827'),
                      'strokeWidth': _canvas_number(style.get('strokeWidth'), 1),
                      'radius': _canvas_number(style.get('radius'), 8)}}


def _canvas_op(op):
    """Chuẩn hoá MỘT op theo `CanvasAction` (agent-protocol.ts); sai giao thức ⇒ `None`."""
    if not isinstance(op, dict):
        return None
    kind = op.get('type')
    if kind == 'CREATE_NODE':
        node = _canvas_node(op.get('node'))
        return None if node is None else {'type': 'CREATE_NODE', 'node': node}
    if kind == 'CONNECT_NODES':
        connector = op.get('connector')
        if not isinstance(connector, dict):
            return None
        source, target = connector.get('fromNodeId'), connector.get('toNodeId')
        if not (isinstance(source, str) and source and isinstance(target, str) and target):
            return None
        result = {'fromNodeId': source, 'toNodeId': target,
                  'fromAnchor': connector.get('fromAnchor') if connector.get('fromAnchor')
                  in CANVAS_ANCHORS else 'center',
                  'toAnchor': connector.get('toAnchor') if connector.get('toAnchor')
                  in CANVAS_ANCHORS else 'center',
                  'stroke': str(connector.get('stroke') or '#3b82f6'),
                  'strokeWidth': _canvas_number(connector.get('strokeWidth'), 2)}
        if isinstance(connector.get('id'), str) and connector['id']:
            result['id'] = connector['id']
        return {'type': 'CONNECT_NODES', 'connector': result}
    if kind == 'UPDATE_NODE':
        node_id = op.get('nodeId')
        if not (isinstance(node_id, str) and node_id) or not isinstance(op.get('patch'), dict):
            return None
        return {'type': 'UPDATE_NODE', 'nodeId': node_id, 'patch': dict(op['patch'])}
    if kind == 'DELETE_NODE':
        node_id = op.get('nodeId')
        return {'type': 'DELETE_NODE', 'nodeId': node_id} \
            if isinstance(node_id, str) and node_id else None
    return None


def _canvas_scene(value):
    """Chuẩn hoá MỘT cảnh (`CanvasScene`, `version:1`) từ dữ liệu chủ nhà hoặc đã lưu."""
    scene = value if isinstance(value, dict) else {}
    nodes = [node for node in (_canvas_node(raw) for raw in scene.get('nodes') or [])
             if node is not None]
    connectors = []
    for raw in scene.get('connectors') or []:
        op = _canvas_op({'type': 'CONNECT_NODES', 'connector': raw})
        if op is None:
            continue
        connector = op['connector']
        raw_id = raw.get('id') if isinstance(raw, dict) else None
        connector['id'] = raw_id if isinstance(raw_id, str) and raw_id else uuid.uuid4().hex[:12]
        connectors.append(connector)
    strokes = [dict(raw) for raw in (scene.get('strokes') or []) if isinstance(raw, dict)]
    return {'version': 1, 'nodes': nodes, 'connectors': connectors, 'strokes': strokes}


def _canvas_apply(scene, op):
    """Áp MỘT op đã chuẩn hoá lên cảnh (giống `applyCanvasAction`); không hợp lệ ⇒ `False`."""
    kind = op['type']
    if kind == 'CREATE_NODE':
        if any(node['id'] == op['node']['id'] for node in scene['nodes']):
            return False
        scene['nodes'].append(op['node'])
        return True
    if kind == 'CONNECT_NODES':
        connector = dict(op['connector'])
        ids = {node['id'] for node in scene['nodes']}
        if connector['fromNodeId'] not in ids or connector['toNodeId'] not in ids:
            return False
        connector.setdefault('id', uuid.uuid4().hex[:12])
        scene['connectors'].append(connector)
        return True
    if kind == 'UPDATE_NODE':
        for index, node in enumerate(scene['nodes']):
            if node['id'] == op['nodeId']:
                merged = {**node, **op['patch'], 'id': node['id']}
                scene['nodes'][index] = _canvas_node(merged) or merged
                return True
        return False
    if kind == 'DELETE_NODE':
        node_id = op['nodeId']
        remaining = [node for node in scene['nodes'] if node['id'] != node_id]
        if len(remaining) == len(scene['nodes']):
            return False
        scene['nodes'] = remaining
        scene['connectors'] = [row for row in scene['connectors']
                               if row['fromNodeId'] != node_id and row['toNodeId'] != node_id]
        return True
    return False


def canvas_draw(rt, session_id, job, action=None, actions=None):
    """`canvas_draw` (§6.4): áp một/một mảng op rồi phát ĐÚNG MỘT `design_canvas` gộp.

    Envelope thiếu hoặc sai kiểu ⇒ `DESIGN_CANVAS_PROTOCOL_INVALID`. Từng op kiểm riêng: op hợp lệ
    được áp và đếm vào `applied`, op sai bị BỎ và đếm vào `rejected` — không bao giờ dựng node bịa.
    Sự kiện chỉ mang các op ĐÃ áp; `sceneVersion` là bộ đếm đơn điệu của run.
    """
    if actions is None:
        if action is None:
            raise _error(DESIGN_CANVAS_PROTOCOL_INVALID_CODE)
        ops = [action]
    elif action is None and isinstance(actions, list):
        ops = actions
    else:
        raise _error(DESIGN_CANVAS_PROTOCOL_INVALID_CODE)
    if not ops:
        raise _error(DESIGN_CANVAS_PROTOCOL_INVALID_CODE)
    state = dict(job['state'] or {})
    scene = _canvas_scene(state.get('canvasScene'))
    applied, rejected = [], 0
    for raw in ops:
        op = _canvas_op(raw)
        if op is None or not _canvas_apply(scene, op):
            rejected += 1
            continue
        applied.append(op)
    seq = int(state.get('canvasSeq') or 0) + 1
    state['canvasSeq'] = seq
    state['canvasScene'] = scene
    rt.store.design_job_save(job['design_id'], session_id, state, revision=job.get('revision'))
    rt.store.emit(session_id, 'design_canvas',
                  {'designId': job['design_id'], 'seq': seq, 'actor': 'agent', 'ops': applied,
                   'sceneVersion': seq})
    return {'applied': len(applied), 'rejected': rejected, 'sceneVersion': seq}


async def persist_design_canvas(rt, session_id, job):
    """Ghi ảnh chụp cảnh vào `.design/<slug>/canvas.v1.json` (đường run tự sở hữu, duyệt ngầm).

    `canvas_draw` giữ chữ ký ĐỒNG BỘ của hợp đồng §2, nên lời gọi box nằm ở đây; tầng dispatch và
    tuyến canvas cùng gọi một chỗ để ảnh chụp bền không lệch khỏi sự kiện.
    """
    state = job['state'] if isinstance(job.get('state'), dict) else {}
    scene = state.get('canvasScene')
    if not isinstance(scene, dict):
        return None
    content = json.dumps(scene, ensure_ascii=False, separators=(',', ':'))
    path = design_canvas_path(job)
    await _write_box_text(rt, session_id, path, content)
    return path


def canvas_store_scene(rt, session_id, job, scene):
    """Lưu cảnh do CHỦ NHÀ gửi (`type:'scene'`) và phát một `design_canvas {actor:'user'}`."""
    state = dict(job['state'] or {})
    seq = int(state.get('canvasSeq') or 0) + 1
    state['canvasSeq'] = seq
    state['canvasScene'] = _canvas_scene(scene)
    updated = rt.store.design_job_save(job['design_id'], session_id, state, revision=job.get('revision'))
    rt.store.emit(session_id, 'design_canvas',
                  {'designId': job['design_id'], 'seq': seq, 'actor': 'user', 'ops': [],
                   'sceneVersion': seq})
    return updated


def canvas_queue_directive(rt, session_id, job, target_node_id, target_node_title, instruction):
    """Xếp chỉ thị canvas (`type:'directive'`) cho lượt Design Lead kế tiếp; trả bản ghi."""
    state = dict(job['state'] or {})
    directive = {'targetNodeId': str(target_node_id or ''), 'targetNodeTitle': str(target_node_title or ''),
                 'instruction': str(instruction or ''), 'at': journal.utc_now_iso()}
    state['directives'] = (state.get('directives') or []) + [directive]
    rt.store.design_job_save(job['design_id'], session_id, state, revision=job.get('revision'))
    return directive


def canvas_queued_directives(job):
    """Chỉ thị canvas đang xếp hàng của một run (khối lời dặn đọc lại)."""
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    return [row for row in (state.get('directives') or []) if isinstance(row, dict)]


# ── Lời hỏi nhiều câu (§7.3) ────────────────────────────────────────────────


def design_prompt_new(rt, session_id, job, kind, questions=None, meta=None):
    """Ghim một lời hỏi nhiều câu vào `state.prompts` rồi phát `design_prompt` (§7.2)."""
    kind = str(kind or '')
    if kind not in DESIGN_PROMPT_KINDS:
        raise ValueError(f'DESIGN_PROMPT_KIND_INVALID: kind ∈ {DESIGN_PROMPT_KINDS}, nhận {kind!r}')
    meta = meta if isinstance(meta, dict) else {}
    state = dict(job['state'] or {})
    prompt = {'promptId': f'dp-{uuid.uuid4().hex[:12]}', 'designId': job['design_id'], 'kind': kind,
              'revision': int(job['revision'] or 0), 'status': 'open',
              'createdAt': journal.utc_now_iso(), 'questions': list(questions or []),
              'actions': ['chooseExit'] if kind == 'exit-choice' else ['start', 'answer'],
              'note': str(meta.get('note') or '')}
    prompts = [item for item in (state.get('prompts') or [])
               if item.get('promptId') != prompt['promptId']]
    prompts.append(prompt)
    state['prompts'] = prompts
    rt.store.design_job_save(job['design_id'], session_id, state, revision=job.get('revision'))
    rt.store.emit(session_id, 'design_prompt',
                  {'promptId': prompt['promptId'], 'designId': job['design_id'], 'kind': kind,
                   'status': 'open'})
    return prompt


def design_prompt_row(job, prompt_id):
    """Lời hỏi trong `state.prompts` theo id, hoặc `None`."""
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    wanted = str(prompt_id)
    return next((item for item in (state.get('prompts') or [])
                 if isinstance(item, dict) and str(item.get('promptId')) == wanted), None)


def design_prompt_answer(rt, session_id, prompt_id, answers, *, start=False):
    """Trả lời MỘT lời hỏi nhiều câu trong MỘT lần gọi (§7.3).

    Câu trả lời thành mục `confirmed` của brief; `start=true` rời `needs_user` và mở lượt tiếp tục.
    """
    job = rt.store.design_job_by_prompt(prompt_id)
    if job is None or job['session_id'] != session_id:
        raise ValueError('DESIGN_PROMPT_UNKNOWN: no such prompt on this session')
    prompt = design_prompt_row(job, prompt_id)
    if prompt is None:
        raise ValueError('DESIGN_PROMPT_UNKNOWN: no such prompt on this run')
    if prompt.get('status') == 'answered':
        raise ValueError('DESIGN_PROMPT_ANSWERED: that prompt is already answered')
    state = dict(job['state'] or {})
    brief = dict(state.get('brief') or {})
    resolved = []
    for answer in (answers or []):
        if not isinstance(answer, dict):
            continue
        qid = str(answer.get('questionId') or '')
        text = str(answer.get('text') or '').strip()
        option = str(answer.get('optionId') or '').strip()
        label = next((label for oid, label in QUESTION_OPTIONS.get(qid, []) if oid == option), option)
        value = text or label
        field = QUESTION_FIELD.get(qid)
        if field and value:
            brief[field] = {'text': value, 'status': 'confirmed', 'source': {'kind': 'user'}}
        resolved.append({'questionId': qid, 'optionId': option or None, 'text': text or None})
    prompt['status'] = 'answered'
    prompt['answers'] = resolved
    prompt['answeredAt'] = journal.utc_now_iso()
    prompts = [item for item in (state.get('prompts') or [])
               if item.get('promptId') != prompt_id]
    prompts.append(prompt)
    state['prompts'] = prompts
    state['brief'] = brief
    status = job['status']
    if start:
        status = 'designing'
        state['phase'] = 'briefing'
        history = list(state.get('phaseHistory') or [])
        history.append({'phase': 'briefing', 'at': journal.utc_now_iso(), 'reason': 'prompt-answered'})
        state['phaseHistory'] = history
    updated = rt.store.design_job_save(job['design_id'], session_id, state, status=status,
                                       revision=job.get('revision'))
    rt.store.emit(session_id, 'design_prompt',
                  {'promptId': prompt_id, 'designId': job['design_id'], 'kind': prompt.get('kind'),
                   'status': 'answered'})
    rt.store.emit(session_id, 'design_scope',
                  {'designId': job['design_id'], 'revision': updated['revision']})
    return {'designId': job['design_id'], 'promptId': prompt_id, 'status': prompt['status'],
            'revision': updated['revision'], 'start': bool(start), 'resume': bool(start)}


# ── Bàn giao (§7.4, §4) ─────────────────────────────────────────────────────


def design_handoff_block(rt, session_id, job, version=None):
    """Khối bàn giao design → main, hoặc `None` khi chưa có gì để bàn giao.

    P1 chưa có hồ sơ soát độc lập (P4), nên hàm trả `None` cho tới khi run có `report` đã soát — một
    chỗ dựng khối, P4 chỉ điền thêm dữ liệu vào cùng cặp mốc.
    """
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    report = state.get('report') if isinstance(state.get('report'), dict) else None
    if not report or not report.get('path'):
        return None
    version = version or report.get('version')
    lines = [DESIGN_HANDOFF_BLOCK_MARKER,
             f'Design run {job["design_id"]} handed off at version {version}.',
             f'Report: {report.get("path")}']
    if state.get('touchList'):
        lines.append(f'Touch list revision: {state["touchList"].get("revision")}; '
                     f'branch: {(state["touchList"].get("branch") or {}).get("name")}')
    lines.append('Rule: build from the handed-off design; do not raise its confidence.')
    lines.append(DESIGN_HANDOFF_BLOCK_END)
    return '\n'.join(lines)


def mark_design_handoff_delivered(rt, session_id, design_id, version):
    """Ghim bản thiết kế đã bàn giao — lượt main kế tiếp không nhắc lại cùng một bản (§4)."""
    session = rt.store.get(session_id)
    runtime_module = _mode_mod()
    mode = dict(runtime_module.design_mode(session))
    delivered = dict(mode.get('handoffDeliveredVersion') or {})
    delivered[str(design_id)] = str(version)
    mode['handoffDeliveredVersion'] = delivered
    session.setdefault('config', {})[runtime_module.DESIGN_MODE_CONFIG_KEY] = mode
    rt.store.update_config(session_id, session['config'])
    return mode
