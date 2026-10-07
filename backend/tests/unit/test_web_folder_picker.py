"""Folder picker contract plus a native probe that cancels only its own dialog."""
import asyncio
import json
import os
import subprocess
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from agentbox.sandbox.machine_router import FOLDER_PICKER_SCRIPT, MachineError, pick_folder, register_routes


@pytest.mark.parametrize('stdout,expected', [
    ('{"path":"D:\\\\Dự án có dấu"}', {'path': 'D:\\Dự án có dấu'}),
    ('\ufeff{"cancelled":true}', {'cancelled': True}),
])
def test_picker_parses_unicode_path_and_explicit_cancel(stdout, expected):
    with patch('agentbox.sandbox.machine_router.os.name', 'nt'), patch('agentbox.sandbox.machine_router.subprocess.run') as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout, '')
        assert pick_folder() == expected
        args = run.call_args.args[0]
        assert args[:6] == ['powershell.exe', '-NoProfile', '-STA', '-WindowStyle', 'Hidden', '-Command']
        assert '$owner.Show();' in args[-1]
        assert '[BoxFoxFolderDialog]::Pick($owner.Handle)' in args[-1]
        assert 'FolderBrowserDialog' not in args[-1]
        assert '$owner.TopMost = $true' in args[-1]


@pytest.mark.parametrize('stdout', ['', 'null', '[]', '{"cancelled":false}', '{"path":123}'])
def test_bad_picker_output_is_an_actionable_error(stdout):
    with patch('agentbox.sandbox.machine_router.os.name', 'nt'), patch('agentbox.sandbox.machine_router.subprocess.run') as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout, '')
        with pytest.raises(MachineError) as error:
            pick_folder()
        assert error.value.code == 'FOLDER_PICKER_UNAVAILABLE'


def test_timeout_is_not_reported_as_user_cancel():
    with patch('agentbox.sandbox.machine_router.os.name', 'nt'), patch('agentbox.sandbox.machine_router.subprocess.run', side_effect=subprocess.TimeoutExpired('picker', 180)):
        with pytest.raises(MachineError) as error:
            pick_folder()
        assert error.value.code == 'FOLDER_PICKER_TIMEOUT'


def test_duplicate_picker_returns_busy_instead_of_queuing(monkeypatch):
    async def scenario():
        import threading
        entered, release = threading.Event(), threading.Event()
        def picker():
            entered.set()
            assert release.wait(5)
            return {'cancelled': True}
        monkeypatch.setattr('agentbox.sandbox.machine_router.pick_folder', picker)
        runtime = type('Runtime', (), {'machine_registry': object()})()
        app = web.Application()
        register_routes(app, runtime)
        async with TestClient(TestServer(app)) as client:
            first = asyncio.create_task(client.post('/api/agent/machines/pick-folder', json={}))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                second = await client.post('/api/agent/machines/pick-folder', json={})
                assert second.status == 409
                assert (await second.json())['code'] == 'FOLDER_PICKER_BUSY'
            finally:
                release.set()
                response = await first
            assert await response.json() == {'cancelled': True}
    asyncio.run(scenario())


NATIVE_PROBE = r'''
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public static class BoxFoxPickerProbe {
  delegate bool EnumProc(IntPtr hwnd, IntPtr param);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr param);
  [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr param);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", EntryPoint="GetWindowLongW")] static extern int GetWindowLong(IntPtr hwnd, int index);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr hwnd, StringBuilder text, int size);
  [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr hwnd, uint msg, IntPtr w, IntPtr l);
  public static bool Found, Visible, TopMost, Foreground, Modern;
  static Timer timer;
  public static void Start() {
    timer = new Timer(); timer.Interval = 500;
    timer.Tick += delegate {
      EnumWindows(delegate(IntPtr hwnd, IntPtr param) {
        uint pid; GetWindowThreadProcessId(hwnd, out pid);
        if (pid != (uint)Process.GetCurrentProcess().Id) return true;
        var cls = new StringBuilder(256); GetClassName(hwnd, cls, cls.Capacity);
        if (cls.ToString() != "#32770") return true;
        Found = true; Visible = IsWindowVisible(hwnd);
        TopMost = (GetWindowLong(hwnd, -20) & 8) != 0;
        Foreground = GetForegroundWindow() == hwnd;
        EnumChildWindows(hwnd, delegate(IntPtr child, IntPtr unused) {
          var childClass = new StringBuilder(256); GetClassName(child, childClass, childClass.Capacity);
          if (childClass.ToString() == "DirectUIHWND" || childClass.ToString() == "DUIViewWndClassName") Modern = true;
          return true;
        }, IntPtr.Zero);
        timer.Stop(); SendMessage(hwnd, 0x0010, IntPtr.Zero, IntPtr.Zero);
        return false;
      }, IntPtr.Zero);
    };
    timer.Start();
  }
  public static void Stop() { timer.Stop(); timer.Dispose(); }
}
'@ -ReferencedAssemblies System.Windows.Forms
[BoxFoxPickerProbe]::Start();
'''


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows folder dialog probe')
def test_native_picker_visible_with_hidden_helper_and_explicit_cancel():
    # Instrument the real script; its in-process timer observes/closes only this probe's dialog.
    script = FOLDER_PICKER_SCRIPT.replace('$owner = New-Object', NATIVE_PROBE + '\n$owner = New-Object', 1)
    script += '\n[BoxFoxPickerProbe]::Stop(); @{found=[BoxFoxPickerProbe]::Found; visible=[BoxFoxPickerProbe]::Visible; topMost=[BoxFoxPickerProbe]::TopMost; foreground=[BoxFoxPickerProbe]::Foreground; modern=[BoxFoxPickerProbe]::Modern} | ConvertTo-Json -Compress\n'
    result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-WindowStyle', 'Hidden', '-Command', script],
                            capture_output=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
    records = [json.loads(line.lstrip('\ufeff')) for line in result.stdout.splitlines() if line.strip()]
    assert records[0] == {'cancelled': True}, records
    assert records[1]['found'] and records[1]['visible'] and records[1]['topMost'] and records[1]['modern'], records
