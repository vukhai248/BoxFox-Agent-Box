import json, os, pathlib, psutil, subprocess, sys, time

repo = pathlib.Path(__file__).resolve().parents[3]
root = repo / '.tmp' / 'desktop-startup-fix' / sys.argv[1]
root.mkdir(parents=True, exist_ok=True)
samples = []
process_samples = []
watched = {}
started = time.perf_counter()
psutil.cpu_percent()
def sample(phase):
    disk = psutil.disk_io_counters()
    samples.append(dict(at=round(time.perf_counter()-started,3), phase=phase,
                        cpu=psutil.cpu_percent(), availableMemory=psutil.virtual_memory().available,
                        diskReadBytes=disk.read_bytes, diskWriteBytes=disk.write_bytes))

for _ in range(12):
    time.sleep(.25); sample('idle-baseline')
env = dict(os.environ)
env.pop('ELECTRON_RUN_AS_NODE', None)
for process in psutil.process_iter(['pid', 'name']):
    if str(process.info['name']).lower() in {'msmpeng.exe', 'system', 'dwm.exe', 'vmmemwsl', 'com.docker.backend.exe', 'docker desktop.exe'}:
        try:
            process.cpu_percent()
            watched[process.pid] = process
        except psutil.Error:
            pass
electron_binary = pathlib.Path(os.environ.get('BOXFOX_PROBE_ELECTRON', str(repo/'desktop/node_modules/electron/dist/electron.exe')))
with (root / 'desktop.stdout.log').open('w', encoding='utf-8') as out, (root / 'desktop.stderr.log').open('w', encoding='utf-8') as err:
    proc = subprocess.Popen([str(electron_binary),
                             str(repo/'desktop/test/windows-lifecycle-probe.cjs'), str(root)],
                            cwd=repo/'desktop', env=env, stdout=out, stderr=err)
    next_process_sample = time.monotonic()
    deadline = time.monotonic()+100
    while proc.poll() is None and time.monotonic()<deadline:
        time.sleep(.25); sample('app-startup-lifecycle')
        if time.monotonic() >= next_process_sample:
            next_process_sample = time.monotonic()+1
            try:
                for process in [psutil.Process(proc.pid), *psutil.Process(proc.pid).children(recursive=True)]:
                    if process.pid not in watched:
                        process.cpu_percent(); watched[process.pid] = process
            except psutil.Error:
                pass
            for process in list(watched.values()):
                try:
                    process_samples.append(dict(at=round(time.perf_counter()-started,3), pid=process.pid,
                                                name=process.name(), cpu=process.cpu_percent(),
                                                rss=process.memory_info().rss))
                except psutil.Error:
                    watched.pop(process.pid, None)
    if proc.poll() is None:
        for child in psutil.Process(proc.pid).children(recursive=True):
            try: child.kill()
            except psutil.Error: pass
        proc.kill()
        print('PROBE TIMEOUT', flush=True)
    proc.wait(timeout=10)
for _ in range(8):
    time.sleep(.25); sample('after-exit')
report = json.loads((root/'lifecycle.json').read_text()) if (root/'lifecycle.json').exists() else {}
alive = []
for pid in report.get('servicePids', []):
    if psutil.pid_exists(pid): alive.append(pid)
result = dict(exitCode=proc.returncode, servicePidsStillAlive=alive, samples=samples, processSamples=process_samples)
(root/'machine-performance.json').write_text(json.dumps(result, indent=2))
summary = dict(exitCode=proc.returncode, lifecyclePassed=report.get('passed'),
               events=report.get('events'), error=report.get('error'), orphanPids=alive,
               systemCpuMax=max(s['cpu'] for s in samples),
               systemCpuAverage=sum(s['cpu'] for s in samples)/len(samples), reportRoot=str(root))
print(json.dumps(summary, indent=2), flush=True)
if proc.returncode != 0 or not report.get('passed') or alive: sys.exit(1)
