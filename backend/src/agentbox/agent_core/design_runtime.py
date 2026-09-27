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
import posixpath
import re
import uuid

from . import journal
from .limits import (
    DESIGN_ACTIVE_STATUSES, DESIGN_ERROR_TEXT, DESIGN_EXIT_CHOICE_REQUIRED_CODE,
    DESIGN_HANDOFF_BLOCK_END, DESIGN_HANDOFF_BLOCK_MARKER, DESIGN_HARD_FORBIDDEN,
    DESIGN_BRANCH_REQUIRED_CODE, DESIGN_CANVAS_PROTOCOL_INVALID_CODE,
    DESIGN_DIFF_DIRTY_BASE_CODE, DESIGN_HANDOFF_UNREVIEWED_CODE, DESIGN_INTERVIEW_IDS,
    DESIGN_INTERVIEW_MAX_QUESTIONS, DESIGN_MODE_EVENT_CODE, DESIGN_OWNED_PREFIX,
    DESIGN_PATH_NOT_APPROVED_CODE, DESIGN_PHASES, DESIGN_PROMPT_KINDS,
    DESIGN_REVIEW_NO_CRITIC_CODE, DESIGN_REVIEW_VERDICT_MISMATCH_CODE,
    DESIGN_REVIEW_VERDICT_MISSING_CODE, DESIGN_STATUSES, DESIGN_STEPS,
    DESIGN_TERMINAL_STATUSES, DESIGN_TOUCH_KINDS, DESIGN_TOUCH_LIST_REQUIRED_CODE,
    DESIGN_TOUCH_LIST_REVISION_STALE_CODE, DESIGN_TOUCH_STATUSES, DESIGN_WRITE_STALE_CODE,
    PLAN_REVIEW_MIN_ANSWER_CHARS,
)

# `DESIGN_PHASES`/`DESIGN_STATUSES` chỉ có mặt ở đây để TÁI XUẤT: hợp đồng §2 chốt chúng là thuộc
# tính của mô-đun này (`design_runtime.DESIGN_PHASES`), còn luật đọc chúng nằm ở `limits`.

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
                      'design_revert', 'canvas_draw', 'design_review', 'design_report')

#: P4 (§7.9): cổng provenance của một kết luận soát độc lập. Bản soát phải là con `plan-review`
#: đã XONG, đã đọc đủ dài (`PLAN_REVIEW_MIN_ANSWER_CHARS`, cùng trần với bản soát plan — không có
#: lý do để bản thiết kế chịu một trần khác), sinh SAU khi run mở, và mang `reviewTarget` đúng
#: `(designId, version)`. Dòng `VERDICT:` đọc từ dòng CUỐI có chữ (khuôn `research_critique`).
DESIGN_REVIEW_SUMMARY_CHARS = 800
DESIGN_REPORT_SUMMARY_CHARS = 1200

#: Nhãn `labels` của `design_report` → vào thẻ báo cáo/handoff. `partial` còn đổi cả status.
DESIGN_PARTIAL_LABEL = 'partial'

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
        was_on = bool(mode.get('on'))
        mode = {**mode, 'on': True,
                'since': mode.get('since') or journal.utc_now_iso(),
                'enteredBy': entered if not was_on else mode.get('enteredBy') or entered,
                'revision': int(mode.get('revision') or 0) + 1}
        if not was_on:
            # §2/§5.1: `entrySeq` = mốc sự kiện lúc BẬT mode (khuôn `research._set_mode`), để giao
            # diện neo dải trạng thái vào đúng chỗ chế độ bắt đầu.
            tail = rt.store.events_tail(session_id, 1)
            mode['entrySeq'] = int(tail[-1]['seq']) if tail else 0
        if job is not None:
            mode['activeRunId'] = job['design_id']
            state = dict(job['state'] or {})
            if state.get('background'):
                state['background'] = False
                rt.store.design_job_save(job['design_id'], session_id, state)
            # §7.3: bật lại mode đóng lời hỏi `exit-choice` còn sót của run — thẻ thoát cũ không được
            # sống qua một lần bật khác.
            _close_exit_prompt(rt, session_id, rt.store.design_job(job['design_id']))
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
            paused = rt.store.design_job_save(job['design_id'], session_id, state, 'paused')
            rt.store.emit(session_id, 'design_run', design_job_event(paused))
            notify_run(rt, session_id, paused)
        else:
            state['background'] = True
            rt.store.design_job_save(job['design_id'], session_id, state)
            rt.store.emit(session_id, 'design_run', design_job_event(
                rt.store.design_job(job['design_id'])))
        # §7.3: lựa chọn đã được ÁP ⇒ đóng lời hỏi `exit-choice` còn mở; nếu không, `refresh` dựng lại
        # thẻ thoát ngay sau khi chủ nhà vừa quyết.
        _close_exit_prompt(rt, session_id, rt.store.design_job(job['design_id']))
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


def batch_payload(state):
    """Lô ghi của một run từ `state['diff']` (`{files, patchPath, at}`, §6.5) — khoá `batch` (§6).

    `None` khi chưa có `design_diff` nào (frontend hiểu `null` là chưa có lô). `status` đọc từ mốc
    admin đã ghim (`batchApprovedAt`/`batchRevertedAt`), không phải từ phỏng đoán của giao diện.
    """
    state = state if isinstance(state, dict) else {}
    diff = state.get('diff') if isinstance(state.get('diff'), dict) else None
    if not diff or not (diff.get('patchPath') or diff.get('files')):
        return None
    files = [row for row in (diff.get('files') or []) if isinstance(row, dict)]
    revert = state.get('revert') if isinstance(state.get('revert'), dict) else {}
    if revert.get('mode') == 'batch':
        status = 'reverted'
    elif state.get('batchApprovedAt'):
        status = 'approved'
    else:
        status = 'proposed'
    return {'index': 0, 'total': 1, 'status': status,
            'revision': 0, 'patchPath': diff.get('patchPath'),
            'added': sum(int(row.get('added') or 0) for row in files),
            'removed': sum(int(row.get('removed') or 0) for row in files),
            'files': files}


def review_payload(state):
    """Kết luận soát độc lập gần nhất của một run — khoá `review` (§6), hoặc `None`.

    Hợp đồng backend là `ok`/`revise` (§7.6), nhưng CẶP GIÁ TRỊ ĐÃ ĐÓNG BĂNG CỦA GIAO DIỆN là
    `passed`/`changes` (`frontend/src/lib/designMode.ts`, `DesignPanel.tsx`). Một chỗ dịch: phát
    ra đúng cặp giao diện đang đọc.
    """
    state = state if isinstance(state, dict) else {}
    review = state.get('review') if isinstance(state.get('review'), dict) else None
    if not review or not review.get('verdict'):
        return None
    return {'version': str(review.get('version') or ''),
            'verdict': 'passed' if review.get('verdict') == 'ok' else 'changes',
            'summary': str(review.get('summary') or '')}


