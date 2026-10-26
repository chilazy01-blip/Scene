"""Convert original glTF rasters at the MuJoCo boundary exactly once.

OBJ TEXCOORD_0 values remain unchanged. MuJoCo's image/UV convention then
requires vertically reversed raster rows. Inputs must be original glTF bytes,
never already exported PNGs. The versioned contract also guards texture caches.
"""
from io import BytesIO
from PIL import Image

TEXTURE_CONVENTION = 'gltf-original-raster-to-mujoco-flip-rows-v1'


def base_color_for_mujoco(document, binary, pbr, maximum_size):
    if not isinstance(maximum_size, int) or maximum_size < 1:
        raise ValueError('Texture cap must be a positive integer')
    info = pbr['baseColorTexture']
    if info.get('texCoord', 0) != 0 or info.get('extensions', {}).get('KHR_texture_transform'):
        raise ValueError('Only untransformed TEXCOORD_0 is currently supported')
    texture = document['textures'][info['index']]
    source = document['images'][texture['source']]
    if 'bufferView' not in source or 'uri' in source:
        raise ValueError('Expected original embedded glTF image bytes')
    view = document['bufferViews'][source['bufferView']]
    if view.get('buffer', 0) != 0:
        raise ValueError('Only the GLB binary buffer is supported')
    start = view.get('byteOffset', 0)
    end = start + view['byteLength']
    if start < 0 or end > len(binary) or end <= start:
        raise ValueError('Invalid embedded image range')
    with Image.open(BytesIO(binary[start:end])) as original:
        image = original.convert('RGB')
        source_size = image.size
    image.thumbnail((maximum_size, maximum_size), Image.Resampling.LANCZOS)
    return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM), source_size
