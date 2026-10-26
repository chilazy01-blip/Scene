"""Resumable, size-balanced evidence hashing for slow storage."""
import os
from pathlib import Path
import sys
import time

from .controller import read, sha, write


def main():
    root, action = Path(sys.argv[1]), sys.argv[2]
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    inventory = read(root / 'evidence/VERIFICATION_SHARDS.json')
    report = {}
    if action == 'merge':
        checked = {}
        for index in range(len(inventory['shards'])):
            result = read(root / f'reports/VERIFY_SHARD_{index}.json')
            if not result['passed']:
                raise ValueError('failed shard')
            for name, digest in result['hashes'].items():
                if name in checked:
                    raise ValueError('duplicate evidence entry')
                checked[name] = digest
        expected = {v['name']: v['expected_sha256'] for shard in inventory['shards'] for v in shard}
        report = {'passed': checked == expected, 'files_checked': len(checked),
                  'historical_bytes_unchanged': checked == expected, 'physics_steps': 0,
                  'inventory_sha256': sha(root / 'evidence/VERIFICATION_SHARDS.json')}
        path = root / 'reports/VERIFY_PREDECESSOR_SHARDED.json'
    elif action == 'diagnose':
        state = read(root / 'STATE.json')
        report = {'passed': True, 'failures': {k: v for k, v in state['jobs'].items() if v['status'] == 'failed'},
                  'next': 'Inspect failed shard/checkpoint and stderr; preserve all costs; append a bounded corrected task.',
                  'whole_run_exit': False}
        path = root / 'reports' / (work.name.upper() + '.json')
    else:
        index = int(action)
        hashes, cache = {}, {}
        started = time.time()
        for row in inventory['shards'][index]:
            file = Path(row['path'])
            stat = file.stat()
            key = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if key not in cache:
                cache[key] = sha(file)
            hashes[row['name']] = cache[key]
            if len(hashes) % 64 == 0:
                write(work / 'CHECKPOINT.json', {'checked': len(hashes), 'epoch': time.time()})
        bad = [r['name'] for r in inventory['shards'][index] if hashes[r['name']] != r['expected_sha256']]
        report = {'passed': not bad, 'hashes': hashes, 'mismatches': bad, 'elapsed_seconds': time.time() - started}
        path = root / f'reports/VERIFY_SHARD_{index}.json'
    write(path, report)
    write(work / 'RESULT.json', {'outcome': 'success' if report['passed'] else 'engineering_failure',
                               'report': str(path), 'report_sha256': sha(path)})
    print({'passed': report['passed'], 'action': action, 'report': str(path)}, flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
