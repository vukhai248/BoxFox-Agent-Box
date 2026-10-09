"""Một hình dạng duy nhất cho phần output tràn ra tệp (F30).

Hai producer của "artifact output" (host executor và worker trong box) từng tự cắt và tự trả một
**đường dẫn trần**, trong khi job ledger lại đòi một **dict ref** (`artifactId`/`version`/
`contentHash`). Hai hình dạng ấy không nói được với nhau, nên phần đã tràn ra tệp không đi vào
được chuỗi bằng chứng có hash — đúng khoảng trống "output refs thống nhất" của F30.

Module này là chỗ duy nhất định nghĩa ngưỡng, bản xem trước, thư mục và ref chuẩn. Worker trong box
là script độc lập (không import được package này), nên nó giữ bản sao bằng số và
`tests/unit/test_output_refs.py` ghim hai bản khớp nhau — thay vì để hai chỗ trôi khỏi nhau im lặng.
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
#: Thư mục chứa phần tràn, tương đối workspace — chỗ UI đọc được (W8.A4.3).
SPILL_DIR = '.generated_artifacts/tools'


def output_ref(path, data, *, version=1):
    """Ref chuẩn của một tệp output: đúng bộ khoá job ledger đòi, cộng đường dẫn để mở.

    `artifactId` suy từ chính nội dung, nên hai lần spill cùng nội dung ra cùng một id — ledger
    không phải phân biệt hai bản giống nhau.
    """
    raw = data.encode('utf-8') if isinstance(data, str) else bytes(data)
    content = hashlib.sha256(raw).hexdigest()
    return {'artifactId': 'spill-' + content[:20], 'version': version, 'contentHash': content,
            'path': path, 'bytes': len(raw)}


def spill(workspace, text, *, threshold=SPILL_THRESHOLD_CHARS, preview=SPILL_PREVIEW_CHARS):
    """Ghi phần tràn vào `SPILL_DIR` và trả `(content, path, ref)`.

    Dưới ngưỡng thì trả nguyên văn và `None` cho cả hai — nơi gọi không phải tự đo lại ngưỡng.
    """
    if len(text) <= threshold:
        return text, None, None
    target = Path(workspace) / SPILL_DIR / (uuid.uuid4().hex + '.txt')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
    path = target.relative_to(Path(workspace)).as_posix()
    return text[:preview] + SPILL_MARKER, path, output_ref(path, text)
