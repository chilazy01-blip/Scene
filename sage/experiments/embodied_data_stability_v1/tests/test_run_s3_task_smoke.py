from sage.experiments.embodied_data_stability_v1.neutral_adapter import TASK_PHASES
from sage.experiments.embodied_data_stability_v1.run_s3_task_smoke import phase_gate


def test_phase_gate_requires_exact_order():
    events = [
        {"phase": phase, "sim_time_s": float(index), "source_event": "report:test"}
        for index, phase in enumerate(TASK_PHASES)
    ]
    assert phase_gate(events)["all_phases_present_once"]
    events[2], events[3] = events[3], events[2]
    assert not phase_gate(events)["all_phases_present_once"]


def test_phase_gate_rejects_timer_only_phase_evidence():
    events = [
        {"phase": phase, "sim_time_s": float(index), "source_event": "report:test"}
        for index, phase in enumerate(TASK_PHASES)
    ]
    events[4]["source_event"] = "timer:carry"
    assert not phase_gate(events)["state_or_contact_driven"]
