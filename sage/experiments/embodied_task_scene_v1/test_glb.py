import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from .glb import changed_document
from sage.experiments.codex_trellis_scene_v2.p021_physics import _node_matrix,GLTF_TO_Z
from sage.experiments.embodied_scene_quality_v2.contracts import Rejected


class GlbTests(unittest.TestCase):
    def test_parent_transform_and_other_node_preserved(self):
        p=np.eye(4);p[:3,:3]=Rotation.from_euler('z',30,degrees=True).as_matrix();p[:3,3]=[1,2,3]
        doc=dict(scenes=[dict(nodes=[0])],nodes=[dict(matrix=p.T.ravel().tolist(),children=[1,2]),
            dict(translation=[.1,.2,.3],extras=dict(scene_object_id='target')),dict(translation=[4,5,6],extras=dict(scene_object_id='other'))])
        delta=np.eye(4);delta[:3,:3]=Rotation.from_euler('y',90,degrees=True).as_matrix();delta[:3,3]=[1,0,0]
        result,index=changed_document(doc,'target',delta)
        actual=GLTF_TO_Z@p@_node_matrix(result['nodes'][1]);expected=delta@GLTF_TO_Z@p@_node_matrix(doc['nodes'][1])
        self.assertTrue(np.allclose(actual,expected,rtol=0,atol=1e-12));self.assertEqual(result['nodes'][2],doc['nodes'][2]);self.assertEqual(index,1)
    def test_missing_or_multiple_target_roots_rejected(self):
        for nodes in [[],[dict(extras=dict(scene_object_id='target')),dict(extras=dict(scene_object_id='target'))]]:
            doc=dict(scenes=[dict(nodes=list(range(len(nodes))))],nodes=nodes)
            with self.assertRaises(Rejected):changed_document(doc,'target',np.eye(4))
