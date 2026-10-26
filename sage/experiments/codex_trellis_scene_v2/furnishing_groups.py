"""Opt-in furniture relationships grounded before matching and after layout repair.

Dimensions are resolved before asset selection. Subsequent placement moves the
same assets; inadequate coverage is reported, never silently stretched.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

from .policies import _obj


def read_config(path):
    if path is None:
        return None
    result = json.loads(Path(path).read_text())
    if result.get('schema') != 'scene-furnishing-groups/v1':
        raise ValueError('Unsupported furnishing group configuration')
    return result


def rotate(x, y, yaw):
    angle = math.radians(yaw)
    return x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)


def local_bounds(obj, anchor):
    points = []
    for x in (-.5, .5):
        for y in (-.5, .5):
            dx, dy = rotate(x * obj['dimensions']['width'], y * obj['dimensions']['length'], obj.get('yaw', 0))
            points.append(rotate(obj['x'] + dx - anchor['x'], obj['y'] + dy - anchor['y'], -anchor.get('yaw', 0)))
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def rug_envelope(group, objects):
    anchor = objects[group['anchor_id']]
    boxes = [local_bounds(objects[i], anchor) for i in group['covered_ids']]
    side, front, back = group.get('margins_m', [.10, .50, .02])
    return [min(b[0] for b in boxes)-side, min(b[1] for b in boxes)-front,
            max(b[2] for b in boxes)+side, max(b[3] for b in boxes)+back]


def ground_groups(brief, architecture, config):
    if not config:
        return
    architecture = architecture.get('architecture', architecture)
    config = deepcopy(config)
    if config.get('object_overrides'):
        by_id = {o['id']: o for o in brief['objects']}
        for identifier, override in config['object_overrides'].items():
            by_id[identifier].update(deepcopy(override))
            if 'dimensions' in override or 'requested_dimensions' in override:
                obj = by_id[identifier]
                obj['dimension_policy'].pop('request_origin', None)
                obj['requested_dimensions'] = deepcopy(override.get('requested_dimensions', obj['dimensions']))
                obj['dimension_grounding'] = 'explicit_furnishing_configuration'
    objects = {o['id']: o for o in brief['objects']}
    for group in config.get('rugs', []):
        poses = {i: dict(o, **o.get('initial_pose', {})) for i, o in objects.items()}
        # Use the existing room-policy layout as the pre-match proposal when
        # the request has not supplied initial poses. Final repairs still reflow
        # the group and validate the already selected asset's coverage.
        for identifier in set(group['covered_ids']) | {group['anchor_id']}:
            if 'x' not in poses[identifier] or 'y' not in poses[identifier]:
                from .planner import _rule_pose
                x,y,yaw = _rule_pose(brief['room_type'],identifier,brief['room'])
                poses[identifier].update(x=x,y=y,yaw=yaw)
        box = rug_envelope(group, poses)
        rug = objects[group['rug_id']]
        rug.pop('initial_pose', None)
        rug['dimensions'].update(width=round(box[2]-box[0], 6), length=round(box[3]-box[1], 6))
        rug['requested_dimensions'] = deepcopy(rug['dimensions'])
        rug['dimension_policy'].pop('request_origin', None)
        rug['furnishing_anchor_id'] = group['anchor_id']
        rug['preserve_source_materials'] = True
        rug['dimension_grounding'] = 'covered_furniture_envelope_with_explicit_margins'
    treatments = config.get('window_treatments')
    if treatments:
        if treatments.get('mode') != 'paired_open':
            raise ValueError('Only explicitly requested paired_open treatment is supported')
        replaced = {o['id'] for o in brief['objects'] if o['category'] in ('curtain_panel', 'curtain_rod')}
        brief['objects'] = [o for o in brief['objects'] if o['id'] not in replaced]
        brief['relations'] = [r for r in brief['relations'] if not any(str(v) in replaced for v in (r.values() if isinstance(r,dict) else r))]
        for window in architecture.get('windows', []):
            width = float(treatments.get('stack_width_m', .5))
            gap = float(treatments.get('opening_gap_m', .02))
            top = min(float(brief['room']['height'])-.15, float(window['sill_height'])+float(window['height'])+.10)
            bottom = float(treatments.get('floor_gap_m', .06))
            for role in ('left', 'right', 'rod'):
                category = 'curtain_rod' if role == 'rod' else 'curtain_panel'
                obj = _obj(f"{window['id']}_curtain_{role}", category, preferred_wall=window['wall'])
                obj['window_treatment'] = {'window_id':window['id'], 'role':role, 'mode':'paired_open',
                                           'stack_width_m':width, 'opening_gap_m':gap}
                obj['dimensions'].update(width=float(window['width'])+2*(width+gap) if role=='rod' else width,
                                          height=.06 if role=='rod' else top-bottom)
                obj['requested_dimensions'] = deepcopy(obj['dimensions'])
                obj['mount_height'] = top if role=='rod' else bottom
                brief['objects'].append(obj)
    for link in config.get('attachments', []):
        existing = next((o for o in brief['objects'] if o['id']==link['id']), None)
        if existing is not None and not link.get('use_existing'):
            raise ValueError('Attachment ID already exists: '+link['id'])
        if existing is not None and existing['category'] != link['category']:
            raise ValueError('Existing attachment category mismatch')
        mode = link['mode']
        if mode not in ('surface', 'under', 'beside'):
            raise ValueError('Unsupported attachment mode')
        obj = existing if existing is not None else _obj(link['id'], link['category'])
        obj['placement_type'] = {'surface':'support','under':'contained','beside':'floor'}[mode]
        if link.get('dimensions_m'):
            obj['dimensions'] = dict(zip(('width','length','height'), link['dimensions_m']))
            obj['requested_dimensions'] = deepcopy(obj['dimensions'])
            obj['dimension_policy'].pop('request_origin', None)
            obj['dimension_grounding'] = 'explicit_furnishing_configuration'
        elif existing is None and obj['dimension_policy'].get('mode') != 'opening_fit':
            # Category defaults are priors, just as for a dimension-free text
            # request. Adding a support edge must not turn them into exact sizes.
            obj['dimension_policy']['request_origin'] = 'inferred_category_prior'
            obj['dimension_grounding'] = 'inferred_category_prior'
        if existing is None:
            obj['provenance'] = 'user_explicit_furnishing_configuration'
        obj['furnishing_attachment'] = deepcopy(link)
        if mode=='surface':
            obj['support_id'] = link['parent_id']
        if mode=='under':
            obj['container_id'] = link['parent_id']
        if existing is None:
            brief['objects'].append(obj)
    # Text expansion already suppresses policy-only extras once an explicit
    # list fills the hard minimum. Count explicit attachments by the same rule,
    # before asset selection or layout. Never drop a requested/linked object.
    explicit_count = sum(o.get('provenance') in ('user_explicit', 'user_explicit_furnishing_configuration')
                         and o['category'] not in ('door', 'window') for o in brief['objects'])
    hard_min = brief['object_budget'].get('hard_min')
    if config.get('attachments') and hard_min is not None and explicit_count >= hard_min:
        protected = {link['parent_id'] for link in config['attachments']} | {link['id'] for link in config['attachments']}
        protected.update(config.get('object_overrides', {}))
        for obj in brief['objects']:
            protected.update(obj[k] for k in ('support_id', 'container_id') if obj.get(k))
        for relation in brief.get('relations', []):
            protected.update(v for v in (relation.values() if isinstance(relation, dict) else relation) if isinstance(v, str))
        for group in config.get('rugs', []):
            protected.update([group['anchor_id'], group['rug_id'], *group['covered_ids']])
        omitted = [o for o in brief['objects'] if not o.get('required', True)
                   and o.get('provenance') == 'room_policy_optional' and o['id'] not in protected]
        if omitted:
            omitted_ids = {o['id'] for o in omitted}
            brief['objects'] = [o for o in brief['objects'] if o['id'] not in omitted_ids]
            brief['furnishing_budget_resolution'] = {
                'reason': 'explicit_text_and_furnishing_list_meets_hard_minimum',
                'explicit_count': explicit_count, 'hard_min': hard_min,
                'omitted_policy_only_proposals': omitted,
                'before_asset_selection_and_layout': True,
                'not_execution_feedback_repair': True,
            }
    brief['furnishing_groups'] = config
    brief['object_budget']['required_object_ids'] = [o['id'] for o in brief['objects'] if o.get('required', True)]
    if len(brief['objects']) > brief['object_budget']['hard_runtime_limit']:
        raise ValueError('Furnishing groups exceed runtime object budget')
    if config.get('wall_pbr'):
        finish = architecture['wall_finish']
        for material in [finish['default'], *finish.get('overrides', {}).values()]:
            material['embed_generated_texture'] = True
            material['embed_pbr_maps'] = True
            material['finish_contrast'] = float(config.get('wall_finish_contrast', 1.8))
            material['finish_relief_m'] = .003 if material.get('texture_type')=='procedural_wood_slat' else .0006
        brief['architecture'] = deepcopy(architecture)


def place_groups(plan):
    config = plan.get('furnishing_groups')
    if not config:
        return
    objects = {o['id']:o for o in plan['objects']}
    for group in config.get('rugs', []):
        anchor, rug = objects[group['anchor_id']], objects[group['rug_id']]
        box = rug_envelope(group, objects)
        dx, dy = rotate((box[0]+box[2])/2, (box[1]+box[3])/2, anchor.get('yaw', 0))
        rug.update(x=anchor['x']+dx, y=anchor['y']+dy, z=0., yaw=anchor.get('yaw', 0))
        for identifier in group['covered_ids']:
            objects[identifier]['z'] = rug['dimensions']['height']
    windows = {w['id']:w for w in plan['architecture'].get('windows', [])}
    for obj in plan['objects']:
        treatment = obj.get('window_treatment')
        if not treatment:
            continue
        window = windows[treatment['window_id']]
        wall, role = window['wall'], treatment['role']
        along = float(window['center'])
        offset = float(window['width'])/2 + treatment['opening_gap_m'] + treatment['stack_width_m']/2
        along += -offset if role=='left' else (offset if role=='right' else 0.)
        inset = .13
        x, y, yaw = {'west':(inset, along, 90), 'east':(plan['room']['width']-inset, along, 270),
                     'south':(along, inset, 180), 'north':(along, plan['room']['length']-inset, 0)}[wall]
        obj.update(x=x,y=y,yaw=yaw,z=obj['mount_height'])
    # Parent-local offsets support arbitrary yaw, including after repairs.
    for obj in plan['objects']:
        link = obj.get('furnishing_attachment')
        if link:
            parent = objects[link['parent_id']]
            fx, fy = link.get('offset_fraction', [0.,0.])
            offset = [fx*parent['dimensions']['width'], fy*parent['dimensions']['length']]
            obj['support_offset'] = offset
            dx,dy = rotate(*offset, parent.get('yaw',0))
            obj.update(x=parent['x']+dx,y=parent['y']+dy,yaw=parent.get('yaw',0)+link.get('yaw_offset_deg',0),z=0.)
            if link['mode']=='surface':
                obj['z'] = parent.get('z',0)+parent['dimensions']['height']
            if link.get('faces_parent'):
                obj['yaw'] = math.degrees(math.atan2(parent['x']-obj['x'], -(parent['y']-obj['y']))) % 360
        elif obj.get('placement_type')=='support' and obj.get('support_id') in objects:
            parent=objects[obj['support_id']]
            dx,dy=rotate(*obj.get('support_offset',[0,0]),parent.get('yaw',0))
            obj.update(x=parent['x']+dx,y=parent['y']+dy,z=parent.get('z',0)+parent['dimensions']['height'],yaw=parent.get('yaw',0))


def allowed_window_treatment(obj, window):
    treatment = obj.get('window_treatment', {})
    if treatment.get('window_id') != window.get('id') or treatment.get('mode') != 'paired_open':
        return False
    # Only the bound rod above this opening may cross its horizontal interval.
    return obj.get('category')=='curtain_rod' and treatment.get('role')=='rod' and obj.get('z',0)>=window['sill_height']+window['height']


def evaluate_groups(plan):
    failures=[]
    objects={o['id']:o for o in plan['objects']}
    for group in plan.get('furnishing_groups',{}).get('rugs',[]):
        rug=objects[group['rug_id']]
        for identifier in group['covered_ids']:
            box=local_bounds(objects[identifier],rug)
            w,l= rug['dimensions']['width']/2, rug['dimensions']['length']/2
            if box[0]<-w-1e-5 or box[2]>w+1e-5 or box[1]<-l-1e-5 or box[3]>l+1e-5:
                failures.append({'type':'rug_group_coverage','severity':'hard','object_id':identifier,'rug_id':rug['id']})
    for obj in plan['objects']:
        link=obj.get('furnishing_attachment',{})
        if link.get('mode')=='under':
            parent=objects[link['parent_id']];box=local_bounds(obj,parent)
            if (box[0]<-parent['dimensions']['width']/2 or box[2]>parent['dimensions']['width']/2 or
                box[1]<-parent['dimensions']['length']/2 or box[3]>parent['dimensions']['length']/2 or
                obj['dimensions']['height']>parent['dimensions']['height']-.08):
                failures.append({'type':'under_furniture_envelope','severity':'hard','object_id':obj['id']})
    return failures
