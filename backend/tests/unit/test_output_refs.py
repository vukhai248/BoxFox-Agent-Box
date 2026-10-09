"""F30 — một hình dạng duy nhất cho output tràn ra tệp.

Trước đợt này, hai producer (`host_executor._spill` và `worker.shell`) trả **đường dẫn trần**, còn
job ledger lại đòi **dict ref** (`artifactId`/`version`/`contentHash`), nên phần đã tràn ra tệp
không vào được chuỗi bằng chứng có hash. Bài kiểm này ghim ba thứ:

- `output_refs.spill` là chỗ duy nhất quyết định ngưỡng/bản xem trước/tên thư mục;
- worker trong box (script độc lập, không import được package) giữ **đúng** những số ấy;
- cổng bằng chứng ưu tiên ref có cấu trúc và mang theo hash của tệp.
"""
from __future__ import annotations

import sys
from pathlib import Path

from agentbox.agent_core import evidence_gate as gate
from agentbox.sandbox import output_refs, worker
from agentbox.sandbox import host_executor as host


def test_text_under_the_threshold_is_returned_untouched(tmp_path):
    text = 'ngắn thôi'
    content, path, ref = output_refs.spill(tmp_path, text)

    assert (content, path, ref) == (text, None, None), 'dưới trần thì không tạo tệp, không ref'
    assert list(tmp_path.iterdir()) == []


def test_over_the_threshold_the_file_lands_where_the_ui_reads_it(tmp_path):
    text = 'x' * (output_refs.SPILL_THRESHOLD_CHARS + 1)
    content, path, ref = output_refs.spill(tmp_path, text)

    assert path.startswith(output_refs.SPILL_DIR + '/'), 'phần tràn phải nằm chỗ UI đọc được'
    assert (tmp_path / path).read_text(encoding='utf-8') == text, 'tệp phải giữ NGUYÊN văn'
    assert len(content) == output_refs.SPILL_PREVIEW_CHARS + len(output_refs.SPILL_MARKER)
    assert content.endswith(output_refs.SPILL_MARKER)


def test_the_ref_carries_the_hash_of_what_is_in_the_file(tmp_path):
    import hashlib

    text = 'y' * (output_refs.SPILL_THRESHOLD_CHARS + 5)
    _, path, ref = output_refs.spill(tmp_path, text)

    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    assert ref['contentHash'] == digest, 'hash phải của chính nội dung, không phải của bản xem trước'
    assert ref['path'] == path and ref['version'] == 1
    assert ref['bytes'] == len(text.encode('utf-8'))
    assert (tmp_path / path).read_bytes() == text.encode('utf-8')


def test_the_same_text_twice_gets_the_same_artifact_id(tmp_path):
    text = 'z' * (output_refs.SPILL_THRESHOLD_CHARS + 1)
    _, first_path, first = output_refs.spill(tmp_path, text)
    _, second_path, second = output_refs.spill(tmp_path, text)

    assert first_path != second_path, 'mỗi lần spill một tệp, không ghi đè lần trước'
    assert first['artifactId'] == second['artifactId'], 'id suy từ nội dung nên hai bản giống nhau chung id'


def test_the_box_worker_keeps_the_same_spill_numbers():
    """Worker là script trong box: nó không import được `output_refs`, nên phải có bài ghim.

    Số lệch nhau giữa hai bên là kiểu lỗi im lặng: bản host cắt ở 20000 còn box cắt ở 15000 thì
    không ai đỏ, chỉ có model nhận hai độ dài khác nhau tuỳ chế độ chạy.
    """
    source = Path(worker.__file__).read_text(encoding='utf-8')

    assert 'SPILL_THRESHOLD_CHARS = %d' % output_refs.SPILL_THRESHOLD_CHARS in source
    assert 'SPILL_PREVIEW_CHARS = %d' % output_refs.SPILL_PREVIEW_CHARS in source
    assert "SPILL_DIR = '%s'" % output_refs.SPILL_DIR in source
    assert 'SPILL_MARKER = %r' % output_refs.SPILL_MARKER in source
    assert worker.SPILL_THRESHOLD_CHARS == output_refs.SPILL_THRESHOLD_CHARS
    assert worker.SPILL_PREVIEW_CHARS == output_refs.SPILL_PREVIEW_CHARS
    assert worker.SPILL_DIR == output_refs.SPILL_DIR


def test_the_host_executor_has_no_second_copy_of_the_numbers():
    assert host.READ_TRUNCATE_ARTIFACT_CHARS is output_refs.SPILL_THRESHOLD_CHARS
    assert host.OUTPUT_PREVIEW_CHARS is output_refs.SPILL_PREVIEW_CHARS
    source = Path(host.__file__).read_text(encoding='utf-8')
    assert 'READ_TRUNCATE_ARTIFACT_CHARS = 20000' not in source, 'không được quay lại bản số thứ hai'


def test_the_acceptance_bench_uses_the_same_two_numbers():
    """Sàn đo (`scripts/eval/work_acceptance_bench.py`) phải cắt đúng như box thật.

    Sàn là thứ quyết định điểm của cả một vòng đo, nên nếu nó lệch khỏi `output_refs` thì bảng điểm
    vẫn xanh trong khi box thật cắt ở chỗ khác — kiểu lệch không ai thấy.
    """
    eval_dir = Path(__file__).resolve().parents[3] / 'scripts' / 'eval'
    sys.path.insert(0, str(eval_dir))
    try:
        import work_acceptance_bench as bench
    finally:
        sys.path.pop(0)

    assert bench.WorkspaceExecutor.TERMINAL_SPILL_CHARS == output_refs.SPILL_THRESHOLD_CHARS
    assert bench.WorkspaceExecutor.TERMINAL_CONTENT_CHARS == output_refs.SPILL_PREVIEW_CHARS


def test_the_evidence_gate_prefers_the_structured_ref(tmp_path):
    text = 'w' * (output_refs.SPILL_THRESHOLD_CHARS + 1)
    _, path, ref = output_refs.spill(tmp_path, text)
    call = {'name': 'terminal_exec', 'args': {'command': 'ls -la'}, 'step': 1,
            # Cả hai cùng có: ref có cấu trúc phải thắng đường dẫn trần.
            'result': {'content': 'ok', 'exit_code': 0, 'artifact': 'duong/dan/tran.txt',
                       'outputRef': ref}}

    fragment, = gate.artifacts_from_calls([call])

    assert fragment['artifact'] == path
    assert fragment['sha256'] == ref['contentHash'] and fragment['bytes'] == ref['bytes']
