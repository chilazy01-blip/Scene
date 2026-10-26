"""Stop is an unannounced event at tick40, never in earlier encoder windows."""

from .sonic_slow_walk_paced_transition import build_transition_reference as walking
from .sonic_walk_stop_transition import build_transition_reference as stopping


def build_transition_reference(planner, **kwargs):
    reference, metadata, velocity = walking(planner, **kwargs)
    metadata.update(
        {
            "stop_command_frame": 40,
            "stop_command_time_s": 0.8,
            "stop_mode": 0,
            "stop_preview_protocol": "event_causal_not_announced_before_tick40",
        }
    )
    return reference, metadata, velocity


def build_stop_reference(planner):
    # Precomputation saves runtime, but these values are inaccessible to the
    # encoder before the event. Both plans have the same pre-event prefix.
    reference, _, velocity = stopping(planner)
    return reference, velocity
