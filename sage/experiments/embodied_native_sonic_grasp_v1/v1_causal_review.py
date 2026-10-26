"""Recorded one-sided push and moving-reference regression; zero integrations."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    t=read_bound_json(root/'version_01/full/TRACE.json');r=read_bound_json(root/'version_01/full/REPORT.json');rows=t['records'][1000:];ss=[s for row in rows for s in row['substeps']]
    assert r['stop_reason']=='grasp_alignment_object_displacement' and r['new_physics_steps']==468
    j=dict(schema='grasp-repair-v1-one-sided-push-review/v1',new_physics_steps=0,all_executed_physics_safe=all(s['safe'] for s in ss),
        maximum_closure=max(row['closure'] for row in rows),peak_force_n={k:max(s['forces'][k] for s in ss) for k in ss[0]['forces']},
        first_object_m=ss[0]['object_m'],last_object_m=ss[-1]['object_m'],object_displacement_m=float(np.linalg.norm(np.array(ss[-1]['object_m'])-ss[0]['object_m'])),
        wrist_reference_first_m=rows[0]['wrist_reference_m'],wrist_reference_last_m=rows[-1]['wrist_reference_m'],
        observation='Middle finger contacts while thumb and index remain absent; closure below .22 at stop. Translating cup causes continuously retargeted wrist to follow, preserving one-sided pushing configuration.',
        inference='Supports separating closure references by contact group and freezing wrist goal before closing. Does not prove increased global motor effort would fix grasp.',
        proposed_correction='single final version: freeze object-relative alignment goal, stop closing an already-loaded contact group while unloaded groups catch up; original finger PD/motor limits unchanged; require sustained real opposing force before lift',
        report=_file_binding(root/'version_01/full/REPORT.json'),trace=_file_binding(root/'version_01/full/TRACE.json'),implementation=_file_binding(Path(__file__)))
    safe_save(root/'V1_CAUSAL_REVIEW.json',j);print({k:j[k] for k in ['maximum_closure','peak_force_n','object_displacement_m']},flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
