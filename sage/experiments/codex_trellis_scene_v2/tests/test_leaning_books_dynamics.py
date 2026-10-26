"""Analytic solver fixture only; never used as a generated furniture asset."""
from pathlib import Path
import tempfile
import unittest
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation
from ..leaning_books import simulate
from ..p021_physics import _bound

class LeaningDynamicsTests(unittest.TestCase):
    def test_free_dofs_full_inertia_and_exact_state_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);wall=root/'wall.npz';book=root/'book.npz'
            np.savez(wall,centers=[[.9,0,.5]],half_sizes=[[.05,.4,.5]])
            mesh=trimesh.creation.box(extents=[.03,.16,.24]);np.savez(book,vertices=mesh.vertices,faces=mesh.faces)
            pose=np.eye(4);pose[:3,:3]=Rotation.from_euler('y',10,degrees=True).as_matrix();pose[:3,3]=[0,0,.3]
            inertia=Rotation.from_euler('z',.2).as_quat()[[3,0,1,2]].tolist()
            binding={'scene_glb':{'unit_test_fixture':True},'spec':{'bookcase_id':'wall'},
                'floor':{'world_bounds_z_up':[[-1,-1,-.1],[1,1,0]]},'objects':{
                    'wall':{'static':True,'initial_body_matrix_z_up':np.eye(4).tolist(),'collider':{'artifact':_bound(wall)}},
                    'book':{'static':False,'initial_body_matrix_z_up':pose.tolist(),'collider':{'artifact':_bound(book)},
                        'mass_kg':.8,'center_of_mass_body_m':[.001,.002,0],
                        'principal_inertia_kg_m2':[.002,.004,.005], 'inertial_quaternion_wxyz':inertia}}}
            result=simulate(binding,root/'run',mu=.5,dt=.001,duration=.25)
            self.assertEqual(result['compiled']['free_dof_count'],6)
            self.assertEqual(result['compiled']['equality_constraint_count'],0)
            self.assertTrue(result['exact_30_step_state_restore'])
            self.assertTrue(result['all_finite'])
            self.assertEqual(result['simulator_warnings'],[])
            self.assertAlmostEqual(result['metrics']['book']['initial_lean_deg'],10)
            self.assertTrue(any('floor' in pair for pair in result['contact_pairs']))
            with np.load(root/'run/contact_wrenches.npz') as data:
                self.assertGreater(data['contact_force_n'][:,0,2].max(),0)
            # A glTF-style Y-up body frame must measure its semantic height
            # axis, rather than silently interpreting body-local Z as height.
            change=Rotation.from_euler('x',90,degrees=True).as_matrix()
            adjusted=pose.copy();adjusted[:3,:3]=pose[:3,:3]@change
            rotated=root/'rotated_book.npz';np.savez(rotated,vertices=mesh.vertices@change,faces=mesh.faces)
            obj=binding['objects']['book'];obj['initial_body_matrix_z_up']=adjusted.tolist()
            obj['collider']['artifact']=_bound(rotated);obj['center_of_mass_body_m']=(change.T@np.array([.001,.002,0])).tolist()
            obj['inertial_quaternion_wxyz']=Rotation.from_matrix(change.T@Rotation.from_quat(np.array(inertia)[[1,2,3,0]]).as_matrix()).as_quat()[[3,0,1,2]].tolist()
            binding['spec']['initial_lean_deg']=10.
            with self.assertRaisesRegex(ValueError,'height axis'):
                simulate(binding,root/'wrong_axis',mu=.5,dt=.001,duration=.25)
            obj['semantic_up_axis_body']=[0,1,0]
            corrected=simulate(binding,root/'semantic_axis',mu=.5,dt=.001,duration=.25)
            self.assertAlmostEqual(corrected['metrics']['book']['initial_lean_deg'],10)

if __name__=='__main__':unittest.main()
