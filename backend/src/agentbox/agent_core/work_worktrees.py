"""W8.A4.3/A4.4: a git branch + worktree per execution run, one worktree per execution node.

The owner's checkout is never the build target: the run gets `boxfox/<slug>-<id6>` in
`.boxfox/worktrees/<runId>/main`, every execution node works in its own
`.boxfox/worktrees/<runId>/n-<nodeId>` branched from the run branch, and an accepted node
is merged into the run branch under one per-run lock. Ship pushes only that branch, so
"owned by the run" is `git diff <baseline>..HEAD` and uncommitted owner changes stay out.

Without a git repository the run falls back to a touch set (`work_touch_locks`): nodes with
overlapping `files` run one after another and a producer that edits outside its declared
files fails with WORK_TOUCHSET_VIOLATION. `BOXFOX_WORK_ISOLATION=0` keeps the legacy shared
checkout (scope gates from A4.2 still apply).

Every git command goes through the sandbox executor (`terminal_exec`), from the workspace
root with explicit `cd`/`git -C` paths built only from harness-generated identifiers.
"""
import asyncio
import base64
import json
import os
import re
import shlex
import time

ISOLATION_ENV = 'BOXFOX_WORK_ISOLATION'
VERSION = 1
BASE_DIR = '.boxfox/worktrees'
ROOT_RE = re.compile(r'^\.boxfox/worktrees/w-[0-9a-f]{10}/(main|n-[A-Za-z0-9_.-]{1,64})$')
INTEGRATION_NODE = '__integration__'
SHA_RE = re.compile(r'[0-9a-f]{40}')
BRANCH_RE = re.compile(r'[A-Za-z0-9._/-]{1,120}')
REPO_RE = re.compile(r'[A-Za-z0-9._/ -]{1,200}')
COMMIT_IDENTITY = "-c user.name=BoxFox -c user.email=boxfox@local"
# Rác do chính lượt chạy sinh ra (bytecode, cache test) không bao giờ thuộc nhánh run: nếu lọt
# vào commit thì `owned_paths` — và cả PR — mang theo tệp không ai viết.
JUNK_PARTS = ('.plans', '.generated_artifacts', '.tmp', '.boxfox', '.pytest_cache', '__pycache__',
              'test-results', 'coverage', 'node_modules')
CHECKPOINT_PATHSPEC = ('-- . ' + ' '.join(f"':(exclude){part}'" for part in JUNK_PARTS)
                       + " ':(exclude,glob)**/*.pyc' ':(exclude)*.pyc'")


def junk(line):
    """True when one `git status --porcelain` line names run-generated junk, not run code.

    `snapshot()` ignores exactly these paths when it hashes the tree, so the ship gate and the
    worktree cleanup must ignore them too: a run that ran its tests always leaves
    `__pycache__/` and `.pytest_cache/` behind, and that must not block shipping forever.
    """
    raw = (line[3:] if len(line) > 3 else '').strip().strip('"')
    raw = raw.split(' -> ')[-1].strip().strip('"')
    parts = [part for part in raw.split('/') if part]
    if not parts:
        return True
    return any(part in JUNK_PARTS for part in parts) or parts[-1].endswith(('.pyc', '.pyo'))
TOUCH_WAIT_SECONDS = 900
TOUCH_POLL_SECONDS = 0.2

