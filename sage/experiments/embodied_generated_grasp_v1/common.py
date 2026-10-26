from pathlib import Path

ROOT = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_generated_grasp_execution_20261026_v1')
PREVIOUS = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_codex_reference_20261025_v1')
ORIGINAL = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_body_grasp_20261025_v1')
PACKAGE = Path(__file__).parent
PYTHON = '/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/cpu_env/bin/python'
ENV37 = '/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/payload_data_20261009/native_parallel_12h_20261011/shared/env37'
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def check(binding):
    if _file_binding(Path(binding['path'])) != binding:
        raise ValueError('changed frozen dependency: '+binding['path'])
