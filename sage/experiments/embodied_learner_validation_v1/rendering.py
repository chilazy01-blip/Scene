"""Reconstruct the exact recorded camera contract; never guess online camera pose."""
from pathlib import Path
import mujoco
from sage.experiments.embodied_abc_v1.quality_visual import build_pair
from sage.experiments.embodied_abc_v1.visual import configure, CAMERAS
from sage.experiments.embodied_scene_bridge.contracts import read


class Renderer:
    def __init__(self, package, camera_contract):
        _, self.model, self.physics_checks = build_pair(Path(package))
        self.data = mujoco.MjData(self.model)
        self.options = configure(self.model, appearance='baseline', camera='source')
        for key, item in read(camera_contract).items():
            camera = self.model.camera(item['model_camera'])
            assert list(item['resolution']) == [320, 240]
            self.model.cam_pos[camera.id] = item['local_position_m']
            self.model.cam_quat[camera.id] = item['local_quaternion_wxyz']
            self.model.cam_fovy[camera.id] = item['fovy_degrees']
        self.renderer = mujoco.Renderer(self.model, height=240, width=320)

    def render(self, state):
        mujoco.mj_setState(self.model, self.data, state, mujoco.mjtState.mjSTATE_INTEGRATION)
        mujoco.mj_forward(self.model, self.data)
        result = {}
        for key, name in CAMERAS.items():
            self.renderer.update_scene(self.data, camera=name, scene_option=self.options)
            result[key] = self.renderer.render().copy()
        return result

    def close(self):
        self.renderer.close()
