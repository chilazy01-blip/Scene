"""One explicit native task definition shared by subtasks and success criteria."""
from dataclasses import dataclass, asdict
from types import MethodType
import copy
import numpy as np
import mujoco


@dataclass(frozen=True)
class TaskContract:
    task_id: str = 'native_g1_box_to_board1_seed111_repair_v1'
    object_name: str = 'box'
    target_name: str = 'shelf_board_1'
    minimum_up_dot: float = 0.95
    box_mass_kg: float = 0.0135206
    parameter_origin: str = 'fixed_upstream_synthetic_parameters_not_measured_real_asset'
    original_demo_environment_fidelity: bool = False


def bind_task_contract(base, contract=TaskContract()):
    from humanoidmimicgen.locomanipulation.utils.scene.success_criteria import (
        AllCriteria, IsStatic, IsUpright, IsInContact)
    obj=getattr(base,contract.object_name);target=getattr(base,contract.target_name)
    original_config=copy.deepcopy(base.task_config())
    config=copy.deepcopy(original_config)
    for task in config.values():
        for subtask in task.values():
            if subtask.get('object_ref','').startswith('shelf_board_'):
                subtask['object_ref']=contract.target_name
    original_objects=base.get_object()
    objects={k:v for k,v in original_objects.items() if not k.startswith('shelf_board_')}
    objects[contract.target_name]=dict(obj_name=target.mj_obj.root_body,obj_type='body')
    criteria=AllCriteria(IsStatic(obj),IsUpright(obj,threshold=contract.minimum_up_dot),IsInContact(obj,target))
    base.task_config=MethodType(lambda self:copy.deepcopy(config),base)
    base.get_object=MethodType(lambda self:copy.deepcopy(objects),base)
    base._get_success_criteria=MethodType(lambda self:criteria,base)
    base._check_success=MethodType(lambda self:bool(criteria.is_true(self)),base)
    refs={sub['object_ref'] for task in base.task_config().values() for sub in task.values()}
    assert refs=={contract.object_name,contract.target_name}
    assert criteria.criteria[-1]._obj_b is target
    return dict(contract=asdict(contract),previous_subtasks=original_config,
                current_subtasks=base.task_config(),exposed_objects=base.get_object(),
                success_contact_target=contract.target_name,bindings_consistent=True)


def validate_assets(model,contract=TaskContract()):
    rows=[]
    for b in range(model.nbody):
        name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,b) or ''
        if name.startswith('box_'):
            inertia=model.body_inertia[b]
            if model.body_mass[b]<=0 or np.any(inertia<=0):raise ValueError('invalid_box_inertia')
            if np.max(inertia)>np.sum(inertia)-np.max(inertia)+1e-12:raise ValueError('nonphysical_principal_inertia')
            rows.append(dict(body=name,mass=float(model.body_mass[b]),inertia=inertia.tolist()))
    total=sum(row['mass'] for row in rows)
    if abs(total-contract.box_mass_kg)>1e-8:raise ValueError('unapproved_box_mass_change')
    return dict(passed=True,body_properties=rows,total_box_mass_kg=total,
                physical_realism_calibrated=False,parameter_origin=contract.parameter_origin,
                scope='internal model validity and declared synthetic identity; not real-world calibration')
