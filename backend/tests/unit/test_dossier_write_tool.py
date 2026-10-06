"""`dossier_write` — cổng chất lượng chạy TRƯỚC, rồi mới ghi (vòng 27 đợt 4, B-3b/C-2).

Thứ tự ba bước là phần cốt lõi của lượt này: đọc sổ rồi chấm, `enforce` thì từ chối và **không chạm
đĩa**, chỉ khi qua (hoặc `warn`) mới gọi op của box. Ca kiểm ghim cả ba mặt: một hồ sơ suông bị từ
chối kèm cách sửa, một hồ sơ đủ bằng chứng đi qua và để lại hàng `E:` trong sổ theo dõi, và ba giá
trị `BOXFOX_RESEARCH_GATE` cho ra ba kết cục khác nhau — trong đó `off` **không** được ghi thành
`clear`, vì hồ sơ không ai chấm thì không phải hồ sơ sạch.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from agentbox.agent_core import limits, research_header, research_quality, research_runtime
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ nên pin `BOXFOX_REFORM=off` cho mọi bài
# (xem `tests/unit/conftest.py`). Bài nào cần đường mới thì đặt env tường minh trong bài.
pytestmark = pytest.mark.legacy_path


EXCERPT = ('Người bệnh đúng tuyến được hưởng 80% chi phí khám chữa bệnh, hồ sơ chuyển tuyến gồm '
           'giấy chuyển tuyến và bản tóm tắt điều trị theo quy định. ') * 3
PAYLOAD = {'docNumber': '75/2023/NĐ-CP', 'effectiveDate': '2023-12-01', 'validity': 'in_force',
           'issuingBody': 'Chính phủ',
           'appliesTo': 'người bệnh có thẻ BHYT chuyển tuyến đúng tuyến'}
URL = 'https://vanban.chinhphu.vn/?docid=75-2023'

MARKDOWN = """# Câu hỏi
Mức hưởng khi chuyển tuyến đúng tuyến là bao nhiêu?

## Phát hiện
Người bệnh đúng tuyến hưởng 80% chi phí khám chữa bệnh [r1] ({url}).

## Nguồn
- r1 — vanban.chinhphu.vn, tầng 1.

## Mâu thuẫn còn lại
Không thấy mâu thuẫn giữa các nguồn đã mở.

## Việc chưa làm
Chưa mở được bản tiếng Anh của văn bản.

## Phản biện
Bản phản biện độc lập đã đọc bản v1 và không nêu mâu thuẫn mới.
""".format(url=URL)

MARKDOWN_L1 = """# Câu hỏi
Mức hưởng khi chuyển tuyến đúng tuyến là bao nhiêu?

## Phát hiện
Người bệnh đúng tuyến hưởng 80% chi phí khám chữa bệnh [r1] ({url}).

