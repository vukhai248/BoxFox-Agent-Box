"""Command admission and lifecycle integration, separate from the model loop."""
import asyncio
import json
import time
import uuid
from ..agent_core import research_runtime
from ..agent_core.limits import (STEER_MAX_PENDING, RESEARCH_MODE_BLOCK_MARKER,
                                 RESEARCH_MODE_BLOCK_END, RESEARCH_MODE_EVENT_CODE,
                                 RESEARCH_HANDOFF_BLOCK_MARKER, RESEARCH_HANDOFF_BLOCK_END,
                                 RESEARCH_BACKGROUND_BLOCK_MARKER, RESEARCH_BACKGROUND_BLOCK_END)
from dataclasses import asdict
from .commands import INFO, ROLE_SKILLS, EXTERNAL
from ..agent_core.attachments import (attachment_prompt_block, validate_attachments,
                                     validate_inline_images)
from ..agent_core.failures import classify_failure, failure_detail
from ..observability.system_log import system_log
from ..agent_core.compression import ContextCompressor, context_estimate, estimate_tokens


def _strip_prompt_block(text, marker, end_marker):
    """Gỡ MỘT khối đã chèn (đủ cặp mốc) khỏi prompt, giữ nguyên phần còn lại.

    Chỉ gỡ khi tìm thấy ĐÚNG khối đã chèn: khối luôn khép bằng `end_marker`, còn một câu nhắc
    trong SOP/AGENT.md chỉ *nhắc tên* khối. Thiếu end_marker ⇒ đó là câu nhắc, không phải khối —
    gỡ theo nó sẽ nuốt phần đuôi của prompt (đo được 2026-09-25: prompt còn 5 647 ký tự).
    """
    start = text.rfind(marker)
    end = text.find(end_marker, start) if start != -1 else -1
    if start == -1 or end == -1:
        return text
    return text[:start] + text[end + len(end_marker):]

