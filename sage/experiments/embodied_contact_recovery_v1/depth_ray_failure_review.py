"""Compare anomalous saved depth pixels against geometry and renderer sampling."""
import os,sys
from pathlib import Path
import numpy as np,h5py,mujoco
from PIL import Image
from .work import E,c,finish


def main(config_path):
    cfg=c.read(config_path);work=Path(os.environ['CONTINUOUS_JOB_DIR']);source=Path(cfg['source_episode'])
    m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
    mujoco.mj_step=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('no integration'))
    usage={'render_passes':0};results=[]
    with h5py.File(cfg['canonical'],'r') as h,h5py.File(source/'TRACE.h5','r') as f:
        for frame in cfg['frames']:
            k=int(h['source_substep_indices'][frame]);mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
            cam=cfg['camera'];cid=m.camera(cam).id;u,v=cfg['pixel'];stored=float(h['cameras/'+cam+'/depth_m'][frame,v,u])
            Image.fromarray(h['cameras/'+cam+'/rgb'][frame]).save(work/f'{frame}_{cam}.png')
            focal=128/np.tan(np.radians(m.cam_fovy[cid])/2);rotation=d.cam_xmat[cid].reshape(3,3)@np.diag([1.,-1.,-1.]);origin=d.cam_xpos[cid].copy();near=float(m.vis.map.znear*m.stat.extent)
            samples=[]
            for du,dv in [(0.5,0.5),(0.375,0.875),(0.875,0.625),(0.125,0.375),(0.625,0.125),(-.5,.5),(1.5,.5),(.5,-.5),(.5,1.5)]:
                ray=np.array([(u+du-128)/focal,(v+dv-128)/focal,1.]);length=float(np.linalg.norm(ray));direction=rotation@ray/length;gid=np.zeros(1,np.int32)
                distance=mujoco.mj_ray(m,d,origin+direction*near*length,direction,np.array([1,1,1,0,0,0],np.uint8),1,-1,gid)
                g=int(gid[0]);depth=(distance+near*length)/length
                samples.append({'pixel_offset':[du,dv],'depth_m':depth,'saved_error_m':abs(stored-depth),'geom':m.geom(g).name if distance>=0 else None,'geom_id':g,'geom_type':int(m.geom_type[g]) if distance>=0 else None,'rgba':m.geom_rgba[g].tolist() if distance>=0 else None})
            renders=[];original_samples=int(m.vis.quality.offsamples)
            for ns in [original_samples,1]:
                m.vis.quality.offsamples=ns;renderer=mujoco.Renderer(m,256,256)
                try:
                    renderer.update_scene(d,camera=cam);renderer.disable_depth_rendering();usage['render_passes']+=1;renderer.render()
                    renderer.enable_depth_rendering();usage['render_passes']+=1;depth=renderer.render().copy()
                    renders.append({'offsamples':ns,'depth_at_pixel_m':float(depth[v,u]),'saved_error_m':abs(float(depth[v,u])-stored),'neighborhood_m':depth[v-1:v+2,u-1:u+2].tolist()})
                    c.write(work/'USAGE.json',usage)
                finally:renderer.close()
            m.vis.quality.offsamples=original_samples
            results.append({'frame':frame,'camera':cam,'pixel':[u,v],'saved_depth_m':stored,'geometric_rays':samples,'renders':renders})
    report={'new_physics_steps':0,'results':results,'renderer_quality_variants_are_diagnostic_only':True,'saved_images_unchanged':True,'production_accepted':False}
    c.write(E/cfg['output'],report);finish(report,usage)


if __name__=='__main__':main(sys.argv[1])