def design_run_payload(job, with_canvas=False):
    """Bản camelCase của một hàng `design_jobs` cho API (hợp đồng §5, §6).

    `with_canvas=True` (chỉ tuyến CHI TIẾT) mang thêm `canvasScene` + `canvasSeq`: tải lại trang là
    thấy đúng cảnh đang có, không phụ thuộc việc phát lại sự kiện `design_canvas`. Danh sách run cố ý
    KHÔNG mang cảnh — nó bị gọi lại mỗi vòng đồng bộ, và một cảnh vài chục node nhân mỗi vòng là lãng
    phí không đổi lại được gì.
    """
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    touch_list = state.get('touchList') if isinstance(state.get('touchList'), dict) else None
    batch = batch_payload(state)
    if batch is not None:
        batch['revision'] = int(job.get('revision') or 0)
    return {'designId': job.get('design_id'), 'sessionId': job.get('session_id'),
            'status': job.get('status'), 'revision': int(job.get('revision') or 0),
            'phase': state.get('phase'), 'origin': state.get('origin'),
            'background': bool(state.get('background')),
            'step': PHASE_STEP.get(str(state.get('phase') or ''), 'clarify'),
            'goal': state.get('goal'), 'brief': state.get('brief') or {},
            'touchList': touch_list, 'prompts': state.get('prompts') or [],
            'phaseHistory': state.get('phaseHistory') or [], 'actions': state.get('actions') or [],
            'touchListRevision': int((touch_list or {}).get('revision') or 0),
            'batch': batch, 'review': review_payload(state),
            **({'canvasScene': _canvas_scene(state.get('canvasScene')),
                'canvasSeq': int(state.get('canvasSeq') or 0),
                # Hàng cũ (ghi trước khi có khoá này) đọc ra `'agent'`: mọi đường gieo/vẽ đều đi
                # qua `canvas_draw`, nên đó là chủ nhân ĐÚNG của một cảnh đã có sẵn.
                'canvasActor': str(state.get('canvasActor') or 'agent')} if with_canvas else {})}


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
    """Đóng một run: ghim `status` + pha `done`, đóng prompt còn mở, nhả `activeRunId` rồi phát tin.

    `design_notice` đi qua CÙNG gác `state.notified` như `notify_run` (§7.2/§12: mỗi loại nhắc chỉ
    nói một lần cho mỗi run) — nếu không, một run đã bị nhắc `blocked` lúc tạm dừng mà sau đó bị huỷ
    sẽ nhắc `blocked` lần thứ hai.
    """
    state = dict(job['state'] or {})
    state['stopReason'] = str(reason or '')
    kind = 'background-done' if state.get('background') else 'blocked'
    notified = dict(state.get('notified') or {})
    fresh_notice = not notified.get(kind)
    if fresh_notice:
        notified[kind] = journal.utc_now_iso()
    state['notified'] = notified
    updated = rt.store.design_job_save(job['design_id'], session_id, state, status=status,
                                       revision=revision)
    updated = set_phase(rt, session_id, updated, PHASE_DONE, reason, force=True) or updated
    # Huỷ run thì không được để prompt nào còn `open`: prompt mở sót là đường hồi sinh run đã đóng.
    _close_open_prompts(rt, session_id, updated)
    if fresh_notice:
        rt.store.emit(session_id, 'design_notice',
                      {'designId': job['design_id'], 'kind': kind})
    release_active_run(rt, session_id, job['design_id'])
    return updated


def _close_open_prompts(rt, session_id, job):
    """Ghim `status:'closed'` cho mọi prompt còn `open` của run; trả `True` khi có prompt phải đóng.

    Prompt mở sót sau khi run đã đóng là đường hồi sinh run (§7.2): `design_prompt_answer` vẫn tìm
    thấy prompt ấy và có thể nhích run về `briefing`.
    """
    state = dict(job.get('state') or {})
    prompts = state.get('prompts')
    if not isinstance(prompts, list):
        return False
    changed = False
    now = journal.utc_now_iso()
    for prompt in prompts:
        if isinstance(prompt, dict) and prompt.get('status') == 'open':
            prompt['status'] = 'closed'
            prompt['closedAt'] = now
            changed = True
    if changed:
        state['prompts'] = prompts
        rt.store.design_job_save(job['design_id'], session_id, state, revision=job.get('revision'))
    return changed


def _close_exit_prompt(rt, session_id, job):
    """Đóng lời hỏi `exit-choice` còn mở khi chủ nhà ĐÃ quyết (§7.3); `True` khi có prompt phải đóng.

    `designStore.refresh()` dựng lại thẻ thoát từ BẤT KỲ lời hỏi `exit-choice` còn `open` của run,
    nên một lời hỏi mở sót sau khi lựa chọn đã được áp sẽ làm thẻ quay lại đúng lúc chủ nhà vừa quyết
    (và lần tắt mode sau đó không gửi gì nữa). Chỉ đóng ĐÚNG loại `exit-choice`; lời hỏi khác
    (`interview`/`out-of-scope`) KHÔNG bị chạm. Ghi `answered` kèm một `design_prompt` — trạng thái ấy
    là thứ giao diện hiểu là đã xử lý (`'closed'` bị nó chuẩn hoá ngược về `open`), và lưu lại hàng
    (nhích `revision`) để lần `refresh` kế tiếp không còn thấy lời hỏi mở.
    """
    state = dict(job.get('state') or {})
    prompts = state.get('prompts')
    if not isinstance(prompts, list):
        return False
    closed = []
    now = journal.utc_now_iso()
    for prompt in prompts:
        if (isinstance(prompt, dict) and prompt.get('kind') == 'exit-choice'
                and prompt.get('status') == 'open'):
            prompt['status'] = 'answered'
            prompt['answeredAt'] = now
            closed.append(prompt['promptId'])
    if not closed:
        return False
    state['prompts'] = prompts
    rt.store.design_job_save(job['design_id'], session_id, state, revision=job.get('revision'))
    for prompt_id in closed:
        rt.store.emit(session_id, 'design_prompt',
                      {'promptId': prompt_id, 'designId': job['design_id'], 'kind': 'exit-choice',
                       'status': 'answered'})
    return True


def notify_run(rt, session_id, job):
    """Phát ĐÚNG MỘT `design_notice` khi run chạm một trạng thái đáng nhắc (§6.3, §7.2).

    Ba loại: `background-done` (run nền tới pha ĐÓNG), `needs-user` (run dừng chờ chủ nhà) và
    `blocked` (run bị tạm dừng). Gác bằng `state.notified[<kind>]` — mỗi lần nhắc chỉ nói một lần
    cho mỗi run, nên một vòng bơm gọi lại không nhân thông báo. Trả hàng job sau khi ghim mốc, hoặc
    `None` khi không có gì để nhắc.
    """
    state = dict(job['state'] or {})
    status = str(job.get('status') or '')
    terminal = status in DESIGN_TERMINAL_STATUSES or str(state.get('phase') or '') == PHASE_DONE
    if bool(state.get('background')) and terminal:
        kind = 'background-done'
    elif status == 'needs_user':
        kind = 'needs-user'
    elif status == 'paused':
        kind = 'blocked'
    else:
        return None
    notified = dict(state.get('notified') or {})
    if notified.get(kind):
        return None
    notified[kind] = journal.utc_now_iso()
    state['notified'] = notified
    updated = rt.store.design_job_save(job['design_id'], session_id, state,
                                       revision=job.get('revision'))
    rt.store.emit(session_id, 'design_notice', {'designId': job['design_id'], 'kind': kind})
    return updated


def release_active_run(rt, session_id, design_id):
    """Nhả `designMode.activeRunId` khi run đã đóng — chế độ vẫn bật, nhưng không còn run nào sống.

    Không nhả thì lượt main sau vẫn nghĩ run đang hoạt động (`design_job_pumpable`, khối mode) và
    chặn mở run mới.
    """
    runtime_module = _mode_mod()
    session = rt.store.get(session_id)
    if session is None:
        return None
    mode = dict(runtime_module.design_mode(session))
    if str(mode.get('activeRunId') or '') != str(design_id):
        return mode
    mode['activeRunId'] = ''
    config = dict(session.get('config') or {})
    config[runtime_module.DESIGN_MODE_CONFIG_KEY] = mode
    rt.store.update_config(session_id, config)
    return mode


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


def _last_user_request(rt, session_id):
    """Tin nhắn GẦN NHẤT của chủ nhà — thứ nút "Tạm thoát" nộp lại (§5.9, IF-2)."""
    session = rt.store.get(session_id) or {}
    for row in reversed(session.get('messages') or []):
        if isinstance(row, dict) and str(row.get('role') or '') == 'user':
            text = str(row.get('content') or '').strip()
            if text:
                return text
    return ''


