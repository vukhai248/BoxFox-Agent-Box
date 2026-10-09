"""v2 — kiểm SỐNG đường trần chi (H10.2) trên instance thật, KHÔNG gọi model.

Chạy: python3 live_allocation_check.py --base 3118 --out /code/.generated_artifacts/v2
Ghi `live-allocation.json` làm bằng chứng cho mục 2(d) của plan v2: runtime-info hiện
allocation khi đang gắn, và route vận hành là nơi duy nhất mở được trần.
"""
import argparse
import json
import pathlib
import urllib.error
import urllib.request


def http(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f'http://127.0.0.1:{base}{path}', data=data, method=method,
                                     headers={'Content-Type': 'application/json',
                                              'X-BoxFox-Admin': '1'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode('utf-8')
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8')
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {'error': raw}


def allocations(base):
    _, info = http(base, 'GET', '/api/agent/runtime-info')
    return info.get('usage', {}).get('allocations')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='3118')
    parser.add_argument('--out', default='/code/.generated_artifacts/v2')
    parser.add_argument('--ceiling', type=float, default=2.0)
    args = parser.parse_args()

    record = {'base': args.base, 'steps': {}}
    before = allocations(args.base)
    record['steps']['runtime-info-before'] = before

    status, session = http(args.base, 'POST', '/api/agent/sessions', {'skills': []})
    sid = session['id']
    record['session'] = sid

    status, put = http(args.base, 'PUT', f'/api/agent/sessions/{sid}/usage-allocation',
                       {'consentRef': 'v2-live-check', 'ceiling': args.ceiling, 'purpose': 'v2-live'})
    record['steps']['put'] = {'status': status, 'body': put}

    listed = allocations(args.base)
    record['steps']['runtime-info-after-put'] = listed

    status, got = http(args.base, 'GET', f'/api/agent/sessions/{sid}/usage-allocation')
    record['steps']['get'] = {'status': status, 'body': got}

    status, again = http(args.base, 'PUT', f'/api/agent/sessions/{sid}/usage-allocation',
                         {'consentRef': 'v2-live-check', 'ceiling': args.ceiling})
    record['steps']['second-put'] = {'status': status, 'body': again}

    status, deleted = http(args.base, 'DELETE', f'/api/agent/sessions/{sid}/usage-allocation')
    record['steps']['delete'] = {'status': status, 'body': deleted}

    record['steps']['runtime-info-after-delete'] = allocations(args.base)

    status, deleted_again = http(args.base, 'DELETE', f'/api/agent/sessions/{sid}/usage-allocation')
    record['steps']['second-delete'] = {'status': status, 'body': deleted_again}

    allocation_id = (put.get('allocation') or {}).get('allocationId')
    listed_ids = [row.get('allocationId') for row in (listed or [])]
    checks = {
        'put 200 + reserved': put.get('allocation', {}).get('state') == 'reserved',
        'runtime-info liệt kê allocation đang gắn': allocation_id in listed_ids,
        'policyRevision là 1': put.get('allocation', {}).get('policyRevision') == 1,
        'remaining = ceiling': put.get('allocation', {}).get('remaining') == args.ceiling,
        'GET attached true': got.get('attached') is True,
        'PUT lần hai 409 ALLOCATION_ALREADY_ATTACHED': (
            record['steps']['second-put']['status'] == 409
            and 'ALLOCATION_ALREADY_ATTACHED' in json.dumps(again)),
        'DELETE detached + release': deleted.get('detached') is True and deleted.get('released') == args.ceiling,
        'runtime-info sạch sau DELETE': allocation_id not in [r.get('allocationId') for r in (allocations(args.base) or [])],
        'DELETE lần hai detached false': deleted_again.get('detached') is False,
    }
    record['checks'] = checks
    record['passed'] = sum(1 for ok in checks.values() if ok)
    record['total'] = len(checks)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'live-allocation.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': record['passed'], 'total': record['total'],
                      'failed': [k for k, v in checks.items() if not v]}, ensure_ascii=False))
    return 0 if record['passed'] == record['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
