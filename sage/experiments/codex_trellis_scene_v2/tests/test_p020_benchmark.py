from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from .. import p020_benchmark as runner
from ..content_chain import content_hash, file_sha256


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def source_fixture(root, candidate, contract='selection_contract', split='selection', alpha=True):
    """Synthetic byte artifacts; actual old source validator checks their chain."""
    p = root / candidate
    p.mkdir(parents=True)
    paths = {}
    for role in ('source_rgb', 'prepared_rgba', 'alpha_mask', 'normalized_white_rgb'):
        paths[role] = p / (role + '.png')
        paths[role].write_bytes((candidate + ':' + role).encode())
    metadata = {
        'source_image_path': str(paths['source_rgb']),
        'prepared_image_path': str(paths['prepared_rgba']),
        'mask_path': str(paths['alpha_mask']),
        'normalized_white_image_path': str(paths['normalized_white_rgb']),
        'source_white_background': {'enforced': True, 'ok': True, 'conforms': True},
        'white_background_isolation': {
            'ok': True, 'exact_white_for_all_alpha_zero_pixels': True,
            'trellis_input_uses_transparent_rgba': True,
            'normalized_white_rgb_path': str(paths['normalized_white_rgb']),
        },
        'alpha_quality': {'ok': alpha},
    }
    paths['alpha_metadata'] = write(p / 'alpha.json', metadata)
    evidence = {'schema': 'scene-v2-flux-trellis-reference-evidence/v1',
                'parent_job_id': candidate, 'reference_job_id': candidate,
                'reference_origin': 'flux_generated', 'complete': True,
                'files': {role: runner.binding(path) for role, path in paths.items()}}
    manifest = write(p / 'manifest.json', evidence)
    return {'id': candidate, 'case_id': contract, 'contract_id': contract,
            'split': split, 'provider': 'flux1-schnell', 'image_kind': 'source_reference',
            'image_path': str(paths['prepared_rgba']), 'hash': file_sha256(paths['prepared_rgba']),
            'raw_path': str(paths['source_rgb']), 'raw_sha256': file_sha256(paths['source_rgb']),
            'rgba_path': str(paths['prepared_rgba']), 'rgba_sha256': file_sha256(paths['prepared_rgba']),
            'source_pointer': runner.binding(manifest), 'alpha_qa_pointer': runner.binding(paths['alpha_metadata'])}


class Fixture:
    def __init__(self, root):
        self.root = root
        requirement = {'id': 'identity', 'question': 'Is the requested furniture present?',
                       'expected': True, 'positive': 'requested furniture', 'negative': 'other furniture',
                       'hard': True, 'depends_on': []}
        contracts = {'contracts': [{'contract_id': key, 'split': split, 'requirements': [requirement]}
                                  for key, split in [('selection_contract', 'selection'), ('heldout_contract', 'heldout')]]}
        self.contracts = write(root / 'contracts.json', contracts)
        self.rows = [source_fixture(root, 'first'), source_fixture(root, 'second')]
        prompt = 'One target item. Pure white background.'
        self.slot = {'slot_id': 'new_slot', 'case_id': 'heldout_contract', 'contract_id': 'heldout_contract',
                     'split': 'heldout', 'provider': 'builtin_imagegen', 'max_generation_calls': 1,
                     'reroll_allowed': False, 'prompt': prompt, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()}
        self.draft = write(root / 'draft.json', {'status': 'DRAFT', 'frozen': False,
                           'existing_inputs': self.rows, 'planned_builtin_slots': [self.slot]})
        code = root / 'method.py'; code.write_text('# fixed test implementation')
        model = root / 'model'; model.mkdir(); weight = model / 'model.bin'; weight.write_bytes(b'fake weights')
        model_binding = {'id': 'fixture', 'path': str(model), 'revision': 'frozen-v1', 'files': [runner.binding(weight)]}
        methods = {}
        for name in ('baseline', 'A', 'B', 'C'):
            params = {'model_path': str(model), 'device': 'cpu'} if name in ('A', 'B') else {}
            if name == 'B': params.update(max_pixels=1024, max_new_tokens=1536)
            methods[name] = {'files': [runner.binding(code)], 'model_bindings': [model_binding] if name in ('A', 'B') else [], 'parameters': params}
        self.settings_data = {'schema': 'p020_experiment_settings_v1', 'methods': methods,
            'budgets': {'max_candidates': 3, 'max_calls_per_candidate': {'A': 1, 'B': 1}, 'max_total_calls': {'A': 3, 'B': 5}},
            'metrics': {'independent_case_denominator': True}, 'choice_rules': {'promotion': 'test_fixture_only'},
            'source_policy': {'scope': '2d_reference_only'},
            'selection_rules': {'scene_dna': {'default': {}, 'by_contract': {'selection_contract': {'palette': 'navy'}}}}}
        self.settings = write(root / 'settings.json', self.settings_data)
        self.frozen = root / 'frozen/frozen_protocol.json'
        self.pool = root / 'sealed/frozen_pool.json'

    def freeze(self):
        runner.freeze_protocol(self.draft, self.contracts, self.settings, self.frozen.parent)

    def seal(self, failed=False):
        row = source_fixture(self.root, 'new', 'heldout_contract', 'heldout')
        row.update(slot_id='new_slot', provider='builtin_imagegen', prompt_sha256=self.slot['prompt_sha256'], generation_call_count=1, terminal_status='success')
        if failed:
            row.update(terminal_status='failed', image_path=None, hash=None, error='generation failed before artifact')
        self.candidates = write(self.root / 'candidate_inputs.json', {'schema': 'p020_candidate_inputs_v1', 'inputs': [row]})
        runner.seal_pool(self.frozen, self.candidates, self.pool.parent)
        self.rows.append(row)

    def sources(self):
        self.source_dir = self.root / 'sources'
        runner.source_evidence(self.source_dir, frozen=self.frozen, pool=self.pool)
        self.source_index = self.source_dir / 'index.json'
        self.source_sha = file_sha256(self.source_index)


