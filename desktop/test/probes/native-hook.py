import json, pathlib, threading, time
from agentbox.sandbox.win.windows_platform import WindowsPlatform
from agentbox.agent_core.desktop_control import DesktopControl

root = pathlib.Path(__file__).resolve().parents[3] / '.tmp/desktop-startup-fix/native-hook'
root.mkdir(parents=True, exist_ok=True)

class ProbePlatform(WindowsPlatform):
    def __init__(self):
        super().__init__()
        self.messages = 0
    def pump_messages(self, on_message):
        def observed(msg):
            self.messages += 1
            return on_message(msg)
        return super().pump_messages(observed)

platform = ProbePlatform()
control = DesktopControl(profile_dir=root, platform=platform)
started = time.perf_counter()
try:
    ok, code = control.install_hooks()
    installed_ms = (time.perf_counter()-started)*1000
    main_id = platform.kernel32.GetCurrentThreadId()
    hook_id = platform._input_hook_thread_id
    posted = False
    if ok and hook_id:
        posted = bool(platform.user32.PostThreadMessageW(hook_id, 0x8001, 0, 0))
        for _ in range(50):
            if platform.messages: break
            time.sleep(.02)
    result = dict(installed=ok, code=code, installMs=round(installed_ms,2),
                  distinctThread=bool(hook_id and hook_id != main_id),
                  postedPrivateMessage=posted, pumpedMessages=platform.messages)
finally:
    control.uninstall_hooks()
result['threadStopped'] = platform._input_hook_thread is None
result['handlesReleased'] = platform._hook is None and platform._mouse_hook is None
result['inputInjected'] = False
result['passed'] = all([result['installed'], result['distinctThread'], result['postedPrivateMessage'],
                        result['pumpedMessages'] > 0, result['threadStopped'], result['handlesReleased']])
(root/'results.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
assert result['passed']
