"""Standalone figures from frozen reports; no simulation or image re-rendering."""
import os
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .work import E, c, finish


def main(config):
    cfg = c.read(config)
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    tasks = c.read(cfg['task_review'])['tasks']
    timing = c.read(cfg['timing_review'])
    assert c.sha(timing['series_path']) == timing['series_sha256']
    outputs = []
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                         'axes.spines.right':False,'savefig.bbox':'tight'})
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), layout='constrained')
    labels = [t['key'] for t in tasks]
    specs = [('maximum_penetration_m',1000,'Maximum penetration (mm)'),
             ('duration_s',1,'Recorded task duration (s)'),
             ('object_max_lift_m',100,'Maximum object lift (cm)'),
             ('grasped_carry_m',100,'Grasped carry distance (cm)')]
    for ax, (field, scale, title) in zip(axes.ravel(), specs):
        vals = [np.nan if t[field] is None else t[field]*scale for t in tasks]
        ax.bar(labels, vals, color='#386a8a')
        ax.set_title(title, loc='left')
        ax.grid(axis='y', alpha=.2)
        ax.set_axisbelow(True)
        if field == 'maximum_penetration_m':
            ax.axhline(10, color='#ba3838', linestyle='--', label='Unchanged 10 mm gate')
            ax.legend(frameon=False)
        for i, value in enumerate(vals):
            if np.isfinite(value):
                ax.annotate(f'{value:.2f}', (i,value), xytext=(0,3), textcoords='offset points',ha='center',fontsize=8)
        ax.margins(y=.18)
    fig.suptitle('Eight complete development records: 0 accepted tasks\nAll eight independent full replays matched every saved dataset', fontsize=13)
    for suffix in ['png','pdf']:
        path = work/('complete_task_outcomes.'+suffix)
        fig.savefig(path, dpi=180)
        outputs.append(path)
    plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, layout='constrained')
    with np.load(timing['series_path']) as archive:
        for row in timing['comparisons']:
            key = row['first']+'__'+row['second']
            times = archive[key+'_time_s']
            milliseconds = (times-times[0])*1000
            a,b = row['first'].split('_f')[-1],row['second'].split('_f')[-1]
            names = {'1_s1':'2.5 ms','2_s1':'1.25 ms','4_s1':'0.625 ms','1_s2':'2.5 ms / 2x iterations'}
            label = names[a]+' vs '+names[b]
            axes[0].plot(milliseconds, archive[key+'_position_m'].max(axis=1)*1000, label=label)
            axes[1].plot(milliseconds, archive[key+'_speed_mps'].max(axis=1), label=label)
    axes[0].axhline(2, color='black', linestyle='--', linewidth=1)
    axes[1].axhline(.05, color='black', linestyle='--', linewidth=1)
    axes[0].set_ylabel('Largest sole position difference (mm)')
    axes[1].set_ylabel('Largest sole speed difference (m/s)')
    axes[1].set_xlabel('Time since first saved poststep sample (ms)')
    axes[0].legend(frameon=False, ncol=2, fontsize=8)
    for ax in axes:ax.grid(alpha=.2)
    fig.suptitle('Saved impact window remains numerically unqualified\nDashed lines are unchanged maximum-based gates; curves are sampled, not continuous-time bounds',fontsize=12)
    for suffix in ['png','pdf']:
        path=work/('foot_timestep_discrepancy.'+suffix)
        fig.savefig(path,dpi=180)
        outputs.append(path)
    plt.close(fig)
    report={'complete':True,'source_task_review_sha256':c.sha(cfg['task_review']),
            'source_timing_review_sha256':c.sha(cfg['timing_review']),
            'files':{str(p):c.sha(p) for p in outputs},'new_physics_steps':0,'new_render_passes':0,
            'production_accepted':False,'plots_do_not_change_quality_classification':True}
    c.write(E/cfg['output'],report)
    finish(report)


if __name__=='__main__':main(sys.argv[1])
