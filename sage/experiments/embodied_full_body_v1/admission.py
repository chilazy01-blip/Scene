"""Reject partial static coverage before a future full-task experiment.

Coverage is necessary, not sufficient: collision checks also need actual
geometry, declared base-pose uncertainty and the controller's action semantics.
Historical runtime traces cannot be relabelled as prospective static evidence.
"""


def require_full_command_coverage(expected_ticks, checked_ticks):
    expected = list(expected_ticks)
    checked = list(checked_ticks)
    if not expected or expected != list(range(len(expected))):
        raise ValueError("expected_ticks_must_start_at_zero_and_be_consecutive")
    if any(type(tick) is not int for tick in checked):
        raise ValueError("integer_ticks_required")
    if len(set(checked)) != len(checked):
        raise ValueError("duplicate_coverage_tick")
    missing = sorted(set(expected) - set(checked))
    extra = sorted(set(checked) - set(expected))
    if missing or extra:
        raise ValueError(f"incomplete_command_coverage: missing={len(missing)}, extra={len(extra)}")
    return len(checked)
