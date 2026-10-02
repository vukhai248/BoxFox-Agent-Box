"""Compact W6.5.3 results.json into the committed evidence file (no model calls)."""
import argparse
import json
from pathlib import Path

KEEP = ('case', 'role', 'cap', 'repeat', 'order', 'status', 'executionStatus', 'executionReason', 'stepsUsed',
        'finalFinishReason', 'lengthHit', 'providerCalls', 'promptTokens', 'completionTokens', 'reasoningTokens',
        'finalCompletionTokens', 'usageComplete', 'wallMs', 'words', 'chars', 'verification', 'childMaxTokens')


def compact(row):
    out = {k: row.get(k) for k in KEEP}
    out['coverage'] = {k: row['coverage'][k] for k in ('score', 'covered', 'total', 'missing', 'tailPresent')}
    out['mechanism'] = row['mechanism']
    out['finishReasons'] = [c['finishReason'] for c in row.get('calls', [])]
    out['load'] = {'before': row['loadBefore'], 'after': row.get('loadAfter')}
    if row.get('error'):
        out['error'] = row['error'][:300]
    return out


def main(args):
    doc = json.loads(Path(args.results).read_text(encoding='utf-8'))
    meta = dict(doc['meta'])
    meta['cases'] = [{k: c[k] for k in ('id', 'role', 'items')} for c in meta['cases']]
    loads = [r['loadBefore']['loadavg'][0] for r in doc['rows']] + [r['loadAfter']['loadavg'][0] for r in doc['rows'] if r.get('loadAfter')]
    evidence = {'item': 'W6.5.3', 'title': 'Cap output helper lookup lồng: 4096 so với 16000 (Space Bunny native)',
                'meta': meta, 'loadSummary': {'loadavg1mMin': min(loads), 'loadavg1mMax': max(loads),
                'loadavg1mMean': round(sum(loads) / len(loads), 2), 'cpuCount': meta.get('cpuCount')},
                'summary': doc['summary'], 'rows': [compact(r) for r in doc['rows']], 'notes': args.note}
    Path(args.out).write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--note', action='append', default=[])
    main(parser.parse_args())
