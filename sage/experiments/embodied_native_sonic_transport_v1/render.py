"""Actual-state video with bounded resources; never integrates or edits the scene."""
import argparse,os,resource,importlib
from pathlib import Path


def run(root,episode,output,version):
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3))
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
    from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
    safe_save(episode.parent/'VIDEO_RENDER_PLAN.json',dict(report=_file_binding(episode/'REPORT.json'),
        implementation=_file_binding(Path(__file__)),new_physics_steps=0,cpu_cores_maximum=8,address_space_gib=16,
        mesa_threads=int(os.environ.get('LP_NUM_THREADS','1')),fps=50,only_actual_interval_end_states=True))
    module=importlib.import_module('.visualize' if version==1 else f'.visualize_v{version}',__package__)
    module.run(root,output,episode)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--episode',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--version',type=int,required=True)
    a=ap.parse_args();run(a.root,a.episode,a.output,a.version)
