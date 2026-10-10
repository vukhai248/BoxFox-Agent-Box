"""Start the loopback BoxFox harness using the repository's Python package."""
from pathlib import Path
import os
import sys
import time
_import_started = time.perf_counter()
if os.environ.get('BOXFOX_DESKTOP_PROFILE'):
    print('[harness] bootstrap import-start at %.3f' % time.time(), flush=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend/src'))
from agentbox.api.server import main
if os.environ.get('BOXFOX_DESKTOP_PROFILE'):
    print('[harness] bootstrap imports: %dms at %.3f' %
          ((time.perf_counter() - _import_started) * 1000, time.time()), flush=True)

if __name__ == '__main__':
    main()
