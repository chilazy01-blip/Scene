"""Exact zero-integration checkpoint/controller-history restoration, never a new pose."""
import numpy as np
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import reorder_mujoco_to_isaaclab


def load_after(mj,model,data,s):
    data.qpos[:]=s['full_qpos_after'];data.qvel[:]=s['full_qvel_after']
    data.qacc_warmstart[:]=s['qacc_warmstart_after'];data.ctrl[:]=s['all_ctrl'];data.time=s['time_after_s']
    data.qfrc_applied[:]=0;data.xfrc_applied[:]=0
    mj.mj_forward(model,data)
    assert np.array_equal(data.qpos,s['full_qpos_after']) and np.array_equal(data.qvel,s['full_qvel_after'])
    assert np.array_equal(data.qacc_warmstart,s['qacc_warmstart_after']) and data.time==s['time_after_s']


def restore(mj,model,data,task,trace,actions,history,defaults,scales):
    assert model.na==model.nmocap==model.neq==model.nuserdata==model.nplugin==0
    data.qpos[:]=trace['initial_qpos'];data.qvel[:]=trace['initial_qvel'];data.time=0
    data.qacc_warmstart[:]=0;data.ctrl[:]=0;mj.mj_forward(model,data)
    for i in range(0,len(trace['warmup_substeps']),4):
        history();target=task.q[0,7:].copy()
        actions[i//4]=reorder_mujoco_to_isaaclab((target-defaults)/scales)
        load_after(mj,model,data,trace['warmup_substeps'][i+3])
    last=trace['warmup_substeps'][-1]
    for row in trace['records']:
        assert np.array_equal(data.qpos,row['substeps'][0]['full_qpos_before'])
        task.update(row['tick'],data,last);task.synchronize(row['tick'],data)
        assert task.stage==row['stage'] and np.array_equal(task.q[row['tick']],row['reference_qpos'])
        assert np.array_equal(task.v[row['tick']],row['reference_velocity'])
        history();actions[row['tick']+10]=np.asarray(row['applied_action_isaaclab'],dtype=np.float32)
        last=row['substeps'][-1];load_after(mj,model,data,last)
    return dict(prefix_physics_steps=len(trace['warmup_substeps'])+sum(len(r['substeps']) for r in trace['records']),
                prefix_active_ticks=len(trace['records']),restored_state_exact=True,extra_activation_plugin_mocap_equality_userdata_states=0)
