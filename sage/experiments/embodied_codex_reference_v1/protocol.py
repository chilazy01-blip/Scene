"""Fresh pilot authorization and a locked ledger; historical evidence stays frozen."""
import fcntl
import importlib
from pathlib import Path
import time

from sage.experiments.embodied_native_sonic_grasp_feedback_v1.protocol import project_target
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save


def check(binding):
    if _file_binding(Path(binding["path"])) != binding:
        raise ValueError("changed frozen dependency: " + binding["path"])


def authorize(root):
    p = read_bound_json(Path(root) / "PROTOCOL.json")
    for key in ("authorization", "plan", "case", "scene", "reference", "prefix_report", "prefix_trace", "prefix_io"):
        check(p[key])
    for binding in [*p["inputs"].values(), *p["dependencies"].values()]:
        check(binding)
    auth = read_bound_json(Path(p["authorization"]["path"]))
    assert auth["user_authorized_trial"] is True
    assert p["prior_native_steps"] == auth["prior_native_steps"] == 84564
    assert p["deadline_epoch_utc"] == auth["deadline_epoch_utc"]
    assert p["max_new_physics_steps"] == auth["max_new_physics_steps"] == 52000
    assert p["solver_schedule"] == {"activation_step": 3960, "noslip_iterations": 3}
    assert p["task_module"] == "sage.experiments.embodied_codex_reference_v1.task"
    return p


def spent_steps(ledger):
    return sum(read_bound_json(Path(x["output"]) / "REPORT.json")["physics_steps"]
               if (Path(x["output"]) / "REPORT.json").exists() else x["maximum_steps"]
               for x in ledger["reservations"])


def reserve(root, output, ceiling):
    p = authorize(root)
    if time.time() >= p["deadline_epoch_utc"]:
        raise RuntimeError("pilot physics deadline reached")
    ledger_root = Path(p["ledger_root"])
    with (ledger_root / "COST.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        ledger = read_bound_json(ledger_root / "COST.json")
        replay = output.name.startswith("continuous_replay")
        charged = output if replay else output.parent / "cost"
        assert not any(x["output"] == str(charged) for x in ledger["reservations"])
        assert 0 < ceiling <= 40 + 4 * p["full_ticks"]
        maximum = ceiling if replay else ceiling - p["prefix_physics_steps"]
        headroom = 0 if replay else ceiling
        if spent_steps(ledger) + maximum + headroom > p["max_new_physics_steps"]:
            raise RuntimeError("insufficient pilot budget including full success replay")
        ledger["reservations"].append(dict(output=str(charged), maximum_steps=maximum,
                                         episode_output=str(output), success_replay_headroom=headroom))
        safe_save(ledger_root / "COST.json", ledger)


def make_task(p, *args):
    return importlib.import_module(p["task_module"]).Task(*args)
