"""Select contact transients from existing traces without new dynamics."""
import sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,c,finish
from .grasp_numerical_evidence import hand_rows


def main(config_path):
    cfg=c.read(config_path);windows=[]
    for item in cfg['windows']:
        folder=E/'jobs'/item['source_job']/'episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'))
        with h5py.File(folder/'TRACE.h5','r') as f:
            contacts=f['contacts/rows'][:];total=len(f['substep/qpos'])
        if item['contact']=='hand':selected=hand_rows(m,contacts)
        else:
            feet=[g for g in range(m.ngeom) if 'ankle_roll' in m.body(int(m.geom_bodyid[g])).name]
            ground=m.geom('ground').id
            selected=contacts[(np.isin(contacts[:,1],feet)&(contacts[:,2]==ground))|(np.isin(contacts[:,2],feet)&(contacts[:,1]==ground))]
        assert len(selected)
        if item.get('metric','penetration')=='force':
            summed=np.zeros(total);np.add.at(summed,selected[:,0].astype(int),np.maximum(selected[:,7],0));peak=int(np.argmax(summed))
        else:peak=int(selected[np.argmin(selected[:,3]),0])
        count=min(item['saved_steps'],total);start=max(0,min(peak-count//2,total-count));cases=[]
        for factor,solver in [(1,1),(2,1),(4,1),(1,2)]:
            key=item['prefix']+f'_f{factor}_s{solver}';case=E/'cases'/(key+'.json');assert not case.exists()
            c.write(case,{'source_folder':str(folder),'start_row':start,'saved_steps':count,'subdivisions':factor,'solver_iteration_factor':solver,'fixed_actual_commands':True,'selected_contact':item['contact']});cases.append(str(case))
        windows.append({**item,'source_trace_sha256':c.sha(folder/'TRACE.h5'),'peak_row':peak,'start_row':start,'saved_steps':count,'cases':cases,'total_integration_steps_reserved':8*count})
    report={'new_physics_steps':0,'windows':windows,'production_accepted':False,'scope':'Measured contact-specific saved-state windows; exact nominal,half/quarter timestep and doubled iterations, no whole-task convergence claim.'};c.write(E/cfg['output'],report);finish(report)


if __name__=='__main__':main(sys.argv[1])
