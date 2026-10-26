"""Render the final simulated whole-room GLB without changing asset geometry."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector


def point_at(obj,target):
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--scene',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resolution',type=int,default=2400)
    parser.add_argument('--samples',type=int,default=96)
    parser.add_argument('--detail',action='store_true')
    parser.add_argument('--desk-detail',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.scene))
    scene=bpy.context.scene;plan=json.loads(args.plan.read_text());room=plan['room']
    for obj in scene.objects:
        if obj.type in {'LIGHT','CAMERA'}:obj.hide_render=True
        side=str(obj.get('architecture_wall',''))
        if side=='south' or obj.name.startswith('wall_south_'):
            obj.hide_render=True
    world=bpy.data.worlds.new('Bedroom daylight');world.use_nodes=True
    world.node_tree.nodes['Background'].inputs[0].default_value=(.65,.72,.82,1.)
    world.node_tree.nodes['Background'].inputs[1].default_value=.3;scene.world=world
    def area(name,location,target,energy,size,color):
        data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.shape='DISK';data.size=size;data.color=color
        obj=bpy.data.objects.new(name,data);scene.collection.objects.link(obj);obj.location=location;point_at(obj,target)
    area('Natural window light',(.6,2.6,2.35),(3.,3.,.8),300,1.6,(.83,.91,1.))
    area('Soft room fill',(2.6,-1.7,3.5),(2.8,3.,1.),500,4.,(1.,.87,.71))
    area('Ceiling bounce',(3.,2.6,4.5),(3.,3.,0.),400,3.,(1.,.94,.84))
    for obj in plan['objects']:
        if obj['category']!='table_lamp':continue
        data=bpy.data.lights.new(obj['id']+'_warm_light','POINT');data.energy=8;data.color=(1.,.62,.30);data.shadow_soft_size=.07
        lamp=bpy.data.objects.new(data.name,data);scene.collection.objects.link(lamp)
        lamp.location=(obj['x'],obj['y']-.035,obj['z']+.31)
    data=bpy.data.cameras.new('Bedroom final camera');camera=bpy.data.objects.new(data.name,data);scene.collection.objects.link(camera)
    if args.desk_detail:
        desk=next(o for o in plan['objects'] if o['category']=='desk')
        angle=math.radians(desk.get('yaw',0))
        front=Vector((math.sin(angle),-math.cos(angle),0))
        side=Vector((math.cos(angle),math.sin(angle),0))
        center=Vector((desk['x'],desk['y'],desk['z']+.80))
        camera.location=center+front*2.15-side*.25+Vector((0,0,.65))
        point_at(camera,center+side*.15);data.lens=40
    elif args.detail:
        shelf=next(o for o in plan['objects'] if o['category']=='bookcase')
        books=[o for o in plan['objects'] if o.get('physics_role')=='free_rigid_book']
        center=Vector(tuple(sum(o['rigid_body_pose_matrix_z_up'][a][3] for o in books)/len(books) for a in range(3)))
        camera.location=center+Vector((.22,-1.35,.24));point_at(camera,center);data.lens=66
    else:
        camera.location=(room['width']*.59,-4.3,4.0)
        point_at(camera,(room['width']*.5,room['length']*.56,1.05));data.lens=40
    data.clip_start=.03;data.clip_end=100;scene.camera=camera
    scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=args.samples
    scene.cycles.use_denoising=True;scene.cycles.max_bounces=8
    scene.render.resolution_x=args.resolution;scene.render.resolution_y=round(args.resolution*.75)
    scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    scene.render.film_transparent=False;scene.render.filepath=str(args.output)
    scene.view_settings.view_transform='AgX'
    try:scene.view_settings.look='AgX - Medium High Contrast'
    except TypeError:pass
    scene.view_settings.exposure=-.4
    bpy.context.view_layer.update()
    metadata={'scene_glb':str(args.scene),'scene_sha256':hashlib.sha256(args.scene.read_bytes()).hexdigest(),
        'plan':str(args.plan),'plan_sha256':hashlib.sha256(args.plan.read_bytes()).hexdigest(),
        'camera_world_matrix_z_up':[list(r) for r in camera.matrix_world], 'lens_mm':data.lens,
        'resolution':[scene.render.resolution_x,scene.render.resolution_y], 'samples':args.samples,
        'engine':'CYCLES_CPU','geometry_and_physical_poses_unchanged':True,
        'cutaway_hidden_wall':'south','asset_materials_unchanged':True,
        'visible_object_ids':sorted({str(o.get('scene_object_id')) for o in scene.objects if o.get('scene_object_id') and not o.hide_render})}
    bpy.ops.render.render(write_still=True)
    metadata['image_sha256']=hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix('.json').write_text(json.dumps(metadata,indent=2)+'\n')


if __name__=='__main__':main()
