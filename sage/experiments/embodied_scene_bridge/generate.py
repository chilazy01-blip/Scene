"""Call the unchanged public CLI and preserve the complete request/attempt."""
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

from .contracts import digest, read, require, verify_freeze, write


def generate(root, attempt_name):
    root = Path(root)
    verify_freeze(root)
    request_key = attempt_name.split('_')[0]
    require(request_key in ('D01', 'D02'), 'unregistered_request')
    if request_key == 'D02':
        amendment = read(root / 'protocol/AMENDMENT_01.json')
        require(amendment['original_freeze_sha256'] == digest(root / 'protocol/FREEZE.json'), 'amendment_freeze')
        for path, expected in amendment['files'].items():
            require(digest(root / path) == expected, 'amended_input_changed')
    request = read(root / f'requests/{request_key}.json')
    require(digest(request['asset_library']) == request['asset_library_sha256'], 'asset_library_changed')
    attempts = root / 'attempts'
    require(len(list(attempts.glob(f'{request_key}_*/generation_attempt.json'))) < 3, 'generation_attempt_budget_exhausted')
    out = attempts / attempt_name
    out.mkdir(exist_ok=False)
    shutil.copyfile(root / f'requests/{request_key}.json', out / 'request.json')
    args = [sys.executable, '-m', 'sage.experiments.codex_trellis_scene_v2.cli',
            '--prompt-file', str(root / f'requests/{request_key}_prompt.txt'),
            '--furnishing-config', str(root / f'requests/{request_key}_furnishing.json'),
            '--output-dir', str(out / 'generator'), '--profile', 'development',
            '--room-type', request['room_type'], '--window-wall', request['window_wall'],
            '--expander', 'rules', '--planner', 'rules', '--no-codex-repair',
            '--repair-iterations', '2', '--asset-mode', 'reuse',
            '--asset-library-manifest', request['asset_library'], '--seed', str(request['seed']),
            '--assemble', '--no-render-preview', '--no-scene-render-acceptance', '--no-mujoco-check']
    row = dict(request_id=request['id'], split=request['split'], argv=args, status='running',
               pipeline='unchanged public CLI with actual GLB assembly', new_asset_generation=False,
               render_acceptance='not requested in M1; no production or RGB certification')
    write(out / 'generation_attempt.json', row)
    began = time.monotonic()
    try:
        with (out / 'generator.log').open('w') as stream:
            result = subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT)
        row['exit_code'] = result.returncode
        summary_path = out / 'generator/run_summary.json'
        row['summary'] = read(summary_path) if summary_path.exists() else None
        require(result.returncode == 0, 'generation_failed')
        require(row['summary']['profile_complete'], 'generator_profile_incomplete')
        require((out / 'generator/scene_codex_trellis_v2.glb').is_file(), 'assembled_glb_missing')
        row['status'] = 'generated'
    except BaseException:
        row.update(status='generation_failed', traceback=traceback.format_exc())
        raise
    finally:
        row['wall_seconds'] = time.monotonic() - began
        write(out / 'generation_attempt.json', row)
    return row
