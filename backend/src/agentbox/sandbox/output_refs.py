"""Một hình dạng duy nhất cho phần output tràn ra tệp (F30).

Hai producer của "artifact output" (host executor và worker trong box) từng tự cắt và tự trả một
**đường dẫn trần**, trong khi job ledger lại đòi một **dict ref** (`artifactId`/`version`/
`contentHash`). Hai hình dạng ấy không nói được với nhau, nên phần đã tràn ra tệp không đi vào
được chuỗi bằng chứng có hash — đúng khoảng trống "output refs thống nhất" của F30.

Module này là chỗ duy nhất định nghĩa ngưỡng, bản xem trước, thư mục và ref chuẩn. Worker trong box
là script độc lập (không import được package này), nên nó giữ bản sao bằng số và
`tests/unit/test_output_refs.py` ghim hai bản khớp nhau — thay vì để hai chỗ trôi khỏi nhau im lặng.

Chỗ ghi tệp khác nhau theo chế độ, và đó là chủ ý: trong box, tệp nằm trong workspace của box (UI
đọc được); trên host, tệp nằm trong `artifacts_dir` của app (profile riêng, **không** ghi vào thư mục
dự án của chủ) — `target_dir` là tham số để nơi gọi truyền chỗ ấy vào.
"""
import hashlib
import uuid
from pathlib import Path

#: Trần trả thẳng cho model: vượt mức này thì phần đầy đủ ra tệp.
SPILL_THRESHOLD_CHARS = 20000
#: Số ký tự còn lại trong câu trả lời khi đã spill.
SPILL_PREVIEW_CHARS = 15000
#: Dấu hiệu nói rõ phần bị cắt nằm ở đâu, không để model đoán là đã có đủ.
SPILL_MARKER = '\n[truncated; see artifact]'
#: Ghi tệp không xong: vẫn phải nói ra, không cắt im lặng (bản cũ trả về bản xem trước trần).
SPILL_FAILED_MARKER = '\n[truncated; artifact write failed]'
#: Thư mục chứa phần tràn, tương đối workspace — chỗ UI đọc được (W8.A4.3).
SPILL_DIR = '.generated_artifacts/tools'


def output_ref(path, data):
    """Ref chuẩn của một tệp output: đúng bộ khoá job ledger đòi, cộng đường dẫn để mở.

    `artifactId` suy từ chính nội dung, nên hai lần spill cùng nội dung ra cùng một id — ledger
    không phải phân biệt hai bản giống nhau. `data` là chuỗi đã mã hoá UTF-8 **đúng như byte đã ghi
    xuống đĩa**; nơi gọi ghi byte thì hash mới tả đúng tệp.
    """
    raw = data.encode('utf-8')
    content = hashlib.sha256(raw).hexdigest()
    return {'artifactId': 'spill-' + content[:20], 'version': 1, 'contentHash': content,
            'path': path, 'bytes': len(raw)}


def spill(root, text, *, target_dir=None):
    """Ghi phần tràn và trả `(content, ref)`; dưới ngưỡng thì trả nguyên văn cùng `None`.

    `root` là mốc tính đường dẫn trong ref. Host mode ghi artifact vào profile của app (ngoài
    workspace người dùng), nên đường dẫn ngoài `root` được trả **tuyệt đối**: người đọc tệp cần một
    đường mở được, không cần một đường đẹp. `target_dir` mặc định là `<root>/.generated_artifacts/tools`.
    """
    if len(text) <= SPILL_THRESHOLD_CHARS:
        return text, None
    root_path = Path(root)
    directory = Path(target_dir) if target_dir is not None else root_path / SPILL_DIR
    target = directory / (uuid.uuid4().hex + '.txt')
    raw = text.encode('utf-8')
    try:
        # Ghi BYTE, không ghi văn bản: `write_text` dịch `\n` thành `\r\n` trên Windows, nên hash và
        # số byte sẽ nói về một chuỗi khác với chuỗi đã nằm trên đĩa — hỏng đúng thứ F30 dựng ra.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    except OSError:
        # Không ghi được (đĩa đầy, chỉ-đọc, `tools` là một tệp…) thì lượt lệnh vẫn phải sống: trả bản
        # xem trước kèm câu nói rõ phần đầy đủ đã mất, thay vì để `execute()` biến cả kết quả lệnh
        # thành `HOST_TOOL_FAILED` — và thay vì cắt im lặng như bản trước F30.
        return text[:SPILL_PREVIEW_CHARS] + SPILL_FAILED_MARKER, None
    try:
        path = target.relative_to(root_path).as_posix()
    except ValueError:
        path = str(target)
    return text[:SPILL_PREVIEW_CHARS] + SPILL_MARKER, output_ref(path, text)
