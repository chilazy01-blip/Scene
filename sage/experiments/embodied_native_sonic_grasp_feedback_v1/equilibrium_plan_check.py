"""Zero-step native closure/path/bound check and a concrete next-case preview."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .posture_screen import load_model,hand_ids,contact_pair,IK
from .mesh_grasp_plan_r2 import DISTAL
from .protocol import read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8]);p=read_bound_json(root/'EQUILIBRIUM_GRASP_PLAN_R3.json');assert p['eligible'];r=read_bound_json(root/'attempt_09/full/REPORT.json');t=read_bound_json(root/'attempt_09/full/TRACE.json');q0=np.array(t['records'][979]['substeps'][-1]['full_qpos_after']);m=load_model(r['model']['path']);d=mujoco.MjData(m);ik=IK(mujoco,m);h=hand_ids(m);names=p['physical_touch_joint_names'];ix=np.array([h['names'].index(n) for n in names]);fq=h['qpos'][ix];out=[]
    for f in np.linspace(0,1,31):
        d.qpos[:]=q0;d.qpos[ik.qids]=p['arm_reference_angles_rad'];d.qpos[fq]=np.array(p['physical_touch_angles_rad'])*f;mujoco.mj_fwdPosition(m,d);bad=[];depth=0.
        for c in d.contact:
            pair=contact_pair(m,c);ns=[a['name'] for a in pair]
            if 'payload_surface' in ns:
                other=pair[1-ns.index('payload_surface')]
                if other['body'].startswith('right_hand_'):
                    depth=max(depth,-float(c.dist))
                    if other['body'] not in DISTAL and c.dist<0:bad.append(dict(reason='non_distal',pair=pair,distance_m=float(c.dist)))
            elif c.dist<0 and any(a['body'].startswith('right_hand_') for a in pair) and any(n.startswith('scene_collision_') for n in ns):bad.append(dict(reason='hand_scene',pair=pair,distance_m=float(c.dist)))
        out.append(dict(fraction=float(f),maximum_virtual_penetration_m=depth,bad=bad,passed=depth<=.001 and not bad))
    a=p['quasistatic_motor_allocation'];reference=np.array(a['motor_reference_angles_rad']);touch=np.array(p['physical_touch_angles_rad']);expected=touch+np.array(a['required_motor_torque_nm'])/h['kp'][ix];assert np.max(np.abs(reference-expected))<1e-12
    case=read_bound_json(root/'CASE_PRESERVED_WRENCH.json');case.update(loaded_preload_targets_n=a['group_normals_n'],equilibrium_motor_reference_rad=dict(zip(names,reference.tolist())),equilibrium_physical_touch_rad=dict(zip(names,touch.tolist())),equilibrium_grasp_plan=_file_binding(root/'EQUILIBRIUM_GRASP_PLAN_R3.json'),feedback_control='From firstclose980 ramp each native motor PD reference to the independently computed equilibrium reference at<=0.006rad/20ms and hold. This supersedes scalar shape/wrench/index-reserve updates; physical touch pose differs from motor target. Preserve existing actual load/hover/slip/carry/place/release gates and original native model/PD/friction/effort/halfclosed bounds. Keep world-steady SONIC wrist and original ordered lower12 walking inputs.');safe_save(root/'CASE_EQUILIBRIUM_PREVIEW.json',case)
    passed=all(x['passed'] for x in out);safe_save(root/'EQUILIBRIUM_PLAN_CHECK.json',dict(passed=passed,new_physics_steps=0,plan=_file_binding(root/'EQUILIBRIUM_GRASP_PLAN_R3.json'),case_preview=_file_binding(root/'CASE_EQUILIBRIUM_PREVIEW.json'),closure_path=out,motor_vs_touch_PD_equilibrium_error_rad=float(np.max(np.abs(reference-expected))),proposed_full_ticks=2220,proposed_full_physics_ceiling=8920,proposed_prefix_physics_steps=3960,proposed_new_suffix_max=4960,proposed_success_replay_max=8920,current_native_actual_steps=61116,projected_cumulative_max=74996,unchanged_cumulative_cap=75000,resource_time_extension_approval_required=True,implementation=_file_binding(Path(__file__)),limitation='Native private physical-touch closure geometry and quasistatic PD/closing-friction equilibrium only. PD motor targets must not be treated as collision-free physical poses. No dynamic candidate, admission or positive episode has been run/exported. Original full-task success and original-init continuous43ctrl replay still required.'));print(dict(passed=passed,bad=[x for x in out if not x['passed']],projected_native_ceiling=74996,waiting_for_time_extension=True),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