def design_scope(rt, session_id, job, action, patch=None, questions=None, kind=None):
    """`design_scope` (§7.1): `propose`/`update` ghép brief, `ask` mở một lời hỏi.

    `ask` mặc định mở lời hỏi `interview`; `kind='out-of-scope'` mở thẻ ngoài phạm vi (§5.9) với
    hai lựa chọn ghim `exit`/`keep` và `meta.request` là tin nhắn gốc của chủ nhà.

    `update` với `patch.revision` là khoá lạc quan so với `design_jobs.revision` SỐNG: lệch ⇒
    `DESIGN_TOUCH_LIST_REVISION_STALE` (không ghi gì).
    """
    action = str(action or '').strip().lower()
    if action not in ('propose', 'ask', 'update'):
        raise ValueError(f'DESIGN_SCOPE_ACTION_INVALID: action ∈ (propose, ask, update), '
                         f'nhận {action!r}')
    state = dict(job['state'] or {})
    if action == 'ask':
        wanted = str(kind or '').strip().lower()
        if wanted == 'out-of-scope':
            patch = patch if isinstance(patch, dict) else {}
            request = str(patch.get('request') or patch.get('note') or '').strip() \
                or _last_user_request(rt, session_id)
            prompt = design_prompt_new(rt, session_id, job, 'out-of-scope',
                                       questions=questions, meta={'request': request})
            return {'designId': job['design_id'], 'revision': prompt['revision'],
                    'phase': state.get('phase'), 'promptId': prompt['promptId']}
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
    # §6.3: duyệt cả danh sách là một câu trả lời — run RỜI `needs_user` và mở lượt tiếp tục.
    updated = rt.store.design_job_save(job['design_id'], session_id, state,
                                       status='designing' if job['status'] == 'needs_user' else None,
                                       revision=job.get('revision'))
    rt.store.emit(session_id, 'design_scope',
                  {'designId': job['design_id'], 'revision': updated['revision']})
    # P1: canvas phải có nghĩa NGAY lúc bắt đầu vẽ. Duyệt danh sách chạm là thời điểm đầu tiên run có
    # đủ dữ liệu thật (brief + các mục sẽ chạm), nên cảnh khởi đầu được gieo ở đây — vẫn là op của
    # `actor:'agent'`, vẫn đi qua `canvas_draw`, không có đường vẽ tắt nào.
    seeded = canvas_seed_from_run(rt, session_id, updated)
    set_phase(rt, session_id, updated, 'drawing', 'touch-list-approved')
    result = {'designId': job['design_id'], 'revision': touch_list['revision'],
              'approved': approved, 'approvedAt': touch_list['approvedAt']}
    if seeded is not None:
        result['canvasOps'] = seeded.get('applied')
        result['canvasRejected'] = seeded.get('rejected')
    return result


# ── Đường ghi có gác (§6.5) ─────────────────────────────────────────────────


def design_dir(job):
    """`.design/<slug>/` — thư mục do run tự sở hữu."""
    return f'{DESIGN_OWNED_PREFIX}{_slug(job["design_id"])}/'


def design_canvas_path(job):
    """Đường dẫn ảnh chụp cảnh của run (hợp đồng §7.5)."""
    return f'{design_dir(job)}canvas.v1.json'


#: Mã hợp đồng nằm ở ĐẦU câu lỗi của worker (`'DESIGN_X: câu'`) — dùng để dựng lại lỗi chuẩn.
_DESIGN_CODE_RE = re.compile(r'(DESIGN_[A-Z0-9_]+)')


async def _box_op(rt, session_id, name, args):
    """Gọi MỘT op worker của đường thiết kế rồi quy lỗi của box về mã hợp đồng (§7.6).

    Qua box THẬT (`sandbox/executor.py`), `_execute` trả payload của worker NGUYÊN VĂN, nên một op bị
    chối về dưới dạng `{'is_error': True, 'error': 'MÃ: câu'}` thay vì NÉM. Chỗ gọi cũ cứ đánh chỉ số
    `result['path']`/`result['branch']`/`result['sha256']` ⇒ `KeyError` và lượt chết với
    `TURN_FAILED_KEYERROR`, còn mã hợp đồng (và câu `DESIGN_ERROR_TEXT`) không bao giờ ra tới chủ nhà.
    Ở đây đọc mã ở đầu câu của worker rồi ném lại ĐÚNG khuôn `MÃ: câu`; câu KHÔNG có mã hợp đồng đã
    biết thì giữ NGUYÊN VĂN (không bao giờ nuốt lỗi) và bản thân câu ấy vẫn là một `ValueError`.
    """
    result = await rt.executor.execute(name, args, session_id)
    if not (isinstance(result, dict) and result.get('is_error')):
        return result
    message = str(result.get('error') or '').strip()
    match = _DESIGN_CODE_RE.match(message)
    if match and match.group(1) in DESIGN_ERROR_TEXT:
        raise _error(match.group(1))
    raise ValueError(message or f'{name}: op trong box thất bại')


async def _box_file_sha(rt, session_id, path):
    """Băm TOÀN BỘ tệp trong box qua op `design_file_sha`; `None` khi chưa có/không đọc được.

    `file_read` cắt ở 30 000 ký tự, nên băm của `content` không bao giờ khớp băm full-file mà
    `design_write` ghim cho tệp dài — đó là `DESIGN_WRITE_STALE` OAN. Cổng stale đọc băm của CẢ
    tệp qua op riêng; op ấy ném khi tệp thiếu, ở đây nuốt thành `None` — đúng nghĩa "chưa có tệp"
    cho nhánh `create`.
    """
    try:
        result = await _box_op(rt, session_id, 'design_file_sha', {'path': path})
    except (ValueError, OSError):
        return None
    value = result.get('sha256') if isinstance(result, dict) else None
    return value if isinstance(value, str) and value else None


async def _write_box_text(rt, session_id, path, content):
    """Ghi một tệp trong box qua op `file_write` (đường `.design/**` do run sở hữu)."""
    return await _box_op(rt, session_id, 'file_write', {'path': path, 'content': content})


def _branch_state(state):
    branch = state.get('branch') if isinstance(state.get('branch'), dict) else {}
    return branch if str(branch.get('base') or '').strip() else {}


def _design_target_path(value):
    """Đường dẫn tương đối CHUẨN của một tham số `path` (§6.5), hoặc chối bằng mã hợp đồng.

    Lớp gác của harness phải quyết định trên ĐÚNG chuỗi mà worker sẽ `resolve()`: trước đây tiền
    tố `.design/` xét trên chuỗi THÔ nên `'.design/../src/App.tsx'` vừa "thuộc run" (bỏ qua cả
    danh sách chạm lẫn cổng nhánh) vừa `resolve()` ra `src/App.tsx` — ghi thẳng vào dự án. Ở đây:
    bỏ khoảng trắng, chối đường dẫn tuyệt đối/mọi đốt `..`/ký tự `\\`, rồi `normpath` về dạng posix.
    """
    text = str(value or '').strip()
    if not text or text.startswith('/') or '\\' in text:
        raise _error(DESIGN_PATH_NOT_APPROVED_CODE)
    normalized = posixpath.normpath(text)
    if normalized in ('.', '..') or normalized.startswith('../'):
        raise _error(DESIGN_PATH_NOT_APPROVED_CODE)
    return normalized


