"""Assemble real source GLBs or render their measured free-body trajectories."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys

import bpy
import numpy as np
from mathutils import Matrix,Vector

GLTF_TO_Z=np.array([[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]],dtype=float)

def bound(path):
    path=Path(path);return {'path':str(path.resolve()),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def check(record):
    actual=bound(record['path'])
    if any(actual[k]!=record[k] for k in ('bytes','sha256')):raise ValueError('Changed input: '+record['path'])

def write(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')

def mesh_points(obj):
    values=np.empty(len(obj.data.vertices)*3);obj.data.vertices.foreach_get('co',values)
    matrix=np.asarray(obj.matrix_world);return values.reshape(-1,3)@matrix[:3,:3].T+matrix[:3,3]

def assemble(plan_path,output):
    plan=json.loads(plan_path.read_text());bpy.ops.wm.read_factory_settings(use_empty=True)
    audit={}
    for row in plan['assets']:
        check(row['source_glb']);before=set(bpy.context.scene.objects)
        bpy.ops.import_scene.gltf(filepath=row['source_glb']['path'])
        members=list(set(bpy.context.scene.objects)-before)
        imported_roots=[o for o in members if o.parent not in members]
        root=bpy.data.objects.new(row['id']+'_root',None);bpy.context.scene.collection.objects.link(root)
        for index,obj in enumerate(members):
            obj.name=f"{row['id']}_source_{index:03d}"
            obj['scene_object_id']=row['id'];obj['scene_category']=row['category']
        pose=np.asarray(row['initial_body_matrix_z_up'])
        normalize=np.linalg.inv(pose)@np.asarray(row['source_to_world_gltf'])@GLTF_TO_Z.T
        for obj in imported_roots:
            old=obj.matrix_world.copy();obj.parent=root
            obj.matrix_world=Matrix(normalize.tolist())@old
        root['scene_object_id']=row['id'];root['scene_category']=row['category']
        root['physical_profile_json']=json.dumps(row['physical_profile'],sort_keys=True)
        # Import already maps source glTF Y-up into Blender Z-up.
        root.matrix_world=Matrix(pose.tolist());bpy.context.view_layer.update()
        points=np.concatenate([mesh_points(o) for o in members if o.type=='MESH'])
        target=np.asarray(row['expected_world_bounds_m'])
        actual=np.array([points.min(axis=0),points.max(axis=0)])
        if not np.allclose(actual,target,atol=2e-5,rtol=0):raise ValueError('Source transform mismatch: '+row['id'])
        audit[row['id']]={'source_glb':row['source_glb'],'actual_world_bounds_m':actual.tolist(),
                          'root_matrix_z_up':pose.tolist(),'mesh_count':sum(o.type=='MESH' for o in members)}
    dims=plan['room'];bpy.ops.mesh.primitive_cube_add(location=(dims['width']/2,dims['length']/2,-.05))
    floor=bpy.context.object;floor.name='floor';floor.dimensions=(dims['width'],dims['length'],.1)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    mat=bpy.data.materials.new('neutral_floor');mat.diffuse_color=(.62,.61,.57,1);mat.use_nodes=True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(.62,.61,.57,1)
    mat.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value=.8;floor.data.materials.append(mat)
    w,h,z=dims['width'],dims['length'],dims['height']
    for name,location,size in [('wall_west',(-.05,h/2,z/2),(.1,h,z)),
            ('wall_east',(w+.05,h/2,z/2),(.1,h,z)),('wall_south',(w/2,-.05,z/2),(w,.1,z)),
            ('wall_north',(w/2,h+.05,z/2),(w,.1,z))]:
        bpy.ops.mesh.primitive_cube_add(location=location);wall=bpy.context.object;wall.name=name
        wall['architecture_wall']=True;wall.dimensions=size
        bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);wall.data.materials.append(mat)
    output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',export_extras=True)
    write(output.with_suffix('.assembly.json'),{'scene_glb':bound(output),'source_plan':bound(plan_path),
          'assets':audit,'independent_book_roots':len([a for a in plan['assets'] if a['category']=='single_book']),
          'furniture_geometry_created_in_blender':False})

def render(scene_path,binding_path,trajectory_path,output,resolution,samples):
    binding=json.loads(binding_path.read_text());trajectory=json.loads(trajectory_path.read_text())
    check(binding['scene_glb']);check(trajectory['scene_glb']);check(trajectory['dense_state'])
    if bound(scene_path)['sha256']!=binding['scene_glb']['sha256']:raise ValueError('Scene binding differs')
    output.mkdir(parents=True,exist_ok=False);bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(scene_path));bpy.context.view_layer.update()
    cutaway=[]
    for obj in bpy.context.scene.objects:
        if obj.get('architecture_wall'):
            obj.hide_render=True;cutaway.append(obj.name)
    roots={};visual_initial={}
    for identifier,obj in binding['objects'].items():
        candidates=[o for o in bpy.context.scene.objects if o.get('scene_object_id')==identifier
                    and (o.parent is None or o.parent.get('scene_object_id')!=identifier)]
        if len(candidates)!=1:raise ValueError('Independent visual root missing: '+identifier)
        roots[identifier]=candidates[0];visual_initial[identifier]=np.asarray(candidates[0].matrix_world).copy()
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=samples
    scene.cycles.use_denoising=True;scene.render.resolution_x=resolution;scene.render.resolution_y=resolution
    scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    if scene.world is None:scene.world=bpy.data.worlds.new('experiment_world')
    scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.8,.8,.8,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.7
    static_id=next(s for s,o in binding['objects'].items() if o['static'])
    shelf_center=np.asarray(binding['objects'][static_id]['world_bounds_z_up']).mean(axis=0)
    for i,(location,power,size) in enumerate([(shelf_center+[-1.2,-2,2.2],450,3),(shelf_center+[1.5,-1,1.7],300,2)]):
        data=bpy.data.lights.new(f'area_{i}','AREA');data.energy=power;data.shape='DISK';data.size=size
        obj=bpy.data.objects.new(data.name,data);scene.collection.objects.link(obj);obj.location=location
        obj.rotation_euler=(Vector(shelf_center)-obj.location).to_track_quat('-Z','Y').to_euler()
    bookids=[s for s in binding['objects'] if not binding['objects'][s]['static']]
    bounds=np.array([binding['objects'][s]['world_bounds_z_up'] for s in bookids]);target=bounds.mean(axis=(0,1))
    cams={}
    for name,location,look,scale in [
            ('overview',shelf_center+[3.5,-5.5,3.],shelf_center,6.6),
            ('bookcase',shelf_center+[1.15,-2.6,1.1],shelf_center,2.0),
            ('books',(target[0]-.25,target[1]-1.1,target[2]+.20),target,.60)]:
        data=bpy.data.cameras.new(name);data.type='ORTHO';data.ortho_scale=scale
        obj=bpy.data.objects.new(name,data);scene.collection.objects.link(obj);obj.location=location
        obj.rotation_euler=(Vector(look)-obj.location).to_track_quat('-Z','Y').to_euler();cams[name]=obj
    records=[]
    with np.load(trajectory['dense_state']['path'],allow_pickle=False) as dense:
        ids=dense['object_ids'].tolist()
        for frame_index,frame in enumerate(trajectory['frames']):
            index=frame['dense_sample_index']
            if abs(dense['time_s'][index]-frame['time_s'])>1e-9:raise ValueError('Frame timestamp mismatch')
            for identifier,obj in roots.items():
                now=np.asarray(frame['bodies'][identifier]['matrix_world_z_up'])
                if not np.allclose(now,dense['matrix_world_z_up'][index,ids.index(identifier)],atol=1e-10,rtol=0):
                    raise ValueError('Render pose differs from saved physics')
                delta=now@np.linalg.inv(np.asarray(binding['objects'][identifier]['initial_body_matrix_z_up']))
                obj.matrix_world=Matrix((delta@visual_initial[identifier]).tolist())
            bpy.context.view_layer.update()
            for name in (['overview','bookcase','books'] if frame_index in (0,len(trajectory['frames'])-1) else ['books']):
                scene.camera=cams[name];path=output/f'{frame_index:03d}_{name}.png';scene.render.filepath=str(path)
                bpy.ops.render.render(write_still=True)
                records.append({'time_s':frame['time_s'],'dense_sample_index':index,'camera':name,'image':bound(path),
                                'camera_matrix_z_up':np.asarray(scene.camera.matrix_world).tolist(),
                                'camera_ortho_scale_m':scene.camera.data.ortho_scale,
                                'visual_root_matrices':{s:np.asarray(o.matrix_world).tolist() for s,o in roots.items()}})
    write(output/'render_manifest.json',{'schema':'p021-leaning-render/v1','scene':bound(scene_path),
        'binding':bound(binding_path),'trajectory':bound(trajectory_path),'frames':records,
        'render_engine':'CYCLES','device':'CPU','resolution':resolution,'samples':samples,
        'architectural_cutaway_hidden_walls':cutaway,
        'all_rendered_poses_checked_against_dense_physics':True})

def inspect_assets(scene_path,binding_path,output):
    binding=json.loads(binding_path.read_text());check(binding['scene_glb'])
    output.mkdir(parents=True,exist_ok=False);bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(scene_path));bpy.context.view_layer.update()
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=16
    scene.cycles.use_denoising=True;scene.render.resolution_x=512;scene.render.resolution_y=512
    scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    if scene.world is None:scene.world=bpy.data.worlds.new('inspection_world')
    scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(1,1,1,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.8
    lamp=bpy.data.lights.new('inspection_light','AREA');lamp.energy=100;lamp.size=1
    light=bpy.data.objects.new(lamp.name,lamp);scene.collection.objects.link(light)
    camera=bpy.data.cameras.new('inspection_camera');camera.type='ORTHO';camera.ortho_scale=.36
    cam=bpy.data.objects.new(camera.name,camera);scene.collection.objects.link(cam);scene.camera=cam
    records=[]
    for identifier,obj in binding['objects'].items():
        if obj['static']:continue
        target=np.asarray(obj['world_bounds_z_up']).mean(axis=0)
        for mesh in meshes:mesh.hide_render=mesh.get('scene_object_id')!=identifier
        light.location=target+np.array([-.4,-.6,.7]);light.rotation_euler=(Vector(target)-light.location).to_track_quat('-Z','Y').to_euler()
        for name,offset in [('front',(.4,-.6,.25)),('rear',(-.4,.6,.25)),('left',(-.6,-.3,.1)),('under',(.3,-.5,-.3))]:
            cam.location=target+np.asarray(offset);cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
            path=output/f'{identifier}_{name}.png';scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)
            records.append({'object_id':identifier,'view':name,'image':bound(path),'camera_matrix':np.asarray(cam.matrix_world).tolist()})
    write(output/'inspection_manifest.json',{'scene':bound(scene_path),'binding':bound(binding_path),'frames':records,
        'purpose':'isolated_actual_generated_geometry_review','human_review':None})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['assemble','render','inspect'])
    parser.add_argument('--plan',type=Path);parser.add_argument('--scene',type=Path);parser.add_argument('--binding',type=Path)
    parser.add_argument('--trajectory',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resolution',type=int,default=640);parser.add_argument('--samples',type=int,default=24)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.mode=='assemble':assemble(args.plan,args.output)
    elif args.mode=='inspect':inspect_assets(args.scene,args.binding,args.output)
    else:render(args.scene,args.binding,args.trajectory,args.output,args.resolution,args.samples)

if __name__=='__main__':main()
