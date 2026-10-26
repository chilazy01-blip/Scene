"""Change one semantic instance transform, retaining GLB mesh/material bytes."""
from copy import deepcopy
from pathlib import Path
import json,struct
import numpy as np
from sage.experiments.codex_trellis_scene_v2.p021_physics import _read_glb,_node_matrix,GLTF_TO_Z
from sage.experiments.embodied_scene_quality_v2.contracts import require,reference,write_new


def changed_document(document,target_id,delta_z):
    doc=deepcopy(document);roots=[];seen=set();delta_g=np.linalg.inv(GLTF_TO_Z)@delta_z@GLTF_TO_Z
    def visit(index,parent,owner=None):
        require(index not in seen,'repeated_gltf_node');seen.add(index)
        node=doc['nodes'][index];own=node.get('extras',{}).get('scene_object_id');local=_node_matrix(node)
        original_world=parent@local
        if own==target_id and owner!=target_id:
            transform=np.linalg.inv(parent)@delta_g@parent@local
            for key in ('translation','rotation','scale'):node.pop(key,None)
            node['matrix']=transform.T.ravel().tolist();roots.append(index)
        for child in node.get('children',[]):visit(child,original_world,own or owner)
    for index in doc['scenes'][doc.get('scene',0)]['nodes']:visit(index,np.eye(4))
    require(len(roots)==1,'task_instance_requires_unique_transform_root')
    return doc,roots[0]


def transform_glb(source,destination,target_id,delta_z):
    doc,binary=_read_glb(Path(source));changed,index=changed_document(doc,target_id,delta_z)
    payload=json.dumps(changed,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    payload+=b' '*((-len(payload))%4);binary+=b'\x00'*((-len(binary))%4)
    length=12+8+len(payload)+8+len(binary)
    with Path(destination).open('xb') as f:
        f.write(struct.pack('<III',0x46546C67,2,length));f.write(struct.pack('<II',len(payload),0x4E4F534A));f.write(payload)
        f.write(struct.pack('<II',len(binary),0x004E4942));f.write(binary)
    return dict(source=reference(source),derived=reference(destination),semantic_id=target_id,changed_node=index,
        world_delta_z_up=np.asarray(delta_z).tolist(),mesh_material_binary_unchanged=True)
