"""Record the explicit user confirmation without changing the reviewed environment."""

import argparse
from pathlib import Path
from .preflight import authorize
from .motion_gate import require_environment_confirmation
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def approve(root, message):
    authorize(root)
    output = root / "ENVIRONMENT_APPROVAL.json"
    if output.exists():
        raise FileExistsError(output)
    if message != "可以就先按这个环境吧":
        raise ValueError(
            "this recorder is for the actual explicit user message in this turn only"
        )
    save(
        output,
        {
            "schema": "native-environment-user-approval/v1",
            "decision": "approved",
            "source": "explicit_user_environment_confirmation",
            "user_message": message,
            "scene": _file_binding(root / "model/SCENE.json"),
            "preview": _file_binding(root / "environment_preview_r2/MANIFEST.json"),
            "plan": _file_binding(root / "PLAN.json"),
            "implementation": _file_binding(Path(__file__)),
            "physics_steps": 0,
            "scope": "confirmed displayed original generated environment, now proceed with bounded standing/walking goal; no layout/model changes or new props",
        },
    )
    require_environment_confirmation(root)
    print(
        {
            "environment_confirmed": True,
            "scene_unchanged": True,
            "separate_dynamic_protocol_still_required": True,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--message", required=True)
    a = p.parse_args()
    approve(a.root, a.message)
