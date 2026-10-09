"""Vòng 24 (D-31/D-32) → Vòng 28 (D-44) — dạng câu trả lời DỜI khỏi prompt rồi hạ xuống GỢI Ý:
kỹ năng `final-report` chỉ mách nước, prompt chỉ còn MỘT dòng nhắc mềm (phiên chính).

Chủ nhà chốt (D-26…D-32, `owner-decisions.md` §4.2): form năm phần bị bỏ; model tự chọn phần hợp
lượt, không in phần rỗng; lượt chỉ hỏi thì trả lời như thường, không báo cáo; tóm tắt do model viết
+ "View details" phải chạy lại. Ngày 2026-09-24 chủ nhà chốt tiếp (D-44): kể cả phần còn lại cũng
**chỉ là gợi ý** — kỹ năng không được ép model trả lời theo khuôn nào; agent trả lời tự nhiên và
ngắn như ChatGPT/Claude.

Ba thứ dưới đây sống ở tầng PROMPT/KỸ NĂNG và phải kiểm được mà KHÔNG cần model thật:

- **Hợp đồng mới** — `runtime.py` không còn `FINAL_REPORT_PARTS`/`FINAL_REPORT_GUIDANCE` và không còn
  khối `=== FINAL REPORT ===`; đúng MỘT hằng `ANSWER_EVIDENCE_LINE` được chèn ngay sau
  `=== ANSWER LENGTH ===`, và CHỈ ở phiên chính (D-18/D-31/D-32). Dòng ấy nay là **nhắc mềm**
  ("you may"), không phải mệnh lệnh (D-44).
- **Kỹ năng là nơi chứa** — `final-report` ở lại `DEFAULT_SKILLS`, tên nó có trong khối
  `=== ENABLED SKILLS`, và nội dung kỹ năng (đọc qua `SkillCatalog`) giữ đủ menu như **danh sách
  gợi ý**: không câu nào bắt model dùng đủ phần, đúng thứ tự, hay luôn khép bằng ảnh.
- **Con trỏ ở bước tổng kết** — bản nhắc việc của LƯỢT trỏ tới kỹ năng, nên nó chỉ xuất hiện ở lượt có
  việc: lượt chỉ hỏi không bao giờ thấy nó (recap rỗng, xem các ca P1.5 giữ nguyên ở dưới).

Ghi chú lịch sử: kế hoạch v2 có nhắc một hằng `ANSWER_PART_MENU` cho menu trong prompt, nhưng hằng đó
chưa từng tồn tại (v3 bỏ ý đó) nên ở đây không có ghim "vắng mặt" cho nó.
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

from agentbox.agent_core import runtime as runtime_module
from agentbox.agent_core.roles import ORCHESTRATOR_TOOLS, ROLES
from agentbox.agent_core.runtime import HarnessRuntime, get_agent_identity, turn_recap
from agentbox.memory.session_store import SessionStore
from agentbox.skills.catalog import DEFAULT_SKILLS, SkillCatalog
from agentbox.sandbox.worker import SESSION_OP_NAMES

SECTION_34 = '### 3.4.'
SKILL_ID = 'final-report'
# Bốn câu của khuôn CŨ (vòng 23): mỗi câu là một hình dạng câu trả lời bị chủ nhà bỏ (D-26/D-28).
RETIRED = ('with these five parts', 'in this order', 'as a short report')
# Năm mục của kỹ năng — một MENU, không phải khuôn: model tự chọn phần hợp lượt (D-26/D-27).
MENU = ('What you did', 'What is left', 'What the owner must decide', 'What is unclear', 'Evidence')
# Dạng "danh sách" của menu: chỗ duy nhất được phép dựng danh sách này là kỹ năng.
MENU_BULLETS = tuple(f'- **{name}**' for name in MENU)


def answer(text='done', calls=None):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class Model:
    """Model giả: trả lần lượt các câu trả lời và ghi lại ĐÚNG `messages` của mỗi lần gọi."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.requests.append(copy.deepcopy(messages))
        return next(self.responses)


