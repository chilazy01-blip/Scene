import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from ..digit_corridor import digit_closure_corridor
from ..geometry import closure_corridor
from ..force_gate import DiagnosticForceEnvelope
from ..intent import GraspRejected
from ..stepping import IntegrationContract
from ..aligned_controller import AlignedGraspController
from ..controller import GraspController
from ...repair_v2.progress import ControlRejected
from ...repair_v2.quality import QualityContract,support_window


class ContactMaskFixture:
    def __init__(self):
        self.qmap=np.arange(3);self.movers=np.array([0,2,3])
        self.c={'inspection':{'groups':{'left_hand':[2],'right_hand':[0,1]}}}
        self.names=['gripper0_right_right_hand_index_0_link_col','box','gripper0_right_right_hand_middle_0_link_col','gripper0_left_left_hand_thumb_0_link_col']
        self.roles=['hand','object','hand','hand']
        self.m=SimpleNamespace(jnt_qposadr=np.arange(3),joint=lambda i:SimpleNamespace(name=['right_hand_index_0','right_hand_middle_0','left_hand_thumb_0'][i]))
        self.d=SimpleNamespace(contact=[SimpleNamespace(geom1=0,geom2=1,dist=-.0001)])
    def set(self,q):self.q=np.asarray(q)
    def clearance(self,*args):
        gap=.002 if self.q[1]>.2 else .03
        return dict(passed=gap>=.003,minimum_clearance=gap,max_penetration=.0001,forbidden=[])


class NumericalRepairTests(unittest.TestCase):
    def test_other_digit_contact_cannot_hide_middle_collision(self):
        q=ContactMaskFixture();start=np.zeros(3);ids=np.array([2,0,1]);targets=np.array([0.,0.,.5])
        self.assertTrue(closure_corridor(q,start,targets,ids)['passed'])
        result=digit_closure_corridor(q,start,targets,ids,moving_only=False)
        self.assertFalse(result['passed']);self.assertEqual(result['digit'],'middle')

    def report(self,dt=.0025):
        return dict(passed=True,production_calibrated=False,candidate_timestep=dt,
                    proposed_diagnostic_limits={s:dict(peak_normal_N=10.,maximum_40ms_impulse_Ns=.3) for s in ('left','right')})
    def row(self,index,force=2.,dt=.0025):
        return dict(time=index*dt,dt=dt,force_semantics='integrated_step_world_force',hand_forces={s:dict(normal_force=force) for s in ('left','right')})
    def test_force_window_retains_full_40ms_at_finer_step(self):
        gate=DiagnosticForceEnvelope(self.report())
        for i in range(15):self.assertFalse(gate.observe(self.row(i)))
        self.assertTrue(gate.observe(self.row(15)));self.assertFalse(gate.production_eligible)
    def test_force_peak_and_impulse_independent(self):
        gate=DiagnosticForceEnvelope(self.report())
        with self.assertRaisesRegex(GraspRejected,'force_envelope'):gate.observe(self.row(0,11.))
        gate=DiagnosticForceEnvelope(self.report())
        with self.assertRaisesRegex(GraspRejected,'force_envelope'):
            for i in range(16):gate.observe(self.row(i,9.))
    def test_failed_numerics_and_stale_observations_remain_closed(self):
        report=self.report();report['passed']=False
        with self.assertRaisesRegex(GraspRejected,'numerical_admission'):DiagnosticForceEnvelope(report)
        gate=DiagnosticForceEnvelope(self.report());gate.observe(self.row(0))
        with self.assertRaisesRegex(GraspRejected,'stale'):gate.observe(self.row(0))
    def test_timing_maps_all_substeps_to_original_command_period(self):
        for dt in [.005,.0025]:
            timing=IntegrationContract(timestep=dt)
            for command in range(3):
                indices=range(timing.first_step(command),timing.first_step(command+1))
                self.assertEqual({timing.command_index(i) for i in indices},{command})
                self.assertAlmostEqual(len(indices)*dt,.02)
        self.assertEqual(IntegrationContract().reserve(4200),dict(task_and_replay_steps=67200,wbc_and_recompute=8400))

    def test_parent_contact_transition_does_not_bypass_load_gate(self):
        controller=object.__new__(AlignedGraspController);controller.phase='pick';controller.grasp_report=None
        def premature_transition(self,*args):
            self.phase='carry';return {},{}
        with patch.object(GraspController,'target',premature_transition):
            with self.assertRaisesRegex(ControlRejected,'load_transfer_required'):controller.target(None)

    def test_finer_step_support_still_requires_one_second(self):
        contract=QualityContract(dt=.0025)
        row=dict(bottom_margin=.01,com_margin=.02,board_vertical_load=2.,weight=2.,force_residual=0.,other_support_load=0.,hand_contacts=0,object_linear=0.,object_angular=0.)
        samples=[dict(row,time=i*.0025) for i in range(400)]
        self.assertFalse(support_window(samples[:200],contract)['passed'])
        self.assertTrue(support_window(samples,contract)['passed'])


if __name__=='__main__':unittest.main()
