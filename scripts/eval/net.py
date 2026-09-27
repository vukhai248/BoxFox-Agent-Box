"""Chỗ DUY NHẤT trong `scripts/eval/` được phép mở socket.

Trước P0a, cả `scripts/eval` không hề gọi mạng: `--dry-run` là mặc định và
`test_eval_setup.py` khẳng định điều đó bằng cách chặn `socket.socket`. Kế hoạch
v2 (mục 8.7 + P0a) đòi ba đường gọi thật — chạy ca qua harness, gọi giám khảo LLM
qua router, và đo ống tìm (gọi SearXNG/nhà cung cấp thật) — nên bất biến cũ phải
nới đúng một chỗ, không phải rải khắp thư mục.

Luật mới, được `test_eval_sources_import_no_network_library` ghim:

* **chỉ** `net.py` được `import` thư viện mạng (`urllib`, `http`, `ssl`…);
* mọi mô-đun khác trong `scripts/eval/*.py` vẫn thuần stdlib-không-mạng;
* `net.py` chỉ được **gọi** từ trong thân hàm của đường `--execute` / cổng chi
  tiền, không bao giờ ở cấp mô-đun, nên `--dry-run` không mở socket.

Không có phụ thuộc ngoài: chỉ `urllib.request` (stdlib).
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 120.0


class NetError(RuntimeError):
    """Lỗi mạng/máy chủ không sinh ra từ một mã HTTP cụ thể (DNS, refused, timeout)."""


class HttpStatusError(NetError):
    """Máy chủ trả một mã HTTP >= 400; giữ cả mã lẫn thân để bên gọi tự quyết thử lại."""

    def __init__(self, status: int, body: str):
        self.status = int(status)
        self.body = body or ''
        super().__init__(f'HTTP {self.status}: {self.body[:200]}')


def request_json(url: str, *, method: str = 'GET', payload: dict | None = None,
                 headers: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Gọi một endpoint JSON và trả đối tượng đã parse.

    Thân rỗng trả `{}`. Mã >= 400 ⇒ `HttpStatusError` (bên gọi tự quyết thử lại
    5xx). Lỗi transport ⇒ `NetError`. Hàm này chỉ được gọi trong đường `--execute`.
    """
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        detail = ''
        try:
            detail = exc.read().decode('utf-8', 'replace')
        except Exception:  # pragma: no cover - thân lỗi không đọc được thì thôi
            detail = ''
        raise HttpStatusError(exc.code, detail) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise NetError(f'{type(exc).__name__}: {exc}') from exc
    raw = raw.strip()
    if not raw:
        return {}
    return json.loads(raw)
