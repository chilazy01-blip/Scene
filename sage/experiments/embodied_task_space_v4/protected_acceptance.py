"""Compare full aligned contact fields before task-error improvements."""
import numpy as np


def accept_step(before, after, hard_residual, tolerance=1e-10):
    old = np.asarray(before["raw"], dtype=float)
    new = np.asarray(after["raw"], dtype=float)
    if old.shape != new.shape or old.ndim != 3 or old.shape[0] != 2 or old.shape[2] != 5:
        raise ValueError("unaligned_current_and_stopping_contact_fields")
    if not np.isfinite(old).all() or not np.isfinite(new).all() or np.any(old < 0) or np.any(new < 0):
        raise ValueError("invalid_contact_measurements")
    previous = before["meta"]["phases"]
    candidate = after["meta"]["phases"]
    if [p["stage"] for p in previous] != [p["stage"] for p in candidate]:
        raise ValueError("phase_identity_changed")
    if not np.isfinite(hard_residual) or hard_residual > 1e-8:
        return dict(accepted=False, reason="original_hard_rows_failed")
    regressions = np.argwhere(new > old + tolerance)
    lost = [p["stage"] for p, q in zip(previous, candidate) if p["passed"] and not q["passed"]]
    if len(regressions) or lost:
        return dict(accepted=False, reason="protected_contact_or_phase_regression", regressed_components=len(regressions),examples=regressions[:10].tolist(),lost_phases=lost)
    old_contact = float(np.sum(old*old)/old.shape[1])
    new_contact = float(np.sum(new*new)/new.shape[1])
    old_task = np.asarray(before["ends"],float)
    new_task = np.asarray(after["ends"],float)
    if old_task.shape != new_task.shape or not np.isfinite(old_task).all() or not np.isfinite(new_task).all() or np.any(old_task < 0) or np.any(new_task < 0):
        raise ValueError("invalid_endpoint_measurements")
    contact_improvement = old_contact-new_contact
    endpoint_improvement = float(np.sum(old_task*old_task)-np.sum(new_task*new_task))
    accepted = bool(after["meta"]["passed"] or contact_improvement > tolerance or (contact_improvement >= -tolerance and endpoint_improvement > tolerance))
    return dict(accepted=accepted,reason="protected_feasibility_progress" if accepted else "no_feasibility_progress",contact_reduction=contact_improvement,endpoint_reduction=endpoint_improvement,lost_phases=[])
