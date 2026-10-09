"""F30 — một hình dạng duy nhất cho output tràn ra tệp.

Trước đợt này, hai producer (`host_executor._spill` và `worker.shell`) trả **đường dẫn trần**, còn
job ledger lại đòi **dict ref** (`artifactId`/`version`/`contentHash`), nên phần đã tràn ra tệp
không vào được chuỗi bằng chứng có hash. Bài kiểm này ghim ba thứ:

- `output_refs.spill` là chỗ duy nhất quyết định ngưỡng/bản xem trước/tên thư mục;
- worker trong box (script độc lập, không import được package) giữ **đúng** những số ấy;
- cổng bằng chứng ưu tiên ref có cấu trúc và mang theo hash của tệp.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from agentbox.agent_core import evidence_gate as gate
from agentbox.sandbox import output_refs, worker
from agentbox.sandbox import host_executor as host


def test_text_under_the_threshold_is_returned_untouched(tmp_path):
    text = 'ngắn thôi'
    content, ref = output_refs.spill(tmp_path, text)

    assert (content, ref) == (text, None), 'dưới trần thì không tạo tệp, không ref'
    assert list(tmp_path.iterdir()) == []


def test_over_the_threshold_the_file_lands_where_the_ui_reads_it(tmp_path):
    text = 'x' * (output_refs.SPILL_THRESHOLD_CHARS + 1)
    content, ref = output_refs.spill(tmp_path, text)

    assert ref['path'].startswith(output_refs.SPILL_DIR + '/'), 'phần tràn phải nằm chỗ UI đọc được'
    assert (tmp_path / ref['path']).read_text(encoding='utf-8') == text, 'tệp phải giữ NGUYÊN văn'
    assert len(content) == output_refs.SPILL_PREVIEW_CHARS + len(output_refs.SPILL_MARKER)
    assert content.endswith(output_refs.SPILL_MARKER)


def test_the_ref_carries_the_hash_of_what_is_in_the_file(tmp_path):
    text = 'y' * (output_refs.SPILL_THRESHOLD_CHARS + 5)
    _, ref = output_refs.spill(tmp_path, text)

    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    assert ref['contentHash'] == digest, 'hash phải của chính nội dung, không phải của bản xem trước'
    assert ref['version'] == 1 and ref['bytes'] == len(text.encode('utf-8'))
    assert (tmp_path / ref['path']).read_bytes() == text.encode('utf-8')


def test_the_same_text_twice_gets_the_same_artifact_id(tmp_path):
    text = 'z' * (output_refs.SPILL_THRESHOLD_CHARS + 1)
    _, first = output_refs.spill(tmp_path, text)
    _, second = output_refs.spill(tmp_path, text)

    assert first['path'] != second['path'], 'mỗi lần spill một tệp, không ghi đè lần trước'
    assert first['artifactId'] == second['artifactId'], 'id suy từ nội dung nên hai bản giống nhau chung id'


def test_the_hash_describes_the_bytes_that_landed_on_disk(tmp_path):
    """Hash và số byte phải tả ĐÚNG tệp, kể cả khi nội dung có xuống dòng.

    `write_text` dịch `\n` thành `\r\n` trên Windows, nên hash tính trên chuỗi sẽ nói về một tệp
    khác với tệp đã ghi — mất đúng tính chất mà F30 dựng ra. Bài kiểm này so hash với `read_bytes()`.
    """
    text = ('dong ' + 'x' * 40 + '\n') * 500
    assert len(text) > output_refs.SPILL_THRESHOLD_CHARS
    _, ref = output_refs.spill(tmp_path, text)

    raw = (tmp_path / ref['path']).read_bytes()
    assert ref['contentHash'] == hashlib.sha256(raw).hexdigest()
    assert ref['bytes'] == len(raw) == len(text.encode('utf-8'))
    # Trên Linux hai cách ghi ra cùng byte, nên ca này một mình không bắt được lỗi dịch xuống dòng
    # của Windows; ghim thêm cách ghi để không ai quay lại `write_text`.
    assert 'target.write_bytes(raw)' in Path(output_refs.__file__).read_text(encoding='utf-8')


def test_a_failed_write_keeps_the_command_result_and_says_the_file_is_missing(tmp_path):
    """Không ghi được tệp (đĩa đầy, chỉ-đọc, `tools` là một tệp) thì vẫn phải trả kết quả lệnh.

    Bản trước F30 cắt im lặng; bản gộp hai producer thì để `OSError` nổi lên thành
    `HOST_TOOL_FAILED`, mất cả exit code lẫn đầu ra. Nay: bản xem trước + một câu nói rõ.
    """
    blocker = tmp_path / 'tools'
    blocker.write_text('tệp, không phải thư mục')
    text = 'q' * (output_refs.SPILL_THRESHOLD_CHARS + 1)

    content, ref = output_refs.spill(tmp_path, text, target_dir=blocker)

    assert ref is None
    assert content.endswith(output_refs.SPILL_FAILED_MARKER)
    assert len(content) == output_refs.SPILL_PREVIEW_CHARS + len(output_refs.SPILL_FAILED_MARKER)


def test_the_box_worker_has_the_same_ref_and_the_same_cut_rule():
    """Worker giữ bản sao: ghim cả hình dạng ref lẫn luật cắt, không chỉ bốn con số."""
    assert worker._spill_ref('a/b.txt', 'nội dung'.encode('utf-8')) == \
        output_refs.output_ref('a/b.txt', 'nội dung')
    assert worker._spill_content('x' * 17000, None) == 'x' * 17000, 'không có tệp thì không được cắt'
    assert worker._spill_content('x' * 25000, 'a/b.txt') == \
        'x' * output_refs.SPILL_PREVIEW_CHARS + output_refs.SPILL_MARKER


def test_the_box_worker_degrades_a_failed_write_like_the_host_does(tmp_path, monkeypatch):
    """Box ghi hỏng thì vẫn phải trả đầu ra: trước đây `OSError` nổi lên thành 'Sandbox unavailable'.

    `_spill` là chỗ quyết định, nên ca này gọi thẳng nó với `WORKSPACE` trỏ vào một tệp — không cần
    box thật, không cần chạy lệnh.
    """
    text = 'q' * (output_refs.SPILL_THRESHOLD_CHARS + 1)
    blocker = tmp_path / 'ws-la-tap-tin'
    blocker.write_text('tệp, không phải thư mục')

    assert worker._spill('ngắn') == (None, None, False), 'dưới trần: không tệp, không hỏng'
    monkeypatch.setattr(worker, 'WORKSPACE', blocker)
    assert worker._spill(text) == (None, None, True), 'ghi hỏng phải được báo riêng, không ném'
    assert worker._spill_content(text, None) == text, 'không có tệp thì trả nguyên văn'


def test_the_box_worker_writes_the_file_and_the_ref_when_it_can(tmp_path, monkeypatch):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    text = 'q' * (output_refs.SPILL_THRESHOLD_CHARS + 1)
    monkeypatch.setattr(worker, 'WORKSPACE', workspace)

    artifact, ref, failed = worker._spill(text)

    assert failed is False and artifact.startswith(output_refs.SPILL_DIR + '/')
    assert (workspace / artifact).read_bytes() == text.encode('utf-8')
    assert ref == output_refs.output_ref(artifact, text)
    assert worker._spill_content(text, artifact) == \
        text[:output_refs.SPILL_PREVIEW_CHARS] + output_refs.SPILL_MARKER
