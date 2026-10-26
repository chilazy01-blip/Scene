"""Preserve the source WBC torso intent separately from measured waist angles."""
import numpy as np
from sage.experiments.embodied_expert_task_v5.phase_controller_r2 import PhaseController as ApproachController
from sage.experiments.embodied_expert_task_v3.phase_reference_r2 import interpolate

class PhaseController(ApproachController):
    def targets(self,actual_q,advance=True):
        goal,command,diag=super().targets(actual_q,advance=advance)
        indices=self.groups['upper_body'];waist=sorted(set(indices)&set(self.groups['lower_body']));columns=[indices.index(j) for j in waist]
        prior=goal['target_upper_body_pose'][columns].copy();source=interpolate(self.inputs['upper'],min(self.progress.phase,920.))
        goal['target_upper_body_pose'][columns]=source[columns]
        diag['native_torso_intent']=dict(source_phase=min(self.progress.phase,920.),pin_indices=waist,source_upper_columns=columns,source_values=source[columns].copy(),replaced_joint_angle_values=prior,semantics='native WBC torso orientation intent; overwritten by learned lower-body joint outputs, not applied as waist joint positions')
        diag['goal']=goal
        return goal,command,diag
