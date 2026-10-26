"""Opt-in P020 protocol/pool runner. No GPU selection, service or generation.

Freeze requires explicit experiment_settings.json (see validate_settings).
A protocol freeze precedes generation. seal-pool then binds one terminal record
per planned slot; source-evidence and score cannot use an unsealed formal pool.
The development source-evidence mode accepts source references only and never
opens rendered views. All model adapters are imported lazily by score/merge.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .content_chain import canonical_json, content_hash, file_sha256

FROZEN_SCHEMA = 'scene-v2-p020-frozen-protocol/v1'
POOL_SCHEMA = 'scene-v2-p020-sealed-pool/v1'
RUNNER_SCHEMA = 'scene-v2-p020-trusted-runner-evidence/v1'
INDEX_SCHEMA = 'scene-v2-p020-runner-evidence-index/v1'
RESULT_SCHEMA = 'scene-v2-p020-score-checkpoint/v1'
METHODS = {'baseline', 'A', 'B', 'C'}


def read_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'expected JSON object: {path}')
    return data


def binding(path: str | Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': file_sha256(path), 'bytes': path.stat().st_size}


def check_binding(record: Any) -> Path:
    if not isinstance(record, dict) or not record.get('path') or not record.get('sha256'):
        raise ValueError('missing explicit path/SHA256 binding')
    path = Path(record['path'])
    actual = binding(path)
    if actual['sha256'] != record['sha256'] or ('bytes' in record and actual['bytes'] != record['bytes']):
        raise ValueError(f'artifact binding changed: {path}')
    return path


def immutable_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Exclusive create; an existing result can never silently be overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(payload) + b'\n'
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return binding(path)


def sealed_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if path.exists() or path.with_suffix('.sha256').exists():
        raise FileExistsError(f'frozen artifact already exists: {path}')
    result = {**payload, 'content_sha256': content_hash(payload)}
    bound = immutable_json(path, result)
    with path.with_suffix('.sha256').open('x', encoding='ascii') as stream:
        stream.write(bound['sha256'] + '\n')
    return result


def check_seal(path: Path, schema: str) -> dict[str, Any]:
    document = read_json(path)
    claimed = document.get('content_sha256')
    payload = {k: v for k, v in document.items() if k != 'content_sha256'}
    if document.get('schema') != schema or claimed != content_hash(payload):
        raise ValueError(f'content seal mismatch: {path}')
    if path.with_suffix('.sha256').read_text().strip() != file_sha256(path):
        raise ValueError(f'file seal mismatch: {path}')
    return document


def _nonempty_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f'explicit nonempty {name} is required')
    return value


def validate_settings(settings: dict[str, Any]) -> None:
    """No metric, budget or promotion threshold is invented by the runner.

    methods: baseline/A/B/C each {files:[binding], model_bindings:[
    {id,path,revision,files:[binding]}], parameters:{...}}. A/B require bound
    model_path and explicit device. B also requires max_pixels/max_new_tokens.
    budgets: max_candidates, max_calls_per_candidate:{A,B}, max_total_calls:{A,B}.
    metrics, choice_rules, source_policy and selection_rules are explicit objects;
    selection_rules.scene_dna={default:{},by_contract:{...}} supplies the original
    legacy helper's inputs, with no inferred colors or shared forced palette.
    """
    if settings.get('schema') != 'p020_experiment_settings_v1':
        raise ValueError('settings schema must be p020_experiment_settings_v1')
    methods = _nonempty_dict(settings.get('methods'), 'methods')
    if set(methods) != METHODS:
        raise ValueError('all baseline/A/B/C method bindings are required')
    for name, method in methods.items():
        if not isinstance(method, dict) or not isinstance(method.get('files'), list) or not method['files']:
            raise ValueError(f'{name} requires explicit method files')
        for record in method['files']:
            check_binding(record)
        models = method.get('model_bindings')
        parameters = method.get('parameters')
        if not isinstance(models, list) or not isinstance(parameters, dict):
            raise ValueError(f'{name} model_bindings and parameters are required')
        for model in models:
            if not all(model.get(key) for key in ('id', 'path', 'revision', 'files')):
                raise ValueError(f'{name} incomplete model binding')
            if not isinstance(model['files'], list):
                raise ValueError('model files must be a list of hash bindings')
            for record in model['files']:
                check_binding(record)
        if name in {'A', 'B'}:
            if not models or not parameters.get('model_path') or not parameters.get('device'):
                raise ValueError(f'{name} requires model_path/device and model bindings')
            if Path(parameters['model_path']).resolve() not in {Path(m['path']).resolve() for m in models}:
                raise ValueError(f'{name} model_path is not bound')
        if name == 'B':
            for key in ('max_pixels', 'max_new_tokens'):
                if type(parameters.get(key)) is not int or parameters[key] < 1:
                    raise ValueError(f'B requires explicit positive {key}')
    budget = _nonempty_dict(settings.get('budgets'), 'budgets')
    if type(budget.get('max_candidates')) is not int or budget['max_candidates'] < 1:
        raise ValueError('max_candidates must be explicit and positive')
    for key in ('max_calls_per_candidate', 'max_total_calls'):
        for method in ('A', 'B'):
            value = budget.get(key, {}).get(method)
            if type(value) is not int or value < 1:
                raise ValueError(f'budget {key}.{method} must be explicit and positive')
    for key in ('metrics', 'choice_rules', 'source_policy', 'selection_rules'):
        _nonempty_dict(settings.get(key), key)
    if settings['source_policy'].get('scope') != '2d_reference_only':
        raise ValueError('source-policy scope must be 2d_reference_only')
    if not isinstance(settings['selection_rules'].get('scene_dna'), dict):
        raise ValueError('selection_rules.scene_dna must explicitly configure the legacy helper')
    scene_dna = settings['selection_rules']['scene_dna']
    if not isinstance(scene_dna.get('default'), dict) or not isinstance(scene_dna.get('by_contract'), dict):
        raise ValueError('scene_dna requires explicit default and by_contract mappings')


def _contracts(document: dict[str, Any]) -> dict[str, Any]:
    rows = document.get('contracts')
    if not isinstance(rows, list) or not rows:
        raise ValueError('contracts must be a nonempty list')
    result = {r['contract_id']: r for r in rows}
    if len(result) != len(rows):
        raise ValueError('duplicate contract IDs')
    # Lightweight structural validation keeps freeze free of model imports.
    for row in rows:
        requirements = row.get('requirements')
        if not isinstance(requirements, list) or not requirements:
            raise ValueError('empty contract requirements')
        ids = {r['id'] for r in requirements}
        if len(ids) != len(requirements):
            raise ValueError('duplicate requirement IDs')
        pending = {r['id']: set(r.get('depends_on', [])) for r in requirements}
        for r in requirements:
            if type(r.get('expected')) not in (bool, int, str) or type(r.get('hard')) is not bool:
                raise ValueError('invalid expected/hard type')
            if not all(isinstance(r.get(k), str) and r[k].strip() for k in ('question', 'positive', 'negative')):
                raise ValueError('missing contrast/question strings')
            if not isinstance(r.get('depends_on'), list) or not set(r['depends_on']) <= ids:
                raise ValueError('invalid dependencies')
        while pending:
            ready = {k for k, v in pending.items() if not v}
            if not ready:
                raise ValueError('dependency cycle')
            pending = {k: v - ready for k, v in pending.items() if k not in ready}
    return result


def freeze_protocol(draft_path: Path, contracts_path: Path, settings_path: Path, output: Path) -> dict[str, Any]:
    draft, contracts, settings = map(read_json, (draft_path, contracts_path, settings_path))
    if draft.get('frozen') is not False or draft.get('status') != 'DRAFT':
        raise ValueError('only an explicit DRAFT can be frozen')
    validate_settings(settings)
    contract_map = _contracts(contracts)
    inputs, slots = draft.get('existing_inputs'), draft.get('planned_builtin_slots')
    if not isinstance(inputs, list) or not isinstance(slots, list):
        raise ValueError('existing inputs and planned slots are required')
    for rows, key in ((inputs, 'id'), (slots, 'slot_id')):
        if len({r[key] for r in rows}) != len(rows):
            raise ValueError('duplicate input/slot IDs')
        for row in rows:
            if row.get('contract_id') not in contract_map or row.get('split') not in ('selection', 'heldout'):
                raise ValueError('formal pool requires known selection/heldout contracts')
            if contract_map[row['contract_id']].get('split') != row['split']:
                raise ValueError('input/contract split mismatch')
    if len(inputs) + len(slots) > settings['budgets']['max_candidates']:
        raise ValueError('candidate count exceeds explicitly declared budget')
    for slot in slots:
        if slot.get('max_generation_calls') != 1 or slot.get('reroll_allowed') is not False:
            raise ValueError('every generation slot must explicitly allow one call and no reroll')
        if slot.get('prompt_sha256') != hashlib.sha256(slot['prompt'].encode()).hexdigest():
            raise ValueError('generation prompt SHA mismatch')
    return sealed_json(output / 'frozen_protocol.json', {
        'schema': FROZEN_SCHEMA, 'frozen': True, 'pool_sealed': False,
        'bindings': [binding(p) for p in (draft_path, contracts_path, settings_path)],
        'runner_binding': binding(Path(__file__)),
        'source_validator_binding': binding(Path(__file__).with_name('asset_source_policy.py')),
        'draft': draft, 'contracts': contracts, 'settings': settings,
        'scope': 'protocol_only_no_generation_no_scoring_no_promotion',
    })


def verify_protocol(path: Path) -> dict[str, Any]:
    doc = check_seal(path, FROZEN_SCHEMA)
    for record in [*doc['bindings'], doc['runner_binding'], doc['source_validator_binding']]:
        check_binding(record)
    validate_settings(doc['settings'])
    _contracts(doc['contracts'])
    return doc


def verify_input(row: dict[str, Any]) -> None:
    if row.get('terminal_status') == 'failed' and row.get('image_path') is None:
        return
    if row.get('hash') != row.get('image_sha256', row.get('hash')):
        raise ValueError('inconsistent image hash fields')
    for path_key, hash_key in (('image_path', 'hash'), ('raw_path', 'raw_sha256'), ('rgba_path', 'rgba_sha256')):
        if row.get(path_key):
            check_binding({'path': row[path_key], 'sha256': row.get(hash_key)})
        elif path_key == 'image_path':
            raise ValueError('missing image without terminal failure placeholder')
    for key in ('source_pointer', 'alpha_qa_pointer'):
        if row.get(key):
            check_binding(row[key])


def seal_pool(frozen_path: Path, candidates_path: Path, output: Path) -> dict[str, Any]:
    protocol = verify_protocol(frozen_path)
    candidates = read_json(candidates_path)
    if candidates.get('schema') != 'p020_candidate_inputs_v1' or not isinstance(candidates.get('inputs'), list):
        raise ValueError('candidate inputs schema must be p020_candidate_inputs_v1')
    planned = {r['slot_id']: r for r in protocol['draft']['planned_builtin_slots']}
    added = candidates['inputs']
    if len(added) != len(planned) or {r.get('slot_id') for r in added} != set(planned):
        raise ValueError('exactly one terminal record per planned slot is required')
    inputs = list(protocol['draft']['existing_inputs'])
    for row in added:
        slot = planned[row['slot_id']]
        if row.get('terminal_status') not in ('success', 'failed') or type(row.get('generation_call_count')) is not int or not 0 <= row['generation_call_count'] <= 1:
            raise ValueError('terminal generation status and at most one call required')
        for key in ('contract_id', 'case_id', 'split', 'provider', 'prompt_sha256'):
            if row.get(key) != slot.get(key):
                raise ValueError(f'new candidate changes frozen slot field: {key}')
        if row['terminal_status'] == 'success' and (row['generation_call_count'] != 1 or not row.get('image_path')):
            raise ValueError('successful slot requires one actual generation call and source')
        if row['terminal_status'] == 'failed' and not row.get('error'):
            raise ValueError('failed slot requires retained error')
        inputs.append(dict(row, id=row.get('id') or row['slot_id']))
    if len({r['id'] for r in inputs}) != len(inputs):
        raise ValueError('candidate IDs must be unique across the whole pool')
    for row in inputs:
        verify_input(row)
    return sealed_json(output / 'frozen_pool.json', {'schema': POOL_SCHEMA,
        'protocol_binding': binding(frozen_path), 'protocol_content_sha256': protocol['content_sha256'],
        'candidate_inputs_binding': binding(candidates_path), 'inputs': inputs,
        'failure_denominator': len(inputs), 'pool_sealed': True, 'scores_or_labels_used': False})


def verify_pool(frozen_path: Path, pool_path: Path, *, artifacts: bool = False) -> tuple[dict, dict]:
    protocol = verify_protocol(frozen_path)
    pool = check_seal(pool_path, POOL_SCHEMA)
    check_binding(pool['protocol_binding'])
    check_binding(pool['candidate_inputs_binding'])
    if pool['protocol_binding']['sha256'] != file_sha256(frozen_path) or pool['protocol_content_sha256'] != protocol['content_sha256']:
        raise ValueError('pool belongs to a different protocol')
    if artifacts:
        for row in pool['inputs']:
            verify_input(row)
    return protocol, pool


def _probe_binding(record: Any) -> tuple[bool | None, Path | None, str]:
    if not isinstance(record, dict) or not record.get('path') or not record.get('sha256'):
        return None, None, 'binding_missing_or_not_yet_recorded'
    try:
        path = check_binding(record)
        return True, path, 'hash_verified'
    except (OSError, UnicodeError) as exc:
        return None, None, f'artifact_unreadable:{type(exc).__name__}'
    except (ValueError, TypeError) as exc:
        return False, None, f'observed_binding_mismatch:{exc}'


def _preflight_source_files(manifest: dict, steps: list, seen: frozenset[str] = frozenset()) -> None:
    files = manifest.get('files', {})
    if not isinstance(files, dict):
        steps.append({'check': 'manifest_file:structure', 'value': False, 'reason': 'observed_files_schema_invalid'})
        return
    for role, record in files.items():
        observed, path, reason = _probe_binding(record)
        steps.append({'check': f'manifest_file:{role}', 'value': observed, 'reason': reason})
        if observed is True and path.suffix == '.json':
            try:
                read_json(path)
            except (OSError, ValueError, UnicodeError) as exc:
                steps.append({'check': f'manifest_file:{role}:parse', 'value': None,
                              'reason': f'bound_json_unreadable:{type(exc).__name__}'})
    upstream = manifest.get('upstream_reference')
    if isinstance(upstream, dict):
        for role in ('manifest', 'reference'):
            if not upstream.get(role):
                continue
            observed, path, reason = _probe_binding(upstream[role])
            steps.append({'check': f'manifest_file:upstream_{role}', 'value': observed, 'reason': reason})
            if role == 'manifest' and observed is True:
                key = str(path.resolve())
                if key in seen or len(seen) >= 32:
                    steps.append({'check': 'manifest_file:upstream_cycle', 'value': False, 'reason': 'observed_upstream_cycle_or_depth_limit'})
                else:
                    try:
                        _preflight_source_files(read_json(path), steps, seen | {key})
                    except (OSError, ValueError, UnicodeError) as exc:
                        steps.append({'check': 'manifest_file:upstream_parse', 'value': None,
                                      'reason': f'upstream_manifest_unreadable:{type(exc).__name__}'})


def source_record(row: dict[str, Any], *, validator: Callable | None = None) -> dict[str, Any]:
    """Independent source and alpha observations: missing is not a failure label."""
    if validator is None:
        from .asset_source_policy import validate_reference_evidence
        validator = validate_reference_evidence
    source, alpha = None, None
    source_steps, alpha_steps = [], []
    manifest, validation, manifest_binding, metadata_binding = None, None, None, None
    image_sha = row.get('hash')
    for path_key, hash_key in [('image_path', 'hash'), ('raw_path', 'raw_sha256'), ('rgba_path', 'rgba_sha256')]:
        if path_key != 'image_path' and not row.get(path_key):
            continue
        state, _, reason = _probe_binding({'path': row.get(path_key), 'sha256': row.get(hash_key)})
        source_steps.append({'check': path_key, 'value': state, 'reason': reason})
    state, manifest_path, reason = _probe_binding(row.get('source_pointer'))
    source_steps.append({'check': 'source_manifest_binding', 'value': state, 'reason': reason})
    if state is True:
        manifest_binding = binding(manifest_path)
        try:
            manifest = read_json(manifest_path)
            supported = manifest.get('schema') in {'scene-v2-flux-trellis-reference-evidence/v1', 'scene-v2-image-trellis-reference-evidence/v2', 'scene-v2-image-trellis-reference-evidence/v3'}
            source_steps.append({'check': 'source_manifest_schema', 'value': supported,
                                 'reason': 'supported_persistent_schema' if supported else 'observed_unsupported_manifest_schema'})
            if supported:
                direct_files = manifest.get('files', {})
                # Preflight missing/unreadable direct files before the old validator
                # conflates inability to inspect them with an observed policy failure.
                _preflight_source_files(manifest, source_steps)
                direct = [step['value'] for step in source_steps if step['check'].startswith('manifest_file:')]
                if all(v is True for v in direct):
                    validation = validator({**manifest, 'manifest': manifest_binding})
                    observed = validation.get('ok') if isinstance(validation, dict) else None
                    if type(observed) is not bool:
                        observed = None
                    source_steps.append({'check': 'legacy_source_validator', 'value': observed,
                                         'reason': 'validator_completed' if observed is not None else 'validator_result_unavailable'})
                for role, field in [('source_rgb', 'raw_sha256'), ('prepared_rgba', 'rgba_sha256')]:
                    if row.get(field):
                        match = direct_files.get(role, {}).get('sha256') == row[field]
                        source_steps.append({'check': f'input_manifest_join:{role}', 'value': match,
                                             'reason': 'image_manifest_hash_match' if match else 'observed_image_manifest_hash_mismatch'})
        except Exception as exc:
            source_steps.append({'check': 'manifest_or_validator_read', 'value': None,
                                 'reason': f'evidence_unavailable:{type(exc).__name__}:{exc}'})
    values = [step['value'] for step in source_steps]
    source = False if False in values else (True if values and all(v is True for v in values) and validation is not None else None)

    # Alpha metadata is a separate bound observation. Its absence never erases a
    # completed positive source validation, and complete/schema never imply QA.
    state, metadata_path, reason = _probe_binding(row.get('alpha_qa_pointer'))
    alpha_steps.append({'check': 'alpha_metadata_binding', 'value': state, 'reason': reason})
    if state is True:
        metadata_binding = binding(metadata_path)
        if manifest is not None and isinstance(manifest.get('files'), dict) and manifest['files'].get('alpha_metadata'):
            match = manifest['files']['alpha_metadata'].get('sha256') == metadata_binding['sha256']
            alpha_steps.append({'check': 'alpha_manifest_join', 'value': match,
                                'reason': 'alpha_manifest_hash_match' if match else 'observed_alpha_manifest_hash_mismatch'})
        try:
            metadata = read_json(metadata_path)
            declared = metadata.get('prepared_image_path')
            target = row.get('rgba_path') or row.get('image_path')
            match = Path(declared).resolve() == Path(target).resolve() if declared and target else None
            alpha_steps.append({'check': 'alpha_image_path_join', 'value': match,
                                'reason': 'alpha_image_path_match' if match else 'alpha_image_path_missing_or_mismatched'})
            quality = metadata.get('alpha_quality')
            value = quality.get('ok') if isinstance(quality, dict) else None
            observed = value if type(value) is bool else None
            alpha_steps.append({'check': 'alpha_quality.ok', 'value': observed,
                                'reason': 'observed_alpha_quality' if observed is not None else 'alpha_quality.ok_missing_or_not_boolean'})
        except Exception as exc:
            alpha_steps.append({'check': 'alpha_metadata_read', 'value': None,
                                'reason': f'alpha_evidence_unreadable:{type(exc).__name__}:{exc}'})
    values = [step['value'] for step in alpha_steps]
    alpha = False if False in values else (True if values and all(v is True for v in values) else None)
    return {'schema': RUNNER_SCHEMA, 'candidate_id': row['id'], 'image_sha256': image_sha,
            'rules': {'source': source, 'alpha': alpha}, 'scope': '2d_reference_only',
            'asset_accepted': False, 'asset_admission_claim_allowed': False,
            'source_manifest_binding': manifest_binding, 'alpha_metadata_binding': metadata_binding,
            'source_validation': validation, 'alpha_quality_field': 'alpha_quality.ok',
            'source_trace': source_steps, 'alpha_trace': alpha_steps,
            'failures': [step['reason'] for step in source_steps + alpha_steps if step['value'] is False],
            'unknown_reasons': [step['reason'] for step in source_steps + alpha_steps if step['value'] is None],
            'model_output_used_as_evidence': False}


def _token(candidate_id: str) -> str:
    return content_hash(candidate_id)[:24]


def source_evidence(output: Path, *, frozen: Path | None = None, pool: Path | None = None,
                    development_inputs: Path | None = None) -> dict[str, Any]:
    if development_inputs is not None:
        if frozen or pool:
            raise ValueError('development and formal source modes are mutually exclusive')
        data = read_json(development_inputs)
        if data.get('schema') != 'p020_dev_inputs_draft_v1' or any(r.get('split') != 'development' for r in data.get('inputs', [])):
            raise ValueError('development source mode requires development-only DEV_INPUTS')
        rows = [r for r in data['inputs'] if r.get('image_kind') == 'source_reference']
        anchor = {'development_inputs': binding(development_inputs)}
    else:
        if frozen is None or pool is None:
            raise ValueError('formal source QA requires a frozen protocol AND sealed pool')
        _, doc = verify_pool(frozen, pool)
        rows, anchor = doc['inputs'], {'pool_binding': binding(pool)}
    records = []
    for row in rows:
        report = source_record(row)
        path = output / 'records' / f'{_token(row["id"])}.json'
        records.append({'candidate_id': row['id'], **immutable_json(path, report)})
    index = {'schema': INDEX_SCHEMA, **anchor, 'records': records,
             'scope': '2d_reference_only', 'failure_denominator': len(rows)}
    immutable_json(output / 'index.json', index)
    return index


def _evidence_index(path: Path, expected_sha256: str, pool_path: Path) -> tuple[dict, dict]:
    check_binding({'path': str(path), 'sha256': expected_sha256})
    index = read_json(path)
    if index.get('schema') != INDEX_SCHEMA or index.get('pool_binding', {}).get('sha256') != file_sha256(pool_path):
        raise ValueError('runner evidence index is not bound to the sealed pool')
    records = {r['candidate_id']: r for r in index.get('records', [])}
    if len(records) != len(index.get('records', [])):
        raise ValueError('duplicate runner evidence records')
    return index, records


def _load_evidence(row: dict, record: dict):
    from .p020_requirement_scoring import load_runner_evidence
    check_binding(record)
    document = read_json(record['path'])
    if document.get('candidate_id') != row['id'] or document.get('scope') != '2d_reference_only':
        raise ValueError('runner evidence candidate/scope mismatch')
    return load_runner_evidence(Path(record['path']), expected_sha256=record['sha256'], image_path=Path(row['image_path']))


@contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _scorer(method: str, parameters: dict):
    if method == 'A':
        from .p020_requirement_scoring import AtomicSiglipScorer
        return AtomicSiglipScorer(parameters['model_path'], device=parameters['device'])
    from .p020_vqa import QwenAtomicScorer
    return QwenAtomicScorer(parameters['model_path'], device=parameters['device'],
                            max_pixels=parameters['max_pixels'], max_new_tokens=parameters['max_new_tokens'])


def score_pool(frozen: Path, pool_path: Path, source_index: Path, source_index_sha256: str,
               method: str, output: Path, *, scorer_factory: Callable | None = None) -> dict[str, Any]:
    if method not in {'A', 'B'}:
        raise ValueError('score lazily executes only A or B')
    protocol, pool = verify_pool(frozen, pool_path)
    _, evidence = _evidence_index(source_index, source_index_sha256, pool_path)
    if set(evidence) != {r['id'] for r in pool['inputs']}:
        raise ValueError('source evidence must retain every sealed candidate')
    contracts = _contracts(protocol['contracts'])
    settings = protocol['settings']; parameters = settings['methods'][method]['parameters']
    root = output / method
    run_key = content_hash({'protocol': file_sha256(frozen), 'pool': file_sha256(pool_path),
                           'source_index': source_index_sha256, 'method': method})
    scorer, result_bindings = None, []
    with _lock(root / '.runner.lock'):
        if (root / 'index.json').exists():
            index = read_json(root / 'index.json')
            if index.get('run_key') != run_key:
                raise ValueError('existing score index belongs to different inputs')
            for record in index['records']:
                check_binding(record)
            return index
        try:
            for row in pool['inputs']:
                stem = _token(row['id']); path = root / 'results' / f'{stem}.json'; started = root / 'calls' / f'{stem}.json'
                if path.exists():
                    old = check_seal(path, RESULT_SCHEMA)
                    if old.get('run_key') != run_key or old.get('candidate_id') != row['id']:
                        raise ValueError('score checkpoint input mismatch')
                    result_bindings.append({'candidate_id': row['id'], **binding(path)})
                    continue
                contract = contracts[row['contract_id']]
                result = {'schema': RESULT_SCHEMA, 'method': method, 'candidate_id': row['id'],
                          'contract_id': row['contract_id'], 'split': row['split'], 'run_key': run_key,
                          'image_sha256': row.get('hash'), 'contract_hash': content_hash(contract),
                          'runner_evidence_binding': evidence[row['id']], 'status': 'error', 'report': None,
                          'error': None, 'raw_prompt': None, 'model_calls_reserved': 0}
                begin = time.perf_counter()
                try:
                    verify_input(row)
                    runner = _load_evidence(row, evidence[row['id']])
                    if method == 'B':
                        from .p020_vqa import build_atomic_prompt
                        result['raw_prompt'] = build_atomic_prompt(contract)
                    else:
                        result['raw_prompt'] = [q[k] for q in contract['requirements'] for k in ('positive', 'negative')]
                    result['raw_prompt_hash'] = content_hash(result['raw_prompt'])
                    if started.exists():
                        if read_json(started).get('run_key') != run_key:
                            raise ValueError('call reservation belongs to different run')
                        result['model_calls_reserved'] = 1
                        raise RuntimeError('interrupted_call_preserved_without_automatic_reroll')
                    used = len(list((root / 'calls').glob('*.json'))) if (root / 'calls').exists() else 0
                    if used >= settings['budgets']['max_total_calls'][method]:
                        raise RuntimeError('frozen_total_call_budget_exhausted')
                    immutable_json(started, {'run_key': run_key, 'candidate_id': row['id'], 'reserved_calls': 1,
                                             'raw_prompt_hash': result['raw_prompt_hash']})
                    result['model_calls_reserved'] = 1
                    if scorer is None:
                        scorer = (scorer_factory or _scorer)(method, parameters)
                    if method == 'A':
                        report = scorer.score(Path(row['image_path']), contract, output_dir=root / 'normalized', runner_evidence=runner)
                    else:
                        report = scorer.score(Path(row['image_path']), contract)
                    if report.get('contract_hash') != content_hash(contract):
                        raise ValueError('adapter returned a report for a different contract')
                    image_hash = report.get('image_binding', {}).get('source_sha256') if method == 'A' else report.get('image', {}).get('sha256')
                    if image_hash != row['hash']:
                        raise ValueError('adapter returned a report for a different image')
                    result.update(status='completed', report=report)
                except Exception as exc:
                    result['error'] = {'type': type(exc).__name__, 'message': str(exc)}
                result['elapsed_seconds'] = time.perf_counter() - begin
                sealed_json(path, result)
                result_bindings.append({'candidate_id': row['id'], **binding(path)})
        finally:
            if scorer is not None:
                scorer.close()
        index = {'schema': 'scene-v2-p020-score-index/v1', 'method': method, 'run_key': run_key,
                 'protocol_binding': binding(frozen), 'pool_binding': binding(pool_path),
                 'source_index_binding': {'path': str(source_index), 'sha256': source_index_sha256},
                 'failure_denominator': len(pool['inputs']), 'records': result_bindings}
        immutable_json(root / 'index.json', index)
        return index


def merge_select(frozen: Path, pool_path: Path, source_index: Path, source_index_sha256: str,
                 scores: Path, output: Path, *, legacy_scorer: Callable | None = None) -> dict[str, Any]:
    from .p020_requirement_scoring import consensus, legacy_visual_candidate_score, select_candidate
    protocol, pool = verify_pool(frozen, pool_path)
    _, evidence = _evidence_index(source_index, source_index_sha256, pool_path)
    contracts = _contracts(protocol['contracts']); reports = {}; score_anchors = []
    for method in ('A', 'B'):
        path = scores / method / 'index.json'; index = read_json(path)
        expected_run = content_hash({'protocol': file_sha256(frozen), 'pool': file_sha256(pool_path), 'source_index': source_index_sha256, 'method': method})
        if index.get('schema') != 'scene-v2-p020-score-index/v1' or index.get('method') != method or index.get('run_key') != expected_run or index.get('pool_binding', {}).get('sha256') != file_sha256(pool_path) or index.get('source_index_binding', {}).get('sha256') != source_index_sha256:
            raise ValueError('method score index does not match pool/source evidence')
        score_anchors.append(binding(path)); mapping = {}
        for record in index['records']:
            checkpoint = read_json(check_binding(record))
            if checkpoint.get('run_key') != expected_run or checkpoint.get('candidate_id') != record['candidate_id']:
                raise ValueError('score checkpoint candidate/run mismatch')
            mapping[record['candidate_id']] = checkpoint
        if len(mapping) != len(index['records']) or set(mapping) != {r['id'] for r in pool['inputs']}:
            raise ValueError('method score index lost candidates')
        reports[method] = mapping
    groups = {}; failures = []
    for row in pool['inputs']:
        cid = row['id']; contract = contracts[row['contract_id']]
        try:
            verify_input(row); runner = _load_evidence(row, evidence[cid])
            branches = {m: reports[m][cid].get('report') or {} for m in ('A', 'B')}
            branches['C'] = consensus(contract, branches['A'], branches['B'], runner_evidence=runner)
            alpha = read_json(check_binding(row['alpha_qa_pointer']))
            style_config = protocol['settings']['selection_rules']['scene_dna']
            scene_dna = style_config['by_contract'].get(row['contract_id'], style_config['default'])
            legacy = (legacy_scorer or legacy_visual_candidate_score)(Path(row['image_path']), alpha, scene_dna)
            value = legacy.get('score')
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('legacy helper did not produce a finite original score')
            candidate = {'candidate_id': cid, 'reports': branches, 'runner_evidence': runner, 'legacy_style': value}
            groups.setdefault(row['contract_id'], []).append(candidate)
        except Exception as exc:
            evidence_document = read_json(check_binding(evidence[cid]))
            failures.append({'candidate_id': cid, 'contract_id': row['contract_id'],
                             'status': 'unavailable_for_ranking', 'legacy_style': None,
                             'source_rules': evidence_document.get('rules'),
                             'runner_evidence_binding': evidence[cid],
                             'reports': {m: reports[m][cid].get('report') for m in ('A', 'B')},
                             'error': f'{type(exc).__name__}: {exc}'})
    results = []
    for contract_id in dict.fromkeys(r['contract_id'] for r in pool['inputs']):
        all_rows = [r for r in pool['inputs'] if r['contract_id'] == contract_id]
        errors = [r for r in failures if r['contract_id'] == contract_id]
        for method in ('baseline', 'A', 'B', 'C'):
            available = groups.get(contract_id, [])
            selection = select_candidate(available, method, contract=contracts[contract_id])
            selection['ranking_candidate_count'] = len(available)
            selection['failure_denominator'] = len(all_rows)
            selection['unavailable_candidates'] = errors
            selection['unavailable_count'] = len(errors)
            selection['candidates'].extend(errors)
            if not available and errors:
                selection['status'] = 'abstain_all_candidates_unavailable'
            results.append({'contract_id': contract_id, 'method': method, 'selection': selection})
    result = {'schema': 'scene-v2-p020-merge-selection/v1', 'pool_binding': binding(pool_path),
              'source_index_binding': {'path': str(source_index), 'sha256': source_index_sha256},
              'score_index_bindings': score_anchors, 'results': results, 'failure_denominator': len(pool['inputs']),
              'style_pair_stage_implemented': False, 'style_pair_calls': 0,
              'B_selection_mode': 'atomic_only_style_pair_stage_not_implemented',
              'scope': 'provisional_candidate_selection_only_not_asset_admission_or_effectiveness_acceptance'}
    immutable_json(output, result)
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    f = sub.add_parser('freeze'); f.add_argument('--draft', type=Path, required=True); f.add_argument('--contracts', type=Path, required=True); f.add_argument('--settings', type=Path, required=True); f.add_argument('--output', type=Path, required=True)
    s = sub.add_parser('seal-pool'); s.add_argument('--frozen', type=Path, required=True); s.add_argument('--candidate-inputs', type=Path, required=True); s.add_argument('--output', type=Path, required=True)
    v = sub.add_parser('verify'); v.add_argument('--frozen', type=Path, required=True); v.add_argument('--pool', type=Path); v.add_argument('--artifacts', action='store_true')
    q = sub.add_parser('source-evidence'); q.add_argument('--frozen', type=Path); q.add_argument('--pool', type=Path); q.add_argument('--development-inputs', type=Path); q.add_argument('--output', type=Path, required=True)
    for name in ('score', 'merge-select'):
        p = sub.add_parser(name); p.add_argument('--frozen', type=Path, required=True); p.add_argument('--pool', type=Path, required=True); p.add_argument('--source-index', type=Path, required=True); p.add_argument('--source-index-sha256', required=True); p.add_argument('--output', type=Path, required=True)
        if name == 'score': p.add_argument('--method', choices=['A', 'B'], required=True)
        else: p.add_argument('--scores', type=Path, required=True)
    a = parser.parse_args(argv)
    if a.command == 'freeze': result = freeze_protocol(a.draft, a.contracts, a.settings, a.output)
    elif a.command == 'seal-pool': result = seal_pool(a.frozen, a.candidate_inputs, a.output)
    elif a.command == 'verify':
        if a.pool: verify_pool(a.frozen, a.pool, artifacts=a.artifacts)
        else: verify_protocol(a.frozen)
        result = {'ok': True}
    elif a.command == 'source-evidence': result = source_evidence(a.output, frozen=a.frozen, pool=a.pool, development_inputs=a.development_inputs)
    elif a.command == 'score': result = score_pool(a.frozen, a.pool, a.source_index, a.source_index_sha256, a.method, a.output)
    else: result = merge_select(a.frozen, a.pool, a.source_index, a.source_index_sha256, a.scores, a.output)
    print(json.dumps({'command': a.command, 'schema': result.get('schema'), 'output': str(getattr(a, 'output', '') or ''), 'ok': True}))


if __name__ == '__main__':
    main()