class RuntimeCommands:
    async def submit(self, sid, prompt, image=None, route=None, invocation_id=None, images=None,
                     attachments=None, allow_steer=True):
        session = self.store.get(sid)
        if not isinstance(prompt, str):
            raise ValueError('Prompt is required')
        # Kiểm tệp/ảnh TRƯỚC khi ghi hàng admission (F8): một danh sách sai phải là 400 chứ
        # không phải một hàng `command_invocations` mắc kẹt ở `running` — hàng đó còn chặn cả
        # lần thử lại cùng `invocationId` (`INVOCATION_CONFLICT`) sau khi client sửa tệp.
        checked_images = validate_inline_images([image, *(images or [])])
        checked_attachments = validate_attachments(attachments)
        invocation_id = invocation_id or uuid.uuid4().hex
        if not isinstance(invocation_id, str) or len(invocation_id) > 100:
            raise ValueError('Invalid invocation ID')
        # `images`/`attachments` PHẢI nằm trong khoá idempotency: nếu không, lần thử lại của
        # cùng `invocationId` với tệp khác sẽ trả kết quả cũ (A7).
        request = json.dumps([prompt, image, route, images, attachments], sort_keys=True)
        old = self.store.db.execute('SELECT request,result FROM command_invocations WHERE session_id=? AND id=?', (sid, invocation_id)).fetchone()
        if old:
            if old[0] != request:
                raise ValueError('INVOCATION_CONFLICT')
            return json.loads(old[1])
        settings = self.commands.settings()
        enabled = settings['enabled'] if settings['initialized'] else session['config']['skills']
        resolved = self.commands.resolve(prompt, enabled, session['config']['subagents'])
        busy = session['status'] in {'running', 'awaiting_decision'}
        steered = False
        if busy and not (resolved.kind == 'control' and resolved.command in INFO | {'stop'}):
            # Vòng 27 (đợt 7, D-43): lượt của PHIÊN GỐC đang chạy thì lời nhắn của chủ nhà không bị
            # trả 409 nữa — nó thành một CHỈ THỊ giữa lượt, bơm vào transcript ở ranh giới bước.
            # Phiên CON giữ nguyên `SESSION_BUSY` (con không nói chuyện với chủ nhà, #5961), và
            # bên gọi có thể tắt đường này bằng `allow_steer=False` (đường `plan_wake` giữ nguyên
            # kết cục `PLAN_WAKE_BUSY` đã tài liệu hoá).
            if allow_steer and not session.get('parent_id') and research_runtime.steer_mode()[0] == 'on':
                if self.store.pending_steer_count(sid) >= STEER_MAX_PENDING:
                    raise ValueError(f'STEER_QUEUE_FULL: đã có {STEER_MAX_PENDING} chỉ thị đang chờ bơm '
                                     f'vào lượt này — chờ lượt bơm bớt rồi gửi tiếp')
                steered = True
            else:
                raise ValueError('SESSION_BUSY: Turn in progress')
        result = {'status': 'steered' if steered else 'running', 'invocationId': invocation_id,
                  'resolution': asdict(resolved)}
        # Persist admission before scheduling a child. Replaying an interrupted invocation never reruns effects.
        with self.store.db:
            self.store.db.execute('INSERT INTO command_invocations VALUES(?,?,?,?)', (sid, invocation_id, request, json.dumps(result)))
        self.store.emit(sid, 'command_resolved', asdict(resolved) | {'invocationId': invocation_id})
        if steered:
            queued = await self.queue_owner_steer(sid, prompt)
            result.update({'steerId': (queued or {}).get('steerId'), 'turn': (queued or {}).get('turn'),
                           'pending': (queued or {}).get('pending'),
                           'output': 'Chỉ thị đã vào hàng đợi của lượt đang chạy.'})
            with self.store.db:
                self.store.db.execute('UPDATE command_invocations SET result=? WHERE session_id=? AND id=?',
                                      (json.dumps(result), sid, invocation_id))
            return result
        if resolved.kind == 'control':
            # `control: True` — hàng `user` của một LỆNH ĐIỀU KHIỂN không phải một lượt: bộ đếm
            # lượt dựng lại từ bảng (`HarnessRuntime._turn_index`) bỏ qua đúng những hàng này.
            self.store.emit(sid, 'user', {'text': prompt, 'control': True})
            if resolved.command == 'stop':
                await self.stop(sid)
                result['output'] = 'Stopped current turn and its children.'
            elif resolved.command == 'compact':
                self.store.save(sid, session['messages'], 'running')
                async def compact():
                    try:
                        async def summarize(history, max_tokens=None):
                            return await self.client.complete(history, [], session['config']['route'],
                                                              max_tokens=max_tokens or 2048)
                        # Ngưỡng của lượt này lấy từ chính phiên: `threshold_tokens` là trần byte quy
                        # ra token (xem `ContextCompressor.__init__`). `/compact` là lệnh có ý thức của
                        # người dùng nên đi thẳng qua ngưỡng, nhưng nó vẫn phải biết mình đang đo bằng
                        # gì — trước đợt này ngưỡng 70 % cứng không bao giờ chạm tới trên cửa sổ 1M.
                        compressor = ContextCompressor(session['config']['contextWindow'])
                        usage = self.last_usage.get(sid)
                        # Phần D — `/compact` không có gì để gộp vẫn phải trả SỐ, không phải một
                        # event trống: 8/33 dòng `unchanged` sống chỉ có mỗi `kind`, nên đọc lại
                        # không biết lượt đó đang đo bằng gì.
                        before = context_estimate(session['messages'], [], usage)
                        messages, event = await compressor.compact(session['messages'], [], summarize,
                                                                   force=True, usage=usage)
                        compact_event = dict(event or {})
                        compact_event.setdefault('kind', 'manual_compact')
                        compact_event.setdefault('beforeEstimate', before)
                        if messages is not session['messages']:
                            # N4 — hàng checkpoint phải tự nói được nó đo bằng gì. Đo trên máy chủ
                            # nhà 2026-09-21: 22 hàng sống chỉ có `id, session_id, messages, reason,
                            # created` — muốn biết cửa sổ/ngưỡng/ước lượng của lần nén đó phải mò
                            # sang `events.payload`. Ghi ngay tại đây, cùng lượt với bản gốc.
                            saved_messages = session['messages']
                            self.store.checkpoint(sid, saved_messages, 'manual_compact', {
                                'before_estimate': (event or {}).get('beforeEstimate', before),
                                'after_estimate': (event or {}).get('afterEstimate'),
                                'context_window': session['config'].get('contextWindow'),
                                'model_id': (session['config'].get('route') or {}).get('modelId'),
                            })
                            # A4 — `/compact` cũng phải để lại **bản đọc được**: cặp
                            # `ck-<sid8>-NNN.json/.md` cộng một dòng `C:` (bản 0.1 chỉ ghi hàng
                            # SQLite, nên đường nén do người dùng gọi là đường duy nhất không có
                            # bản mở được bằng mắt — đúng đường dễ bị hỏi "đã nén gì" nhất).
                            await self.write_journal_checkpoint(sid, saved_messages, messages,
                                                                compact_event, session['config'])
                            # Hóa đơn cũ thuộc về transcript cũ.
                            self.last_usage.pop(sid, None)
                        self.skill_loader.reset(sid)
                        self.store.save(sid, messages, 'completed')
                        self.refresh_journal_brief(sid, messages)
                        self.store.emit(sid, 'compression', event or {'kind': 'unchanged',
                                                                     'beforeEstimate': before,
                                                                     'afterEstimate': context_estimate(messages, [], None),
                                                                     'reason': 'nothing_to_compact'})
                        self.store.emit(sid, 'assistant', {'text': 'Context compaction complete.', 'final': True})
                        self.store.emit(sid, 'finish', {'status': 'completed'})
                    except asyncio.CancelledError:
                        self.store.save(sid, session['messages'], 'cancelled')
                        raise
                    except Exception as exc:
                        code, message = classify_failure(exc)
                        self.store.save(sid, session['messages'], 'failed')
                        self.store.emit(sid, 'error', {'message': message, 'code': code})
                        system_log.write('compact.failed', level='error', session_id=sid, errorCode=code,
                                         message=message, detail=failure_detail(exc))
                self.tasks[sid] = asyncio.create_task(compact())
                return result
            elif resolved.command == 'help':
                result['output'] = '\n'.join('/' + c['slug'] + ' — ' + c['description'] for c in self.commands.list() if c['enabled'])
            elif resolved.command == 'skills':
                result['output'] = '\n'.join(f"{s['id']}: {'enabled' if s['id'] in enabled else 'disabled'}; {s['readiness']}" for s in self.catalog.list())
            elif resolved.command == 'agents':
                result['output'] = json.dumps([dict(r) for r in self.store.db.execute('SELECT id,role,status FROM sessions WHERE parent_id=?', (sid,))], ensure_ascii=False)
            else:
                result['output'] = json.dumps({'sessionId': sid, 'status': session['status'], 'route': session['config']['route'],
                    'executor': session['config'].get('executor', 'native'), 'enabledSkills': enabled,
                    'loadedSkills': sorted({k[0] for k in self.skill_loader.loaded.get(sid, set())}),
                    'contextEstimate': estimate_tokens(session['messages']), 'estimateOnly': True}, ensure_ascii=False)
            result['status'] = self.store.get(sid)['status']
            self.store.emit(sid, 'assistant', {'text': result.get('output', ''), 'final': True, 'control': True})
        elif resolved.kind == 'mode':
            # P1 (§5.2, cửa 3): lệnh mode KHÔNG đi qua đường lượt thường. `/research` (rỗng)
            # và `/research status` không mở lượt; `/research <text>` bật mode rồi nộp lượt.
            outcome = self._mode_command(sid, session, resolved)
            result.update(outcome['result'])
            if not outcome.get('submit'):
                result['status'] = self.store.get(sid)['status']
            if outcome.get('submit'):
                session = self.store.get(sid)
                self._next_turn_skills(session, enabled, invocation_id, resolved.prompt or prompt)
                self.start(sid, resolved.prompt, image, route,
                           await self.route_metadata(session, route), images=images,
                           attachments=attachments, invocation_id=invocation_id)
        elif resolved.kind == 'message':
            self._next_turn_skills(session, enabled, invocation_id, prompt)
            # Route của lượt có thể đổi model; tra metadata của CHÍNH model đó (cùng
            # nguồn như lúc tạo phiên) để `start()` vẫn đối chiếu được `thinkingLevel`
            # thay vì bỏ qua kiểm tra (B13).
            self.start(sid, prompt, image, route, await self.route_metadata(session, route),
                       images=images, attachments=attachments, invocation_id=invocation_id)
        else:
            self._next_turn_skills(session, enabled, invocation_id, prompt)
            session = self.store.get(sid)
            if route:
                session['config']['route'] = route
                subagents = session['config'].get('subagents', [])
                existing_models = {s.get('model') for s in subagents if s.get('model')}
                is_single = (
                    bool(session['config'].get('isSingleModel'))
                    or bool(session['config'].get('singleModel'))
                    or (len(existing_models) == 1 and not any(m in {'inherit', 'default'} for m in existing_models))
                )
                if is_single and subagents:
                    from ..agent_core.runtime import route_to_model_spec
                    new_spec = route_to_model_spec(route)
                    if new_spec:
                        session['config']['isSingleModel'] = True
                        session['config']['singleModel'] = new_spec
                        for s in subagents:
                            s['model'] = new_spec
                self.store.update_config(sid, session['config'])
            # Nhánh command/skill: khối tệp đính kèm phải được dựng ở ĐÂY nữa, nếu không
            # đường skill mất đường dẫn dù người dùng đã đính kèm tệp (A7).
            block = attachment_prompt_block(checked_attachments)
            event = {'text': prompt}
            if checked_attachments:
                event['attachments'] = checked_attachments
            self.store.emit(sid, 'user', event)
            self.store.save(sid, session['messages'] + [{'role': 'user',
                                                        'content': f'{prompt}\n\n{block}' if block else prompt}], 'running')
            self.tasks[sid] = asyncio.create_task(
                self._command_task(sid, resolved, block, checked_images))
        with self.store.db:
            self.store.db.execute('UPDATE command_invocations SET result=? WHERE session_id=? AND id=?', (json.dumps(result), sid, invocation_id))
        return result

    def _sync_mode_block(self, session, invocation_id=None, turn_text=''):
        """Chèn/gỡ khối ACTIVE MODE + khối run chạy nền + khối bàn giao theo TỪNG LƯỢT
        (§5.2, §5.10).

        Cùng cách với khối ENABLED SKILLS: mỗi khối được GỠ trước rồi chèn lại, nên số lần xuất
        hiện trong prompt hệ thống luôn là MỘT (review F5). Khối bàn giao chỉ dựng khi mode TẮT và
        chưa bàn giao bản hồ sơ ấy cho lượt main nào.

        `invocation_id` phải là id của LƯỢT này: lượt bơm `research-resume-<id>` dùng hồ sơ
        research (kể cả khi mode đã tắt), nên khối của nó không phải khối main (review F8). Không
        truyền ⇒ giữ nguyên hành vi cũ cho lượt thường.

        `turn_text` là nội dung lượt NGƯỜI DÙNG đang dựng (chưa nằm trong `messages` lúc gọi): khối
        bàn giao chọn run theo nó. Không truyền ⇒ luật cũ (run chưa bàn giao mới nhất).
        """
        messages = session.get('messages') or []
        if not messages:
            return
        profile = self.turn_profile(session, invocation_id)
        current = messages[0].get('content') or ''
        # Gỡ cả ba khối đã chèn ở lượt trước: khối mode, dòng nhắc run nền, và khối bàn giao.
        for marker, end_marker in ((RESEARCH_MODE_BLOCK_MARKER, RESEARCH_MODE_BLOCK_END),
                                   (RESEARCH_BACKGROUND_BLOCK_MARKER, RESEARCH_BACKGROUND_BLOCK_END),
                                   (RESEARCH_HANDOFF_BLOCK_MARKER, RESEARCH_HANDOFF_BLOCK_END)):
            current = _strip_prompt_block(current, marker, end_marker)
        # Lượt đang dựng là `turn_text`: nếu lượt NÓI TÊN một run thì khối bàn giao phải là run ấy,
        # không phải run chưa bàn giao mới nhất (review D-5). KHÔNG đọc `messages[0]`: đó là PROMPT
        # HỆ THỐNG — nơi khối ACTIVE MODE/ENABLED SKILLS được chèn — và đo sống 2026-09-25 (D-8, vòng
        # kiểm thử P2–P5 lần 3) cho thấy nó không chứa token `r-<n>` nào, nên mọi lượt đều rơi về luật
        # "run mới nhất" và nút "Dùng cho plan" bàn giao SAI run.
        handoff = self.research_handoff(session, turn_text)
        content = current.rstrip()
        for block in [profile['promptBlock'], (handoff or {}).get('block')]:
            if block:
                content = (content + '\n\n' + block) if content else block
        if content != (messages[0].get('content') or ''):
            messages[0]['content'] = content
        if handoff:
            self.mark_handoff_delivered(session, handoff['researchId'], handoff['version'])

    def _set_mode(self, sid, session, on, entered_by):
        """Bật/tắt mode trong `config.researchMode` + phát sự kiện `research_mode` (§4.1)."""
        from ..agent_core.runtime import research_mode
        mode = research_mode(session)
        if on:
            if not mode['on']:
                mode['on'] = True
                mode['enteredBy'] = entered_by if entered_by in ('toggle', 'command') else 'command'
                tail = self.store.events_tail(sid, 1)
                mode['entrySeq'] = int(tail[-1]['seq']) if tail else 0
                mode['since'] = time.time()
        else:
            mode['on'] = False
            mode['enteredBy'] = ''
        mode['revision'] = int(mode.get('revision') or 0) + 1
        session.setdefault('config', {})['researchMode'] = mode
        self.store.update_config(sid, session['config'])
        self.store.emit(sid, RESEARCH_MODE_EVENT_CODE, {'on': mode['on'], 'by': entered_by,
                                                        'activeRunId': mode.get('activeRunId'),
                                                        'revision': mode['revision']})
        return mode

    def _active_mode_job(self, sid):
        """Run đang HOẠT ĐỘNG (kể cả `needs_user`) của mode, hoặc `None`."""
        from ..agent_core.limits import RESEARCH_JOB_ORIGIN
        active = {'scoping', 'researching', 'verifying', 'synthesizing', 'critiquing', 'needs_user'}
        for job in self.store.research_jobs_for(sid):
            state = job.get('state') if isinstance(job.get('state'), dict) else {}
            if str(state.get('origin') or '') == RESEARCH_JOB_ORIGIN and job['status'] in active:
                return job
        return None

    def _emit_prompt(self, sid, job, prompt):
        """Ghim một `research_prompt` vào `state.prompts` rồi phát sự kiện (§5.12).

        Lời hỏi nhiều câu KHÔNG chặn lượt: nó là dữ liệu bền trong job, trả lời qua tuyến `answers`.
        """
        state = dict(job['state'] or {})
        prompts = [item for item in (state.get('prompts') or []) if item.get('promptId') != prompt['promptId']]
        prompts.append(prompt)
        state['prompts'] = prompts
        self.store.research_job_save(job['research_id'], sid, state, revision=job.get('revision'))
        self.store.emit(sid, 'research_prompt', {'promptId': prompt['promptId'],
                                                 'researchId': job['research_id'],
                                                 'kind': prompt['kind'], 'status': prompt['status']})
        return prompt

    def _exit_choice_prompt(self, job):
        """Lời hỏi thoát mode khi run còn chạy (#6078) — server tạo, không cần mô hình."""
        return {'promptId': f'rp-exit-{job["research_id"][:12]}', 'researchId': job['research_id'],
                'kind': 'exit-choice', 'revision': job.get('revision', 1), 'blocking': True,
                'createdAt': time.time(), 'status': 'open',
                'questions': [{'id': 'exit', 'text': 'Run đang chạy. Tắt chế độ Research thì run thế nào?',
                               'why': 'run chưa kết thúc', 'options': [
                                   {'id': 'pause', 'label': 'Tạm dừng run', 'cost': None},
                                   {'id': 'background', 'label': 'Tiếp tục chạy nền', 'cost': None}],
                               'allowFreeText': False, 'affects': [], 'required': True}],
                'actions': [], 'note': 'Đóng lời hỏi mà không chọn thì không đổi gì.'}

    def _research_status_card(self, sid):
        """Thẻ trạng thái run cho `/research status` — KHÔNG mở lượt, KHÔNG gọi mô hình (M-16)."""
        job = self._active_mode_job(sid)
        if job is None:
            job = next((item for item in self.store.research_jobs_for(sid)), None)
        if job is None:
            return {'kind': 'status', 'message': 'Chưa có research run nào trong phiên này.'}
        state = job.get('state') if isinstance(job.get('state'), dict) else {}
        return {'kind': 'status', 'researchId': job['research_id'], 'status': job['status'],
                'phase': state.get('phase'), 'background': bool(state.get('background')),
                'scopeRevision': int((state.get('scope') or {}).get('revision') or 0),
                'revision': job.get('revision'),
                'message': (f'{job["research_id"]} · {job["status"]}'
                            f' · pha {state.get("phase") or "—"}'
                            f'{" · chạy nền" if state.get("background") else ""}')}

    def _mode_command(self, sid, session, resolved):
        """Xử lý `Resolution.kind='mode'` (§5.2, cửa 3).

        `/research` (rỗng) bật mode, KHÔNG gửi lượt. `/research <text>` bật mode rồi nộp lượt
        thường. `/research status` phát lại thẻ trạng thái. `/research off` có run đang chạy thì
        phát lời hỏi thoát và GIỮ mode (M-10c).
        """
        arg = (resolved.prompt or '').strip()
        low = arg.lower()
        result = {'output': ''}
        if low == 'status':
            card = self._research_status_card(sid)
            result['output'] = card['message']
            # D-4 (vòng kiểm thử P2–P5): sự kiện phải mang `message`. Trước đây trường này bị cắt
            # nên `/research status` đúng ở tầng server mà im lặng với người dùng: giao diện dựng
            # thẻ trạng thái từ chính sự kiện này, không có chỗ nào khác để đọc câu trạng thái.
            self.store.emit(sid, 'research_run', card)
            return {'result': result}
        if low == 'off':
            job = self._active_mode_job(sid)
            if job is not None:
                from ..agent_core.runtime import background_runs_enabled
                if not background_runs_enabled():
                    # F7 (§5.13): công tắc chạy nền TẮT ⇒ `/research off` tạm dừng run rồi tắt
                    # mode luôn; không phát lời hỏi thoát vì không còn lựa chọn "chạy nền" nào.
                    state = dict(job['state'] or {})
                    state['background'] = False
                    self.store.research_job_save(job['research_id'], sid, state, 'paused')
                    self.store.emit(sid, 'research_run', {
                        'researchId': job['research_id'], 'status': 'paused',
                        'phase': state.get('phase'), 'background': False,
                        'revision': job['revision'] + 1})
                    self._set_mode(sid, session, False, 'command')
                    result['output'] = 'Đã tắt chế độ Research và tạm dừng run.'
                    return {'result': result}
                prompt = self._emit_prompt(sid, job, self._exit_choice_prompt(job))
                result['output'] = ('Run đang chạy — chọn "Tạm dừng" hoặc "Tiếp tục chạy nền" '
                                    '(lời hỏi exit-choice).')
                return {'result': result, 'prompt': prompt}
            self._set_mode(sid, session, False, 'command')
            result['output'] = 'Đã tắt chế độ Research.'
            return {'result': result}
        # `/research` hoặc `/research <nội dung>` ⇒ bật mode.
        self._set_mode(sid, session, True, 'command')
        result['output'] = 'Đã bật chế độ Research.'
        return {'result': result, 'submit': bool(arg)}

    def _next_turn_skills(self, session, enabled, invocation_id=None, turn_text=''):
        """Viết lại khối kỹ năng + khối mode/nền/bàn giao cho LƯỢT này.

        `invocation_id` đi tiếp xuống `_sync_mode_block` để lượt bơm `research-resume-*` nhận
        đúng hồ sơ research ngay ở bước dựng prompt (review F8).

        `turn_text` là nội dung lượt NGƯỜI DÙNG đang dựng: mọi chỗ gọi hàm này chạy TRƯỚC
        `self.start(...)`, nên lượt mới CHƯA nằm trong `session['messages']` — đi tiếp xuống
        `_sync_mode_block` để chọn đúng run khi bàn giao (D-8).
        """
        session['config']['skills'] = list(enabled)
        self.store.update_config(session['id'], session['config'])
        messages = session['messages']
        marker = '=== ENABLED SKILLS (Load full content via skill_view before executing complex workflows) ===\n'
        if messages and marker in messages[0].get('content', ''):
            prefix, tail = messages[0]['content'].split(marker, 1)
            # Chỗ này chỉ được thay DANH SÁCH KỸ NĂNG. Bản cũ cắt từ marker tới hết chuỗi nên nuốt
            # luôn mọi khối phía sau: đo sống 2026-09-21 thấy lượt đầu tiên mất `=== ANSWER LENGTH ===`
            # trước khi tới tay mô hình (vòng 23 lúc đó còn mất thêm khối khuôn báo cáo). Giữ nguyên
            # phần đuôi (mọi khối `\n\n=== ` sau danh sách).
            _, _, body = tail.partition('\n\n=== ')
            rest = ('\n\n=== ' + body) if body else ''
            messages[0]['content'] = prefix + marker + self.catalog.prompt(enabled) + rest
        # Preserve historical tool exchange structure, remove obsolete active instruction bodies.
        for m in messages[1:]:
            if m.get('name') == 'skill_view':
                m['content'] = '[Historical skill read. Reload with skill_view if needed for the new turn.]'
        self.skill_loader.reset(session['id'])
        # P1 (§5.2/§5.10): chèn/gỡ khối ACTIVE MODE và khối bàn giao theo LƯỢT này.
        self._sync_mode_block(session, invocation_id, turn_text)
        self.store.save(session['id'], messages)

    async def _command_task(self, sid, resolved, block='', images=None):
        """Chạy lệnh/kỹ năng trong phiên con; khối tệp đính kèm đi CÙNG con (A7).

        `block` là khối đường dẫn mà lượt người dùng đã mang: mô hình làm việc thật ở đây là
        phiên con, nên nếu chỉ ghép khối vào thân của phiên cha thì tệp vẫn vô hình với nó —
        đúng triệu chứng BUG-40 mà A7 dựng lên để xoá. `images` là mảng ảnh đã kiểm của lượt
        (ảnh đơn cũ đã gộp vào đây); chỉ đường `native` dùng tới, đường `claude-code` nhận chữ.
        """
        try:
            session = self.store.get(sid)
            if resolved.executor == 'claude-code':
                # Pre-flight the CLI before creating any child: a missing CLI is a setup
                # problem for the owner, not a failed subagent (HANDOFF §5.1).
                from ..sandbox.claude_executor import ClaudeExecutor
                probe = await ClaudeExecutor(self.executor.container).probe()
                if probe.get('status') != 'ready':
                    reason = probe.get('reason') or 'Claude Code CLI is not ready inside the sandbox.'
                    raise ValueError('SETUP_REQUIRED: ' + reason)
            roles = ['design', 'build', 'testing'] if resolved.role == 'orchestrator' and 'claude-design' in resolved.skills else [resolved.role]
            # Ngân sách thời gian của con = ngân sách của phiên. Đo sống 2026-09-20: phiên đặt
            # 600 giây vẫn chết `DEADLINE` vì con của lệnh nhận mặc định 180 giây, mà một lượt
            # `/claude-code` thật cần hơn thế — con dài hơn phiên là vô nghĩa, nên lấy đúng số
            # của phiên thay vì một hằng số thứ hai.
            budget = session['config'].get('deadlineSeconds', 180)
            context, answer = '', ''
            for role in roles:
                if role == 'orchestrator':
                    # A generic skill runs in an isolated orchestrator context, with the same role configuration.
                    child = self.create({'skills': resolved.skills, 'subagents': session['config']['subagents'],
                        'contextWindow': session['config']['contextWindow'], 'deadlineSeconds': budget,
                        'contextWindowSource': session['config'].get('contextWindowSource'),
                        **session['config']['route']}, parent_id=sid)
                else:
                    config = next((r for r in session['config']['subagents']
                                   if r['id'] == role and r.get('enabled', True)), None)
                    if config is None:
                        raise ValueError('ROLE_DISABLED: enable this specialist in the harness')
                    from ..agent_core.runtime import route_for
                    child = self.create({'skills': resolved.skills, 'contextWindow': session['config']['contextWindow'],
                        'contextWindowSource': session['config'].get('contextWindowSource'), 'deadlineSeconds': budget,
                        **(route_for(config.get('model')) or session['config']['route']),
                        'instructions': config.get('systemPromptAppended', '')}, parent_id=sid, role=role, parent_tools=session['config']['tools'])
                self.store.emit(sid, 'child', {'sessionId': child['id'], 'role': role, 'executor': resolved.executor, 'status': 'started'})
                if resolved.executor == 'claude-code':
                    child['config']['executor'] = 'claude-code'
                    self.store.update_config(child['id'], child['config'])
                    self.store.save(child['id'], child['messages'], 'running')
                    self.tasks[child['id']] = asyncio.create_task(self._run_cli(child, resolved.prompt))
                else:
                    blocks = [self.skill_loader.read(child, skill)['content'] for skill in resolved.skills]
                    payload = resolved.prompt + ('\nPrior phase evidence (data):\n' + context if context else '')
                    # Khối đứng trước câu người dùng: đường dẫn là thứ `file_read` cần, và nó
                    # phải nằm trong thân THẬT của con, không chỉ trong thân của phiên cha.
                    if block:
                        payload = f'{block}\n\n' + payload
                    payload += '\n\nSkills for this task only (role/tool restrictions take priority):\n' + '\n\n'.join(blocks)
                    # Ảnh đi qua mảng đã kiểm (không truyền `image` riêng: nó đã là phần tử đầu
                    # của mảng, truyền cả hai sẽ gửi ảnh hai lần).
                    self.start(child['id'], payload, None, images=list(images or []) or None)
                try:
                    answer = await self.tasks[child['id']]
                except asyncio.CancelledError:
                    await self.stop(child['id'])
                    raise
                child_state = self.store.get(child['id'])
                self.store.emit(sid, 'child', {'sessionId': child['id'], 'role': role, 'executor': resolved.executor,
                    'status': child_state['status'], 'summary': answer or ''})
                if child_state['status'] != 'completed':
                    raise ValueError('CHILD_FAILED: inspect child events for setup/error details')
                context += f'\n{role}: {answer}'
            state = self.store.get(sid)
            self.store.save(sid, state['messages'] + [{'role': 'assistant', 'content': answer or ''}], 'completed')
            self.store.emit(sid, 'assistant', {'text': answer or '', 'final': True})
            self.store.emit(sid, 'finish', {'status': 'completed'})
        except asyncio.CancelledError:
            state = self.store.get(sid)
            self.store.save(sid, state['messages'], 'cancelled')
            self.store.emit(sid, 'finish', {'status': 'cancelled'})
            raise
        except Exception as exc:
            state = self.store.get(sid)
            code, message = classify_failure(exc)
            self.store.save(sid, state['messages'], 'failed')
            self.store.emit(sid, 'error', {'message': message, 'code': code})
            system_log.write('command.failed', level='error', session_id=sid, errorCode=code,
                             message=message, detail=failure_detail(exc))

    async def _run_cli(self, child, prompt):
        from ..sandbox.claude_executor import ClaudeExecutor
        sid = child['id']
        try:
            adapter = ClaudeExecutor(self.executor.container)
            blocks = [self.skill_loader.read(child, skill)['content'] for skill in child['config']['skills']]
            async with self.writer_lock:
                answer = await adapter.run(sid, prompt, child['role'], '\n\n'.join(blocks),
                    lambda event: self.store.emit(sid, 'executor', event), child['config']['deadlineSeconds'])
            self.store.save(sid, child['messages'] + [{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': answer}], 'completed')
            self.store.emit(sid, 'assistant', {'text': answer, 'final': True})
            return answer
        except asyncio.CancelledError:
            self.store.save(sid, child['messages'], 'cancelled')
            raise
        except Exception as exc:
            code, message = classify_failure(exc)
            self.store.save(sid, child['messages'], 'failed')
            self.store.emit(sid, 'error', {'message': message, 'code': code})
            system_log.write('executor.failed', level='error', session_id=sid, errorCode=code,
                             message=message, detail=failure_detail(exc))
            return None