# Dirty-file manifest (relative to HEAD) for touch-set mode: a file not listed equals HEAD,
# so comparing two manifests detects every edit, revert or new file between them.
DIRTY_SCRIPT = r'''import hashlib,json,os,subprocess
SKIP={'.plans','.tmp','.boxfox','.generated_artifacts','.pytest_cache','__pycache__','node_modules','.git'}
def ignored(path):
 return any(x in SKIP for x in path.split('/'))
files={}; head=''
# Only a workspace that IS the repository root may read `git status`: a workspace inside a bigger
# repo would otherwise report that repo's files (paths relative to it), which is not this run's tree.
top=subprocess.run(['git','rev-parse','--show-toplevel'],capture_output=True).stdout.decode().strip()
inside=bool(top) and os.path.realpath(top)==os.path.realpath('.')
proc=subprocess.run(['git','status','--porcelain=v1','-z','--untracked-files=all'],capture_output=True) if inside else None
if proc is not None and proc.returncode==0:
 head=subprocess.run(['git','rev-parse','HEAD'],capture_output=True).stdout.decode().strip()
 items=proc.stdout.split(b'\0'); i=0
 while i<len(items):
  entry=items[i].decode('utf-8','replace'); i+=1
  if len(entry)<4: continue
  code,path=entry[:2],entry[3:]
  if code[0] in 'RC': i+=1
  if ignored(path): continue
  if os.path.isfile(path) and not os.path.islink(path):
   with open(path,'rb') as f: files[path]=hashlib.sha256(f.read()).hexdigest()
  else: files[path]='<deleted>'
else:
 # Touch-set runs have no git at all: hash the real tree so an edit outside the
 # declared files is still detectable (bounded walk, small files only).
 seen=0
 for base,dirs,names in os.walk('.'):
  dirs[:]=[d for d in dirs if not ignored(d)]
  for name in names:
   path=os.path.relpath(os.path.join(base,name),'.')
   if ignored(path): continue
   seen+=1
   if seen>4000: break
   try:
    if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path)>1048576: continue
    with open(path,'rb') as f: files[path]=hashlib.sha256(f.read()).hexdigest()
   except OSError: continue
  if seen>4000: break
print(json.dumps({'schema':'work-dirty/1','head':head,'files':files}))
'''
DIRTY_COMMAND = "python3 -c \"import base64;exec(base64.b64decode('%s'))\"" % base64.b64encode(
    DIRTY_SCRIPT.encode()).decode()


def enabled():
    return os.environ.get(ISOLATION_ENV, '1').strip().lower() not in ('0', 'off', 'false', 'no')


def q(value):
    return shlex.quote(str(value))


def repo_path(value):
    """Workspace-relative repository directory ('' = the workspace itself)."""
    if value is None or value == '':
        return ''
    raw = str(value).strip()
    repo = raw.strip('/')
    if raw.startswith('/') or not repo or not REPO_RE.fullmatch(repo) or '..' in repo.split('/'):
        raise ValueError('WORK_REPO_PATH_INVALID: repoPath must be a relative directory inside the workspace')
    return '' if repo == '.' else repo


def git_mode(run):
    iso = run.get('isolation') or {}
    return iso.get('version', 0) >= VERSION and iso.get('mode') == 'git'


class IsolationError(ValueError):
    """A coded isolation failure; the message starts with the WORK_* code."""


