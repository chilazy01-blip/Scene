"""Generated-source binding on the exact-time collector, preserving native inputs."""
import numpy as np
from .runtime import K,J,Path,read,digest
from .dataset_alignment import align as original_align

def align(name):
    method=read(K/'results'/name/'METHOD.json')
    package=Path(method['package'])
    c=read(package/'CONTRACT.json')
    native=read(J/'results/B1/CONTRACT.json')
    assert c['qpos_by_pin']==native['qpos_by_pin'] and c['joint_names']==native['joint_names']
    fields,states,binding=original_align(name)
    binding.update(source_role='accepted_self_generated_single_episode',
        source_domain='self_generated_scene_verified_reused_assets',
        scene=method['case']['scene'],scene_sha256=method['scene_sha256'],
        contract_sha256=digest(package/'CONTRACT.json'),
        reference_sha256=method['reference_sha256'])
    assert binding['model_sha256']==method['model_sha256']
    return fields,states,binding

