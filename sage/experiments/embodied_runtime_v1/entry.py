# Deliberately import only built-in sys before checking Python's isolated mode.
import sys
if not sys.flags.isolated:
    raise SystemExit('isolated_interpreter_required: launch with python -I')

# -I ignores PYTHONDONTWRITEBYTECODE. Set the interpreter flag explicitly
# before importing workspace/dependency code; child interpreters also need -B.
sys.dont_write_bytecode = True

import argparse
import hashlib
from pathlib import Path
import runpy

PROJECT = Path('/data/wsj/main/scene')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--runtime-sha256', required=True)
    parser.add_argument('output')
    parser.add_argument('script')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    runtime = Path(args.runtime).resolve()
    script = Path(args.script).resolve()
    output = Path(args.output).resolve()
    for path in [runtime, script, output]:
        if not path.is_relative_to('/data/wsj/main'):
            raise SystemExit('workspace_path_required')
    if hashlib.sha256(runtime.read_bytes()).hexdigest() != args.runtime_sha256:
        raise SystemExit('runtime_hash_mismatch')
    # Isolated Python excludes script directory and PYTHONPATH. Only the project
    # package root is added; workload siblings never become import candidates.
    if str(script.parent) in sys.path or '' in sys.path:
        raise SystemExit('workload_directory_on_import_path')
    sys.path.insert(0, str(PROJECT))
    with (output / 'worker_claim').open('x') as stream:
        stream.write('isolated CPU worker\n')
    worker = runpy.run_path(str(runtime))['worker']
    return worker(output, script, args.arguments, False)


if __name__ == '__main__':
    raise SystemExit(main())
