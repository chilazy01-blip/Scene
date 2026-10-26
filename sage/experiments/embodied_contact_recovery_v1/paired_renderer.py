"""Read RGB and metric depth from the same pinnedMuJoCo3.7 raster pass."""
import numpy as np
import mujoco

def rgbd(renderer,model):
 assert mujoco.__version__=='3.7.0'
 renderer.disable_depth_rendering()
 rgb=renderer.render().copy()
 raw=np.empty((renderer.height,renderer.width),dtype=np.float32)
 mujoco.mjr_readPixels(None,raw,renderer._rect,renderer._mjr_context)
 znear=np.float32(model.vis.map.znear*model.stat.extent);zfar=np.float32(model.vis.map.zfar*model.stat.extent)
 c=-(zfar+znear)/(zfar-znear);d=-(np.float32(2)*zfar*znear)/(zfar-znear)
 c=np.float32(-.5)*c-np.float32(.5);d=np.float32(-.5)*d
 depth=(d/(raw.astype(np.float64)+c)).astype(np.float32)
 if renderer._gl_context:depth=np.flipud(depth).copy()
 return rgb,depth
