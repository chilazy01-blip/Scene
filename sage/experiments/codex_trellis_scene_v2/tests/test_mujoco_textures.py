import io
import unittest
import numpy as np
from PIL import Image
from sage.experiments.embodied_scene_v1.mujoco_textures import base_color_for_mujoco


class TextureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.pixels = np.array([[[255, 0, 0], [0, 255, 0]],
                                [[0, 0, 255], [255, 255, 0]]], dtype=np.uint8)
        stream = io.BytesIO()
        Image.fromarray(self.pixels).save(stream, format='PNG')
        self.binary = stream.getvalue()
        self.document = {'textures': [{'source': 0}], 'images': [{'bufferView': 0}],
                         'bufferViews': [{'byteLength': len(self.binary)}]}
        self.pbr = {'baseColorTexture': {'index': 0}}

    def test_original_asymmetric_raster_converts_once_without_mutation(self):
        image, size = base_color_for_mujoco(self.document, self.binary, self.pbr, 2048)
        self.assertEqual(size, (2, 2))
        np.testing.assert_array_equal(image, self.pixels[::-1])
        np.testing.assert_array_equal(Image.open(io.BytesIO(self.binary)), self.pixels)

    def test_no_upscaling(self):
        image, _ = base_color_for_mujoco(self.document, self.binary, self.pbr, 512)
        self.assertEqual(image.size, (2, 2))

    def test_unsupported_uv_set_or_transform_fails(self):
        for extra in ({'texCoord': 1}, {'extensions': {'KHR_texture_transform': {'offset': [.2, 0]}}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                base_color_for_mujoco(self.document, self.binary, {'baseColorTexture': {'index': 0, **extra}}, 512)

    def test_external_or_truncated_image_fails(self):
        with self.assertRaises(ValueError):
            base_color_for_mujoco(self.document, self.binary[:-1], self.pbr, 512)
        self.document['images'][0] = {'uri': 'already_exported.png'}
        with self.assertRaises(ValueError):
            base_color_for_mujoco(self.document, self.binary, self.pbr, 512)
