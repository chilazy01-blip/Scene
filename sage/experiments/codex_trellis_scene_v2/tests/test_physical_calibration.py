import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ..physical_calibration import analyze


class PhysicalCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);raw=self.root/'synthetic_fixture.txt';raw.write_text('Synthetic unit test data, not actual measurement')
        binding=dict(path=raw.name,sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
        self.doc=dict(schema='scene-physical-measurements/v1',source_kind='human_physical_measurement',
            collector='synthetic test fixture only',collected_at='fixture',instrument='fixture',instrument_calibration_record='fixture',
            asset_source=binding,raw_evidence=[binding],records=[dict(kind='mass',object_id='fixture',unit='g',instrument_resolution=1.,trials=[790.,800.,810.])])

    def run_analysis(self):
        path=self.root/'fixture.json';path.write_text(json.dumps(self.doc));return analyze(path)

    def test_mass_units_repeatability_and_no_default_promotion(self):
        result=self.run_analysis();row=result['results'][0]
        self.assertAlmostEqual(row['mean'],.8)
        self.assertAlmostEqual(row['sample_standard_deviation'],.01)
        self.assertFalse(result['simulation_defaults_changed'])
        self.assertFalse(result['independent_provenance_verified'])

    def test_inferred_or_corrupted_data_cannot_be_measured(self):
        self.doc['source_kind']='simulation'
        with self.assertRaises(ValueError):self.run_analysis()
        self.doc['source_kind']='human_physical_measurement';self.doc['asset_source']['sha256']='0'*64
        with self.assertRaises(ValueError):self.run_analysis()

    def test_empty_nonfinite_or_insufficient_trials_rejected(self):
        for trials in ([],[.8,.9],[.8,.9,float('nan')]):
            self.doc['records'][0]['trials']=trials
            with self.assertRaises(ValueError):self.run_analysis()

    def test_sliding_fit_uses_only_moving_segment_and_records_assumptions(self):
        times=[0,.1,.2,.3,.4]
        record=dict(kind='horizontal_sliding_friction',contact_pair=['fixture A','fixture B'],gravity_m_s2=9.81,measured_plane_tilt_deg=0.,
            assumptions=dict(released_no_applied_force=True,translation_without_rolling=True,constant_normal_load=True,same_contact_material_pair=True),
            trials=[dict(time_s=times,speed_m_s=[2.-mu*9.81*t for t in times]) for mu in (.29,.3,.31)])
        self.doc['records']=[record];result=self.run_analysis()
        self.assertAlmostEqual(result['results'][0]['mean'],.3)
        record['trials'][0]['speed_m_s'][-1]=0.
        with self.assertRaises(ValueError):self.run_analysis()

    def test_new_run_ledger_isolated_from_historical_root(self):
        from unittest.mock import patch
        from sage.experiments.embodied_scene_v2.config import ledger
        historical=self.root/'historical';current=self.root/'current'
        with patch('sage.experiments.embodied_scene_v2.config.ROOT',historical):
            ledger(dict(event='synthetic_isolation_fixture'),root=current)
        self.assertTrue((current/'CASE_LEDGER.jsonl').exists())
        self.assertFalse(historical.exists())
