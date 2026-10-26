"""Mainline physical pose contracts; synthetic meshes below are test fixtures."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.spatial.transform import Rotation
import trimesh
from ..scene_physics import transform_objects,extend_brief,read_config
from ..p021_physics import _read_glb,_node_matrix,GLTF_TO_Z,_bound
from ..leaning_books import make_model,simulate
from ..brief import build_baseline_brief
from ..scene_graph import build_typed_scene_graph,materialize_scene_graph


class MainlinePhysicsTests(unittest.TestCase):
    def config(self):
        return {'schema':'scene-leaning-physics/v1','mu':.5,'angle_deg':10.,'duration_s':5.,
            'book_count':5,'book_dimensions':[.03,.16,.24],'bookcase_dimensions':[.9,.32,1.6],
            'replace_compound_books':True}

    def test_group_is_five_required_contained_nodes(self):
        brief=build_baseline_brief('A warm bedroom with a bookcase and books.')
        extend_brief(brief,self.config());graph=build_typed_scene_graph(brief,brief['architecture'])
        books=[o for o in brief['objects'] if o['category']=='single_book']
        self.assertEqual(len(books),5)
        self.assertFalse(any(o['category']=='book_stack' for o in brief['objects']))
        for book in books:
            self.assertIn(book['id'],brief['object_budget']['required_object_ids'])
            node=next(n for n in graph['nodes'] if n['id']==book['id'])
            self.assertEqual(node['parent_relation'],'contained_in')

    def test_invalid_friction_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json';c=self.config();c['mu']=float('nan');p.write_text(json.dumps(c))
            with self.assertRaises(ValueError):read_config(p)

    def test_rigid_transform_preserves_embedded_geometry_and_texture_buffers(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source.glb';target=root/'final.glb'
            scene=trimesh.Scene();scene.add_geometry(trimesh.creation.box(),node_name='book')
            source.write_bytes(scene.export(file_type='glb'))
            # Add semantic binding through the scene exporter, with a transformed parent.
            document,binary=_read_glb(source)
            meshnode=next(n for n in document['nodes'] if 'mesh' in n)
            meshnode['extras']={'scene_object_id':'book'}
            import struct
            raw=json.dumps(document).encode();raw+=b' '*((-len(raw))%4)
            source.write_bytes(struct.pack('<4sII',b'glTF',2,28+len(raw)+len(binary))+
                struct.pack('<I4s',len(raw),b'JSON')+raw+struct.pack('<I4s',len(binary),b'BIN\0')+binary)
            delta=np.eye(4);delta[:3,:3]=Rotation.from_euler('y',10,degrees=True).as_matrix();delta[:3,3]=[2,3,1]
            old=_node_matrix(meshnode)
            transform_objects(source,target,{'book':delta})
            new,payload=_read_glb(target);node=next(n for n in new['nodes'] if 'mesh' in n)
            np.testing.assert_allclose(GLTF_TO_Z@_node_matrix(node),delta@GLTF_TO_Z@old,atol=1e-12)
            self.assertEqual(payload,binary)
            with self.assertRaises(ValueError):transform_objects(source,root/'missing.glb',{'absent':delta})

    def test_stationary_hull_does_not_add_free_dofs_and_rotated_row_is_measured(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);mesh=trimesh.creation.box(extents=[.03,.16,.24]);p=root/'hull.npz'
            np.savez(p,vertices=mesh.vertices,faces=mesh.faces)
            pose=np.eye(4);pose[:3,:3]=Rotation.from_euler('zy',[90,10],degrees=True).as_matrix()
            # Intrinsic semantic row: yaw applied after lean.
            pose[:3,:3]=Rotation.from_euler('z',90,degrees=True).as_matrix()@Rotation.from_euler('y',10,degrees=True).as_matrix()
            pose[:3,3]=[0,0,.3];fixed=np.eye(4);fixed[:3,3]=[.8,0,.3]
            binding={'scene_glb':{'test_fixture':True},'spec':{'bookcase_id':'fixed','lean_axis_world':[0,1,0],'initial_lean_deg':10},
                'floor':{'world_bounds_z_up':[[-1,-1,-.1],[1,1,0]]},'objects':{
                'fixed':{'static':True,'initial_body_matrix_z_up':fixed.tolist(),'collider':{'artifact':_bound(p)}},
                'book':{'static':False,'initial_body_matrix_z_up':pose.tolist(),'collider':{'artifact':_bound(p)},
                    'mass_kg':.8,'center_of_mass_body_m':[0,0,0],'principal_inertia_kg_m2':[.002,.004,.005],
                    'inertial_quaternion_wxyz':[1,0,0,0]}}}
            result=simulate(binding,root/'run',mu=.5,dt=.001,duration=.25)
            self.assertEqual(result['compiled']['free_dof_count'],6)
            self.assertTrue(result['exact_30_step_state_restore'])
            self.assertAlmostEqual(result['metrics']['book']['initial_lean_deg'],10)

    def test_scene_graph_keeps_full_physical_rotation(self):
        brief=build_baseline_brief('A bedroom with a bookcase.')
        extend_brief(brief,self.config());graph=build_typed_scene_graph(brief,brief['architecture'])
        book=next(o for o in brief['objects'] if o['category']=='single_book')
        matrix=np.eye(4);matrix[:3,:3]=Rotation.from_euler('y',10,degrees=True).as_matrix()
        book['rigid_body_pose_matrix_z_up']=matrix.tolist()
        result=materialize_scene_graph(graph,brief['objects'])
        node=next(n for n in result['nodes'] if n['id']==book['id'])
        self.assertEqual(node['pose']['world_rigid_body_matrix_z_up'],matrix.tolist())