class Executor:
    """Executor giả tối thiểu: đủ để lượt chạy, không ghi đĩa, không gọi box."""

    async def execute(self, name, args, sid, **_identity):
        if name == 'file_write':
            return {'content': f"Written {args.get('path')}"}
        if name in ('terminal_exec', 'run_command'):
            return {'content': 'ok', 'exit_code': 0}
        if name in SESSION_OP_NAMES:
            # Op nhật ký của box (A1/A7) trả `{ok, …}` như worker thật: thiếu `ok` thì
            # `session_journal._safe` coi là CHƯA ghi được và ghim `JOURNAL_DEGRADED`.
            return {'ok': True}
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def run_turn(tmp_path, client, prompt, *, name='prompt.db', role='orchestrator', parent_id=None):
    store = SessionStore(tmp_path / name)
    runtime = HarnessRuntime(store, Executor(), client)
    session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'deepseek-v4-flash'},
                             parent_id=parent_id, role=role)
    sid = session['id']
    attach = getattr(client, 'attach', None)
    if attach is not None:
        attach(runtime, sid)

    async def run():
        await runtime.submit(sid, prompt)
        await runtime.tasks[sid]

    asyncio.run(run())
    return store, runtime, session


def system_prompt(runtime, session):
    return runtime.store.get(session['id'])['messages'][0]['content']


def assistant_text(store, sid):
    return [event['data'] for event in store.events(sid) if event['type'] == 'assistant'][-1]['text']


def recap_messages(messages):
    return [message for message in messages
            if isinstance(message.get('content'), str)
            and message['content'].startswith(runtime_module.RECAP_HEADER)]


def section_34(identity):
    """Mục §3.4 của `AGENT.md` — bản được NẠP THẬT cho mọi vai, nên đọc nó chứ không đọc tệp."""
    start = identity.index(SECTION_34)
    return identity[start:identity.index('### 3.5.', start)]


# ------------------------------------------------- P2(a) prompt sạch mọi khối dạng câu trả lời

def test_prompt_khong_con_khoi_dang_cau_tra_loi_nao(tmp_path):
    """P2(a) — prompt phiên chính không còn khối `=== FINAL REPORT ===` và không còn lời khuôn."""
    store, runtime, session = run_turn(tmp_path, Model([answer('xong')]), 'việc gì đó')
    prompt = system_prompt(runtime, session)

    assert '=== FINAL REPORT ===' not in prompt
    for phrase in ('five parts', 'with these five parts', 'in this order'):
        assert phrase not in prompt, f'{phrase!r} vẫn còn trong prompt phiên chính'
    store.close()


def test_hai_hang_so_cua_khuon_nam_phan_da_bi_xoa_han():
    """P2(a) — hợp đồng là "xoá hẳn": hai hằng số cũ không được còn để ai đó chèn lại."""
    assert not hasattr(runtime_module, 'FINAL_REPORT_PARTS')
    assert not hasattr(runtime_module, 'FINAL_REPORT_GUIDANCE')


def test_chu_da_nghi_huu_khong_con_o_bon_cho():
    """P2(a) — bốn câu của khuôn cũ vắng ở BỐN chỗ: runtime.py, SOP, `AGENT.md` §3.4, kỹ năng.

    Đọc thẳng TỆP `runtime.py` (không chỉ hằng số) vì khuôn cũ nằm rải ở cả hằng số lẫn SOP: một bản
    chép sót lại ở bất cứ đâu là một lần model được dạy lại form cũ.
    """
    identity = get_agent_identity()
    assert identity != runtime_module.IDENTITY, 'bài kiểm này chỉ có nghĩa khi AGENT.md đang được nạp'
    places = (('runtime.py', Path(runtime_module.__file__).read_text(encoding='utf-8')),
              ('ORCHESTRATOR_SOP_GUIDANCE', runtime_module.ORCHESTRATOR_SOP_GUIDANCE),
              ('AGENT.md §3.4', section_34(identity)),
              (f'kỹ năng {SKILL_ID}', SkillCatalog().read(SKILL_ID)['content']))
    for where, text in places:
        for phrase in RETIRED:
            assert phrase not in text, f'{phrase!r} còn ở {where}'


