"""Identical camera extraction for offline observations and closed-loop policy input."""
import mujoco
import numpy as np
from .visual import configure, CAMERAS
from .quality_visual import build_pair

class ObservationRenderer:
    def __init__(self, package, width=320, height=240, improved=True):
        if improved:
            _,self.model,self.physics_checks=build_pair(package)
        else:
            self.model=mujoco.MjModel.from_xml_path(str(package/'model.xml'))
            self.physics_checks={}
        self.data=mujoco.MjData(self.model)
        self.options=configure(self.model,width=width,height=height)
        self.renderer=mujoco.Renderer(self.model,height=height,width=width)
        self.mask=mujoco.mjtState.mjSTATE_INTEGRATION

    def render(self, state):
        assert len(state)==mujoco.mj_stateSize(self.model,self.mask)
        mujoco.mj_setState(self.model,self.data,state,self.mask)
        mujoco.mj_forward(self.model,self.data)
        frames={}
        for key,name in CAMERAS.items():
            self.renderer.update_scene(self.data,camera=name,scene_option=self.options)
            frames[key]=self.renderer.render().copy()
        return frames

    def close(self):
        self.renderer.close()