def _is_hard_forbidden(path):
    """Danh sách đen cứng áp theo TIỀN TỐ thư mục, không chỉ so khớp nguyên chuỗi (§6.5).

    `.git/` phải chặn cả `.git/config`: nếu không, mục `.git/` chỉ khớp đúng chuỗi `.git/` còn
    `.git/config` lọt qua phép so nguyên chuỗi và worker ghi được tệp bên trong `.git/`.
    """
    for entry in DESIGN_HARD_FORBIDDEN:
        if path == entry or path.startswith(entry) or path.startswith(entry.rstrip('/') + '/'):
            return True
    return False


def _batch_revert_paths(state):
    """Đường dẫn của LÔ ghi đã ghim (`state.diff.files`, dự phòng `state.actions`) (§6.5).

    Chỉ đường của DỰ ÁN: `.design/**` là đồ của run, không phải lô cần hoàn tác. Danh sách rỗng
    nghĩa là chưa có lô nào — `revert-batch` không được quét cả cây.
    """
    diff = state.get('diff') if isinstance(state.get('diff'), dict) else {}
    rows = [row.get('path') for row in (diff.get('files') or []) if isinstance(row, dict)]
    if not any(str(value or '').strip() for value in rows):
        rows = [row.get('path') for row in (state.get('actions') or []) if isinstance(row, dict)]
    out = []
    for value in rows:
        text = _design_target_path(value) if str(value or '').strip() else ''
        if not text or text.startswith(DESIGN_OWNED_PREFIX) or text in out:
            continue
        out.append(text)
    return out


def _approved_items(touch_list):
    return {item.get('path') for item in (touch_list or {}).get('items') or []
            if item.get('status') in ('approved', 'written')}


async def design_branch_create(rt, session_id, job, name):
    """`design_branch_create` (§6.5): tạo nhánh thiết kế từ `HEAD` và ghim `base` sha vào run.

    Cây làm việc còn thay đổi chưa lưu của chủ nhà ⇒ `DESIGN_DIFF_DIRTY_BASE` (không tạo nhánh trên
    một nền bẩn). Việc dựng lệnh git nằm trong worker; lỗi worker (`DESIGN_MAIN_BRANCH_FORBIDDEN`,
    `DESIGN_BRANCH_EXISTS`, `DESIGN_WORKSPACE_NOT_REPO`) đi thẳng ra ngoài.
    """
    dirty = await _box_op(rt, session_id, 'design_diff', {'base': 'HEAD', 'paths': None})
    if (dirty.get('files') if isinstance(dirty, dict) else None):
        raise _error(DESIGN_DIFF_DIRTY_BASE_CODE)
    result = await _box_op(rt, session_id, 'design_branch_create', {'name': str(name or '')})
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
    normalized = _design_target_path(path)
    if _is_hard_forbidden(normalized):
        raise _error(DESIGN_PATH_NOT_APPROVED_CODE)
    owned = normalized.startswith(DESIGN_OWNED_PREFIX)
    entry = next((item for item in touch_list.get('items') or []
                  if item.get('path') == normalized), None)
    if not owned and (entry is None or entry.get('status') not in ('approved', 'written')):
        raise _error(DESIGN_PATH_NOT_APPROVED_CODE)
    if not owned and not _branch_state(state):
        raise _error(DESIGN_BRANCH_REQUIRED_CODE)

    # §6.5: `insert` đã ghim băm ⇒ phải đối chiếu băm của CẢ tệp (xem `_box_file_sha`).
    before_sha = await _box_file_sha(rt, session_id, normalized)
    if (entry is not None and entry.get('sha256') and mode == 'insert'
            and before_sha != entry['sha256']):
        raise _error(DESIGN_WRITE_STALE_CODE)

    write_args = {'path': normalized, 'content': content, 'mode': mode}
    if anchor is not None:
        write_args['anchor'] = anchor
    if position is not None:
        write_args['position'] = position
    result = await _box_op(rt, session_id, 'design_write', write_args)

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
              'sha256Before': before_sha, 'sha256After': result['sha256'],
              'bytes': result.get('bytes'), 'reason': reason,
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
    diff = await _box_op(rt, session_id, 'design_diff',
                         {'base': branch['base'], 'paths': paths or None})
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
    if mode == 'file':
        # Quy về đường dẫn chuẩn TRƯỚC khi đối chiếu danh sách chạm — xem `_design_target_path`.
        scope = [_design_target_path(item) for item in (paths or []) if str(item or '').strip()]
        allowed = _approved_items(state.get('touchList'))
        for path in scope:
            if path not in allowed and not path.startswith(DESIGN_OWNED_PREFIX):
                raise _error(DESIGN_PATH_NOT_APPROVED_CODE)
        if not scope:
            return {'reverted': []}
    else:
        # §6.5: cổng nhánh như đường ghi; phạm vi = ĐÚNG lô đã ghim, không quét cả cây.
        if not branch:
            raise _error(DESIGN_BRANCH_REQUIRED_CODE)
        scope = _batch_revert_paths(state)
        if not scope:
            return {'reverted': []}
    result = await _box_op(rt, session_id, 'design_revert', {'base': base, 'paths': scope, 'mode': mode})
    reverted = list(result.get('reverted') or []) + list(result.get('deleted') or [])
    # Đọc lại state MỚI NHẤT rồi mới gộp: cửa sổ giữa `execute` và đây có thể có lượt khác đã ghi
    # thêm `diff`/`prompts`/`reviews`; chép đè bằng state cũ sẽ nuốt mất chúng.
    live = rt.store.design_job(job['design_id'])
    fresh = dict(live['state'] or {})
    touch_list = fresh.get('touchList') if isinstance(fresh.get('touchList'), dict) else None
    if touch_list is not None:
        for item in touch_list.get('items') or []:
            if item.get('path') in set(reverted) and item.get('status') == 'written':
                item['status'] = 'approved'
                item['sha256'] = None
        fresh['touchList'] = touch_list
    undone = set(reverted)
    fresh['actions'] = [row for row in (fresh.get('actions') or [])
                        if row.get('path') not in undone]
    fresh['revert'] = {'paths': reverted, 'mode': mode, 'at': journal.utc_now_iso()}
    rt.store.design_job_save(job['design_id'], session_id, fresh, revision=live.get('revision'))
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
    # Ai vừa ghi cảnh: hàng `design_jobs` là nguồn duy nhất còn lại khi cửa sổ sự kiện đã trôi
    # (tải lại trang), nên tuyến chi tiết phải nói được cảnh ấy của AGENT hay của CHỦ NHÀ.
    state['canvasActor'] = 'agent'
    rt.store.design_job_save(job['design_id'], session_id, state, revision=job.get('revision'))
    rt.store.emit(session_id, 'design_canvas',
                  {'designId': job['design_id'], 'seq': seq, 'actor': 'agent', 'ops': applied,
                   'scene': scene, 'sceneVersion': seq})
    return {'applied': len(applied), 'rejected': rejected, 'sceneVersion': seq}


def canvas_scene_has_nodes(job):
    """Cảnh canvas trong hàng run đã có node nào chưa.

    Tuyến duyệt danh sách chạm dùng hàm này để quyết định ghim ảnh chụp: cảnh ĐÃ có nội dung thì ảnh
    chụp phải được ghi kể cả khi lượt duyệt này không thêm op nào (một lần ghi hỏng trước đó không
    được để ảnh chụp mất hẳn — cơ sở dữ liệu đã giữ cảnh, tệp chỉ là bản soi).
    """
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    scene = state.get('canvasScene') if isinstance(state.get('canvasScene'), dict) else {}
    return any(isinstance(raw, dict) for raw in (scene.get('nodes') or []))


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
    """Lưu cảnh do CHỦ NHÀ gửi (`type:'scene'`) và phát một `design_canvas {actor:'user'}`.

    IF-1: sự kiện mang luôn `scene` ĐÃ RÚT GỌN như lúc lưu trong `state.canvasScene` — sửa của chủ
    nhà đi với `ops: []`, nên thiếu `scene` thì client không dựng lại được và báo oan các op sau của
    agent là bị chối.
    """
    state = dict(job['state'] or {})
    seq = int(state.get('canvasSeq') or 0) + 1
    stored = _canvas_scene(scene)
    state['canvasSeq'] = seq
    state['canvasScene'] = stored
    state['canvasActor'] = 'user'
    updated = rt.store.design_job_save(job['design_id'], session_id, state, revision=job.get('revision'))
    rt.store.emit(session_id, 'design_canvas',
                  {'designId': job['design_id'], 'seq': seq, 'actor': 'user', 'ops': [],
                   'scene': stored, 'sceneVersion': seq})
    return updated


