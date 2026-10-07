"""Đọc/ghi file kế hoạch (`.plans`) cho phiên host mode — dùng CHUNG bộ đọc với box.

Vì sao nạp `deploy/docker/plan_files.py` thay vì viết lại
---------------------------------------------------------
`plan_files.py` là nguồn chân lý của hợp đồng `GET /__box/plans` (nhóm theo tên file, khối header,
collision, warning, `.reviews`). Host mode phải trả ĐÚNG payload đó, nếu không tab Plan sẽ nói hai
sự thật khác nhau tuỳ chế độ — đúng thứ mà `docs/plan/web-machine-modes.md` cấm. Backend đã có tiền
lệ nạp module này theo đường dẫn (`backend/tests/unit/test_plan_header.py`), nên ở đây giữ một nguồn.

Vị trí module (theo thứ tự thử)
-------------------------------
1. `BOXFOX_PLAN_READER` — đường dẫn tường minh (test, hoặc bản đóng gói đặt chỗ khác).
2. `<gốc>/deploy/docker/plan_files.py` — bản checkout.
3. `<cạnh gói>/docker-context/plan_files.py` — bản desktop đóng gói: `resources/harness/` và
   `resources/docker-context/` nằm cạnh nhau (`desktop/scripts/build-app.mjs`).
4. `<cwd>/deploy/docker/plan_files.py` — chạy từ gốc repo.

Không tìm thấy ⇒ `HostPlanReaderUnavailable`. Người gọi phải trả lỗi CÓ MÃ thay vì im lặng coi như
`.plans` rỗng: "không đọc được" khác "chưa có kế hoạch nào".
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

#: Biến môi trường trỏ thẳng tới `plan_files.py` (dùng trong test và bản đóng gói lạ).
READER_ENV = 'BOXFOX_PLAN_READER'
#: Tên file `.plans` nằm trong workspace của phiên (giống box: `<workspace>/.plans`).
PLANS_DIRNAME = '.plans'

_CACHE: ModuleType | None = None


class HostPlanReaderUnavailable(RuntimeError):
    """Không tìm thấy bộ đọc `.plans` của box ⇒ host mode không đọc/ghi được kế hoạch."""


def reader_candidates() -> tuple[Path, ...]:
    """Các đường dẫn sẽ thử, theo thứ tự ưu tiên (đường dẫn tuyệt đối, chưa lọc tồn tại)."""
    here = Path(__file__).resolve()
    roots = [here.parents[4], here.parents[4].parent, Path.cwd()]
    paths: list[Path] = []
    override = os.environ.get(READER_ENV)
    if override:
        paths.append(Path(override).expanduser())
    for root in roots:
        paths.append(root / 'deploy' / 'docker' / 'plan_files.py')
        paths.append(root / 'docker-context' / 'plan_files.py')
    return tuple(dict.fromkeys(paths))  # giữ thứ tự ưu tiên, bỏ đường dẫn trùng


def plan_reader() -> ModuleType:
    """Nạp (và nhớ) module bộ đọc. Raise `HostPlanReaderUnavailable` khi thiếu."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    for candidate in reader_candidates():
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location('boxfox_host_plan_files', candidate)
        if spec is None or spec.loader is None:  # pragma: no cover - phòng vệ
            continue
        module = importlib.util.module_from_spec(spec)
        # Phải có mặt trong `sys.modules` TRƯỚC khi chạy: `@dataclass` phân giải `ClassVar`/`InitVar`
        # qua `sys.modules[cls.__module__]`, thiếu là `AttributeError` ngay lúc tạo dataclass.
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(spec.name, None)
            raise
        _CACHE = module
        return module
    raise HostPlanReaderUnavailable(
        'Không tìm thấy bộ đọc `.plans` (deploy/docker/plan_files.py). '
        f'Đặt biến {READER_ENV} hoặc chạy harness từ gốc repo.')


def plans_root(workspace) -> Path:
    """`<workspace>/.plans` — cùng quy ước với box (`PLAN_ROOT` của ide-proxy)."""
    return Path(workspace) / PLANS_DIRNAME


def plan_manifest(workspace) -> dict:
    """Payload của `GET /__box/plans`: `{plans, ignoredCount, warnings}`."""
    return plan_reader().scan_plans(plans_root(workspace)).to_payload()


def plan_document(workspace, identity, version) -> dict:
    """Payload của `GET /__box/plans/content`. `version` nhận cả chuỗi như query của box."""
    return plan_reader().read_plan(plans_root(workspace), identity, version).to_payload()


def write_plan_review(workspace, identity, decision, note='', version=None) -> dict:
    """Payload của `POST /__box/plans/review` — bản ghi đã lưu trong `<workspace>/.plans/.reviews`."""
    return plan_reader().write_review(plans_root(workspace), identity, decision, note, version)


def error_status(exc: BaseException) -> tuple[int, str]:
    """`(status, public message)` của lỗi bộ đọc; lỗi lạ ⇒ 500 kèm câu trung tính."""
    status = getattr(exc, 'status_code', None)
    message = getattr(exc, 'public_message', None)
    if isinstance(status, int) and isinstance(message, str):
        return status, message
    return 500, 'Không đọc được file kế hoạch.'
