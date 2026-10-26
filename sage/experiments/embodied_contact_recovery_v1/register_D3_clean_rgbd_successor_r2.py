"""Bind the next D3 export stage only after actual prerequisite files exist."""
import copy,json,re
from pathlib import Path
from .work import E,c
from . import controller_recovery_v4 as controller


def renamed(value):
    return json.loads(json.dumps(value).replace('C3_full_RGBD_', 'D3_clean_full_RGBD_').replace('C3_RGBD_shard_', 'D3_clean_RGBD_shard_').replace('C3_FULL_RGBD_', 'D3_CLEAN_FULL_RGBD_').replace('C3_', 'D3_').replace('C_development_03', 'D_development_03'))


def main():
    state=c.read(E/'STATE.json');definitions=state['additional_jobs'];additions={}
    def succeeded(name):return state['jobs'].get(name,{}).get('status')=='succeeded'
    def clone(source,key,config):
        if key in state['jobs']:return
        old=definitions[source];new=renamed(copy.deepcopy(old));case=E/'cases'/(key+'.json')
        if case.exists():assert c.read(case)==config
        else:c.write(case,config)
        new['argv'][-1]=str(case)
        files=[]
        for path in old['inputs']:
            if path==old['argv'][-1]:continue
            dest=Path(renamed(path))
            match=re.search(r'D3_clean_RGBD_shard_(\d+)',str(dest))
            if match and int(match.group(1))>=5:continue
            match=re.search(r'D3_clean_full_RGBD_read_(\d+)',str(dest))
            if match and int(match.group(1))>=3:continue
            match=re.search(r'/chunks/(\d+)\.h5$',str(dest))
            if match and int(match.group(1))>=5:continue
            assert dest.is_file(),str(dest)
            files.append(dest)
        if key.endswith('assembly_01'):
            module=Path(__file__).with_name('rgbd_episode_assembly_r3.py')
            files.append(module); files.append(Path(__file__).with_name('rgbd_shards_r2.py'))
            new['argv']=[x.replace('sage.experiments.embodied_contact_recovery_v1.rgbd_episode_assembly_r2','sage.experiments.embodied_contact_recovery_v1.rgbd_episode_assembly_r3') for x in new['argv']]
        new['inputs']={str(p):c.sha(p) for p in [*files,case]}
        additions[key]=new
    assembly='D3_clean_full_RGBD_assembly_01';export='D3_clean_full_RGBD_export_01'
    if all(succeeded(f'D3_clean_RGBD_shard_{i:04}') for i in range(5)):
        cfg=renamed(c.read(definitions['C3_full_RGBD_assembly_01']['argv'][-1]));cfg['shard_jobs']=cfg['shard_jobs'][:5];cfg['expected_rows']=1066
        clone('C3_full_RGBD_assembly_01',assembly,cfg)
    if succeeded(assembly):clone('C3_full_RGBD_export_01',export,renamed(c.read(definitions['C3_full_RGBD_export_01']['argv'][-1])))
    if succeeded(export):
        for i,(first,stop) in enumerate([(0,500),(500,1000),(1000,1066)]):
            key=f'D3_clean_full_RGBD_read_{i:02}';cfg={'dataset_root':str(E/'jobs'/export/'dataset'),'first_row':first,'stop_row':stop}
            clone('C3_full_RGBD_read_00',key,cfg)
    if all(succeeded(f'D3_clean_full_RGBD_read_{i:02}') for i in range(3)):
        cfg=renamed(c.read(definitions['C3_full_RGBD_acceptance_01']['argv'][-1]));cfg['read_jobs']=cfg['read_jobs'][:3]
        clone('C3_full_RGBD_acceptance_01','D3_clean_full_RGBD_acceptance_01',cfg)
    if additions:
        result=controller.extend_jobs(E,additions,'Continue full failed D3 RGBD export and real-reader validation from completed bound predecessor artifacts')
        print({'registered':list(additions),'decision':result['action']})
    else:print({'registered':[],'waiting_for_actual_prerequisites':True})


if __name__=='__main__':main()
