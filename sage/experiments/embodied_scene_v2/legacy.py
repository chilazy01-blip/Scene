"""Isolated old five-book ablation; no mass recalculation or bedroom substitution."""
from pathlib import Path
from copy import deepcopy
import json,time
import numpy as np
import trimesh
from sage.experiments.embodied_scene_v1.package import bound
from sage.experiments.codex_trellis_scene_v2.p021_physics import _geometry,metric_object_mesh
from sage.experiments.codex_trellis_scene_v2.leaning_books import voxel_boxes
from sage.experiments.codex_trellis_scene_v2.multilevel_proxy import build_component_aware_sdf
from sage.experiments.codex_trellis_scene_v2.collision_mesh_cleanup import cleanup_collision_mesh,CollisionMeshCleanupConfig
from .legacy_dynamics import simulate
from .config import ROOT,write_json,ledger

SOURCE=ROOT.with_name('p021_material_leaning_20260908_v1')/'leaning_fullflow_v3'

def prepare():
    out=ROOT/'legacy';out.mkdir(exist_ok=False)
    source=SOURCE/'physics_binding/geometry_binding.json';binding=json.loads(source.read_text())
    groups,_=_geometry(Path(binding['scene_glb']['path']),binding['spec']);meshes={}
    for name,obj in binding['objects'].items():
        mesh=metric_object_mesh(groups[name],np.asarray(obj['initial_body_matrix_z_up']))
        path=out/(name+'_true_mesh.npz');np.savez_compressed(path,vertices=mesh.vertices,faces=mesh.faces);meshes[name]=bound(path)
    shelf=binding['spec']['bookcase_id'];original=binding['objects'][shelf];pitch=original['collider']['pitch_m']/2
    raw=np.load(meshes[shelf]['path']);mesh=trimesh.Trimesh(raw['vertices'],raw['faces'],process=False)
    clean,cleanup=cleanup_collision_mesh(mesh,CollisionMeshCleanupConfig())
    if not cleanup['accepted']:clean=mesh.copy()
    proxy=build_component_aware_sdf(clean,pitch=pitch,padding_voxels=3,surface_dilation_voxels=0,fill_watertight_components=True,maximum_split_components=512,
        metadata={'purpose':'round2_collision_resolution_only','mass_recomputed':False,'source':bound(source)})
    proxy.save(out/'shelf_fine_voxels.npz');centers,half=voxel_boxes(proxy)
    path=out/'shelf_fine_cuboids.npz';np.savez_compressed(path,centers=centers,half_sizes=half)
    fine=deepcopy(binding);fine['objects'][shelf]['collider']=dict(method='same_undilated_component_voxels_half_pitch',pitch_m=pitch,box_count=len(centers),artifact=bound(path),occupied_volume_m3=float(np.prod(half*2,axis=1).sum()))
    for geom,b in [('G0',binding),('G1',fine)]:write_json(out/(geom+'_binding.json'),b)
    cases=[]
    for mu in [.005,.5]:
        for dt in [.001,.0005,.00025]:
            for geom in ['G0','G1']:
                for stiff in (['S0','S1'] if mu==.005 else ['S0']):
                    cases.append(dict(case_id=f'legacy__mu{mu}__dt{dt}__{geom}__{stiff}',mu=mu,dt=dt,geometry=geom,stiffness=stiff,timeconst_s=.004 if stiff=='S0' else .002))
    write_json(out/'cases.json',cases)
    write_json(out/'PROTOCOL.json',dict(source=bound(source),source_code=bound(SOURCE/'source_snapshot/leaning_books.py') if (SOURCE/'source_snapshot/leaning_books.py').exists() else bound(Path(__file__).with_name('legacy_dynamics.py')),
        models=[bound(out/(x+'_binding.json')) for x in ['G0','G1']],true_meshes=meshes,geometry_pitch=[.005,pitch],
        geometry_definition='same original cleanup/component occupancy/fill convention; only half pitch; includes original watertight-component fill, not a newly changed surface-only method',mass_and_inertia_unchanged=True,initial_poses_unchanged=True,solref_positive_timeconst=True,dt_safety_all_passed=all(c['dt']<=c['timeconst_s']/2+1e-12 for c in cases)))
    print('Legacy prepared',len(cases),'conditions;',len(centers),'fine shelf cuboids',flush=True)

def witness(row,binding,out):
    peak=row['peak_contact_witness'];dense=np.load(out/'dense_state.npz');index=peak['sample_index'];names=list(dense['object_ids']);frames=dense['matrix_world_z_up'];point=np.asarray(peak['position_m']);normal=np.asarray(peak['normal']);closest=[]
    for name in peak['owners']:
        if name=='floor':
            box=np.asarray(binding['floor']['world_bounds_z_up']);mesh=trimesh.creation.box(extents=np.ptp(box,axis=0));pose=np.eye(4);pose[:3,3]=box.mean(0)
        else:
            path=ROOT/'legacy'/(name+'_true_mesh.npz');raw=np.load(path);mesh=trimesh.Trimesh(raw['vertices'],raw['faces'],process=False);pose=frames[index,names.index(name)]
        local=(np.linalg.inv(pose)@np.r_[point,1])[:3]
        cp,dist,face=mesh.nearest.on_surface([local]);world=pose[:3,:3]@cp[0]+pose[:3,3]
        closest.append(dict(owner=name,closest_true_triangle_point_world=world.tolist(),witness_distance_m=float(dist[0]),face_id=int(face[0])))
    a,b=[np.asarray(c['closest_true_triangle_point_world']) for c in closest]
    ids=sorted(set(np.clip(index+np.rint(np.array([-.02,-.005,0,.005,.02])/row['dt_s']).astype(int),0,len(frames)-1)))
    evidence=dict(peak=peak,actual_triangle_nearest_points=closest,normal_projected_local_gap_m=float(np.dot(b-a,normal)),nearest_point_separation_m=float(np.linalg.norm(b-a)),
        limitation='Local nearest-triangle separation at solver witness, not a certified global signed mesh penetration depth.',frames=[dict(time_s=float(dense['time_s'][i]),sample_index=int(i),bodies={str(n):dict(matrix_world_z_up=frames[i,j].tolist()) for j,n in enumerate(names)}) for i in ids])
    write_json(out/'IMPACT_EVIDENCE.json',evidence)

def run_case(c):
    out=ROOT/'legacy'/c['case_id'];binding=json.loads((ROOT/'legacy'/(c['geometry']+'_binding.json')).read_text());binding['round2_timeconst_multiplier']=c['timeconst_s']/.004
    ledger(dict(case_id=c['case_id'],event='attempt_start',output=str(out),stratum='legacy'))
    r=simulate(binding,out,mu=c['mu'],dt=c['dt']);witness(r,binding,out)
    if c['geometry']=='G0' and c['stiffness']=='S0':
        old=SOURCE/'dynamics'/f"{'low' if c['mu']==.005 else 'normal'}_{c['dt']:.6f}"/'dense_state.npz'
        a=np.load(old);b=np.load(out/'dense_state.npz');write_json(out/'OLD_REPRODUCTION.json',dict(source=bound(old),integration_state_bitwise_equal=bool(np.array_equal(a['integration_state'],b['integration_state'])),max_state_difference=float(np.max(abs(a['integration_state']-b['integration_state'])))))
    ledger(dict(case_id=c['case_id'],event='attempt_end',status='completed',result=bound(out/'result.json'),stratum='legacy'))
    print(c['case_id'],'max penetration',r['max_contact_penetration_m'],flush=True)
