"""Recover complete W6.5 metrics from SQLite, including records after event 500."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from collections import Counter


def summarize(folder):
    rows = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
    canonical = []
    for original in rows:
        row = {k: original.get(k) for k in ('case', 'repeat', 'profile', 'status', 'oracle',
            'latencySeconds', 'readSources', 'requiredSources', 'fullReads', 'appliedBudget', 'childConfig')}
        path = folder / f'{row["case"]}-{row["repeat"]}' / 'sessions.db'
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        cid = original.get('childId')
        events = [(kind, json.loads(payload)) for kind, payload in db.execute(
            'SELECT kind,payload FROM events WHERE session_id=? ORDER BY seq', (cid,))]
        row.update(eventCount=len(events), stepsUsed=max((d.get('stepsUsed', 0) for k, d in events if k == 'turn_end'), default=0),
            toolCalls=sum(k == 'tool_end' for k, _ in events),
            toolErrors=sum(k == 'tool_end' and bool(d.get('is_error') or (d.get('result') or {}).get('is_error')) for k, d in events),
            partialReasons=[d.get('code') for k, d in events if k == 'notice' and d.get('code')],
            completionAttempts=sum(d.get('completionAttempts', 0) for k, d in events if k == 'turn_end'),
            knownOutputTokens=sum(d.get('outputTokens') or 0 for k, d in events if k == 'turn_end'),
            missingUsageSteps=sum(k == 'turn_end' and d.get('completionUsageComplete') is False for k, d in events),
            largestClientCallSeconds=max((c['seconds'] for c in original.get('completions', [])), default=None),
            rawResultHash=hashlib.sha256((folder / 'results.json').read_bytes()).hexdigest())
        tools = [json.dumps({'name': d.get('name'), 'args': d.get('args')}, sort_keys=True, ensure_ascii=False)
                 for k, d in events if k == 'tool_start']
        row['duplicateCalls'] = sum(n - 1 for n in Counter(tools).values())
        db.close()
        canonical.append(row)
    (folder / 'canonical-metrics.json').write_text(json.dumps(canonical, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'profile': folder.name, 'completedRows': len(rows), 'oracleRows': sum(bool(r['oracle']) for r in rows),
            'statuses': dict(Counter(r['status'] for r in rows)), 'rows': canonical}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('folders', nargs='+')
    p.add_argument('--output', required=True)
    args = p.parse_args()
    result = [summarize(Path(f).resolve()) for f in args.folders]
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([{k: r[k] for k in ('profile', 'completedRows', 'oracleRows', 'statuses')} for r in result]))
