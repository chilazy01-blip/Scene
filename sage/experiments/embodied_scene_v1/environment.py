"""Small interactive API over a frozen episode model (no training claim)."""
import os
os.environ.setdefault('MUJOCO_GL', 'egl')
from pathlib import Path
import json
import numpy as np
import mujoco
from .cameras import canonicalize_stretch_cameras


class SceneEnvironment:
    """Load once; reset(seed=0), step(actuator_controls), render(), save/restore().

    Controls retain the native model actuator units. Panda uses joint torques
    and finger position targets; Stretch uses the original mixed actuators.
    Episode task.json and model actuator ranges describe the exact interface.
    """
    def __init__(self, episode):
        self.path = Path(episode)
        self.task = json.loads((self.path/'task.json').read_text())
        self.model = (mujoco.MjModel.from_binary_path(str(self.path/'model.mjb')) if (self.path/'model.mjb').exists()
                      else mujoco.MjModel.from_xml_path(str(self.path/'model.xml')))
        self.optical_correction=canonicalize_stretch_cameras(self.model) if self.task['task']=='navigate' else []
        self.data = mujoco.MjData(self.model)
        reset = np.load(self.path/'reset_state.npz',allow_pickle=False)
        self.initial_state = reset['state'].copy()
        self.mask = mujoco.mjtState(int(reset['state_spec']))
        self.renderer = None
        self.reset()

    def reset(self, seed=0):
        if seed != 0:
            raise ValueError('This frozen pilot supports seed=0 only; randomization requires a new task version')
        mujoco.mj_resetData(self.model,self.data)
        self.restore(self.initial_state)
        return self.observe()

    def save(self):
        state = np.empty(mujoco.mj_stateSize(self.model,self.mask))
        mujoco.mj_getState(self.model,self.data,state,self.mask)
        return state

    def restore(self,state):
        state=np.asarray(state,dtype=float)
        if state.shape != self.initial_state.shape or not np.isfinite(state).all():
            raise ValueError('Invalid integration state')
        mujoco.mj_setState(self.model,self.data,state,self.mask)
        mujoco.mj_forward(self.model,self.data)

    def step(self,action,substeps=1):
        action=np.asarray(action,dtype=float)
        if action.shape != (self.model.nu,) or not np.isfinite(action).all():
            raise ValueError('Action must be a finite vector of model.nu actuator controls')
        limited=self.model.actuator_ctrllimited.astype(bool)
        if np.any(action[limited] < self.model.actuator_ctrlrange[limited,0]) or np.any(action[limited] > self.model.actuator_ctrlrange[limited,1]):
            raise ValueError('Action exceeds model actuator control limits')
        if not isinstance(substeps,int) or not 1 <= substeps <= 100:
            raise ValueError('substeps must be an integer in [1,100]')
        self.data.ctrl[:]=action
        mujoco.mj_step(self.model,self.data,nstep=substeps)
        # Sensors and body transforms correspond to returned qpos and time.
        mujoco.mj_forward(self.model,self.data)
        return self.observe()

    def observe(self):
        return dict(time=float(self.data.time),qpos=self.data.qpos.copy(),qvel=self.data.qvel.copy(),
                    controls=self.data.ctrl.copy(),body_positions=self.data.xpos.copy(),sensors=self.data.sensordata.copy())

    def render(self,camera=None,width=640,height=480):
        if self.task.get('physics_only'):raise ValueError('Use the full visual episode for RGB/depth observations')
        if self.renderer is None:
            self.renderer=mujoco.Renderer(self.model,height=height,width=width)
        if camera is None:
            camera=mujoco.MjvCamera();camera.lookat[:]=[.8,1.5,.8];camera.distance=2.5;camera.azimuth=150;camera.elevation=-30
        option=mujoco.MjvOption();option.geomgroup[3:]=0;option.sitegroup[:]=0
        if isinstance(camera,str):option.geomgroup[4]=1
        self.renderer.update_scene(self.data,camera=camera,scene_option=option)
        self.renderer.disable_depth_rendering();self.renderer.disable_segmentation_rendering()
        rgb=self.renderer.render().copy()
        self.renderer.enable_depth_rendering();depth=self.renderer.render().copy();self.renderer.disable_depth_rendering()
        self.renderer.enable_segmentation_rendering();seg=self.renderer.render().copy();self.renderer.disable_segmentation_rendering()
        return dict(time=float(self.data.time),rgb=rgb,depth_m=depth,segmentation_object_id_type=seg)

    def close(self):
        if self.renderer is not None:self.renderer.close();self.renderer=None
