"""Traceable physical parameter inventory and explicit calibration gaps, no stepping."""
import sys
import xml.etree.ElementTree as ET
import numpy as np
import mujoco
from .work import E,R,P,finish,c
source=R/'shared/target/MODEL.xml';root=ET.parse(source).getroot();m=mujoco.MjModel.from_xml_path(str(source))
obj=m.body('red_block').id;robot=m.body('base').id
object_xml=root.find(".//body[@name='red_block']")
objects=[]
for g in object_xml.findall('geom'):
 gid=m.geom(g.get('name')).id;s=m.geom_size[gid]
 volume=float(np.pi*s[0]**2*2*s[1] if g.get('type')=='cylinder' else 8*np.prod(s))
 objects.append({'name':g.get('name'),'source_XML':g.attrib,'volume_m3':volume,'density_kg_m3':float(g.get('density')),'component_mass_kg':volume*float(g.get('density')),'contact_friction':m.geom_friction[gid].tolist(),'solref':m.geom_solref[gid].tolist(),'solimp':m.geom_solimp[gid].tolist()})
assert abs(sum(x['component_mass_kg'] for x in objects)-m.body_mass[obj])<1e-12
joints=[]
for a in range(m.nu):
 j=int(m.actuator_trnid[a,0]);name=m.joint(j).name
 joints.append({'joint':name,'control_unit':'rad_position' if m.actuator_biasprm[a,1]!=0 else 'Nm_torque','ctrlrange':m.actuator_ctrlrange[a].tolist(),'forcerange':m.actuator_forcerange[a].tolist(),'gainprm':m.actuator_gainprm[a].tolist(),'biasprm':m.actuator_biasprm[a].tolist(),'joint_range_rad':m.jnt_range[j].tolist(),'armature':float(m.dof_armature[m.jnt_dofadr[j]]),'damping':float(m.dof_damping[m.jnt_dofadr[j]])})
materials=[]
for name in ['ground','table_top','table_white_top','red_cylinder','left_hand_thumb_2_link_col','right_hand_thumb_2_link_col']:
 g=m.geom(name).id;materials.append({'geom':name,'friction':m.geom_friction[g].tolist(),'solref':m.geom_solref[g].tolist(),'solimp':m.geom_solimp[g].tolist(),'condim':int(m.geom_condim[g]),'parameter_source':'bound XML/model','empirical_calibration_found':False})
old_protocol=c.read(P/'repair_v2/CALIBRATION_PROTOCOL.json');qa=c.read(E/'reports/C_development_01r_RECORDED_QUALITY.json')
report={'physics_steps':0,'source_model_sha256':c.sha(source),'object_mass_kg':float(m.body_mass[obj]),'object_inertia_kg_m2':m.body_inertia[obj].tolist(),
        'object_components':objects,'component_mass_sum_matches_compiled_mass':True,'composite_geometry_note':'Cylinder and box caps form declared compound body; density is heterogeneous, overlapping regions use additive component mass, as source specifies.',
        'material_color_is_not_calibration':'red_plastic names a visual material; source densities100/10kg/m3 and friction3 remain inherited uncalibrated model parameters.',
        'robot_total_mass_kg':float(m.body_subtreemass[robot]),'contact_parameters':materials,'actuator_contract':joints,'integrator':int(m.opt.integrator),'dt_s':float(m.opt.timestep),
        'solver':int(m.opt.solver),'solver_iterations':int(m.opt.iterations),'solver_tolerance':float(m.opt.tolerance),'cone':int(m.opt.cone),'impratio':float(m.opt.impratio),
        'calibration_protocol_source_sha256':c.sha(P/'repair_v2/CALIBRATION_PROTOCOL.json'),'retained_numerical_thresholds':old_protocol['thresholds'],
        'required_current_timestep_windows':[{'label':'current','dt':.0025,'iteration_multiplier':1},{'label':'half_step','dt':.00125,'iteration_multiplier':1},{'label':'quarter_step','dt':.000625,'iteration_multiplier':1},{'label':'double_solver','dt':.0025,'iteration_multiplier':2}],
        'measured_log_peak_contact_force_N':qa['metrics']['max_contact_force_N'],'force_acceptance_threshold_N':None,'impulse_acceptance_threshold_Ns':None,
        'known_missing_evidence':['independent payload mass/inertia calibration for this specific object','friction/material/contact compliance physical justification','force and transient acceptance thresholds tied to this model','current-step and solver convergence for qualified contact sequence'],
        'no_guessed_force_thresholds':True,'research_observation_allowed':True,'production_physics_calibrated':False,'production_accepted':False}
c.write(E/'PHYSICAL_PARAMETER_EVIDENCE.json',report);finish(report)
