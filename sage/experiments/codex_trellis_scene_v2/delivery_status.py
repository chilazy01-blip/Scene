"""Single machine definition of Scene V2 run completion and deliverability."""

from __future__ import annotations

from typing import Any


PROFILE_REQUIREMENTS = {
    "plan": (
        "scene_brief",
        "architecture",
        "typed_scene_graph",
        "asset_plan",
        "layout",
        "layout_validation",
    ),
    "development": (
        "scene_brief",
        "architecture",
        "typed_scene_graph",
        "asset_plan",
        "layout",
        "layout_validation",
    ),
    "production": (
        "scene_brief",
        "architecture",
        "typed_scene_graph",
        "asset_plan",
        "assets_ready_and_qa",
        "layout",
        "layout_validation",
        "relation_geometry",
        "blender_assembly",
        "final_multichannel_render",
        "structural_performance_check",
        "final_hash_audit",
    ),
    "benchmark": (
        "scene_brief",
        "architecture",
        "typed_scene_graph",
        "asset_plan",
        "layout",
        "layout_validation",
        "benchmark_metrics",
    ),
}


def evaluate_terminal_status(profile: str, stages: dict[str, bool]) -> dict[str, Any]:
    if profile not in PROFILE_REQUIREMENTS:
        raise ValueError(f"unknown run profile: {profile}")
    required = PROFILE_REQUIREMENTS[profile]
    missing = [stage for stage in required if not bool(stages.get(stage))]
    complete = not missing
    deliverable = bool(profile == "production" and complete)
    if deliverable:
        terminal_status = "production_deliverable"
    elif complete:
        terminal_status = f"{profile}_complete_non_deliverable"
    else:
        terminal_status = "diagnostic_failure_preserved"
    return {
        "schema": "scene-v2-terminal-status/v1",
        "profile": profile,
        "terminal_status": terminal_status,
        "deliverable": deliverable,
        "profile_complete": complete,
        "required_stages": list(required),
        "missing_required_stages": missing,
        "stages": {key: bool(value) for key, value in sorted(stages.items())},
    }


def apply_profile_defaults(args: Any) -> None:
    profile = str(getattr(args, "profile", "development"))
    if profile == "production":
        if str(args.asset_mode) == "plan":
            raise ValueError("production profile forbids --asset-mode=plan")
        args.assemble = True
        args.render_preview = True
        args.scene_render_acceptance = True
        args.mujoco_check = True
        args.allow_invalid = False
        args.allow_render_acceptance_failure = False
