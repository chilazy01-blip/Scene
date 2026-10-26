"""Shared, explicitly logged interface repairs for the existing C and D methods."""
import numpy as np
from .leg_interpolation import LegInterpolation
from .work import c

def install(config):
 import run,instrument
 from ik import sim
 initial=c.read(config['interpolation_initial_targets'])['leg_position_targets_rad']
 calibration=c.read(config['archived_grasp_calibration'])
 offset=np.asarray(calibration['local_centroid_m'],float)
 old_apply=run.G1Controller.apply_pd_control
 def apply(ctrl,target):
  if not hasattr(ctrl,'_contact_leg_interpolation'):
   ids=[ctrl.joint_names.index(n) for n in initial]
   memory=np.asarray(target).copy()
   for n,x in initial.items():memory[ctrl.joint_names.index(n)]=x
   ctrl._contact_leg_interpolation=LegInterpolation(ids,config.get('interpolation_substeps',8))
   ctrl._contact_leg_interpolation.apply(memory)
  applied=ctrl._contact_leg_interpolation.apply(target)
  tr=instrument.ACTIVE_TRACE
  if tr is not None:
   tr.append('interpolation/requested',target);tr.append('interpolation/applied',applied)
  return old_apply(ctrl,applied)
 run.G1Controller.apply_pd_control=apply
 old_overlay=run.G1Controller.arm_overlay
 def overlay(ctrl,target,proj_gravity=None):
  result=old_overlay(ctrl,target,proj_gravity)
  if not ctrl.reach_active and ctrl.frozen_arm_pos is None:
   result[ctrl.joint_names.index(config['stow_joint'])]+=config['stow_offset_rad']
  return result
 run.G1Controller.arm_overlay=overlay
 def archived_center(runner):
  tr=instrument.ACTIVE_TRACE
  if tr is not None:
   tr.append('calibration/physics_row',tr.n);tr.append('calibration/local_centroid_m',offset)
  return offset.copy()
 sim.Runner.grasp_center_offset=archived_center
 return {'leg_interpolation_seconds':config.get('interpolation_substeps',8)*.0025,
         'stow_joint':config['stow_joint'],'stow_offset_rad':config['stow_offset_rad'],
         'archived_grasp_calibration':config['archived_grasp_calibration'],
         'current_plant_gains_limits_unchanged':True,'runtime_state_writes':False,
         'method_failure_lineages_unchanged':True}
