"""Executable M0 gates and content-addressed evidence."""
import hashlib
import json
import math
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, code):
    if not condition:
        raise ValueError(code)


def validate_protocol(p):
    require(p['schema'] == 'embodied-generator-protocol/v1', 'protocol_schema')
    require(p['tasks'] == ['pick_place', 'place_in_container'], 'task_scope')
    require(p['robot'] == 'Panda', 'robot_scope')
    require(p['control']['physics_dt_s'] == .001 and p['control']['action_dt_s'] == .05,
            'control_schedule')
    require(p['control']['action'] == 'absolute_joint7_and_finger_half_opening', 'action_contract')
    require(p['repairs']['new_task_repair_budget'] == 0, 'M1_is_unmodified_generator_B')
    require(p['resources'] == dict(cpu_max=8, memory_high_gib=12, memory_max_gib=16,
                                  runtime_max_s=900, gpu_peak_gib=12, gpu_reserve_gib=4), 'resource_contract')
    for v in p['success'].values():
        require(type(v) in (int, float) and math.isfinite(v) and v > 0, 'success_threshold')
    require(p['split_policy']['final_test_feedback_forbidden'] is True, 'test_feedback')
    require(p['attempt_budget']['generator_requests'] > 0, 'attempt_budget')
    return True


def validate_split_registry(rows, require_learning=False):
    """Any shared source, near-duplicate family OR layout family joins splits."""
    seen = {}
    for row in rows:
        require(row['split'] in ('development', 'train', 'validation', 'test'), 'unknown_split')
        for field in ('source_asset_groups', 'asset_content_sha256', 'layout_families'):
            require(bool(row.get(field)), 'missing_group:' + field)
            for group in row[field]:
                key = (field, group)
                require(key not in seen or seen[key] == row['split'], 'split_leakage:' + field + ':' + group)
                seen[key] = row['split']
    if require_learning:
        require({'train', 'validation', 'test'} <= {r['split'] for r in rows}, 'learning_splits_not_frozen')
    return True


def verify_freeze(root):
    root = Path(root)
    freeze = read(root / 'protocol/FREEZE.json')
    for relative, expected in freeze['files'].items():
        require(digest(root / relative) == expected, 'frozen_input_changed:' + relative)
    validate_protocol(read(root / 'protocol/PROTOCOL.json'))
    return freeze


def select_task_objects(plan, request):
    """Bind by category and generated support edge, never by historical names."""
    objects = plan['objects']
    require(len({o['id'] for o in objects}) == len(objects), 'duplicate_semantic_id')
    by_id = {o['id']: o for o in objects}
    selector = request['target_selector']
    candidates = [o for o in objects if o['category'] in selector['categories']
                  and o.get('support_id') in by_id
                  and by_id[o['support_id']]['category'] in request['support_categories']]
    require(len(candidates) == 1, 'task_binding_not_unique')
    target = candidates[0]
    if request['task'] == 'place_in_container':
        # A bounding box or a category name is not a certified cavity.
        containers = [o for o in objects if o.get('functional', {}).get('open_cavity', {}).get('verified')]
        require(len(containers) == 1, 'verified_container_cavity_missing')
        raise ValueError('container_runtime_not_implemented')
    require(request['task'] == 'pick_place', 'unsupported_task')
    return target, by_id[target['support_id']]
