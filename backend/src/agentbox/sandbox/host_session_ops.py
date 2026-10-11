"""Load the shared session-file operations for host mode.

The Docker worker and host executor must write the same ``.session-history``
format.  Keep one implementation and load it from the checkout or packaged
docker-context, just like ``host_plans`` does for plan files.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_CACHE: ModuleType | None = None


def _candidates() -> tuple[Path, ...]:
    here = Path(__file__).resolve()
    package_root = here.parents[4]
    return (
        package_root / 'deploy' / 'docker' / 'session_ops.py',
        package_root.parent / 'docker-context' / 'session_ops.py',
    )


def _module() -> ModuleType:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    for candidate in _candidates():
        if not candidate.is_file():
            continue
        parent = str(candidate.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        spec = importlib.util.spec_from_file_location('boxfox_host_session_ops', candidate)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(spec.name, None)
            continue
        _CACHE = module
        return module
    raise RuntimeError('HOST_SESSION_OPS_UNAVAILABLE: không tìm thấy session_ops.py')


def run(name: str, args: dict) -> dict:
    """Run a shared operation without letting file errors kill the chat turn."""
    return _module().run_op(name, args)