#: Trần số mục danh sách chạm gieo lên canvas — canvas để ĐỌC, không phải bảng dữ liệu.
CANVAS_SEED_ITEMS_MAX = 8

#: Id ổn định của hai node khung, để lần gieo sau (và agent) cập nhật đúng node thay vì tạo trùng.
CANVAS_SEED_WORKSPACE_ID = 'seed-workspace'
CANVAS_SEED_SCREEN_ID = 'seed-screen'


def _brief_text(brief, key):
    """Chữ của một mục brief — nhận cả dạng chuỗi, dạng `{'text': ...}` (câu trả lời §7.2) lẫn mảng."""
    value = (brief or {}).get(key)
    if isinstance(value, dict):
        return str(value.get('text') or value.get('value') or '').strip()
    if isinstance(value, list):
        return '; '.join(str(item).strip() for item in value if str(item).strip())
    return str(value or '').strip()


def _seed_card(node_id, x, y, width, height, card, title, body):
    """Một node `card` của cảnh gieo — màu lấy đúng bảng màu của canvas (`index.css`)."""
    return {'id': node_id, 'kind': 'card', 'shape': None, 'card': card, 'x': x, 'y': y,
            'width': width, 'height': height, 'title': title, 'body': body, 'url': None,
            'style': {'fill': '#121212', 'stroke': '#262626', 'strokeWidth': 1, 'radius': 12}}


def _seed_link(from_node_id, to_node_id):
    """Một nét nối của cảnh gieo — cùng kiểu nét với mọi mũi tên khác trên canvas."""
    return {'type': 'CONNECT_NODES', 'connector': {'fromNodeId': from_node_id, 'toNodeId': to_node_id,
                                                   'fromAnchor': 'right', 'toAnchor': 'left',
                                                   'stroke': '#3b82f6', 'strokeWidth': 2}}


def canvas_seed_ops(job):
    """Op gieo cảnh canvas từ brief + danh sách chạm ĐÃ DUYỆT (P1: canvas không được để trống).

    Vì sao cần: canvas chỉ có nội dung khi MÔ HÌNH tự nhớ gọi `canvas_draw`, nên một dự án thật vẫn
    cho ra canvas trống — chủ nhà không có gì để nhìn, để bấm, hay để bảo sửa. Ở đây run tự dựng một
    bản đồ tối thiểu từ dữ liệu ĐÃ CÓ (brief + danh sách chạm vừa được duyệt): khối dự án → màn hình
    đích → từng mục sẽ chạm, kèm lý do/rủi ro và mũi tên nối.

    Hàm THUẦN (không đụng store, không phát sự kiện) và KHÔNG ghi đè: cảnh đã có NEO GIEO
    (`seed-workspace`) ⇒ `[]`. Điều kiện chỉ hỏi "cảnh có node nào chưa" là quá rộng: agent vẽ một
    node trong lúc hỏi brief là cả run mất luôn bản đồ — trong khi mẻ gieo chỉ THÊM node, không sửa
    node của ai.
    """
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    scene = _canvas_scene(state.get('canvasScene'))
    if any(node.get('id') == CANVAS_SEED_WORKSPACE_ID for node in scene['nodes']):
        return []
    brief = state.get('brief') if isinstance(state.get('brief'), dict) else {}
    touch_list = state.get('touchList') if isinstance(state.get('touchList'), dict) else {}
    items = [row for row in (touch_list.get('items') or []) if isinstance(row, dict)]
    scope = _brief_text(brief, 'mode') or 'chưa rõ'
    target = _brief_text(brief, 'screen') or 'màn hình đích'
    project = _brief_text(brief, 'project') or _brief_text(brief, 'path') or ''
    goal = _brief_text(brief, 'goal')
    ops = [
        {'type': 'CREATE_NODE', 'node': _seed_card(
            CANVAS_SEED_WORKSPACE_ID, 40, 40, 380, 180, 'ui-mockup',
            (f'Dự án: {project}' if project else 'Dự án đang mở'),
            'Bản đồ khởi đầu do run tự dựng từ brief và danh sách chạm đã duyệt. '
            + (f'Mục tiêu: {goal}' if goal else ''))},
        {'type': 'CREATE_NODE', 'node': _seed_card(
            CANVAS_SEED_SCREEN_ID, 520, 40, 380, 180, 'ui-mockup',
            f'Màn hình đích: {target}',
            f'Phạm vi: {scope} · Nền tảng: {_brief_text(brief, "platform") or "chưa rõ"}')},
        _seed_link(CANVAS_SEED_WORKSPACE_ID, CANVAS_SEED_SCREEN_ID),
    ]
    for index, item in enumerate(items[:CANVAS_SEED_ITEMS_MAX]):
        node_id = f'seed-touch-{index + 1}'
        path = str(item.get('path') or '').strip() or f'(mục {index + 1})'
        body = ' · '.join(part for part in (str(item.get('kind') or 'new'),
                                            str(item.get('reason') or '').strip(),
                                            f"rủi ro: {item.get('risk') or 'low'}") if part)
        ops.append({'type': 'CREATE_NODE', 'node': _seed_card(
            node_id, 960, 40 + 160 * index, 380, 130, 'directive-annotation', path, body)})
        ops.append(_seed_link(CANVAS_SEED_SCREEN_ID, node_id))
    return ops


def canvas_seed_from_run(rt, session_id, job):
    """Gieo cảnh canvas cho một run rồi phát ĐÚNG MỘT `design_canvas` (qua `canvas_draw`).

    Dùng chung đường phát sự kiện với mọi lần vẽ khác: nhờ vậy bộ đếm `canvasSeq`, ảnh chụp
    `.design/<slug>/canvas.v1.json` và luật "chỉ op ĐÃ ÁP mới vào sự kiện" không bị lệch.
    Trả `None` khi không có gì để gieo (cảnh đã có nội dung).
    """
    ops = canvas_seed_ops(job)
    if not ops:
        return None
    return canvas_draw(rt, session_id, job, actions=ops)


def canvas_queue_directive(rt, session_id, job, target_node_id, target_node_title, instruction):
    """Xếp chỉ thị canvas (`type:'directive'`) cho lượt Design Lead kế tiếp; trả bản ghi."""
    state = dict(job['state'] or {})
    directive = {'targetNodeId': str(target_node_id or ''), 'targetNodeTitle': str(target_node_title or ''),
                 'instruction': str(instruction or ''), 'at': journal.utc_now_iso()}
    state['directives'] = (state.get('directives') or []) + [directive]
    rt.store.design_job_save(job['design_id'], session_id, state, revision=job.get('revision'))
    return directive


def canvas_queued_directives(job):
    """Chỉ thị canvas đang xếp hàng của một run (khối lời dặn đọc lại).

    `job` có thể là `None`: lượt design của một chế độ đang bật mà `activeRunId` đã được nhả
    (run xong) vẫn dựng khối mode, và một khối mode không được sập vì thiếu run.
    """
    state = job.get('state') if isinstance(job, dict) and isinstance(job.get('state'), dict) else {}
    return [row for row in (state.get('directives') or []) if isinstance(row, dict)]


# ── Lời hỏi nhiều câu (§7.3) ────────────────────────────────────────────────


