"""Analytic shapes below are tests, never substitutes for generated assets."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from ..physical_mass import profile_from_material_slots
from ..physical_mass import surface_mass_properties

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from ..physical_mass import density_prior,point_mass_properties,combine_mass_properties,estimate_mass_properties
from ..leaning_books import voxel_boxes,arrange_leaning_books
from ..collision_proxy import VoxelSDF


class PhysicalMassTests(unittest.TestCase):
    def test_surface_cube_inertia_and_tessellation_invariance(self):
        mesh=trimesh.creation.box(extents=[2,2,2]);a=surface_mass_properties(mesh,3)
        np.testing.assert_allclose(a['center_of_mass_m'],[0,0,0],atol=1e-12)
        np.testing.assert_allclose(a['inertia_tensor_kg_m2'],np.eye(3)*(5*3*4/18),atol=1e-12)
        b=surface_mass_properties(mesh.subdivide(),3)
        np.testing.assert_allclose(a['inertia_tensor_kg_m2'],b['inertia_tensor_kg_m2'],atol=1e-12)

    def test_surface_mass_is_rotation_equivariant(self):
        mesh=trimesh.creation.box(extents=[.2,.3,.4]);a=surface_mass_properties(mesh,2)
        rotation=Rotation.from_euler('xyz',[.3,.7,1.1]).as_matrix();matrix=np.eye(4)
        matrix[:3,:3]=rotation;matrix[:3,3]=[1,2,3];mesh.apply_transform(matrix)
        b=surface_mass_properties(mesh,2)
        np.testing.assert_allclose(b['center_of_mass_m'],[1,2,3],atol=1e-12)
        np.testing.assert_allclose(b['inertia_tensor_kg_m2'],rotation@a['inertia_tensor_kg_m2']@rotation.T,atol=1e-12)

    def test_material_library_slots_preserve_surface_vs_structure(self):
        surface=profile_from_material_slots('cabinet',[{'material_family':'wood','package_id':'light_oak_satin_v1','slot_role':'furniture_body'}])
        self.assertEqual(surface['material_scope'],'appearance')
        structural=profile_from_material_slots('bookcase',[{'material_family':'wood','material_scope':'bulk','slot_role':'shelves'}],structure='solid_panels')
        self.assertEqual(structural['material'],'wood')
        self.assertEqual(structural['material_scope'],'bulk')
        mixed=profile_from_material_slots('chair',[{'material_family':family,'material_scope':'bulk','slot_role':'load_bearing_frame'} for family in ('wood','steel')])
        self.assertEqual(mixed['material'],'unknown')

    def test_appearance_changes_do_not_replace_unknown_bulk_material(self):
        a=density_prior({'category':'sofa','material':'wood','material_scope':'appearance'})
        b=density_prior({'category':'sofa','material':'metal','material_scope':'appearance'})
        self.assertEqual(a['density_kg_m3'],b['density_kg_m3'])
        self.assertEqual(a['kind'],'category_envelope_density_prior')
        self.assertNotEqual(a['density_kg_m3'],density_prior({'category':'single_book'})['density_kg_m3'])

    def test_identified_materials_have_distinct_bulk_priors(self):
        wood=density_prior({'material':'wood','material_scope':'bulk'})
        steel=density_prior({'material':'steel','material_scope':'bulk'})
        self.assertGreater(steel['density_kg_m3'],wood['density_kg_m3']*5)
        self.assertFalse(wood['measured'])

    def test_cell_inertia_matches_analytic_solid_box(self):
        h=.01
        points=np.stack(np.meshgrid(*(np.arange(n)*h for n in (10,20,30)),indexing='ij'),axis=-1).reshape(-1,3)
        mass=3.;result=point_mass_properties(points,np.full(len(points),mass/len(points)),cell_size_m=h)
        extent=np.array([.1,.2,.3]);expected=mass/12*(np.sum(extent**2)-extent**2)
        np.testing.assert_allclose(np.diag(result['inertia_tensor_kg_m2']),expected,atol=1e-13)

    def test_material_mass_distribution_changes_center_and_is_rotation_equivariant(self):
        points=np.array([[-1.,0,0],[1.,0,0]])
        masses=np.array([1.,3.]);a=point_mass_properties(points,masses,cell_size_m=.1)
        np.testing.assert_allclose(a['center_of_mass_m'],[.5,0,0])
        r=Rotation.from_euler('xyz',[.2,.4,.7]).as_matrix();offset=np.array([4,5,6])
        b=point_mass_properties(points@r.T+offset,masses,cell_size_m=.1)
        np.testing.assert_allclose(b['center_of_mass_m'],r@np.array(a['center_of_mass_m'])+offset)
        np.testing.assert_allclose(b['inertia_tensor_kg_m2'],r@a['inertia_tensor_kg_m2']@r.T,atol=1e-12)

    def test_parallel_axis_aggregation(self):
        components=[{'mass_kg':m,'center_of_mass_m':[x,0,0],'inertia_tensor_kg_m2':(np.eye(3)*m/6).tolist()}
                    for m,x in [(1,-1),(3,1)]]
        combined=combine_mass_properties(components)
        np.testing.assert_allclose(combined['center_of_mass_m'],[.5,0,0])
        np.testing.assert_allclose(np.diag(combined['inertia_tensor_kg_m2']),[4/6,4/6+3,4/6+3])

    def test_open_geometry_uses_explicit_category_fallback_and_zero_dilation(self):
        mesh=trimesh.creation.box(extents=[.2,.2,.3]);mesh.update_faces(np.arange(len(mesh.faces)-2))
        with tempfile.TemporaryDirectory() as tmp:
            result=estimate_mass_properties(mesh,{'category':'bookcase','material':'wood',
                   'material_scope':'bulk','structure':'solid_panels'},Path(tmp),pitch_m=.02)
            self.assertEqual(result['mass_origin'],'category_envelope_fallback')
            self.assertEqual(result['surface_dilation_voxels'],0)
            self.assertAlmostEqual(result['mass_kg'],100*.2*.2*.3)
            self.assertIn('open_surface',result['fallback_reason'])

    def test_closed_book_prior_and_cache_detect_modified_voxels(self):
        mesh=trimesh.creation.box(extents=[.03,.16,.24]);mesh.update_faces(np.arange(len(mesh.faces)-1))
        profile={'category':'single_book','material':'paper','material_scope':'bulk','structure':'bound_paper_block'}
        with tempfile.TemporaryDirectory() as tmp:
            result=estimate_mass_properties(mesh,profile,Path(tmp),pitch_m=.002)
            self.assertEqual(result['mass_origin'],'undilated_material_voxel_volume')
            self.assertIn('closed_book',result['solid_reconstruction'])
            again=estimate_mass_properties(mesh,profile,Path(tmp),pitch_m=.002)
            self.assertTrue(again['cache_hit'])
            Path(result['voxel_files'][0]['path']).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'cache changed'):
                estimate_mass_properties(mesh,profile,Path(tmp),pitch_m=.002)

    def test_explicit_mass_needs_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'source'):
                estimate_mass_properties(trimesh.creation.box(),{'mass_kg':2},Path(tmp),pitch_m=.1)

    def test_explicit_mass_range_must_contain_mass(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'range'):
                estimate_mass_properties(trimesh.creation.box(),{'mass_kg':2,'mass_source':'test_measurement','mass_range_kg':[3,1]},Path(tmp),pitch_m=.1)


class LeaningGeometryTests(unittest.TestCase):
    def test_cuboids_preserve_cavity_and_do_not_double_count(self):
        occupancy=np.ones((6,7,8),dtype=bool);occupancy[1:5,:6,1:7]=False
        proxy=VoxelSDF(np.zeros_like(occupancy,dtype=float),occupancy,np.array([0.,0,0]),.01,{})
        centers,half=voxel_boxes(proxy)
        counts=np.zeros(occupancy.shape,dtype=int)
        for center,size in zip(centers,half):
            lower=np.rint((center-size)/.01+.5).astype(int);upper=np.rint((center+size)/.01+.5).astype(int)
            counts[lower[0]:upper[0],lower[1]:upper[1],lower[2]:upper[2]]+=1
        np.testing.assert_array_equal(counts,occupancy.astype(int))
        self.assertAlmostEqual(np.prod(half*2,axis=1).sum(),occupancy.sum()*.01**3)

    def test_independent_row_tilt_bottoms_and_separation(self):
        meshes=[trimesh.creation.box(extents=[.03,.16,.24]) for _ in range(5)]
        slot={'support_z_m':.5,'right_inner_x_m':.4,'book_center_y_m':0}
        poses=arrange_leaning_books(meshes,slot)
        for mesh,pose in zip(meshes,poses):
            points=mesh.vertices@pose[:3,:3].T+pose[:3,3]
            self.assertAlmostEqual(points[:,2].min(),.5005)
            self.assertAlmostEqual(np.degrees(np.arctan2(pose[0,2],pose[2,2])),10)
        self.assertEqual(len(poses),5)
        self.assertTrue(all(a[0,3]<b[0,3] for a,b in zip(poses,poses[1:])))

if __name__=='__main__':unittest.main()