def test_cau_chi_dan_sop_chi_con_mot_dong_trung_thuc():
    """P2(a) — SOP không còn TRỎ về khối nào, cũng không chép lời khuôn: chỉ một dòng trung thực."""
    sop = runtime_module.ORCHESTRATOR_SOP_GUIDANCE
    assert 'FINAL REPORT block' not in sop
    assert 'the real commands you ran, the real files you changed, no invented output' in sop
    assert [bullet for bullet in MENU_BULLETS if bullet in sop] == [], \
        'khuôn chỉ được định nghĩa ở MỘT chỗ: kỹ năng'


# ------------------------------ P2(b) một dòng NHẮC MỀM về ảnh, chỉ phiên chính (D-18/D-32/D-44)

def test_dong_bang_chung_dung_mot_lan_va_nam_sau_answer_length(tmp_path):
    """P2(b) — dòng nhắc mềm: đúng một lần, ngay sau `=== ANSWER LENGTH ===`, ASCII, ngắn, KHÔNG ra lệnh."""
    line = runtime_module.ANSWER_EVIDENCE_LINE
    assert line.isascii(), 'prompt là tiếng Anh: dòng nhắc phải thuần ASCII'
    assert len(line) <= 200, 'một dòng, không phải một khối'
    assert 'you may' in line, 'D-44: đây là gợi ý (you may), không phải mệnh lệnh'
    for order in ('closes the answer with the', 'must ', 'Always '):
        assert order not in line, f'D-44: dòng nhắc không được ra lệnh ({order!r})'
    assert 'never a fabricated image' in line, 'luật trung thực thì vẫn giữ'

    store, runtime, session = run_turn(tmp_path, Model([answer('xong')]), 'việc gì đó')
    prompt = system_prompt(runtime, session)

    assert prompt.count(line) == 1, 'phiên chính nhận ĐÚNG một lần'
    assert prompt.index('=== ANSWER LENGTH ===') < prompt.index(line)
    store.close()


def test_moi_vai_nhan_chu_dan_do_dai_nhung_chi_phien_chinh_nhan_dong_bang_chung(tmp_path):
    """P2(b) — `ANSWER LENGTH` cho MỌI vai; dòng bằng chứng CHỈ phiên chính (D-18)."""
    store = SessionStore(tmp_path / 'roles.db')
    runtime = HarnessRuntime(store, Executor(), Model([]))
    main = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm'})
    prompt = system_prompt(runtime, main)
    assert runtime_module.ANSWER_LENGTH_HINT in prompt
    assert runtime_module.ANSWER_EVIDENCE_LINE in prompt

    for role in ROLES:
        child = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm'},
                               parent_id=main['id'], role=role)
        child_prompt = system_prompt(runtime, child)
        assert runtime_module.ANSWER_LENGTH_HINT in child_prompt, f'vai {role} phải biết độ dài câu trả lời'
        assert runtime_module.ANSWER_EVIDENCE_LINE not in child_prompt, \
            f'vai {role} trả kết quả cho CHA, không báo cáo chủ nhà'
        assert f'=== ASSIGNED ROLE: {role.upper()} ===' in child_prompt
        assert ROLES[role].instructions in child_prompt
    store.close()


# ------------------------------------------------ P2(c) kỹ năng `final-report` giữ cả dạng câu trả lời

def test_ky_nang_final_report_giu_menu_duoi_dang_goi_y():
    """P2(c) — kỹ năng (đọc qua `SkillCatalog`) giữ đủ menu như GỢI Ý, kèm mẹo đọc trên chat panel."""
    content = SkillCatalog().read(SKILL_ID)['content']

    for bullet in MENU_BULLETS:
        assert bullet in content, f'menu thiếu mục {bullet!r}'
    for phrase in ('not a form', 'Nothing here is compulsory', 'View details', 'you may'):
        assert phrase in content, f'kỹ năng thiếu câu gợi ý {phrase!r}'
    for order in ('closes the answer', 'never in the middle', 'Not optional', 'must open with'):
        assert order.lower() not in content.lower(), f'D-44: kỹ năng còn ra lệnh ({order!r})'
    # Chữ trong kỹ năng viết hoa "Never print an empty part" — luật là luật, không phụ thuộc viết hoa.
    assert 'never print an empty part' in content.lower(), 'D-27: hết việc thì không in mục rỗng'
    # D-26: menu KHÔNG được trôi ngược thành khuôn — cấm câu bắt dùng đủ năm phần. Các câu dưới đây
    # không có trong bản hiện tại, nên ghim này chỉ đỏ khi ai đó viết lại kỹ năng thành khuôn cứng.
    for phrase in ('all five', 'five parts', 'every part', 'in this order', 'must use'):
        assert phrase not in content.lower(), f'D-26: menu đã thành khuôn cứng ({phrase!r})'
    assert 'pick by content, not habit' in content.lower(), 'D-26: luật tự chọn phần phải còn'
    assert SKILL_ID in DEFAULT_SKILLS, 'D-31: kỹ năng Ở LẠI DEFAULT_SKILLS'


