"""Invoke the existing SAGE generator on the bound development request."""
import os
from pathlib import Path
from .work import E,finish
from sage.experiments.embodied_continuous_v2 import controller as c

work=Path(os.environ['CONTINUOUS_JOB_DIR'])
mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()}
health={'available_bytes':mem['MemAvailable'],'dirty_writeback_bytes':mem['Dirty']+mem['Writeback'],
        'affinity':sorted(os.sched_getaffinity(0)),'gpu_work':False}
c.write(work/'HOST_HEALTH.json',health)
assert mem['MemAvailable']>16*1024**3 and mem['Dirty']+mem['Writeback']<8*1024**3
for kind in ['CONFIG','CACHE','DATA']:
    folder=work/('xdg_'+kind.lower());folder.mkdir(exist_ok=True);os.environ['XDG_'+kind+'_HOME']=str(folder)
os.environ['SAGE_BLENDER_TIMEOUT']='300'
from sage.experiments.codex_trellis_scene_v2.cli import build_parser
from sage.experiments.codex_trellis_scene_v2.pipeline import run_pipeline
args=c.read(E/'generated/requests/development_01/CLI.json')
parsed=build_parser().parse_args(args)
summary=run_pipeline(parsed)
finish({'generated':True,'public_cli':args,'summary':summary,'physics_steps':0,
        'render_passes':0,'production_accepted':False,'source_domain':'own_SAGE_generator_reused_source_bound_fixture_assets'})
