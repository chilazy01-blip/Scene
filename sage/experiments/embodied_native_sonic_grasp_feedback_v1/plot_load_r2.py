"""Standalone plot of actual probe force and wrist-versus-cup displacement."""
import argparse
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(folder):
    j=read_bound_json(folder/'FORCE_CHECK.json');r=read_bound_json(folder/'full/REPORT.json');t=read_bound_json(folder/'full/TRACE.json');rows=j['rows'];x=np.array([a['forensic']['time_s'] for a in rows]);hand=np.array([a['forensic']['hand_force_world_n'][2] for a in rows]);desk=np.array([a['forensic']['desk_force_world_n'][2] for a in rows]);weight=rows[0]['forensic']['weight_n']
    fig,axes=plt.subplots(1,2,figsize=(12,4.3),constrained_layout=True)
    ax=axes[0];ax.plot(x,hand,label='Actual hand force on cup, vertical');ax.plot(x,desk,label='Actual desk support, vertical',alpha=.8);ax.axhline(weight,c='k',ls='--',label='Cup weight (1.4715 N)');ax.axhline(0,c='grey',lw=.7);ax.set(xlabel='Actual simulation time (s)',ylabel='Upward force (N)',title='A feasible static wrench is not the realized wrench');ax.legend(fontsize=8);ax.grid(alpha=.2)
    selected=[a for a in rows if a['stage_at_quality_evaluation']=='load_probe'];ax=axes[1]
    if selected:
        tt=np.array([a['forensic']['time_s'] for a in selected]);wz=np.array([a['wrist_m'][2] for a in selected]);oz=np.array([a['forensic']['cup_com_m'][2] for a in selected]);ax.plot(tt,(wz-wz[0])*1000,label='Actual wrist rise');ax.plot(tt,(oz-oz[0])*1000,label='Actual cup COM rise');ax.axhline(6,c='grey',ls='--',label='Probe cup-rise gate (6 mm)');ax.set(title='10 mm load probe: measured motion',xlabel='Actual simulation time (s)',ylabel='Vertical displacement from first probe sample (mm)');ax.legend(fontsize=8);ax.grid(alpha=.2)
    else:ax.text(.5,.5,'Load probe not entered',ha='center',va='center',transform=ax.transAxes);ax.set_axis_off()
    path=folder/'actual_load_probe.png';fig.suptitle('Native full G1 + original mug / SONIC29 / ACTUAL FAILED ATTEMPT' if not r['grasp_test_passed'] else 'Native full G1 + original mug / SONIC29 / actual load test',fontsize=12);fig.savefig(path,dpi=160);plt.close(fig)
    safe_save(folder/'LOAD_PLOT.json',dict(new_physics_steps=0,force_check=_file_binding(folder/'FORCE_CHECK.json'),report=_file_binding(folder/'full/REPORT.json'),figure=_file_binding(path),implementation=_file_binding(Path(__file__)),interpretation='Exact recorded force/state reconstruction samples, no interpolation or counterfactual rollout; connecting lines are a viewing aid. Separate axes show full close/recovery force and probe-only displacement.'))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,required=True);run(p.parse_args().folder)