class FakeScorer:
    def __init__(self, method, calls, fail_first=False):
        self.method, self.calls, self.fail_first = method, calls, fail_first
        self.closed = False

    def score(self, image, contract, **kwargs):
        self.calls.append(str(image))
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError('synthetic model crash')
        rows = [{**q, 'verdict': 'pass', 'contrast_score': .9} for q in contract['requirements']]
        report = {'schema': 'scene-v2-p020-requirement-predictions/v1', 'method': self.method,
                  'contract_hash': content_hash(contract), 'requirements': rows,
                  'inference': {'raw_response': 'synthetic raw text'}}
        report['image_binding' if self.method == 'A' else 'image'] = {
            'source_sha256' if self.method == 'A' else 'sha256': file_sha256(Path(image))}
        return report

    def close(self):
        self.closed = True


class P020BenchmarkTests(unittest.TestCase):
    def test_freeze_missing_policy_fails_and_exclusive_freeze_catches_tampered_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            bad = copy.deepcopy(f.settings_data); del bad['choice_rules']; write(f.settings, bad)
            with self.assertRaisesRegex(ValueError, 'choice_rules'):
                f.freeze()
            self.assertFalse(f.frozen.exists())
            write(f.settings, f.settings_data); f.freeze()
            before = f.frozen.read_bytes()
            with self.assertRaises(FileExistsError): f.freeze()
            self.assertEqual(f.frozen.read_bytes(), before)
            (Path(tmp) / 'method.py').write_text('# changed after freeze')
            with self.assertRaisesRegex(ValueError, 'binding changed'):
                runner.verify_protocol(f.frozen)

    def test_pool_requires_exactly_one_terminal_record_per_slot_and_rejects_prompt_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp)); f.freeze()
            new = source_fixture(Path(tmp), 'n', 'heldout_contract', 'heldout')
            new.update(slot_id='new_slot', provider='builtin_imagegen', prompt_sha256=f.slot['prompt_sha256'], generation_call_count=1, terminal_status='success')
            path = write(Path(tmp) / 'inputs.json', {'schema':'p020_candidate_inputs_v1', 'inputs':[new,new]})
            with self.assertRaisesRegex(ValueError, 'one terminal'): runner.seal_pool(f.frozen,path,f.pool.parent)
            new['prompt_sha256']='0'*64; write(path, {'schema':'p020_candidate_inputs_v1','inputs':[new]})
            with self.assertRaisesRegex(ValueError, 'prompt_sha256'): runner.seal_pool(f.frozen,path,f.pool.parent)
            self.assertFalse(f.pool.exists())

    def test_unsealed_formal_source_and_score_are_rejected_without_adapter_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp)); f.freeze(); factory=Mock()
            with self.assertRaises(ValueError): runner.source_evidence(Path(tmp)/'out',frozen=f.frozen)
            with self.assertRaises(FileNotFoundError):
                runner.score_pool(f.frozen,f.pool,Path(tmp)/'source.json','0'*64,'A',Path(tmp)/'scores',scorer_factory=factory)
            factory.assert_not_called()

    def test_real_source_validator_does_not_confuse_complete_manifest_with_alpha_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=source_fixture(Path(tmp),'bad_alpha',alpha=False)
            report=runner.source_record(row)
            self.assertEqual(report['rules'],{'source':True,'alpha':False})
            self.assertEqual(report['scope'],'2d_reference_only')
            self.assertFalse(report['asset_accepted'])
            self.assertTrue(report['source_validation']['ok'])
            other=source_fixture(Path(tmp),'unknown_alpha',alpha='true')
            report=runner.source_record(other)
            self.assertIsNone(report['rules']['alpha'])
            self.assertIn('alpha_quality.ok_missing_or_not_boolean',report['unknown_reasons'])

    def test_forged_alpha_pointer_or_changed_source_cannot_gain_source_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=source_fixture(Path(tmp),'x')
            alternate=write(Path(tmp)/'other_alpha.json',{'alpha_quality':{'ok':True}})
            row['alpha_qa_pointer']=runner.binding(alternate)
            report=runner.source_record(row)
            self.assertTrue(report['rules']['source'])
            self.assertFalse(report['rules']['alpha'])
            self.assertIn('observed_alpha_manifest_hash_mismatch',report['failures'])
            row=source_fixture(Path(tmp),'y')
            Path(row['raw_path']).write_bytes(b'changed pixels')
            self.assertFalse(runner.source_record(row)['rules']['source'])

    def test_missing_alpha_pointer_does_not_erase_confirmed_source_and_missing_source_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=source_fixture(Path(tmp),'x')
            row['alpha_qa_pointer']=None
            report=runner.source_record(row)
            self.assertEqual(report['rules'],{'source':True,'alpha':None})
            self.assertTrue(report['source_validation']['ok'])
            self.assertTrue(report['alpha_trace'])
            row['source_pointer']=None
            report=runner.source_record(row)
            self.assertEqual(report['rules'],{'source':None,'alpha':None})

    def test_missing_direct_or_upstream_file_is_unknown_not_confirmed_quality_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=source_fixture(Path(tmp),'direct')
            Path(row['alpha_qa_pointer']['path']).unlink()
            report=runner.source_record(row)
            self.assertEqual(report['rules'],{'source':None,'alpha':None})
            self.assertTrue(report['unknown_reasons'])
            row=source_fixture(Path(tmp),'upstream')
            manifest=runner.read_json(row['source_pointer']['path'])
            manifest['upstream_reference']={'manifest':{'path':str(Path(tmp)/'missing.json'),'sha256':'0'*64}}
            write(Path(row['source_pointer']['path']),manifest)
            row['source_pointer']=runner.binding(row['source_pointer']['path'])
            report=runner.source_record(row)
            self.assertIsNone(report['rules']['source'])
            self.assertTrue(report['rules']['alpha'])

    def test_development_source_mode_rejects_selection_and_omits_rendered_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=source_fixture(Path(tmp),'d');path=write(Path(tmp)/'dev.json',{'schema':'p020_dev_inputs_draft_v1','inputs':[row]})
            with self.assertRaises(ValueError):runner.source_evidence(Path(tmp)/'rejected',development_inputs=path)
            row['split']='development';view=dict(row,id='view',image_kind='rendered_3d_view',image_path='/not/read.png')
            write(path,{'schema':'p020_dev_inputs_draft_v1','inputs':[row,view]})
            result=runner.source_evidence(Path(tmp)/'sources',development_inputs=path)
            self.assertEqual(result['failure_denominator'],1)

    def test_model_failure_remains_in_denominator_resume_does_not_repeat_and_checkpoint_is_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp));f.freeze();f.seal();f.sources();calls=[];scorer=FakeScorer('A',calls,True)
            out=Path(tmp)/'scores';factory=Mock(return_value=scorer)
            index=runner.score_pool(f.frozen,f.pool,f.source_index,f.source_sha,'A',out,scorer_factory=factory)
            records=[runner.read_json(x['path']) for x in index['records']]
            self.assertEqual(index['failure_denominator'],3)
            self.assertEqual([x['status'] for x in records],['error','completed','completed'])
            self.assertIn('synthetic model crash',records[0]['error']['message'])
            self.assertTrue(records[0]['raw_prompt'])
            self.assertEqual(len(calls),3);self.assertTrue(scorer.closed)
            runner.score_pool(f.frozen,f.pool,f.source_index,f.source_sha,'A',out,scorer_factory=factory)
            self.assertEqual(len(calls),3)
            Path(index['records'][0]['path']).write_text('{}')
            with self.assertRaisesRegex(ValueError,'binding changed'):
                runner.score_pool(f.frozen,f.pool,f.source_index,f.source_sha,'A',out,scorer_factory=factory)

    def test_interrupted_reserved_call_is_not_automatically_reissued(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp));f.freeze();f.seal();f.sources();out=Path(tmp)/'scores'
            key=content_hash({'protocol':file_sha256(f.frozen),'pool':file_sha256(f.pool),'source_index':f.source_sha,'method':'B'})
            write(out/'B/calls'/f'{runner._token("first")}.json',{'run_key':key,'candidate_id':'first','reserved_calls':1})
            calls=[]
            index=runner.score_pool(f.frozen,f.pool,f.source_index,f.source_sha,'B',out,scorer_factory=lambda m,p:FakeScorer(m,calls))
            self.assertEqual(len(calls),2)
            first=runner.read_json(index['records'][0]['path'])
            self.assertIn('interrupted_call_preserved',first['error']['message'])
            self.assertEqual(first['model_calls_reserved'],1)

    def test_merge_uses_canonical_contract_independent_evidence_and_per_contract_legacy_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp));f.freeze();f.seal();f.sources();out=Path(tmp)/'scores'
            for method in ('A','B'):
                runner.score_pool(f.frozen,f.pool,f.source_index,f.source_sha,method,out,scorer_factory=lambda m,p:FakeScorer(m,[]))
            observed=[]
            def legacy(image,alpha,scene_dna):
                observed.append((str(image),scene_dna))
                return {'score':2.0 if 'second' in str(image) else 1.0}
            result=runner.merge_select(f.frozen,f.pool,f.source_index,f.source_sha,out,Path(tmp)/'selection.json',legacy_scorer=legacy)
            self.assertEqual(result['failure_denominator'],3)
            self.assertEqual([c for _,c in observed],[{'palette':'navy'},{'palette':'navy'},{}])
            selection=[x for x in result['results'] if x['contract_id']=='selection_contract']
            self.assertEqual([x['selection']['selected'] for x in selection],['second']*4)
            self.assertTrue(all(x['selection']['canonical_contract_provided'] for x in selection))
            self.assertFalse(result['style_pair_stage_implemented'])

    def test_terminal_missing_image_kept_as_error_record_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp));f.freeze();f.seal(failed=True);f.sources();calls=[]
            index=runner.score_pool(f.frozen,f.pool,f.source_index,f.source_sha,'A',Path(tmp)/'scores',scorer_factory=lambda m,p:FakeScorer(m,calls))
            self.assertEqual(len(calls),2)
            self.assertEqual(index['failure_denominator'],3)
            self.assertEqual(runner.read_json(index['records'][-1]['path'])['status'],'error')

    def test_unavailable_candidate_retains_denominator_without_erasing_other_candidate_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp))
            f.rows[1].update(terminal_status='failed',image_path=None,hash=None,error='missing candidate image')
            draft=runner.read_json(f.draft);draft['existing_inputs']=f.rows;write(f.draft,draft)
            f.freeze();f.seal();f.sources();out=Path(tmp)/'scores'
            for method in ('A','B'):
                runner.score_pool(f.frozen,f.pool,f.source_index,f.source_sha,method,out,scorer_factory=lambda m,p:FakeScorer(m,[]))
            result=runner.merge_select(f.frozen,f.pool,f.source_index,f.source_sha,out,Path(tmp)/'selection.json',legacy_scorer=lambda *a:{'score':.75})
            selection=[x['selection'] for x in result['results'] if x['contract_id']=='selection_contract']
            self.assertEqual([x['selected'] for x in selection],['first']*4)
            self.assertTrue(all(x['failure_denominator']==2 and x['ranking_candidate_count']==1 for x in selection))
            self.assertTrue(all(len(x['candidates'])==2 for x in selection))
            self.assertTrue(all(x['unavailable_candidates'][0]['legacy_style'] is None for x in selection))


if __name__=='__main__': unittest.main()