class Worktrees:
    def __init__(self, graph):
        self.graph, self.db = graph, graph.db
        self.integration_locks = {}
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS work_worktrees (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, repo_path TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE, branch TEXT NOT NULL, base_commit TEXT,
                status TEXT NOT NULL, doc TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS work_worktrees_run ON work_worktrees(run_id);
            CREATE TABLE IF NOT EXISTS work_touch_locks (
                run_id TEXT NOT NULL, node_id TEXT NOT NULL, path TEXT PRIMARY KEY, acquired REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS work_ships (
                ship_key TEXT PRIMARY KEY, run_id TEXT NOT NULL, status TEXT NOT NULL, doc TEXT NOT NULL);
        ''')
        self.reconcile()

    # ---- ledger ------------------------------------------------------------------------------ #

    @staticmethod
    def as_dict(row):
        return {key: row[key] for key in row.keys()}

    def row(self, ident):
        row = self.db.execute('SELECT * FROM work_worktrees WHERE id=?', (ident,)).fetchone()
        if row is None:
            return None
        return self.as_dict(row) | {'doc': json.loads(row['doc'])}

    def rows(self, run_id):
        return [self.as_dict(r) | {'doc': json.loads(r['doc'])} for r in
                self.db.execute('SELECT * FROM work_worktrees WHERE run_id=? ORDER BY rowid', (run_id,)).fetchall()]

    def put(self, ident, run_id, repo, path, branch, base, status, doc=None):
        with self.db:
            self.db.execute(
                'INSERT INTO work_worktrees VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                'path=excluded.path, branch=excluded.branch, base_commit=excluded.base_commit, '
                'status=excluded.status, doc=excluded.doc',
                (ident, run_id, repo, path, branch, base, status,
                 json.dumps(doc or {}, ensure_ascii=False)))

    def set_status(self, ident, status, **extra):
        current = self.row(ident)
        if current is None:
            return
        doc = current['doc'] | extra | {'updatedAt': time.time()}
        with self.db:
            self.db.execute('UPDATE work_worktrees SET status=?, doc=? WHERE id=?',
                            (status, json.dumps(doc, ensure_ascii=False), ident))

    def reconcile(self):
        """Process start: no admission owns a half-made worktree, merge or push any more."""
        with self.db:
            self.db.execute("UPDATE work_worktrees SET status='abandoned' WHERE status='creating'")
            for row in self.db.execute("SELECT id, doc FROM work_worktrees WHERE status='integrating'").fetchall():
                doc = json.loads(row['doc']) | {'needsAbort': True}
                self.db.execute('UPDATE work_worktrees SET doc=? WHERE id=?',
                                (json.dumps(doc, ensure_ascii=False), row['id']))
            self.db.execute("UPDATE work_ships SET status='interrupted' WHERE status='started'")
            self.db.execute('DELETE FROM work_touch_locks')

    # ---- shell ------------------------------------------------------------------------------- #

    async def sh(self, sid, command, timeout=60):
        result = await self.graph.rt.executor.execute('terminal_exec', {'command': command, 'timeout': timeout}, sid)
        result = result if isinstance(result, dict) else {}
        text = str(result.get('content') or result.get('output') or '')
        code = result.get('exit_code', result.get('exitCode'))
        return (not result.get('is_error') and code in (0, None)), text.strip()

    async def git(self, sid, path, args, timeout=60):
        return await self.sh(sid, f'git -C {q(path or ".")} {args}', timeout)

    async def sh_in(self, sid, repo, command, timeout=60):
        """One shell command inside the repository directory ('' = the workspace root)."""
        return await self.sh(sid, f'cd {q(repo or ".")} && {command}', timeout)

    # ---- A4.3: resolve the repository ------------------------------------------------------- #

    async def resolve(self, run, args, sid):
        """Which repository this run builds in. Never touches run['whole_binding']."""
        if not enabled():
            return {'version': VERSION, 'mode': 'legacy', 'reason': f'{ISOLATION_ENV}=0', 'createdAt': time.time()}
        if args.get('repoPath'):
            repo = repo_path(args['repoPath'])
            ok, out = await self.git(sid, repo, 'rev-parse --show-toplevel')
            if not ok or not out.splitlines() or not out.splitlines()[-1].startswith('/'):
                raise IsolationError(f'WORK_REPO_PATH_INVALID: {repo or "."} is not a git repository')
            return {'repoPath': repo}
        # `.` is the run's repository only when it IS the repository root: a workspace that is a
        # subdirectory of a bigger repo must not build on that repo's HEAD (and never writes its
        # worktrees into a tree the owner did not offer).
        ok, out = await self.sh_in(sid, '', 't=$(git rev-parse --show-toplevel 2>/dev/null) && [ -n "$t" ] '
                                            '&& [ "$t" = "$(pwd -P)" ] && echo workspace-is-repo')
        if ok and out.splitlines() and out.splitlines()[-1] == 'workspace-is-repo':
            return {'repoPath': ''}
        ok, out = await self.sh_in(sid, '', "for d in */; do [ -e \"$d.git\" ] && printf 'repo:%s\\n' \"${d%/}\"; done; true")
        found = sorted({line[5:] for line in out.splitlines() if line.startswith('repo:')
                        and REPO_RE.fullmatch(line[5:]) and '..' not in line[5:]})
        if len(found) > 1:
            raise IsolationError('WORK_REPO_AMBIGUOUS: several git repositories in the workspace ('
                                 + ', '.join(found[:8]) + '); call work_run phase=execute with repoPath')
        if found:
            return {'repoPath': found[0]}
        return {'version': VERSION, 'mode': 'touchset', 'reason': 'no git repository in the workspace',
                'createdAt': time.time()}

    def branch_name(self, run):
        slug = re.sub(r'[^A-Za-z0-9._-]+', '-', str(run.get('slug') or 'work')).strip('-.')[:60] or 'work'
        return f'boxfox/{slug}-{run["runId"][2:8]}'

    async def ensure_run(self, run, args, sid):
        """Idempotent: the run's isolation record + run worktree, created at first execute admission."""
        iso = run.get('isolation')
        if iso and iso.get('version', 0) >= VERSION:
            if iso.get('mode') == 'git':
                await self.verify_run(run, sid)
                await self.recover_merges(run, sid)
            return iso
        legacy = any(n['stages'].get('execute', {}).get('status') == 'accepted' for n in run['nodes'])
        if legacy:
            # Code from an earlier admission already lives in the shared checkout.
            run['isolation'] = {'version': VERSION, 'mode': 'legacy', 'createdAt': time.time(),
                                'reason': 'execution nodes were accepted before isolation'}
            return run['isolation']
        found = await self.resolve(run, args, sid)
        if found.get('mode'):
            run['isolation'] = found
            return found
        repo = found['repoPath']
        ok, baseline = await self.git(sid, repo, 'rev-parse HEAD')
        baseline = baseline.splitlines()[-1] if baseline else ''
        if not ok or not SHA_RE.fullmatch(baseline):
            raise IsolationError('WORK_WORKTREE_CREATE_FAILED: repository has no commit to branch from '
                                 '(commit once, or call with repoPath)')
        _, base_branch = await self.git(sid, repo, 'rev-parse --abbrev-ref HEAD')
        base_branch = (base_branch.splitlines() or ['HEAD'])[-1]
        if not BRANCH_RE.fullmatch(base_branch):
            base_branch = 'HEAD'
        # Keep worktrees out of the owner's `git status` before measuring it.
        await self.sh(sid, f"d=$(cd {q(repo or '.')} && cd \"$(git rev-parse --git-common-dir)\" && pwd) && "
                      "mkdir -p \"$d/info\" && (grep -qxF '/.boxfox/' \"$d/info/exclude\" 2>/dev/null || "
                      "printf '/.boxfox/\\n' >> \"$d/info/exclude\")")
        ok, dirty = await self.sh(sid, f'git -C {q(repo or ".")} status --porcelain=v1 -z | tr -cd "\\000" | wc -c; '
                                  f'git -C {q(repo or ".")} status --porcelain=v1 -z | sha256sum')
        lines = dirty.splitlines()
        count = int(lines[0]) if ok and lines and lines[0].strip().isdigit() else 0
        fingerprint = lines[1].split()[0] if ok and len(lines) > 1 and lines[1].split() else None
        branch = self.branch_name(run)
        path = f'{BASE_DIR}/{run["runId"]}/main'
        ident = f'{run["runId"]}:main'
        self.put(ident, run['runId'], repo, path, branch, baseline, 'creating')
        await self.add_worktree(sid, repo, path, branch, baseline)
        self.put(ident, run['runId'], repo, path, branch, baseline, 'ready', {'createdAt': time.time()})
        run['isolation'] = {'version': VERSION, 'mode': 'git', 'repoPath': repo, 'baselineCommit': baseline,
                            'baselineBranch': base_branch, 'branch': branch, 'root': path,
                            'userDirty': {'count': count, 'fingerprint': fingerprint}, 'createdAt': time.time()}
        run['integration'] = {'status': 'pending', 'head': baseline, 'treeHash': None, 'snapshot': None,
                              'needsTests': False, 'nodes': {}, 'checkIds': [], 'at': time.time()}
        return run['isolation']

    async def add_worktree(self, sid, repo, path, branch, start):
        exists, _ = await self.git(sid, repo, f'rev-parse --verify --quiet {q("refs/heads/" + branch)}')
        present, _ = await self.sh(sid, f'test -f {q(path + "/.git")}')
        if present:
            ok, current = await self.git(sid, path, 'rev-parse --abbrev-ref HEAD')
            if ok and current.splitlines() and current.splitlines()[-1] == branch:
                return
            raise IsolationError(f'WORK_WORKTREE_CREATE_FAILED: {path} exists on another branch')
        # `path` is harness-generated (ROOT_RE charset); "$PWD" anchors it at the workspace.
        command = (f'worktree add "$PWD/{path}" {q(branch)}' if exists else
                   f'worktree add -b {q(branch)} "$PWD/{path}" {q(start)}')
        ok, out = await self.sh(sid, f'mkdir -p {q(path.rsplit("/", 1)[0])} && git -C {q(repo or ".")} {command}', 120)
        if not ok:
            raise IsolationError('WORK_WORKTREE_CREATE_FAILED: ' + out[-300:])

    async def verify_run(self, run, sid):
        iso = run['isolation']
        present, _ = await self.sh(sid, f'test -f {q(iso["root"] + "/.git")}')
        if not present:
            raise IsolationError(f'WORK_WORKTREE_CREATE_FAILED: run worktree {iso["root"]} is missing; '
                                 'the run branch is kept — restore the worktree or cancel the run')

    async def recover_merges(self, run, sid):
        """A restart during integration: abort a half-made merge, the node returns to accepted."""
        for row in self.rows(run['runId']):
            if row['status'] != 'integrating' or not row['doc'].get('needsAbort'):
                continue
            root = run['isolation']['root']
            merging, _ = await self.git(sid, root, 'rev-parse -q --verify MERGE_HEAD')
            if merging:
                await self.git(sid, root, 'merge --abort')
            node_id = row['id'].split(':n-', 1)[-1]
            (run.get('integration') or {}).get('nodes', {}).pop(node_id, None)
            self.set_status(row['id'], 'ready', needsAbort=False, recoveredAt=time.time())

    # ---- A4.3: node worktrees ---------------------------------------------------------------- #

    def node_ident(self, run, node):
        return f'{run["runId"]}:n-{node["id"]}'

    async def ensure_node(self, run, node, sid):
        """Idempotent per (run, node): {root, branch, base}. Never falls back to the owner's checkout."""
        iso = run['isolation']
        if node['id'] == INTEGRATION_NODE:
            # A repair round on the run branch itself: the child works in the run worktree,
            # which is the checkout of that branch and is written by nobody else.
            return {'root': iso['root'], 'branch': iso['branch'], 'base': iso['baselineCommit']}
        ident = self.node_ident(run, node)
        row = self.row(ident)
        if row and row['status'] in ('ready', 'integrated', 'integrating'):
            present, _ = await self.sh(sid, f'test -f {q(row["path"] + "/.git")}')
            if present:
                return {'root': row['path'], 'branch': row['branch'], 'base': row['base_commit']}
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', node['id']):
            raise IsolationError('WORK_WORKTREE_CREATE_FAILED: node id cannot name a worktree')
        ok, head = await self.git(sid, iso['root'], 'rev-parse HEAD')
        head = head.splitlines()[-1] if head else ''
        if not ok or not SHA_RE.fullmatch(head):
            raise IsolationError('WORK_WORKTREE_CREATE_FAILED: run branch HEAD unreadable')
        generation = int((row or {}).get('doc', {}).get('generation', 0)) + (1 if row else 0)
        branch = f'{iso["branch"]}--{node["id"]}' + (f'-g{generation}' if generation else '')
        path = f'{BASE_DIR}/{run["runId"]}/n-{node["id"]}' + (f'-g{generation}' if generation else '')
        if row and row['path'] != path:
            # The old worktree (conflict/abandoned) is kept on disk for inspection; never deleted here.
            with self.db:
                self.db.execute("UPDATE work_worktrees SET id=?, status=CASE WHEN status IN ('ready','integrated') "
                                "THEN 'abandoned' ELSE status END WHERE id=?", (ident + f'@g{generation - 1}', ident))
        self.put(ident, run['runId'], iso['repoPath'], path, branch, head, 'creating', {'generation': generation})
        try:
            await self.add_worktree(sid, iso['repoPath'], path, branch, head)
        except IsolationError:
            self.set_status(ident, 'abandoned')
            raise
        self.put(ident, run['runId'], iso['repoPath'], path, branch, head, 'ready',
                 {'generation': generation, 'createdAt': time.time()})
        return {'root': path, 'branch': branch, 'base': head}

    def code_root(self, run, node):
        """(root, base) of the tree the node's code lives in; (None, None) for legacy/touch-set."""
        if not git_mode(run):
            return None, None
        if node['id'] == INTEGRATION_NODE:
            return run['isolation']['root'], run['isolation']['baselineCommit']
        row = self.row(self.node_ident(run, node))
        return (row['path'], row['base_commit']) if row else (None, None)

    async def checkpoint(self, run, node, attempt, sid):
        """Commit the producer's work in its node worktree (after producer, before derive)."""
        root, base = self.code_root(run, node)
        if not root:
            raise IsolationError('WORK_WORKTREE_CREATE_FAILED: node worktree missing at checkpoint')
        message = f'boxfox({run["runId"]}): {node["id"]} attempt {int(attempt)}'
        ok, out = await self.sh(sid, f'cd {q(root)} && git add -A {CHECKPOINT_PATHSPEC} && '
                                f'git {COMMIT_IDENTITY} commit -q --allow-empty --no-verify -m {q(message)} && '
                                "git rev-parse HEAD 'HEAD^{tree}' && "
                                f'git diff --name-only {q(base)}..HEAD', 120)
        lines = out.splitlines()
        shas = [line for line in lines if SHA_RE.fullmatch(line)]
        if not ok or len(shas) < 2:
            raise IsolationError('WORK_WORKTREE_CHECKPOINT_FAILED: ' + out[-300:])
        commit, tree = shas[0], shas[1]
        paths = [line for line in lines[lines.index(tree) + 1:] if line][:400]
        row = None if node['id'] == INTEGRATION_NODE else self.row(self.node_ident(run, node))
        return {'nodeCommit': commit, 'treeHash': tree, 'branch': (row or run['isolation'])['branch'],
                'base': base, 'paths': paths}

    # ---- A4.3: integration ------------------------------------------------------------------- #

    async def integrate(self, run, node, sid):
        """Merge an accepted node into the run branch. A conflict aborts and leaves the branch as it was."""
        iso, integration = run['isolation'], run.setdefault('integration', {'nodes': {}})
        meta = node['stages']['execute'].get('artifact') or {}
        commit = (meta.get('binding', {}).get('codeCommit') or {}).get('nodeCommit')
        if not commit:
            raise IsolationError('WORK_INTEGRATION_CONFLICT: accepted node has no checkpoint commit')
        if integration.get('nodes', {}).get(node['id']) == commit:
            return {'merged': False, 'already': True}
        lock = self.integration_locks.setdefault(run['runId'], asyncio.Lock())
        async with lock:
            root = iso['root']
            ident = self.node_ident(run, node)
            row = self.row(ident)
            ok, head = await self.git(sid, root, 'rev-parse HEAD')
            head = head.splitlines()[-1] if ok and head else ''
            ff, _ = await self.git(sid, root, f'merge-base --is-ancestor {q(head)} {q(commit)}')
            self.set_status(ident, 'integrating', commit=commit, needsAbort=False)
            if ff:
                merged, out = await self.git(sid, root, f'merge --ff-only -q {q(commit)}', 120)
            else:
                merged, out = await self.git(sid, root, f'{COMMIT_IDENTITY} merge --no-ff --no-edit -q '
                                             f'-m {q("boxfox(" + run["runId"] + "): integrate " + node["id"])} '
                                             f'{q(commit)}', 120)
            if not merged:
                await self.git(sid, root, 'merge --abort')
                _, after = await self.git(sid, root, 'rev-parse HEAD')
                self.set_status(ident, 'conflict', commit=commit, output=out[-600:])
                integration.update(status='conflict', at=time.time())
                raise IsolationError(f'WORK_INTEGRATION_CONFLICT: node {node["id"]} conflicts with the run branch '
                                     f'(run branch unchanged at {(after.splitlines() or [head])[-1][:12]}): '
                                     + out[-300:])
            ok, info = await self.git(sid, root, "rev-parse HEAD 'HEAD^{tree}'")
            shas = [line for line in info.splitlines() if SHA_RE.fullmatch(line)]
            self.set_status(ident, 'integrated', commit=commit, mergedAt=time.time(), fastForward=bool(ff))
            node_tree = (meta.get('binding', {}).get('codeCommit') or {}).get('treeHash')
            integration.setdefault('nodes', {})[node['id']] = commit
            integration.update(head=shas[0] if shas else None, treeHash=shas[1] if len(shas) > 1 else None,
                               status='pending', snapshot=None, at=time.time())
            tested = [n for n in run['nodes'] if n['id'] in integration['nodes'] and n.get('tests')]
            integration['needsTests'] = bool(integration.get('needsTests') or not ff or len(tested) > 1
                                             or (node_tree and integration['treeHash'] != node_tree))
            return {'merged': True, 'fastForward': bool(ff), 'head': integration['head']}

    async def integration_snapshot(self, run, sid):
        """Interface for converged review (quality-recovery §1): the run branch's current code."""
        from .work_checks import snapshot
        iso = run['isolation']
        snap = await snapshot(self.graph, sid, iso['root'], iso['baselineCommit'])
        ok, info = await self.git(sid, iso['root'], "rev-parse HEAD 'HEAD^{tree}'")
        shas = [line for line in info.splitlines() if SHA_RE.fullmatch(line)]
        return {'hash': (snap or {}).get('hash'), 'snapshot': snap, 'branch': iso['branch'], 'worktree': iso['root'],
                'head': shas[0] if shas else None, 'treeHash': shas[1] if len(shas) > 1 else None}

    async def owned_paths(self, run, sid):
        iso = run['isolation']
        ok, out = await self.git(sid, iso['root'], f'diff --name-only {q(iso["baselineCommit"])}..HEAD')
        return [line for line in out.splitlines() if line][:500] if ok else []

    async def diff_text(self, run, sid, limit=12000):
        iso = run['isolation']
        _, stat = await self.git(sid, iso['root'], f'diff --stat {q(iso["baselineCommit"])}..HEAD')
        _, body = await self.git(sid, iso['root'], f'diff {q(iso["baselineCommit"])}..HEAD', 120)
        return stat[-3000:], body[:limit] + ('\n[diff truncated]' if len(body) > limit else '')

    # ---- A4.3: touch-set fallback ------------------------------------------------------------ #

    def touch_paths(self, node):
        return sorted({str(p).strip().strip('/') for p in node.get('files') or [] if str(p).strip().strip('/')})

    async def lock_touchset(self, run, node):
        """Wait (never fail) until no other node holds an overlapping declared file."""
        paths = self.touch_paths(node)
        if not paths:
            return []
        deadline = time.monotonic() + TOUCH_WAIT_SECONDS
        while True:
            held = self.db.execute('SELECT run_id, node_id, path FROM work_touch_locks').fetchall()
            mine = (run['runId'], node['id'])
            busy = [r for r in held if (r['run_id'], r['node_id']) != mine and any(
                r['path'] == p or r['path'].startswith(p + '/') or p.startswith(r['path'] + '/') for p in paths)]
            if not busy:
                with self.db:
                    for p in paths:
                        self.db.execute('INSERT OR REPLACE INTO work_touch_locks VALUES(?,?,?,?)',
                                        (run['runId'], node['id'], p, time.time()))
                return paths
            if time.monotonic() > deadline:
                raise IsolationError('WORK_TOUCHSET_BUSY: overlapping files stayed locked by '
                                     + ', '.join(sorted({r['node_id'] for r in busy})))
            await asyncio.sleep(TOUCH_POLL_SECONDS)

    def release_touchset(self, run, node):
        with self.db:
            self.db.execute('DELETE FROM work_touch_locks WHERE run_id=? AND node_id=?', (run['runId'], node['id']))

    async def dirty_manifest(self, sid):
        ok, out = await self.sh(sid, DIRTY_COMMAND, 90)
        try:
            value = json.loads(out.splitlines()[-1]) if ok and out else None
        except (ValueError, IndexError):
            return None
        return value if isinstance(value, dict) and value.get('schema') == 'work-dirty/1' else None

    def touch_violations(self, node, before, after):
        if not before or not after:
            return None  # cannot measure; the code snapshot gate stays authoritative
        allowed = self.touch_paths(node)
        changed = sorted({p for p in set(before['files']) | set(after['files'])
                          if before['files'].get(p) != after['files'].get(p)})
        if before.get('head') != after.get('head'):
            changed.append('<HEAD moved>')
        return [p for p in changed if not any(p == a or p.startswith(a + '/') for a in allowed)]

    # ---- A4.4: ship idempotency -------------------------------------------------------------- #

    def ship_record(self, key):
        row = self.db.execute('SELECT * FROM work_ships WHERE ship_key=?', (key,)).fetchone()
        return (json.loads(row['doc']) | {'status': row['status'], 'shipKey': key, 'runId': row['run_id']}) if row else None

    def ship_claim(self, key, run_id, doc):
        """True when this call owns the ship; supersedes other trees of the same run."""
        with self.db:
            self.db.execute("UPDATE work_ships SET status='superseded' WHERE run_id=? AND ship_key<>? "
                            "AND status IN ('started','interrupted','failed')", (run_id, key))
            won = self.db.execute("INSERT OR IGNORE INTO work_ships VALUES(?,?,?,?)",
                                  (key, run_id, 'started', json.dumps(doc, ensure_ascii=False))).rowcount
            if not won:
                won = self.db.execute("UPDATE work_ships SET status='started', doc=? WHERE ship_key=? "
                                      "AND status IN ('interrupted','failed')",
                                      (json.dumps(doc, ensure_ascii=False), key)).rowcount
        return bool(won)

    def ship_finish(self, key, status, doc):
        with self.db:
            self.db.execute('UPDATE work_ships SET status=?, doc=? WHERE ship_key=?',
                            (status, json.dumps(doc, ensure_ascii=False), key))

    # ---- cleanup ----------------------------------------------------------------------------- #

    async def action(self, session, args):
        """`work_graph action=cleanup_worktrees`: remove clean worktrees of a closed run."""
        from .work_graph import TERMINAL_STATUSES
        graph = self.graph
        run = graph.resolve(session['id'], args.get('runId'))
        if session.get('parent_id') or session['id'] != run['sessionId']:
            raise PermissionError('WORK_ROOT_ONLY: only the run owner may clean worktrees')
        if run['status'] not in TERMINAL_STATUSES:
            raise ValueError('WORK_RUN_OPEN: cleanup_worktrees only removes worktrees of a shipped, cancelled '
                             'or rejected run')
        if graph.busy(run):
            raise ValueError('WORK_RUN_BUSY: work_run is running for this run; wait for it to return')
        report = await self.cleanup(run, session['id'])
        graph.save(run, 'worktrees_cleaned', json.dumps(report)[:300])
        return graph.result(run, 'Worktrees cleaned') | {'worktrees': report}

    async def orphans(self, sid, run_id=None):
        """Worktree directories on disk that no ledger row owns."""
        ok, out = await self.sh(sid, f'ls -d {BASE_DIR}/w-*/* 2>/dev/null; true')
        known = {r['path'] for r in self.db.execute('SELECT path FROM work_worktrees').fetchall()}
        found = []
        for path in out.splitlines():
            path = path.strip().rstrip('/')
            if ROOT_RE.fullmatch(path) or re.fullmatch(r'\.boxfox/worktrees/w-[0-9a-f]{10}/n-[A-Za-z0-9_.-]{1,72}', path):
                if path not in known and (run_id is None or path.split('/')[2] == run_id):
                    found.append(path)
        return found

    async def cleanup(self, run, sid):
        """Remove clean worktrees of a closed run; keep branches; keep and report dirty ones."""
        removed, kept, orphaned = [], [], []
        for row in self.rows(run['runId']):
            if row['status'] in ('removed',):
                continue
            present, _ = await self.sh(sid, f'test -e {q(row["path"] + "/.git")}')
            if not present:
                self.set_status(row['id'], 'removed', reason='missing on disk')
                continue
            ok, dirty = await self.git(sid, row['path'], 'status --porcelain=v1 --untracked-files=all')
            dirty_lines = [line for line in dirty.splitlines() if line and not junk(line)]
            if not ok or dirty_lines:
                kept.append({'path': row['path'], 'branch': row['branch'], 'dirty': dirty_lines[:20]})
                continue
            done, out = await self.git(sid, row['repo_path'] or '.', f'worktree remove "$PWD/{row["path"]}"')
            if done:
                self.set_status(row['id'], 'removed', removedAt=time.time())
                removed.append({'path': row['path'], 'branch': row['branch']})
            else:
                kept.append({'path': row['path'], 'branch': row['branch'], 'error': out[-300:]})
        for path in await self.orphans(sid, run['runId']):
            ident = f'{run["runId"]}:orphan:{path.rsplit("/", 1)[-1]}'
            self.put(ident, run['runId'], (run.get('isolation') or {}).get('repoPath', ''), path, '', None, 'orphaned')
            orphaned.append(path)
        return {'removed': removed, 'kept': kept, 'orphaned': orphaned}
