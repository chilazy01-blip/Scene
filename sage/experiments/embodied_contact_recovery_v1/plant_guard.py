"""Enforce fixed physical parameters after the first dynamic state is recorded."""
import hashlib
import numpy as np

FIELDS=('body_mass body_inertia body_ipos body_iquat body_pos body_quat '
        'jnt_type jnt_pos jnt_axis jnt_range jnt_limited jnt_stiffness '
        'dof_armature dof_damping dof_frictionloss dof_solref dof_solimp '
        'geom_pos geom_quat geom_size geom_type geom_contype geom_conaffinity '
        'geom_friction geom_solref geom_solimp geom_margin geom_gap '
        'actuator_trnid actuator_trntype actuator_dyntype actuator_gaintype '
        'actuator_biastype actuator_dynprm actuator_gainprm actuator_biasprm '
        'actuator_gear actuator_ctrlrange actuator_forcerange actuator_actrange '
        'actuator_ctrllimited actuator_forcelimited actuator_actlimited '
        'pair_solref pair_solimp pair_friction exclude_signature').split()
OPTIONS=('timestep gravity wind density viscosity integrator solver iterations '
         'tolerance noslip_iterations noslip_tolerance cone impratio '
         'disableflags enableflags').split()

class PlantGuard:
 def __init__(self,model):
  self.fields={n:np.array(getattr(model,n),copy=True) for n in FIELDS}
  self.options={n:np.array(getattr(model.opt,n),copy=True) for n in OPTIONS}
  self.checks=0
  h=hashlib.sha256()
  for group in [self.fields,self.options]:
   for n,v in group.items():h.update(n.encode());h.update(v.tobytes())
  self.sha256=h.hexdigest()
 def check(self,model):
  for obj,group in [(model,self.fields),(model.opt,self.options)]:
   for name,value in group.items():
    assert np.array_equal(getattr(obj,name),value),'runtime_plant_mutation:'+name
  self.checks+=1