def test_ky_nang_va_con_tro_deu_la_goi_y_khong_ep_khuon(tmp_path):
    """D-44 — không chỗ nào ở tầng prompt/kỹ năng còn ÉP model theo khuôn trả lời.

    Chủ nhà 2026-09-24: *"chỉ là skill gợi ý agent trả lời, không nên khoá cứng như vậy… agent vẫn
    trả lời tự nhiên như ChatGPT/Claude và trả lời ngắn"*. Ca này ghim đúng chỗ ấy: con trỏ ở bước
    tổng kết nói "đọc nếu thấy giúp" (không bắt đọc), và nó không ra lệnh chụp lại ảnh.
    """
    closer = runtime_module.RECAP_CLOSER
    assert 'optional menu of ideas' in closer, 'D-44: kỹ năng được mời, không bị bắt đọc'
    assert 'you would say it to the owner in chat' in closer, 'D-44: văn tự nhiên là chuẩn'
    for order in ('Before you write the answer', 're-capture every item', 'it holds the answer shape'):
        assert order not in closer, f'D-44: con trỏ còn ra lệnh ({order!r})'

    store, runtime, session = run_turn(tmp_path, Model([answer('xong')]), 'việc gì đó')
    prompt = system_prompt(runtime, session)
    assert 'Treat that line as the rule' not in prompt, 'D-44: không còn câu "coi đó là luật"'
    store.close()


def test_ten_ky_nang_co_trong_khoi_enabled_skills_cua_prompt(tmp_path):
    """P2(c) — phiên mới thấy tên kỹ năng trong khối `=== ENABLED SKILLS`, và mở được bằng `skill_view`.

    Không truyền `skills` khi tạo phiên: mặc định của engine là `DEFAULT_SKILLS` — đúng đường mà một
    phiên thật đi qua, nên bài này đo cả danh sách mặc định lẫn khối prompt.
    """
    store = SessionStore(tmp_path / 'skills.db')
    runtime = HarnessRuntime(store, Executor(), Model([]))
    session = runtime.create({'connectionId': 'c1', 'modelId': 'm'})
    prompt = system_prompt(runtime, session)

    assert '=== ENABLED SKILLS' in prompt
    assert f'- {SKILL_ID}: ' in prompt, 'kỹ năng phải có tên trong danh sách kỹ năng của prompt'
    assert 'skill_view' in ORCHESTRATOR_TOOLS, 'kỹ năng phải MỞ ĐƯỢC: vai chính có công cụ đọc kỹ năng'
    store.close()


def test_agent_md_muc_34_tro_ve_ky_nang_chu_khong_chep_khuon():
    """P2(c) — `AGENT.md` §3.4 (bản NẠP THẬT cho mọi vai) chỉ TRỎ về kỹ năng, không dựng khuôn thứ hai.

    §3.4 cố ý nói lại luật bằng lời của nó (kể cả luật markdown-only của vòng 23) nhưng KHÔNG được
    chép danh sách phần — chép lại là có hai bản khuôn, và bản nạp thật (tệp này) lại là bản không ai
    đọc khi sửa prompt.
    """
    section = section_34(get_agent_identity())

    assert SKILL_ID in section and 'skill_view' in section, '§3.4 phải chỉ model mở kỹ năng'
    assert [bullet for bullet in MENU_BULLETS if bullet in section] == [], \
        '§3.4 không được chép menu của kỹ năng'
    assert section.isascii(), 'mục §3.4 trong AGENT.md phải thuần ASCII'