def design_prompt_new(rt, session_id, job, kind, questions=None, meta=None):
    """Ghim một lời hỏi nhiều câu vào `state.prompts` rồi phát `design_prompt` (§7.2)."""
    kind = str(kind or '')
    if kind not in DESIGN_PROMPT_KINDS:
        raise ValueError(f'DESIGN_PROMPT_KIND_INVALID: kind ∈ {DESIGN_PROMPT_KINDS}, nhận {kind!r}')
    meta = meta if isinstance(meta, dict) else {}
    if kind == 'out-of-scope':
        # §5.9/IF-2: hai lựa chọn ĐƯỢC GHIM id `exit`/`keep` như `exit-choice` ghim `pause`/
        # `background`; thẻ giao diện chỉ hiện được khi có đủ cặp ấy.
        request = str(meta.get('request') or '').strip()
        given = [item for item in (questions or []) if isinstance(item, dict)]
        text = str((given[0] if given else {}).get('text') or '').strip() or request \
            or 'Yêu cầu này nằm ngoài phạm vi thiết kế.'
        questions = [{'id': 'out-of-scope', 'text': text, 'why': '',
                      'allowFreeText': False, 'required': True,
                      'options': [{'id': 'exit', 'label': 'Tạm thoát để main xử lý'},
                                  {'id': 'keep', 'label': 'Giữ trong design'}]}]
    state = dict(job['state'] or {})
    prompt = {'promptId': f'dp-{uuid.uuid4().hex[:12]}', 'designId': job['design_id'], 'kind': kind,
              'revision': int(job['revision'] or 0), 'status': 'open',
              'createdAt': journal.utc_now_iso(), 'questions': list(questions or []),
              'actions': ['chooseExit'] if kind == 'exit-choice' else ['start', 'answer'],
              'note': str(meta.get('note') or '')}
    if kind == 'out-of-scope' and meta.get('request'):
        # IF-2: `meta.request` là TIN NHẮN GỐC của chủ nhà — nút "Tạm thoát" nộp lại tin ấy.
        prompt['meta'] = {'request': str(meta.get('request'))}
    prompts = list(state.get('prompts') or [])
    prompts.append(prompt)
    state['prompts'] = prompts
    # §6.3/§7.8: một lời hỏi có câu BẮT BUỘC là câu CHẶN — run dừng ở `needs_user` tới khi chủ nhà
    # trả lời (`design_prompt_answer(start=true)`) hoặc duyệt danh sách chạm.
    blocking = any(bool(item.get('required')) for item in (questions or []) if isinstance(item, dict))
    status = job['status']
    if blocking and status in DESIGN_ACTIVE_STATUSES:
        status = 'needs_user'
    updated = rt.store.design_job_save(job['design_id'], session_id, state, status=status,
                                       revision=job.get('revision'))
    rt.store.emit(session_id, 'design_prompt',
                  {'promptId': prompt['promptId'], 'designId': job['design_id'], 'kind': kind,
                   'status': 'open'})
    if status != job['status']:
        rt.store.emit(session_id, 'design_run', design_job_event(updated))
        notify_run(rt, session_id, updated)
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
    # §7.2: run đã đóng (huỷ/xong) thì lời hỏi không còn hiệu lực — không được nhích pha lùi về
    # `briefing` hay hồi sinh run. `close_run` đóng prompt còn mở, đây là lớp gác thứ hai.
    if (str(job.get('status') or '') in DESIGN_TERMINAL_STATUSES
            or str((job.get('state') or {}).get('phase') or '') == PHASE_DONE):
        raise ValueError('DESIGN_PROMPT_ANSWERED: the run is closed; that prompt no longer applies')
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
    advanced = False
    if start:
        status = 'designing'
        advanced = state.get('phase') != 'briefing'
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
    # §6.3/§7.2: trả lời "Bắt đầu" là một lần NHÍCH PHA (`-` → `briefing`) — cùng luật "mỗi lần
    # nhích pha phát đúng một `design_run`" như `set_phase` (đường này tự ghi pha vì phải ghi kèm
    # brief/status trong MỘT giao dịch).
    if advanced:
        rt.store.emit(session_id, 'design_run', design_job_event(updated))
    return {'designId': job['design_id'], 'promptId': prompt_id, 'status': prompt['status'],
            'revision': updated['revision'], 'start': bool(start), 'resume': bool(start)}


# ── Soát độc lập + báo cáo (§7.9, §6.3) ─────────────────────────────────────


def _clamp_issues(issues, limit=30):
    """Ghim `issues[]` về hình dạng của lược đồ `design_review` (khuôn `research._clamp_issues`)."""
    rows = []
    for item in (issues or []):
        if not isinstance(item, dict):
            continue
        rows.append({'severity': str(item.get('severity') or 'medium'),
                     'title': str(item.get('title') or item.get('summary') or '')[:200],
                     'detail': str(item.get('detail') or item.get('text') or '')[:2000],
                     'path': str(item.get('path') or '') or None})
    return rows[:limit]


def design_draft_path(job, version):
    """`.design/<slug>/v<N>-design.md` — bản nháp của một version, hoặc đường dẫn mà nó SẼ mang.

    Bản nháp do Design Lead ghi qua `design_write` nên nó nằm trong `state.actions`; chưa ghi thì
    trả về đường dẫn quy ước để `delegate_task(reviewTarget.kind='design')` có chỗ bám.
    """
    wanted = f'v{int(version)}-design.md'
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    for row in reversed(state.get('actions') or []):
        path = str((row or {}).get('path') or '')
        if path == f'{design_dir(job)}{wanted}':
            return path
    return f'{design_dir(job)}{wanted}'


