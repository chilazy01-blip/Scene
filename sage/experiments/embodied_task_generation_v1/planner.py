"""Task requirements constrain asset eligibility before public scene generation."""
from copy import deepcopy
from itertools import product
import numpy as np
from scipy.spatial.transform import Rotation

from sage.experiments.embodied_scene_quality_v1.contracts import require


def corners(dimensions):
    return np.array(list(product((-1., 1.), repeat=3))) * np.asarray(dimensions)/2


def orientations(dimensions, posture, allowed_yaw):
    require(posture in ('broad_face_down', 'upright'), 'unsupported_posture')
    axis = int(np.argmin(dimensions)) if posture == 'broad_face_down' else 2
    base = [Rotation.from_euler('y', 90, degrees=True),
            Rotation.from_euler('x', -90, degrees=True), Rotation.identity()][axis]
    return [(yaw, (Rotation.from_euler('z', yaw, degrees=True)*base).as_matrix()) for yaw in allowed_yaw]


def perturbation_envelope(dimensions, orientation, angle_deg):
    points = corners(dimensions)
    poses = [orientation]
    poses += [(Rotation.from_euler(axis, sign*angle_deg, degrees=True).as_matrix()@orientation)
              for axis in ('x', 'y') for sign in (-1, 1)]
    return np.max([np.ptp(points@rot.T, axis=0) for rot in poses], axis=0)


def select(library, request, policy, cavity=None):
    rows = library['assets']; supports = [a for a in rows if a['category']==request['support_category']]
    targets = [a for a in rows if a['asset_id'] in request['target_pool']]
    require(len(targets)==len(set(request['target_pool'])), 'missing_or_duplicate_target_pool')
    require(len(supports)==1, 'support_selection_not_unique')
    support=supports[0]
    support_dims=np.array([support['dimensions'][k] for k in ('width','length','height')])
    if request['task']=='place_in_container':
        require(cavity is not None and cavity['verified'], 'certified_cavity_required')
        bounds=np.asarray(cavity['inner_bounds_local_m']); available=bounds[1]-bounds[0]
    else:
        require(request['task']=='place_on_surface', 'unsupported_task')
        available=support_dims.copy(); available[:2]-=2*policy['surface_edge_inset_m'];available[2]=np.inf
    decisions=[]; eligible=[]
    for target in sorted(targets,key=lambda a:a['asset_id']):
        dims=np.array([target['dimensions'][k] for k in ('width','length','height')])
        require(np.isfinite(dims).all() and (dims>0).all(), 'invalid_asset_dimensions')
        for yaw,rot in orientations(dims,request['posture'],policy['allowed_yaw_deg']):
            envelope=perturbation_envelope(dims,rot,policy['rotation_envelope_deg'])
            required=envelope.copy();required[:2]+=2*(policy['placement_margin_m']+policy['xy_offset_envelope_m'])
            required[2]+=2*policy['placement_margin_m']
            fit=bool(np.all(required<=available))
            record=dict(asset_id=target['asset_id'],yaw_deg=yaw,orientation=rot.tolist(),
                nominal_dimensions_m=np.ptp(corners(dims)@rot.T,axis=0).tolist(),
                required_dimensions_m=required.tolist(),eligible=fit,
                reason='declared_geometric_range_fits' if fit else 'declared_geometric_range_exceeds_support')
            decisions.append(record)
            if fit:eligible.append((float(np.prod(record['nominal_dimensions_m'][:2])),target['asset_id'],yaw,target,record))
    chosen=min(eligible,key=lambda row:row[:3]) if eligible else None
    return dict(request_id=request['id'],status='selected_pending_geometry_and_dynamics' if chosen else 'rejected_before_generation',
        task=request['task'],posture=request['posture'],support_asset_id=support['asset_id'],
        available_dimensions_m=[float(x) if np.isfinite(x) else None for x in available],
        candidates=decisions,selected=chosen[4] if chosen else None,
        physical_qualification='unknown',selection_uses_physics_results=False)


def generation_inputs(library, request, selection):
    require(selection['selected'] is not None, 'rejected_request_cannot_generate')
    chosen=selection['selected']['asset_id'];support_category=request['support_category']
    subset=deepcopy(library)
    subset['library_id']=library['library_id']+'__task_'+request['id']
    # All alternative target assets are removed before the public selector runs.
    subset['assets']=[a for a in subset['assets'] if a['category']!='single_book' or a['asset_id']==chosen]
    parent='desk' if support_category=='desk' else support_category
    furnishing=dict(schema='scene-furnishing-groups/v1',attachments=[dict(
        id='task_target',category='single_book',parent_id=parent,mode='surface',
        offset_fraction=[0.,0.],use_existing=True)])
    names=['a wooden desk','an office chair','a bookcase','a floor lamp','one individual single book']
    if support_category!='desk':names.append('one '+support_category.replace('_',' '))
    prompt=('Create a compact modern study for placing a book flat on a supporting surface. '
        'The mandatory objects are '+', '.join(names)+'. No objects beyond the mandatory list. '
        'Keep the main window on the north wall and a clear route from the door. '
        'Put the single book on the '+parent.replace('_',' ')+' as specified in the accompanying furnishing configuration.')
    from sage.experiments.codex_trellis_scene_v2.brief import build_baseline_brief
    baseline=build_baseline_brief(prompt,request.get('room_type','study'))
    targets=[o for o in baseline['objects'] if o['category']=='single_book']
    supports=[o for o in baseline['objects'] if o['category']==support_category]
    require(len(targets)==len(supports)==1,'ambiguous_baseline_roles')
    furnishing['attachments'][0].update(id=targets[0]['id'],parent_id=supports[0]['id'])
    return subset,furnishing,prompt