# ---------------------------------------------------- P2(d) con trỏ chỉ có ở lượt có việc (D-31)

def test_con_tro_o_buoc_tong_ket_tro_toi_ky_nang(tmp_path):
    """P2(d) — recap của LƯỢT CÓ VIỆC trỏ tới kỹ năng, và vẫn là chữ KHÔNG được dán vào câu trả lời."""
    client = Model([answer('', calls=[call('file_write', {'path': 'src/app.py', 'content': 'x'})]),
                    answer('Đã sửa `src/app.py`.')])
    store, runtime, session = run_turn(tmp_path, client, 'sửa app giúp tôi')
    sid = session['id']

    recap = recap_messages(client.requests[1])
    assert len(recap) == 1, 'bước tổng kết phải có ĐÚNG một khối nhắc việc'
    content = recap[0]['content']
    assert SKILL_ID in content and 'skill_view' in content, 'con trỏ phải chỉ đúng kỹ năng và cách mở'
    assert 'must not be pasted into it' in content
    assert 'owner request (excerpt): sửa app giúp tôi' in content
    assert 'files changed: src/app.py' in content
    assert content.startswith(runtime_module.RECAP_HEADER)
    assert len(content.splitlines()) <= runtime_module.RECAP_MAX_LINES + 2
    assert recap_messages(client.requests[0]) == [], 'lượt chưa làm gì thì không tốn một dòng nào'

    transcript = json.dumps(runtime.store.get(sid)['messages'], ensure_ascii=False)
    assert runtime_module.RECAP_HEADER not in transcript, 'khối nhắc việc KHÔNG vào transcript'
    assert assistant_text(store, sid) == 'Đã sửa `src/app.py`.'
    assert runtime_module.RECAP_HEADER not in assistant_text(store, sid), 'không lọt vào câu trả lời'
    store.close()


# ------------------------------------- P1.5 giữ nguyên: bản nhắc việc của lượt, mọi ca cũ còn giá trị

def test_recap_vang_khi_luot_chi_doc(tmp_path):
    """P1.5 + P2(d) — lượt chỉ đọc không có gì để nhắc: KHÔNG recap ⇒ lượt hỏi thường không thấy con trỏ."""
    client = Model([answer('', calls=[call('file_read', {'path': 'src/app.py'})]),
                    answer('Đã đọc tệp: nội dung là x.')])
    store, _runtime, session = run_turn(tmp_path, client, 'đọc tệp này')
    sid = session['id']

    assert recap_messages(client.requests[1]) == []
    assert runtime_module.RECAP_HEADER not in json.dumps(client.requests[1], ensure_ascii=False)
    assert assistant_text(store, sid) == 'Đã đọc tệp: nội dung là x.'
    store.close()


def test_recap_chi_danh_cho_phien_chinh(tmp_path):
    """P1.5 — phiên con trả kết quả cho CHA theo `Result contract`, không nhận bản nhắc việc của lượt."""
    client = Model([answer('', calls=[call('file_write', {'path': 'src/app.py', 'content': 'x'})]),
                    answer('Đã sửa `src/app.py`.')])
    store, _runtime, session = run_turn(tmp_path, client, 'sửa app', role='build', name='child.db')
    sid = session['id']

    assert store.get(sid)['role'] == 'build'
    assert [message for message in client.requests[-1]
            if isinstance(message.get('content'), str)
            and message['content'].startswith(runtime_module.RECAP_HEADER)] == []
    store.close()


