"""Retain one complete curve basis while opening all phases for condition repair.

The template is a source of active-joint references and progress only. Robot
root/body/object states, tracking residuals, goals and contacts must come from
and be independently audited in the actual condition. This creates no success.
"""
import copy

def all_phase_plan(nominal_plan):
    plan=copy.deepcopy(nominal_plan)
    if plan.get('phase_count')!=15 or len(plan.get('inserted_knots',[]))!=15:
        raise ValueError('original_complete_phase_template_required')
    plan['template_original_failed_phases']=plan['failed_phases']
    plan['failed_phases']=list(range(15))
    plan['active_phases']=list(range(15))
    plan['selection']='fixed qualified whole nominal basis, all condition-adaptation phases free; no phase splicing'
    return plan
