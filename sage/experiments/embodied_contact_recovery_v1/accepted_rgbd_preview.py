"""Extract exact accepted research pixels for visual inspection without rendering."""
import os,sys
from pathlib import Path
import numpy as np,h5py
from PIL import Image
from .work import E,c,finish

def main(config):
 cfg=c.read(config);root=Path(cfg['dataset_root']);work=Path(os.environ['CONTINUOUS_JOB_DIR']);binding=c.read(root/'BINDING.json');acceptance=c.read(cfg['acceptance_report']);assert acceptance['passed'] and acceptance['dataset_binding_sha256']==c.sha(root/'BINDING.json');assert binding['diagnostic_sites_visible'] is False
 files=[]
 with h5py.File(root/'canonical.h5','r') as f:
  for row in cfg['frames']:
   for camera in binding['cameras']:
    pixels=f['cameras/'+camera+'/rgb'][row];path=work/(camera+'_'+str(row)+'.png');Image.fromarray(pixels).save(path)
    assert np.array_equal(np.asarray(Image.open(path)),pixels)
    files.append({'frame':row,'camera':camera,'file':str(path),'sha256':c.sha(path),'pixel_roundtrip_exact':True})
 report={'passed':True,'images':files,'new_render_passes':0,'new_physics_steps':0,'source_failed_development':True,'production_accepted':False,'dataset_binding_sha256':c.sha(root/'BINDING.json')};c.write(E/cfg['output'],report);finish(report)
if __name__=='__main__':main(sys.argv[1])