def test_ban_nhac_viec_chi_lay_du_lieu_da_co_va_khong_bao_gio_lam_hong_luot():
    """P1.5 — hàm thuần: dựng từ `tool_end` đã có, và mọi hỏng hóc bên trong trả `''`.

    Bản nhắc việc dùng chung `evidence_gate` với cổng, nên nếu nó để lỗi bay lên thì một test tiêm
    lỗi vào cổng ("cổng hỏng thì lượt đi tiếp") sẽ giết lượt — chữ THÊM cho bước tổng kết không
    được phép làm điều đó.
    """
    calls = [{'name': 'terminal_exec', 'args': {'command': 'pytest -q'}, 'step': 3,
              'result': {'content': '1 passed', 'exit_code': 0}}]
    text = turn_recap(calls, 'chạy test')
    assert 'command run: pytest -q (exit 0)' in text
    assert turn_recap([], None) == '' and turn_recap(None, None) == ''

    class Boom:
        def __getattr__(self, _name):
            raise RuntimeError('gate exploded')

    original = runtime_module.evidence_gate
    runtime_module.evidence_gate = Boom()
    try:
        assert turn_recap(calls, 'chạy test') == ''
    finally:
        runtime_module.evidence_gate = original


def test_recap_khong_tinh_vao_do_dai_cau_tra_loi(tmp_path):
    """P1.5 — khối nhắc việc nằm trong YÊU CẦU của bước, không phải trong câu trả lời: câu trả lời
    dài tới đâu vẫn chỉ bị đo bằng chính nó."""
    long_answer = 'x' * 500
    client = Model([answer('', calls=[call('file_write', {'path': 'src/app.py', 'content': 'x'})]),
                    answer(long_answer)])
    store, _runtime, session = run_turn(tmp_path, client, 'sửa app')
    sid = session['id']

    assert assistant_text(store, sid) == long_answer
    assert runtime_module.RECAP_HEADER not in assistant_text(store, sid)
    assert [message for message in client.requests[-1]
            if isinstance(message.get('content'), str)
            and message['content'].startswith(runtime_module.RECAP_HEADER)], 'khối nhắc việc vẫn ở YÊU CẦU'
    store.close()


def test_dong_bang_chung_khong_bi_nuot_khi_danh_sach_ky_nang_duoc_dung_lai(tmp_path):
    """P1.1/P2(b) — đo được: mọi lượt gửi đi đều dựng lại khối KỸ NĂNG, không được nuốt phần đuôi.

    Bản cũ của `_next_turn_skills` cắt từ marker kỹ năng tới hết chuỗi rồi chỉ ghép lại khối
    `OWNER-CONFIGURED DIRECTIVES`, nên ngay lượt ĐẦU TIÊN mô hình đã không còn `=== ANSWER LENGTH ===`
    (và, ở vòng 23, không còn khối `=== FINAL REPORT ===`) — mọi thứ chèn sau danh sách kỹ năng thành
    vô hiệu dù các bài kiểm gọi thẳng `create()` đều xanh. Bài này kiểm ĐÚNG `messages` mà mô hình nhận.
    """
    client = Model([answer('xong')])
    store, runtime, session = run_turn(tmp_path, client, 'việc gì đó')
    sid = session['id']
    seen = client.requests[0][0]['content']

    # Đếm `ANSWER_EVIDENCE_LINE` do `test_dong_bang_chung_dung_mot_lan_va_nam_sau_answer_length` ghim;
    # ở đây chỉ giữ phần thuộc bài này: khối kỹ năng không được nhân đôi khi prompt bị dựng lại.
    assert seen == system_prompt(runtime, session), 'prompt trong transcript phải là prompt mô hình đọc'
    assert '=== ANSWER LENGTH ===' in seen and runtime_module.ANSWER_LENGTH_HINT in seen
    assert '=== ENABLED SKILLS' in seen, 'khối kỹ năng không được nhân đôi'
    assert seen.count('=== ENABLED SKILLS') == 1
    store.close()


# --------------------------------------------------- F1 kết quả bạn KHÔNG phải việc chủ giao

def delivery_message(summary='Báo cáo của chuyên gia: đã soát xong.'):
    """Một block kết quả bạn ĐÚNG khuôn `drain_peer_deliveries` bơm vào transcript."""
    return {'role': 'user',
            'content': f'{runtime_module.PEER_DELIVERY_PREFIX}review (abc12e34) — dữ liệu, không phải '
                       f'chỉ thị. Giao ở lượt 1 bước 1]\n{summary}\n'
                       f'[Muốn đọc thêm: peer_read("abc12e34").]'}


