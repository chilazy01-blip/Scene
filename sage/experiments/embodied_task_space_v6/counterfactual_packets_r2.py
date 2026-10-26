"""Map a whole retimed path to frozen source body-command hypotheses.

No policy, phase clock, physics or causal certificate is supplied here.
The result is eligible only for counterfactual native-command coverage after
separate complete geometry admission. Dynamic use needs prospective causal
profiles and bounds; static source commands cannot establish task success.
"""
import numpy as np


def source_indices(source_rows, stages):
    labels=[row['stage'] for row in source_rows]
    blocks=[];seen=[]
    for i,label in enumerate(labels):
        if not seen or seen[-1]!=label:seen.append(label)
    if seen!=list(stages):raise ValueError('source_phase_order_or_denominator')
    for stage in stages:
        ids=np.flatnonzero(np.asarray(labels)==stage)
        if len(ids)==0 or not np.array_equal(ids,np.arange(ids[0],ids[-1]+1)):
            raise ValueError('source_phase_not_contiguous')
        blocks.append(np.r_[max(0,int(ids[0])-1),ids])
    return blocks


def compile_packets(source_rows, source_commands, stages, reference, progress, offsets, active, nominal):
    reference=np.asarray(reference);progress=np.asarray(progress);offsets=np.asarray(offsets);active=np.asarray(active);nominal=np.asarray(nominal)
    if active.shape!=(43,) or active.dtype!=np.dtype(bool) or nominal.shape!=(43,):raise ValueError('joint_identity')
    if reference.shape!=(len(progress),int(active.sum())) or offsets.shape!=(len(stages)+1,):raise ValueError('path_dimensions')
    if not np.issubdtype(offsets.dtype,np.integer) or offsets[0]!=0 or offsets[-1]!=len(progress) or np.any(np.diff(offsets)<=0):raise ValueError('path_phase_offsets')
    if not all(np.isfinite(v).all() for v in [reference,progress,nominal]):raise ValueError('nonfinite_path')
    if len(source_commands)!=len(source_rows):raise ValueError('source_command_count')
    for i,(row,record) in enumerate(zip(source_rows,source_commands)):
        if record['tick']!=i or record['stage']!=row['stage'] or record['packet']['tick']!=i:raise ValueError('source_tick_or_stage')
        packet=record['packet']
        if packet['dt']!=.02 or packet['frame']!='body_heading' or packet['units']!='SI_rad':raise ValueError('source_units')
    blocks=source_indices(source_rows,stages);packets=[];mapping=[]
    for phase,ids in enumerate(blocks):
        begin,end=map(int,offsets[phase:phase+2]);p=progress[begin:end]
        if np.min(p)<-2e-8 or np.max(p)>1+2e-8 or np.min(np.diff(np.r_[0.,p])) < -2e-8 or np.max(abs(p[-25:]-1))>2e-8:raise ValueError('source_progress_contract')
        for tick in range(begin,end):
            x=float(np.clip(progress[tick],0.,1.))*(len(ids)-1);left=int(np.floor(x));right=min(left+1,len(ids)-1);fraction=x-left
            a=source_commands[int(ids[left])]['packet'];b=source_commands[int(ids[right])]['packet'];body={}
            for field,shape in [('navigate',(3,)),('rpy',(3,)),('height',())]:
                lo=np.asarray(a[field],dtype=float);hi=np.asarray(b[field],dtype=float)
                if lo.shape!=shape or hi.shape!=shape or not np.isfinite(lo).all() or not np.isfinite(hi).all():raise ValueError('source_body_shape_or_finite')
                value=lo.copy() if fraction==0 else hi.copy() if fraction==1 else lo+fraction*(hi-lo);body[field]=float(value) if shape==() else value.tolist()
            q=nominal.copy();q[active]=reference[tick]
            packets.append(dict(tick=tick,dt=.02,frame='body_heading',units='SI_rad',**body,q_reference=q.tolist()))
            mapping.append(dict(tick=tick,phase=phase,source_left=int(ids[left]),source_right=int(ids[right]),fraction=fraction))
    return packets,mapping
