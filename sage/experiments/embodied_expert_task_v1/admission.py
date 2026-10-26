"""Separate source provenance, replay fidelity, and completed-task evidence."""


def review_release(manifest, requested_task):
    rows = manifest.get("tasks", [])
    row = next((r for r in rows if requested_task in (r.get("task"), r.get("environment"))), None)
    if row is None:
        return {"completed_physical_reference": False, "reason": "requested_task_absent"}
    state_only = manifest.get("mode") == "recorded-state"
    physics = bool(row.get("physics_fidelity", False)) and not state_only
    task = (bool(row.get("final_success", False)) and row.get("success_steps", 0) > 0) if state_only else (bool(row.get("task_success_ever", False)) and bool(row.get("final_task_success", False)))
    completed = physics and task
    reason = ("state_visualization_requires_physical_validation" if state_only else
              "source_task_not_completed" if not task else
              "physics_fidelity_not_verified" if not physics else
              "independent_quality_and_project_task_checks_still_required")
    return {"completed_physical_reference": completed, "reason": reason,
            "physics_fidelity_claimed": physics, "task_completion_claimed": task,
            "qualified_fb2_episodes": 0, "inherits_project_acceptance": False}
