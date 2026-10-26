"""New physical identity, renewed admission, unchanged task acceptance gates."""

import argparse
from pathlib import Path
import time
import xml.etree.ElementTree as ET
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def prepare(root, parent, diagnostic, qualification=None):
    import mujoco

    if root.exists():
        raise FileExistsError(root)
    result = read_bound_json(diagnostic / "DIAGNOSTIC_RESULT.json")
    equiv = read_bound_json(diagnostic / "KINEMATICS_EQUIVALENCE.json")
    if result["selected_profile"] != "multiccd" or not equiv["passed"]:
        raise ValueError("no justified configuration")
    mode = "full_transport" if qualification else "standing_pick_place"
    if qualification:
        q = read_bound_json(qualification / "AUDIT.json")
        if not q["task_passed"] or q["task_mode"] != "standing_pick_place":
            raise ValueError("standing pickup/place not qualified")
    model_dir = root / "model"
    model_dir.mkdir(parents=True)
    scene = read_bound_json(parent / "model/SCENE.json")
    xml = ET.parse(scene["model"]["path"]).getroot()
    option = xml.find("option")
    if option is None:
        option = ET.SubElement(xml, "option")
    flag = option.find("flag")
    if flag is None:
        flag = ET.SubElement(option, "flag")
    flag.set("multiccd", "enable")
    target = [1.85 if qualification else 1.60, 2.45, 0.86]
    xml.find(".//body[@name='task_target']").set("pos", f"{target[0]} {target[1]} 0")
    path = model_dir / "model.xml"
    path.write_text(ET.tostring(xml, encoding="unicode"))
    m = mujoco.MjModel.from_xml_path(str(path))
    assert int(m.opt.enableflags) == 16 and int(m.opt.cone) == 0
    assert (m.nq, m.nv, m.nu, m.neq, m.nmocap) == (57, 55, 43, 0, 0)
    scene.update(
        model=_file_binding(path),
        parent_scene=_file_binding(parent / "model/SCENE.json"),
        implementation=_file_binding(Path(__file__)),
        declared_contact_change="native MULTICCD enabled; geometry/mass/friction/solver/integrator unchanged",
    )
    scene["task_fixtures"]["target"]["center_m"] = target
    save(model_dir / "SCENE.json", scene)
    case = read_bound_json(parent / "CASE.json")
    start = [0.85, 2.8] if qualification else [1.31, 2.77]
    case.update(
        task_mode=mode,
        protocol_root=str(root),
        model_path=str(path),
        scene_manifest_path=str(model_dir / "SCENE.json"),
        scene_manifest=_file_binding(model_dir / "SCENE.json"),
        start_xy_m=start,
        source_root_goal_xy_m=[1.25, 2.8] if qualification else start,
        target_root_goal_xy_m=[1.65, 2.72] if qualification else start,
        goal_xy_m=[1.65, 2.72] if qualification else start,
        target_object_xyz_m=target,
    )
    if qualification:
        case["pickup_place_qualification"] = _file_binding(qualification / "AUDIT.json")
    save(root / "CASE.json", case)
    cert = read_bound_json(parent / "PREFLIGHT_SAFE.json")
    cert.update(
        case=_file_binding(root / "CASE.json"),
        parent_certificate=_file_binding(parent / "PREFLIGHT_SAFE.json"),
        scope="same geometric waypoint; physical contact configuration requalified independently; full approach requires actual state IK and collision guards",
    )
    save(root / "PREFLIGHT_SAFE.json", cert)
    deps = {}
    for package in (
        "embodied_transport_v1",
        "embodied_transport_hybrid_v1",
        "embodied_transport_hybrid_v2",
        "embodied_transport_hybrid_v3",
        "embodied_transport_contact_v1",
    ):
        for p in sorted((Path(__file__).parent.parent / package).glob("*.py")):
            if not p.name.startswith("test"):
                deps[package + "/" + p.name] = _file_binding(p)
    save(
        root / "PROTOCOL.json",
        {
            "schema": "contact-qualified-hybrid-transport/v1",
            "created_utc_timestamp": time.time(),
            "case": _file_binding(root / "CASE.json"),
            "contact_diagnostic": _file_binding(diagnostic / "DIAGNOSTIC_RESULT.json"),
            "fk_equivalence": _file_binding(diagnostic / "KINEMATICS_EQUIVALENCE.json"),
            "qualification": (
                _file_binding(qualification / "AUDIT.json") if qualification else None
            ),
            "finite_stage": "one selected contact configuration, standing qualification then one full continuous case; no identical rejected rerun",
            "active_budgets_ticks": [100, 300, 500, 1000, 1500, 2000],
            "per_process_wall_s": 180,
            "control": "unchanged H3 SONIC22+rightarm7 official PD/effort and declared arm bias; FK evaluator numerically equivalent",
            "unchanged_acceptance": "20mm whole-object source clearance and opposing100substeps; target handfree instantaneous speed<.02m/s/root<.04/up>=.97/pelvis>=.7 for100substeps; full requires both real carry foot cycles and>=.2m object transport",
            "dependencies": deps,
            "parent_dependencies": {},
            "hybrid_parent_dependencies": {},
            "repeat_rejected_identical_case": False,
        },
    )
    print({"prepared": mode, "root": str(root), "native_multiccd": True})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--parent", type=Path, required=True)
    p.add_argument("--diagnostic", type=Path, required=True)
    p.add_argument("--qualification", type=Path)
    a = p.parse_args()
    prepare(a.root, a.parent, a.diagnostic, a.qualification)
