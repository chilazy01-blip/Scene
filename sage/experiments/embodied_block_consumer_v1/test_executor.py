import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
import numpy as np
from .executor import ActionBlockExecutor,canonical_contract,validate_contract,validate_block

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.contract=canonical_contract();self.ranges=np.tile([-3.,3.],(7,1));self.block=np.zeros((50,15),dtype=np.float64);self.block[:,14]=.02
    def test_valid_block_preserves_values_and_copies(self):
        self.block[:,7:14]=np.arange(7)/10;value=validate_block(self.block,self.contract,self.ranges)
        np.testing.assert_array_equal(value,self.block);self.assertFalse(np.shares_memory(value,self.block))
    def test_legacy_vector_rejected(self):
        with self.assertRaisesRegex(ValueError,'action_shape_or_dtype'):validate_block(np.zeros(8),self.contract,self.ranges)
    def test_missing_velocity_block_rejected(self):
        with self.assertRaisesRegex(ValueError,'action_shape_or_dtype'):validate_block(np.zeros((50,8)),self.contract,self.ranges)
    def test_implicit_float32_conversion_rejected(self):
        with self.assertRaisesRegex(ValueError,'action_shape_or_dtype'):validate_block(self.block.astype(np.float32),self.contract,self.ranges)
    def test_nonfinite_velocity_rejected(self):
        self.block[10,7]=np.nan
        with self.assertRaisesRegex(ValueError,'nonfinite_action'):validate_block(self.block,self.contract,self.ranges)
    def test_position_out_of_range_rejected(self):
        self.block[20,3]=4.
        with self.assertRaisesRegex(ValueError,'joint_position_range'):validate_block(self.block,self.contract,self.ranges)
    def test_gripper_out_of_range_rejected(self):
        self.block[40,14]=-.01
        with self.assertRaisesRegex(ValueError,'gripper_range'):validate_block(self.block,self.contract,self.ranges)
    def test_wrong_units_rejected(self):
        self.contract['velocity_unit']='deg/s'
        with self.assertRaisesRegex(ValueError,'action_contract_changed'):validate_contract(self.contract)
    def test_wrong_timestep_rejected(self):
        self.contract['substep_dt_s']=.01
        with self.assertRaisesRegex(ValueError,'action_contract_changed'):validate_contract(self.contract)
    def test_wrong_joint_order_rejected(self):
        self.contract['joint_order'].reverse()
        with self.assertRaisesRegex(ValueError,'action_contract_changed'):validate_contract(self.contract)
    def executor(self):
        e=object.__new__(ActionBlockExecutor);e.contract=self.contract;e.joint_ranges=self.ranges;e.failed=False;e.steps=0;e.blocks=0;e.origin=0.;e.max_steps=17500
        e.data=SimpleNamespace(time=0.);e.model=SimpleNamespace(opt=SimpleNamespace(timestep=.001));e.controller=Mock();return e
    def test_bad_last_substep_rejected_before_any_control_or_step(self):
        e=self.executor();self.block[-1,14]=.041
        with patch('mujoco.mj_step') as integrate:
            with self.assertRaisesRegex(ValueError,'gripper_range'):e.step(self.block,block_index=0,start_time=0.)
            integrate.assert_not_called();e.controller.action.assert_not_called();self.assertEqual(e.steps,0)
    def test_wrong_block_sequence_rejected(self):
        e=self.executor()
        with self.assertRaisesRegex(ValueError,'block_order'):e.step(self.block,block_index=1,start_time=0.)
        e.controller.action.assert_not_called()
    def test_wrong_start_time_rejected(self):
        e=self.executor()
        with self.assertRaisesRegex(ValueError,'block_start_time'):e.step(self.block,block_index=0,start_time=.001)
        e.controller.action.assert_not_called()