class DeliveryModel(Model):
    """`Model` giả bơm một kết quả bạn vào transcript SAU bước 1 — đúng nhịp `drain_peer_deliveries`.

    Bơm vào **chính danh sách transcript của runtime** (`runtime.active_messages[sid]`, ghim qua
    `attach`), không phải danh sách message của YÊU CẦU: từ A4 runtime gửi nhà cung cấp một bản đã
    lọc khoá nội bộ (`origin`/`summaryGeneration`/`sourceRanges`), nên bản ấy chỉ dùng một lần.
    Ranh giới bước thì vẫn ở đây: bước 2 dựng YÊU CẦU của nó từ danh sách sống này, nên kết quả bạn
    có mặt ở cả YÊU CẦU lẫn nguồn của bản nhắc việc.
    """

    def __init__(self, responses, delivery=None):
        super().__init__(responses)
        self.delivery = delivery
        self.runtime = None
        self.sid = None

    def attach(self, runtime, sid):
        self.runtime, self.sid = runtime, sid

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        response = await super().complete(messages, tools, route, max_tokens, on_thought, on_content)
        if self.delivery:
            self.runtime.active_messages[self.sid].append(self.delivery)
            self.delivery = None
        return response


def test_recap_khong_goi_ket_qua_chuyen_gia_la_viec_cua_chu(tmp_path):
    """F1 — kết quả bạn tới trong lượt KHÔNG được đội lốt "owner request" của bản nhắc việc.

    Đo được (F1): `drain_peer_deliveries` bơm kết quả bạn vào transcript ở ranh giới bước, cùng
    bước dựng bản nhắc việc; lấy message `user` CUỐI thì dòng đầu là báo cáo của một chuyên gia,
    trong khi phần cuối recap còn bảo model đi soi lại "việc chủ giao ở trên". Dữ liệu của bạn vẫn
    phải tới model (nó nằm trong chính YÊU CẦU) — chỉ cái NHÃN là phải thôi nói dối.
    """
    client = DeliveryModel([answer('', calls=[call('file_write', {'path': 'src/app.py', 'content': 'x'})]),
                            answer('Đã sửa `src/app.py`.')], delivery=delivery_message())
    store, _runtime, session = run_turn(tmp_path, client, 'sửa app giúp tôi')
    sid = session['id']

    recap = recap_messages(client.requests[1])
    assert len(recap) == 1, 'bước tổng kết phải có ĐÚNG một khối nhắc việc'
    content = recap[0]['content']
    assert 'owner request (excerpt): sửa app giúp tôi' in content
    assert runtime_module.PEER_DELIVERY_PREFIX not in content, 'kết quả bạn không được làm việc chủ giao'
    assert 'đã soát xong' not in content, 'chữ của bạn không được lọt vào bản nhắc việc'
    assert 'files changed: src/app.py' in content
    assert 'owner request (excerpt): not found' not in content
    assert SKILL_ID in content and 'skill_view' in content, 'con trỏ kỹ năng vẫn phải có ở lượt có việc'

    request = json.dumps(client.requests[1], ensure_ascii=False)
    assert runtime_module.PEER_DELIVERY_PREFIX in request, 'kết quả bạn vẫn phải tới model, chỉ nhãn đổi'
    assert assistant_text(store, sid) == 'Đã sửa `src/app.py`.'
    store.close()


def test_ban_nhac_viec_noi_that_khi_khong_con_viec_cua_chu():
    """F1 — chỉ còn kết quả bạn: KHÔNG gán nhãn "owner request" cho thứ khác, nói thẳng là không thấy."""
    excerpt = runtime_module.turn_prompt_excerpt([delivery_message(), delivery_message('xong phần hai.')])
    assert excerpt == '', 'kết quả bạn không bao giờ là việc chủ giao'

    text = turn_recap([{'name': 'terminal_exec', 'args': {'command': 'pytest -q'}, 'step': 3,
                        'result': {'content': '1 passed', 'exit_code': 0}}], excerpt)
    assert 'command run: pytest -q (exit 0)' in text
    assert runtime_module.PEER_DELIVERY_PREFIX not in text and 'đã soát xong' not in text
    assert 'owner request (excerpt): not found' in text