## Nguồn
- r1 — vanban.chinhphu.vn, tầng 1.
""".format(url=URL)


class FixtureExecutor:
    """Box giả: ghi lại đúng tham số `dossier_write` và trả đường dẫn như worker thật."""

    def __init__(self, conflict_path=None):
        self.calls = []
        self.conflict_path = conflict_path

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        relative = args['path'] if self.conflict_path is None else self.conflict_path
        return {'relativePath': relative, 'version': 1, 'bytes': len(args['markdown'].encode('utf-8')),
                'sha1': 'abc123', 'files': [relative, args['path'].rsplit('/', 1)[0] + '/sources.jsonl']}

    async def cleanup(self, sid):
        pass


class FixtureModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.delenv('BOXFOX_RESEARCH_GATE', raising=False)
    store = SessionStore(tmp_path / 'sessions.db')
    executor = FixtureExecutor()
    runtime = HarnessRuntime(store, executor, FixtureModel())
    sid = runtime.create({'skills': []})['id']
    session = store.get(sid)
    yield store, runtime, sid, session, executor
    store.close()


def engine(fn, runtime, session, args):
    """Gọi THẲNG engine (sync hay async): biên dispatch của main đã bị Research gateway đóng
    (`RESEARCH_MAIN_READ_ONLY`) — biên ấy được ghim ở `tests/unit/test_research_gateway.py`.
    """
    out = fn(runtime, session, args)
    return asyncio.run(out) if inspect.isawaitable(out) else out


def seed_row(runtime, session, **overrides):
    args = {'claim': 'quy định chuyển tuyến đúng tuyến', 'url': URL, 'excerpt': EXCERPT,
            'payload': PAYLOAD}
    args.update(overrides)
    return engine(research_runtime.source_add, runtime, session, args)


def write(runtime, session, **overrides):
    """Gọi `dossier_write` (engine). Có brief thì ghi cho ĐÚNG việc của brief (một lượt một việc)."""
    args = {'level': 2, 'profile': 'health', 'markdown': MARKDOWN, 'title': 'Chuyển tuyến 2026'}
    args['researchId'] = research_runtime.research_config(session).get('researchId') or 'chuyen-tuyen-2026'
    args.update(overrides)
    return engine(research_runtime.dossier_write, runtime, session, args)


def test_a_dossier_without_sources_is_refused_before_anything_is_written(harness):
    store, runtime, sid, session, executor = harness
    with pytest.raises(ValueError) as exc:
        write(runtime, session, markdown='# Câu hỏi\nChuyển tuyến thế nào?\n')
    message = str(exc.value)
    assert research_quality.RESEARCH_QUALITY_PREFIX in message
    assert 'khắc phục:' in message
    assert executor.calls == [], 'cổng từ chối ⇒ KHÔNG có tệp nào được ghi'
    assert store.dossier_versions('chuyen-tuyen-2026') == []


def test_a_dossier_that_quotes_a_row_the_ledger_does_not_have_is_refused(harness):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    with pytest.raises(ValueError, match='research-sources-unproven'):
        write(runtime, session, markdown=MARKDOWN.replace('[r1]', '[r7]'))
    assert executor.calls == []


def test_a_dossier_with_evidence_lands_in_the_research_room_with_its_header(harness):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    answer = write(runtime, session)
    room = research_runtime.dossier_dir_for('chuyen-tuyen-2026')
    assert answer['relativePath'] == f'{room}/v1-chuyen-tuyen-2026.md', \
        'không brief ⇒ phòng vẫn đúng khuôn `.research/<slug>-<yyyymmdd-hhmm>`'
    assert answer['version'] == 1
    assert answer['gate']['ok'] is True and answer['gate']['mode'] == 'enforce'
    assert executor.calls[0][0] == 'dossier_write'
    header = research_header.parse_research_header(executor.calls[0][1]['markdown'])
    assert header.status == 'ok'
    assert (header.research_id, header.profile, header.level) == ('chuyen-tuyen-2026', 'health', 2)
    assert header.gate == 'clear' and header.rows == 1
    assert store.dossier_versions('chuyen-tuyen-2026') == [1]
    assert store.dossier_latest('chuyen-tuyen-2026')['relative_path'].endswith('v1-chuyen-tuyen-2026.md')


def test_the_written_dossier_leaves_a_journal_row_pointing_at_the_file(harness, monkeypatch):
    """Hàng `E:` là con trỏ kiểm chứng: mở sổ theo dõi của phiên là thấy tệp nào vừa được ghi."""
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    from agentbox.agent_core import session_journal

    caught = []
    original = session_journal.insert_row

    def capture(store_, sid_, kind, summary, **kwargs):
        caught.append((kind, summary, kwargs))
        return original(store_, sid_, kind, summary, **kwargs)

    monkeypatch.setattr(session_journal, 'insert_row', capture)
    answer = write(runtime, session)
    assert answer['journal'] is True
    assert caught and caught[0][0] == 'evidence'
    assert caught[0][2]['evidence'][0]['path'] == \
        f'{research_runtime.dossier_dir_for("chuyen-tuyen-2026")}/v1-chuyen-tuyen-2026.md'
    assert caught[0][2]['data']['research']['version'] == 1


def test_warn_mode_writes_the_dossier_and_says_what_is_missing(harness, monkeypatch):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    monkeypatch.setenv('BOXFOX_RESEARCH_GATE', 'warn')
    answer = write(runtime, session, markdown=MARKDOWN.replace('## Nguồn\n- r1 — vanban.chinhphu.vn, tầng 1.\n', ''))
    assert answer['version'] == 1 and answer['gate']['ok'] is False
    assert 'warning' in answer
    assert executor.calls, 'warn ⇒ vẫn ghi'
    assert research_header.parse_research_header(executor.calls[0][1]['markdown']).gate == 'warn'


def test_off_mode_still_writes_but_never_calls_the_dossier_clean(harness, monkeypatch):
    store, runtime, sid, session, executor = harness
    monkeypatch.setenv('BOXFOX_RESEARCH_GATE', 'off')
    answer = write(runtime, session, markdown='# Câu hỏi\nkhông nguồn, không mục\n')
    assert answer['gate']['mode'] == 'off' and answer['gate']['ok'] is True
    header = research_header.parse_research_header(executor.calls[0][1]['markdown'])
    assert header.gate == 'unbacked', 'cổng tắt ⇒ `unbacked`, KHÔNG phải `clear`'


def test_level_three_needs_the_critique_verdict_once_it_exists(harness):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    first = write(runtime, session, level=3, profile='health')
    assert first['version'] == 1
    notices = [row['data'] for row in store.events(sid) if row['type'] == 'notice']
    assert limits.RESEARCH_CRITIQUE_MISSING_CODE in [item['code'] for item in notices]
    assert research_header.parse_research_header(executor.calls[0][1]['markdown']).gate == 'warn', \
        'mức 3 chưa phản biện ⇒ `warn`, không phải `clear`'
    store.record_research_verification('chuyen-tuyen-2026', 1, sid, 'revise', ['thiếu mục Mâu thuẫn'],
                                      critic_session_id='critic-1', critic_answer_chars=900)
    with pytest.raises(ValueError, match='research-critique-missing'):
        write(runtime, session, level=3, profile='health', overwrite=True)
    good = write(runtime, session, level=3, profile='health', critique='ok', overwrite=True)
    assert good['version'] == 2
    assert research_header.parse_research_header(executor.calls[-1][1]['markdown']).critique == 'ok'


def test_a_bad_level_a_bad_profile_and_a_bad_slug_are_named_as_such(harness):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    with pytest.raises(ValueError, match='RESEARCH_LEVEL_INVALID'):
        write(runtime, session, level=7)
    with pytest.raises(ValueError, match='RESEARCH_PROFILE_INVALID'):
        write(runtime, session, profile='không-có')
    with pytest.raises(ValueError, match='RESEARCH_ID_INVALID'):
        write(runtime, session, researchId='Chuyen Tuyen 2026')
    with pytest.raises(ValueError, match='DOSSIER_INVALID'):
        write(runtime, session, markdown='   ')
    with pytest.raises(ValueError, match='RESEARCH_ID_INVALID'):
        write(runtime, session, researchId='')
    assert executor.calls == []


def test_a_path_the_box_writes_somewhere_else_is_refused(harness):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    executor.conflict_path = '.research/khac/v1-khac.md'
    with pytest.raises(ValueError, match='DOSSIER_WRITE_CONFLICT'):
        write(runtime, session)
    assert store.dossier_versions('chuyen-tuyen-2026') == [], 'không đăng ký gì khi box ghi sai chỗ'


def test_a_research_branch_reports_its_rows_up_and_never_writes_the_dossier(harness):
    """Hồ sơ do MAIN ghi (ledger subplan §A3.5): nhánh con giữ sổ, không giữ đường ghi hồ sơ.

    Ca này ghim cả hai mặt của bất biến "không mở quyền ghi cho con": tên công cụ KHÔNG có trong
    `config['tools']` của nhánh, và một lời gọi thẳng cũng bị cổng vai từ chối — nếu chỉ thiếu tên
    công cụ thì một đường gọi khác (dispatch trực tiếp) vẫn ghi được hồ sơ, và hàng rào sẽ là trang trí.
    """
    store, runtime, sid, session, executor = harness
    engine(research_runtime.research_brief, runtime, session,
           {'tier': 2, 'jobProfile': 'health', 'question': 'Mức hưởng chuyển tuyến?',
            'rationale': 'văn bản chính thống'})
    research_id = research_runtime.research_config(store.get(sid))['researchId']
    branch = runtime.create({'skills': []}, parent_id=sid, role='research')
    child = store.get(branch['id'])
    assert 'dossier_write' not in child['config']['tools'], 'nhánh con không có đường ghi hồ sơ'
    assert 'source_add' in child['config']['tools'], 'nhưng nó vẫn ghi được sổ'
    # Dòng sổ do NHÁNH ghi vẫn thuộc sổ của VIỆC (chủ sở hữu là phiên giữ brief).
    seed_row(runtime, child)
    assert store.source_count(sid) == 1 and store.source_count(child['id']) == 0
    with pytest.raises(PermissionError, match='for the orchestrator'):
        engine(research_runtime.dossier_write, runtime, child,
               {'researchId': research_id, 'level': 2, 'profile': 'health',
                'markdown': MARKDOWN, 'title': 'Chuyển tuyến'})
    assert [name for name, _args, _sid in executor.calls] == ['journal_append'], \
        'lượt bị từ chối: chỉ hàng `D:` của brief, không có lệnh nào chạm tệp hồ sơ'
    # Và main ghi được — trên đúng sổ ấy.
    room = research_runtime.research_config(store.get(sid))['dossierDir']
    answer = write(runtime, session, researchId=research_id)
    assert answer['relativePath'] == f'{room}/v1-{research_id}.md'
    assert answer['gate']['ok'] is True, 'cổng chấm trên sổ của việc (dòng của nhánh đã vào đó)'


def test_a_table_sent_as_the_documented_list_shape_reaches_the_box(harness):
    """Lược đồ `dossier_write.tables` là LIST ⇒ bảng phải tới box, không được mất âm thầm.

    Đo được trước khi vá: chỉ `dict` mới đi tiếp, nên model gửi đúng lược đồ bị **mất bảng**, và
    mapping rỗng `{}` còn bị biến thành `[{}]` (box từ chối cả lần ghi vì tên bảng rỗng).
    """
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    table = {'name': 'gia-theo-quy', 'markdown': '| Quý | Giá |\n| --- | --- |\n| Q3/2026 | 3 100 |\n'}
    write(runtime, session, tables=[table])
    assert executor.calls[-1][1]['tables'] == [table]
    write(runtime, session, tables={'dung-luong': table['markdown']})
    assert executor.calls[-1][1]['tables'] == [{'name': 'dung-luong', 'markdown': table['markdown']}]
    write(runtime, session, tables={}), 'gọi lần thứ ba: không có bảng nào'
    assert executor.calls[-1][1]['tables'] == [], 'không bảng ⇒ list rỗng, KHÔNG phải `[{}]`'
    assert store.dossier_versions('chuyen-tuyen-2026') == [1, 2, 3], 'ba bản, không bản nào bị bỏ'


def test_only_the_right_roles_may_write_a_dossier_or_read_a_status(harness):
    store, runtime, sid, session, executor = harness
    other = runtime.create({'skills': []}, parent_id=sid, role='plan-review')
    # Cổng vai nằm trong ENGINE (dispatch của main đã đóng — xem `engine`), nên bài này gọi thẳng.
    for fn, args in ((research_runtime.dossier_write, {'researchId': 'x-y', 'level': 1, 'profile': 'law',
                                                       'markdown': '# Câu hỏi\nx\n'}),
                     (research_runtime.research_verify, {'researchId': 'x-y', 'version': 1,
                                                         'verdict': 'ok'}),
                     (research_runtime.research_status, {'researchId': 'x-y'}),
                     (research_runtime.research_brief, {'tier': 2, 'jobProfile': 'law',
                                                        'question': 'x'})):
        with pytest.raises(PermissionError):
            engine(fn, runtime, store.get(other['id']), args)


# --- #6025: brief có ý kiến chủ nhà ⇒ mục soi ý kiến ba nhãn là điều kiện để ghi ----------


REVIEW_WITH_LABELS = """### Soi ý kiến chủ nhà
- ủng hộ: thông tư mới nâng mức hưởng [r1]
- phản bác: không nguồn nào nói giảm (https://baochinhphu.vn/b)
- chưa chắc: chưa mở được bản gốc của phụ lục [r1]
"""


def dossier_calls(executor):
    """Chỉ các lời gọi GHI HỒ SƠ — hàng `D:` của brief đi qua cùng box nên phải lọc ra."""
    return [item for item in executor.calls if item[0] == 'dossier_write']


def with_owner_views(runtime, session, views=('phí chuyển tuyến sẽ tăng trong 2026',)):
    return engine(research_runtime.research_brief, runtime, session, {
        'tier': 2, 'jobProfile': 'health', 'question': 'Mức hưởng chuyển tuyến 2026?',
        'rationale': 'cần dẫn nguồn văn bản', 'ownerViews': list(views)})


def test_owner_views_in_the_brief_make_the_three_label_review_a_condition(harness):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    brief = with_owner_views(runtime, session)
    assert brief['ownerViews'], 'brief phải giữ ý kiến chủ nhà'
    with pytest.raises(ValueError) as exc:
        write(runtime, session)
    assert 'research-owner-views-missing' in str(exc.value)
    assert 'ba nhãn' in str(exc.value)
    assert not dossier_calls(executor), 'cổng từ chối ⇒ KHÔNG có tệp nào được ghi'


def test_the_same_dossier_passes_once_the_review_carries_the_three_labels(harness):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    with_owner_views(runtime, session)
    answer = write(runtime, session, review=REVIEW_WITH_LABELS)
    assert dossier_calls(executor)[0][0] == 'dossier_write'
    assert answer['gate']['ok'] is True
    assert 'research-owner-views-missing' not in answer['gate']['issues']


def test_a_review_label_without_a_source_is_still_refused(harness):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    with_owner_views(runtime, session)
    bare = ('### Soi ý kiến chủ nhà\n- ủng hộ: có lẽ đúng\n- phản bác: có lẽ sai\n'
            '- chưa chắc: chưa rõ\n')
    with pytest.raises(ValueError) as exc:
        write(runtime, session, review=bare)
    assert 'nhãn chưa kèm nguồn' in str(exc.value)
    assert not dossier_calls(executor)


def test_a_brief_without_owner_views_never_asks_for_the_label_section(harness):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    engine(research_runtime.research_brief, runtime, session, {
        'tier': 2, 'jobProfile': 'health', 'question': 'Mức hưởng chuyển tuyến 2026?',
        'rationale': 'cần dẫn nguồn văn bản'})
    answer = write(runtime, session)
    assert 'research-owner-views-missing' not in answer['gate']['issues']


def test_a_dossier_for_another_job_is_refused_while_a_brief_is_open(harness):
    """Một lượt một việc: brief mở việc nào thì hồ sơ ghi cho việc ấy.

    Bản trước nhận `researchId` lạ rồi vẫn ghi vào PHÒNG của brief ⇒ tệp hồ sơ mang hai danh tính
    (header ghi id này, hàng `E:` và bản ghi hồ sơ trỏ việc khác), và bản vá phòng hồ sơ đã bắt được
    đúng chỗ lệch ấy.
    """
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    brief = engine(research_runtime.research_brief, runtime, session, {
        'tier': 2, 'jobProfile': 'health', 'question': 'Mức hưởng chuyển tuyến 2026?',
        'rationale': 'văn bản chính thống'})
    other_id = 'viec-khac-2026'
    assert other_id != brief['researchId']
    with pytest.raises(ValueError) as exc:
        write(runtime, session, researchId=other_id)
    assert limits.RESEARCH_BRIEF_TAKEN_CODE in str(exc.value)
    assert not dossier_calls(executor), 'cổng từ chối ⇒ không tệp nào được ghi'


def test_a_room_that_does_not_belong_to_the_job_is_refused_not_a_nameerror(harness):
    """Phòng hồ sơ phải là `.research/<researchId>-<yyyymmdd-hhmm>` của ĐÚNG việc đang ghi.

    Bản trước so `path` với chính `dossier_dir` (vòng lặp rỗng) và `DOSSIER_DIR_MISMATCH_CODE` chưa
    từng được import ⇒ một phòng sai đi thẳng xuống đĩa, còn nhánh báo lỗi thì `NameError`.
    """
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)
    session.setdefault('config', {})['research'] = {
        'researchId': 'chuyen-tuyen-2026', 'tier': 2, 'jobProfile': 'health',
        'question': 'Mức hưởng chuyển tuyến?', 'dossierDir': '.research/phong-cua-viec-khac-20260101-0000',
        'ceilingSeconds': 1200, 'turn': int(runtime.active_turn.get(sid) or 0)}
    with pytest.raises(ValueError) as exc:
        write(runtime, session)
    assert limits.DOSSIER_DIR_MISMATCH_CODE in str(exc.value)
    assert not dossier_calls(executor), 'không có lệnh nào chạm tệp hồ sơ'


def test_a_version_that_the_room_already_has_is_skipped_not_a_dead_end(harness):
    """Bản `v1` đã có trong PHÒNG mà chỉ mục chưa biết ⇒ ghi `v2`, không chết ở `DOSSIER_VERSION_TAKEN`.

    Op của box từ chối ghi đè một bản đã có (bản cũ là bằng chứng), mà số bản lại tính từ chỉ mục:
    một tệp do lượt trước để lại (ghi hỏng giữa chừng) làm câu lệnh hỏng lặp lại y hệt ở mọi lần thử,
    trong khi cách sửa câu lỗi mách ("ghi bản kế") không thi hành được — lượt kiểm thử `v27d` (F-A).
    """
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)

    class TakenOnceExecutor(FixtureExecutor):
        async def execute(self, name, args, sid):
            self.calls.append((name, args, sid))
            if args['path'].rsplit('/', 1)[-1].startswith('v1-'):
                raise RuntimeError('DOSSIER_VERSION_TAKEN: %s already exists; write the next version'
                                   % args['path'])
            relative = args['path']
            return {'relativePath': relative, 'version': 2, 'bytes': len(args['markdown'].encode('utf-8')),
                    'sha1': 'abc123', 'files': [relative]}

    runtime.executor = TakenOnceExecutor()
    answer = write(runtime, session)
    assert answer['version'] == 2 and answer['relativePath'].endswith('v2-chuyen-tuyen-2026.md')
    assert store.dossier_versions('chuyen-tuyen-2026') == [2]
    assert research_header.parse_research_header(runtime.executor.calls[-1][1]['markdown']).version == 2, \
        'header phải mang số bản THẬT SỰ được ghi'
    assert [call[1]['path'].rsplit('/', 1)[-1] for call in runtime.executor.calls][-2:] == \
        ['v1-chuyen-tuyen-2026.md', 'v2-chuyen-tuyen-2026.md'], 'thử bản 1 rồi bản 2, không nhảy số'


def test_a_version_loop_that_never_lands_gives_up_and_says_which_code(harness):
    """Hết ngân sách thử ⇒ ném NGUYÊN VĂN lỗi của box, không nuốt và không thử vô hạn."""
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session)

    class AlwaysTakenExecutor(FixtureExecutor):
        async def execute(self, name, args, sid):
            self.calls.append((name, args, sid))
            raise RuntimeError('DOSSIER_VERSION_TAKEN: %s already exists' % args['path'])

    runtime.executor = AlwaysTakenExecutor()
    with pytest.raises(RuntimeError, match='DOSSIER_VERSION_TAKEN'):
        write(runtime, session)
    assert len(runtime.executor.calls) == limits.DOSSIER_VERSION_ATTEMPTS_MAX
    assert store.dossier_versions('chuyen-tuyen-2026') == [], 'không có bản nào được đăng ký'
