from copy import deepcopy
import unittest
import numpy as np
from sage.experiments.codex_trellis_scene_v2.asset_geometry_dimensions import infer_proportion_preserving_dimensions
from sage.experiments.codex_trellis_scene_v2.support_footprint_repair import repair_support_footprints
from sage.experiments.codex_trellis_scene_v2.whole_scene_audit import audit_glb_world_transforms
import trimesh


class GeometryDimensionRepairTests(unittest.TestCase):
    def test_horizontal_correspondence_proposal_preserves_geometry_ratios(self):
        mesh=trimesh.creation.box(extents=[.8,1,.12])  # glTF Y-up
        entry={'dimensions':{'width':.03,'length':.2,'height':.25}}
        result=infer_proportion_preserving_dimensions(mesh.vertices,entry)
        self.assertEqual(result['asset_local_yaw_offset_degrees'],90)
        self.assertTrue(result['semantic_orientation_review_required'])
        self.assertEqual(result['dimensions'],dict(width=.030000000000000013,length=.2,height=.25))

    def test_uniform_envelope_does_not_invent_an_axis_stretch(self):
        mesh=trimesh.creation.box(extents=[1,1,1])
        entry={'dimensions':{'width':.2,'length':.3,'height':.4}}
        result=infer_proportion_preserving_dimensions(mesh.vertices,entry,fit_inferred_envelope=True)
        self.assertTrue(all(abs(v-.2)<1e-10 for v in result['dimensions'].values()))

    def test_oblique_readback_checks_real_shape_and_detects_thin_axis_error(self):
        yaw=37.;angle=np.deg2rad(yaw)
        z_to_gltf=np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]],float)
        pose=trimesh.transformations.rotation_matrix(angle,[0,0,1]);pose[:3,3]=[1,2,.5]
        plan={'objects':[{'id':'test','x':1,'y':2,'z':0,'yaw':yaw,'dimensions':dict(width=.2,length=.6,height=1)}]}
        scene=trimesh.Scene();scene.add_geometry(trimesh.creation.box(extents=[.2,.6,1]),node_name='test_geometry_0',parent_node_name='test_root')
        scene.graph.update(frame_from='world',frame_to='test_root',matrix=z_to_gltf@pose)
        self.assertTrue(audit_glb_world_transforms(plan,scene)['ok'])
        scene.geometry[next(iter(scene.geometry))].apply_scale([.95,1,1])
        self.assertFalse(audit_glb_world_transforms(plan,scene)['ok'])


if __name__=='__main__':unittest.main()