def _tree_identity(state):
    """Vân tay của CÂY ĐÃ GHI tại một thời điểm: danh sách lô + băm các lần ghi (§7.9).

    `design_review(ok)` ghim vân tay này; `design_report` so lại — ghi thêm/rút bớt SAU lúc `ok`
    làm vân tay đổi và bản bàn giao không còn khớp thứ đã được soát.
    """
    diff = state.get('diff') if isinstance(state.get('diff'), dict) else {}
    files = [{'path': row.get('path'), 'status': row.get('status'), 'sha256': row.get('sha256')}
             for row in (diff.get('files') or []) if isinstance(row, dict)]
    actions = [[row.get('path'), row.get('sha256After')] for row in (state.get('actions') or [])
               if isinstance(row, dict)]
    blob = json.dumps({'files': files, 'actions': actions}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def _read_proof(rt, child_id, path, content_hash):
    """Con soát có ĐỌC đúng byte của bản nháp không — dùng lại `research._review_read_proof`.

    Một hàm, một luật (đọc mọi lát cắt liền mạch rồi băm ra đúng `content_hash`): bản soát nói mình
    đã đọc bản nháp mà chưa từng `file_read` nó thì không mở được cổng `design_review`.
    """
    if not path or not content_hash:
        return False
    from . import research_runtime
    return research_runtime._review_read_proof(rt, child_id, str(path), str(content_hash))


def _design_critic(rt, session_id, job, design_id, version, *, draft=None, draft_hash=None):
    """Con `plan-review` ĐỦ ĐIỀU KIỆN cho `(designId, version)` này, hoặc ném mã lỗi cổng (§7.9).

    Bốn điều kiện tiên quyết: vai `plan-review`, đã `completed`, sinh SAU khi run mở, và mang
    `reviewTarget` trỏ ĐÚNG `(kind='design', designId, version)`. Các kiểm này đứng TRƯỚC mọi nhánh
    đọc chữ — một bản soát đúng danh tính mà thiếu dòng VERDICT phải ra
    `DESIGN_REVIEW_VERDICT_MISSING`, không phải `DESIGN_REVIEW_NO_CRITIC` (bài học finding 7 của
    `research_critique`). Dòng `VERDICT:` chỉ đọc từ dòng CUỐI có chữ.

    Khi có `draft_hash` (bản nháp đã ghi thật trong box), con được chọn phải chứng minh nó đã ĐỌC
    đúng bản ấy — khuôn bằng chứng đọc của `research._review_read_proof`. Con mới nhất có dòng
    VERDICT nhưng đọc thiếu không được mở cổng; khi ấy cả lô không còn con nào dùng được.
    """
    created = float(job.get('created') or 0)
    usable = []
    for child in rt.store.children_of(session_id):
        if child.get('role') != 'plan-review' or child.get('status') != 'completed':
            continue
        if float(child.get('started') or 0) < created:
            continue
        if int(child.get('answer_chars') or 0) < PLAN_REVIEW_MIN_ANSWER_CHARS:
            continue
        session = rt.store.get(child['session_id']) or {}
        target = (session.get('config') or {}).get('reviewTarget') or {}
        if target.get('kind') != 'design' or str(target.get('designId') or '') != str(design_id) \
                or target.get('version') != version:
            continue
        usable.append(child)
    if not usable:
        raise _error(DESIGN_REVIEW_NO_CRITIC_CODE)
    ordered = sorted(usable, key=lambda row: (float(row.get('started') or 0),
                                              str(row.get('session_id'))), reverse=True)
    newest = ordered[0]
    for critic in ordered:
        text = ''
        for event in rt.store.events_tail(critic['session_id']):
            if event.get('type') != 'assistant':
                continue
            data = event.get('data') if isinstance(event.get('data'), dict) else {}
            piece = data.get('text')
            if isinstance(piece, str) and piece.strip():
                text = piece
        lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
        found = re.match(r'(?i)^VERDICT:\s*(ok|revise)$', lines[-1] if lines else '')
        if found is not None:
            if draft_hash and not _read_proof(rt, critic['session_id'], draft, draft_hash):
                continue
            return critic, found.group(1).lower()
        if str(critic['session_id']) == str(newest['session_id']):
            tail = ' | '.join(line[:120] for line in lines[-2:])
            raise ValueError(f'{DESIGN_REVIEW_VERDICT_MISSING_CODE}: '
                             f'{DESIGN_ERROR_TEXT[DESIGN_REVIEW_VERDICT_MISSING_CODE]} '
                             f'(con {str(newest["session_id"])[:8]}: {len(lines)} dòng có chữ; '
                             f'cuối: {tail!r})')
    raise _error(DESIGN_REVIEW_NO_CRITIC_CODE)


def _review_markdown(review):
    """`review.md` — kết luận soát độc lập, cùng hình dạng cho mọi version (§7.9)."""
    lines = [f'# Design review v{review["version"]}', '',
             f'- verdict: {review["verdict"]}',
             f'- critic: {review.get("criticSessionId") or "?"}',
             f'- at: {review.get("at") or ""}', '',
             '## Summary', '', str(review.get('summary') or '(none)'), '', '## Issues', '']
    issues = review.get('issues') or []
    lines.extend([f'- [{row.get("severity")}] {row.get("title")}'
                  + (f' ({row.get("path")})' if row.get('path') else '')
                  + (f' — {row.get("detail")}' if row.get('detail') else '')
                  for row in issues] or ['- (none)'])
    return '\n'.join(lines) + '\n'


async def design_review(rt, session_id, job, design_id, version, verdict, issues=None, summary=''):
    """`design_review` (§7.9): ghi kết luận soát ĐỘC LẬP của một version, chỉ khi có bản soát thật.

    Ba cổng theo ĐÚNG thứ tự: chưa có con `plan-review` đạt ⇒ `DESIGN_REVIEW_NO_CRITIC`; bản soát
    không có dòng `VERDICT:` ⇒ `DESIGN_REVIEW_VERDICT_MISSING`; `verdict` ghi vào LỆCH dòng ấy ⇒
    `DESIGN_REVIEW_VERDICT_MISMATCH`. Ghi `review.md` vào `.design/<slug>/`, cập nhật `state.review`
    rồi đẩy pha: `ok` ⇒ `reviewing`, `revise` ⇒ về `scaffolding`. Trả hình dạng §6.
    """
    if job is None:
        raise ValueError('DESIGN_JOB_UNKNOWN: open a run first (design_scope / the mode toggle)')
    design_id = str(design_id or job['design_id']).strip()
    if design_id != str(job['design_id']):
        raise ValueError('DESIGN_JOB_UNKNOWN: that run belongs to another conversation')
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError('DESIGN_REVIEW_INVALID: version must be a positive integer')
    verdict = str(verdict or '').strip().lower()
    if verdict not in ('ok', 'revise'):
        raise ValueError("DESIGN_REVIEW_INVALID: verdict must be 'ok' or 'revise'")
    # §7.9: ràng buộc `version` với nội dung THẬT của bản nháp — cổng soát phải đứng trên bản đã
    # ghi, và con soát phải chứng minh đã đọc đúng byte ấy (khuôn `research._review_read_proof`).
    draft = design_draft_path(job, int(version))
    draft_hash = await _box_file_sha(rt, session_id, draft)
    critic, critic_verdict = _design_critic(rt, session_id, job, design_id, version,
                                            draft=draft, draft_hash=draft_hash)
    if critic_verdict != verdict:
        raise ValueError(f'{DESIGN_REVIEW_VERDICT_MISMATCH_CODE}: '
                         f'{DESIGN_ERROR_TEXT[DESIGN_REVIEW_VERDICT_MISMATCH_CODE]} '
                         f'(bản soát nói {critic_verdict!r}, bạn ghi {verdict!r})')
    live = rt.store.design_job(design_id) or job
    review = {'version': int(version), 'verdict': critic_verdict,
              'summary': str(summary or '')[:DESIGN_REVIEW_SUMMARY_CHARS],
              'issues': _clamp_issues(issues), 'at': journal.utc_now_iso(),
              'criticSessionId': critic['session_id'],
              'draftPath': draft, 'contentHash': draft_hash,
              'treeHash': _tree_identity(live.get('state') or {})}
    state = dict(live['state'] or {})
    state['review'] = review
    state['reviews'] = [row for row in (state.get('reviews') or [])
                        if int((row or {}).get('version') or 0) != int(version)] + [review]
    updated = rt.store.design_job_save(design_id, session_id, state,
                                       revision=live.get('revision'))
    rt.store.emit(session_id, 'design_run', design_job_event(updated))
    await _write_box_text(rt, session_id, f'{design_dir(updated)}review.md',
                          _review_markdown(review))
    set_phase(rt, session_id, updated, 'reviewing' if verdict == 'ok' else 'scaffolding',
              f'review-{verdict}')
    return {'designId': design_id, 'version': int(version), 'verdict': verdict, 'recorded': True}


def _report_markdown(job, report):
    """`report.md` — thẻ báo cáo của run (một tệp cho mỗi run, bản mới nhất thắng)."""
    lines = [f'# Design report {job["design_id"]}', '',
             f'- status: {job["status"]}',
             f'- version: v{report["version"]}',
             f'- branch: {(report.get("branch") or {}).get("name") or "(none)"} '
             f'(base {(report.get("branch") or {}).get("base") or "?"})',
             f'- draft: {report.get("path")}',
             f'- labels: {", ".join(report.get("labels") or []) or "none"}', '',
             '## Summary', '', str(report.get('summary') or '(none)'), '',
             '## Next steps for the build agent', '']
    lines.extend([f'- {text}' for text in (report.get('nextSteps') or [])] or ['- (none)'])
    return '\n'.join(lines) + '\n'


async def design_report(rt, session_id, job, summary, labels=None, next_steps=None):
    """`design_report` (§7.9): thẻ báo cáo + khối bàn giao, CHỈ khi version hiện tại đã `ok`.

    Chưa có kết luận `ok` ⇒ `DESIGN_HANDOFF_UNREVIEWED`. Ghi `report.md`, phát `design_report` với
    đúng khoá §9, đóng run (pha `done`, nhả `activeRunId`) và nhắc `background-done` một lần nếu run
    đang chạy nền. Trả hình dạng §6.
    """
    if job is None:
        raise ValueError('DESIGN_JOB_UNKNOWN: open a run first (design_scope / the mode toggle)')
    state = dict(job['state'] or {})
    reviews = [row for row in (state.get('reviews') or []) if isinstance(row, dict)]
    latest = max(reviews, key=lambda row: int(row.get('version') or 0), default=None)
    if latest is None or latest.get('verdict') != 'ok':
        raise _error(DESIGN_HANDOFF_UNREVIEWED_CODE)
    version = int(latest.get('version') or 0)
    # §7.9: bàn giao ĐÚNG thứ đã được soát. Bản nháp đã ghim băm mà nay khác ⇒ nội dung đổi sau lúc
    # `ok`; vân tay cây đổi ⇒ có lần ghi/rút thêm sau lúc `ok`. Cả hai đều là bàn giao chưa soát.
    if latest.get('contentHash'):
        current_hash = await _box_file_sha(rt, session_id, design_draft_path(job, version))
        if current_hash != latest['contentHash']:
            raise _error(DESIGN_HANDOFF_UNREVIEWED_CODE)
    if latest.get('treeHash') and _tree_identity(state) != latest['treeHash']:
        raise _error(DESIGN_HANDOFF_UNREVIEWED_CODE)
    labels = [str(item).strip() for item in (labels or []) if str(item).strip()]
    next_steps = [str(item).strip() for item in (next_steps or []) if str(item).strip()]
    branch = _branch_state(state)
    report = {'version': version, 'path': design_draft_path(job, version),
              'reportPath': f'{design_dir(job)}report.md', 'labels': labels,
              'summary': str(summary or '')[:DESIGN_REPORT_SUMMARY_CHARS],
              'nextSteps': next_steps, 'verdict': latest.get('verdict'),
              'criticSessionId': latest.get('criticSessionId'), 'at': journal.utc_now_iso(),
              'branch': {'name': branch.get('name'), 'base': branch.get('base')} if branch else None}
    state['report'] = report
    state['stopReason'] = 'design-report'
    status = 'partial' if DESIGN_PARTIAL_LABEL in labels else 'completed'
    updated = rt.store.design_job_save(job['design_id'], session_id, state, status=status,
                                       revision=job.get('revision'))
    await _write_box_text(rt, session_id, report['reportPath'], _report_markdown(updated, report))
    updated = set_phase(rt, session_id, updated, PHASE_DONE, 'design-report', force=True) or updated
    rt.store.emit(session_id, 'design_report',
                  {'designId': job['design_id'], 'version': version,
                   'branch': report['branch'], 'path': report['path'], 'labels': labels,
                   'summary': report['summary']})
    # Bàn giao: run đóng ⇒ không còn run sống để bơm hoặc để khối mode bám vào.
    release_active_run(rt, session_id, job['design_id'])
    if state.get('background'):
        # Nhắc `background-done` TRƯỚC khi hạ cờ — `notify_run` chỉ thấy run nền khi cờ còn bật.
        updated = notify_run(rt, session_id, updated) or updated
        live = dict(updated['state'] or {})
        live['background'] = False
        updated = rt.store.design_job_save(job['design_id'], session_id, live,
                                           revision=updated.get('revision'))
    rt.store.emit(session_id, 'design_run', design_job_event(updated))
    return {'designId': job['design_id'], 'version': version, 'path': report['path'],
            'labels': labels}


# ── Bàn giao (§7.4, §4) ─────────────────────────────────────────────────────


def _brief_split(brief):
    """Chia brief thành HAI danh sách không trộn: phần chủ nhà xác nhận, phần agent giả định (§6.6).

    `confirmed` chỉ nhận mục `status='confirmed'` VÀ `source.kind='user'` — khuôn `research_handoff`.
    """
    confirmed, assumed = [], []
    for key, value in (brief or {}).items():
        if key == 'revision':
            continue
        if isinstance(value, dict):
            text = str(value.get('text') or value.get('value') or '').strip()
            source = value.get('source') if isinstance(value.get('source'), dict) else {}
            if not text:
                continue
            if value.get('status') == 'confirmed' and source.get('kind') == 'user':
                confirmed.append(f'{key}: {text}')
            else:
                assumed.append(f'{key}: {text}')
            continue
        text = '; '.join(str(item) for item in value if str(item).strip()) \
            if isinstance(value, list) else str(value or '').strip()
        if text:
            assumed.append(f'{key}: {text}')
    return confirmed, assumed


def _handoff_review(state, version):
    """Kết luận soát của ĐÚNG version bàn giao (bản mới nhất nếu thiếu bản khớp)."""
    review = state.get('review') if isinstance(state.get('review'), dict) else {}
    if int(review.get('version') or 0) == int(version or 0):
        return review
    return next((row for row in (state.get('reviews') or [])
                 if isinstance(row, dict) and int(row.get('version') or 0) == int(version or 0)), {})


def design_handoff_block(rt, session_id, job, version=None):
    """Khối `=== DESIGN HANDOFF ===` của một run ĐÃ có `report`, hoặc `None` (§6.6).

    Nội dung là hợp đồng giao diện: run + status, nhánh thiết kế + base, đường dẫn `v<N>-design.md`,
    các tệp đã ghi, danh sách chạm, kết luận độc lập, việc còn lại cho agent xây dựng, và hai danh
    sách TÁCH BIỆT "Bạn đã xác nhận" / "Giả định của agent". Khối được dựng MỘT LẦN cho mỗi
    `(designId, version)`; `_sync_mode_block` gỡ rồi chèn lại đúng một lần.
    """
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    report = state.get('report') if isinstance(state.get('report'), dict) else None
    if not report or not report.get('path'):
        return None
    version = version or report.get('version')
    review = _handoff_review(state, version)
    touch_list = state.get('touchList') if isinstance(state.get('touchList'), dict) else {}
    branch = _branch_state(state) or (touch_list.get('branch') or {})
    confirmed, assumed = _brief_split(state.get('brief') or {})
    items = [row for row in (touch_list.get('items') or []) if isinstance(row, dict)]
    written = [row for row in items if row.get('status') == 'written']
    lines = [DESIGN_HANDOFF_BLOCK_MARKER,
             f'designId: {job["design_id"]}  status: {job["status"]}  version: v{version}',
             f'branch: {branch.get("name") or "(none)"} (base {branch.get("base") or "?"})',
             f'draft: {report.get("path")}  report: {report.get("reportPath") or ""}',
             'files written (approved touch list): '
             + ('; '.join(str(row.get('path')) for row in written) if written else '(none)'),
             'independent verdict: '
             + f'{review.get("verdict") or "?"} — {review.get("summary") or ""}'.strip()]
    for row in items:
        lines.append(f'touch: [{row.get("kind")}/{row.get("status")}] {row.get("path")}'
                     f' — {row.get("reason") or ""}')
    lines.append('Bạn đã xác nhận: ' + ('; '.join(confirmed) if confirmed else '(chưa có mục nào)'))
    lines.append('Giả định của agent: ' + ('; '.join(assumed) if assumed else '(không có)'))
    lines.append('Việc còn lại cho agent xây dựng: '
                 + ('; '.join(report.get('nextSteps') or []) or '(không có)'))
    lines.append('Rule: build on the SAME design branch; do not raise the confidence of this design, '
                 'and do not write paths outside the approved touch list.')
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
