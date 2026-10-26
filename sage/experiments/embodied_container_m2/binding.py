"""Fail before model loading when any bound input differs from the protocol."""
from pathlib import Path
from xml.etree import ElementTree as ET
from importlib.metadata import version
from sage.experiments.embodied_scene_bridge.contracts import read, digest, require


def verify_package(protocol):
    source = Path(protocol['source_scene'])
    require(digest(source/'FILES.json') == protocol['source_files_sha256'], 'source_manifest_changed')
    files = read(source/'FILES.json')
    require({'model.xml', 'task.json'} <= set(files), 'incomplete_source_manifest')
    for name, expected in files.items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'invalid_manifest_path')
        require((source/relative).is_file(), 'missing_source_file:' + name)
        require(digest(source/relative) == expected, 'source_file_changed:' + name)
    require(files['model.xml'] == protocol['source_xml_sha256'], 'source_xml_binding_mismatch')
    for node in ET.parse(source/'model.xml').iter():
        if node.get('file'):
            require(node.get('file') in files, 'unbound_model_reference:' + node.get('file'))
    task = read(source/'task.json')
    require(task['success'] == protocol['success'], 'task_success_protocol_mismatch')
    require(task['control'] == protocol['action_contract'], 'task_control_protocol_mismatch')
    require(task['task'] == 'place_in_container', 'container_task_required')
    require(task['cavity'] == read(source/'container_certificate.json'), 'cavity_certificate_mismatch')
    require(task['cavity']['verified'] and task['cavity']['proxy_pitch_m'] == .005, 'uncertified_container')
    require(not task['cavity']['fill_interior'] and not task['cavity']['artificial_bottom_added'], 'unsupported_container_proxy')
    return dict(source_scene=str(source), manifest_sha256=digest(source/'FILES.json'),
                files=files, task_sha256=files['task.json'], model_sha256=files['model.xml'])


def verify_run(root, name, seed):
    root = Path(root)
    freeze = read(root/'protocol/FREEZE.json')
    require(digest(root/'protocol/PROTOCOL.json') == freeze['files']['PROTOCOL.json'], 'protocol_changed')
    for path, expected in freeze['code'].items():
        require(digest(path) == expected, 'controller_changed:' + path)
    protocol = read(root/'protocol/PROTOCOL.json')
    require(protocol['schema'] == 'embodied-container-M2/v1', 'protocol_schema')
    registration = protocol['execution']['registered_attempts'].get(name)
    require(registration is not None and registration['seed'] == seed, 'unregistered_attempt')
    require(seed in protocol['execution']['seeds'], 'unregistered_seed')
    lock_path = Path(protocol['dependency_lock_path'])
    require(digest(lock_path) == protocol['planner']['dependencies_sha256'], 'dependency_lock_changed')
    require(version('ompl') == read(lock_path)['version'] == protocol['planner']['version'], 'planner_version_mismatch')
    binding = verify_package(protocol)
    binding['protocol_sha256'] = digest(root/'protocol/PROTOCOL.json')
    binding['controller_files'] = freeze['code']
    return protocol, binding
