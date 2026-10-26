"""Recover frozen source navigation goals, then retime them with whole progress.

Source body poses are counterfactual observations, not navigation targets:
using an observed perturbed base position as its own goal would erase the
original robustness perturbation. This preserves the actual task/recovery goal.
"""
import math
import numpy as np


def source_goals(context,stages,intent,rows,result):
    lookup={s[0]:i for i,s in enumerate(stages)};certificates={r['stage']:r for r in result['stage_results']};goals=[]
    for row in rows:
        index=lookup[row['stage']];start,end=stages[index][1:];logical=row['logical_tick']*.02
        value=intent(context,logical,[np.zeros(3)]*2,[np.eye(3)]*2);height=value['height'];xy=[value['planned_x'],value['planned_y']];yaw=value['heading']
        if row['kind']=='nominal' and index>0:
            previous=certificates[stages[index-1][0]].get('certified_recovery') or {}
            if previous.get('passed'):
                fraction=min(1.,(logical-start)/min(2.5,end-start-.02))
                height=float(np.clip(height+(-.04 if previous['name']=='lower' else 0.)*(1-fraction*fraction*(3-2*fraction)),.64,.74))
        if row['kind']=='recovery':
            recovery=certificates[row['stage']]['certified_recovery']
            if not recovery['passed']:raise ValueError('source_recovery_not_certified')
            xy=recovery['target_xy'];height=row['height_command']
        goals.append([*xy,yaw,height])
    result=np.asarray(goals,dtype=float)
    if result.shape!=(len(rows),4) or not np.isfinite(result).all():raise ValueError('source_body_goal_layout')
    return result


def retime_goals(source,mapping):
    source=np.asarray(source);out=[]
    if source.ndim!=2 or source.shape[1]!=4 or not np.isfinite(source).all():raise ValueError('body_goal_layout')
    for tick,row in enumerate(mapping):
        if row['tick']!=tick or not 0<=row['fraction']<=1:raise ValueError('body_goal_clock')
        a=source[row['source_left']];b=source[row['source_right']];f=row['fraction']
        value=a.copy() if f==0 else b.copy() if f==1 else a+f*(b-a)
        delta=math.atan2(math.sin(b[2]-a[2]),math.cos(b[2]-a[2]));value[2]=a[2]+f*delta;out.append(value)
    return np.asarray(out)
