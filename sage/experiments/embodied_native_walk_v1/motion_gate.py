"""Fail closed until the user explicitly confirms the exact displayed environment."""

from pathlib import Path
from .preflight import authorize
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def require_environment_confirmation(root):
    root = Path(root)
    approval = root / "ENVIRONMENT_APPROVAL.json"
    if not approval.is_file():
        raise PermissionError(
            "user has not confirmed the displayed native room; zero motion steps authorized"
        )
    p = authorize(root)
    a = read_bound_json(approval)
    if (
        a.get("decision") != "approved"
        or a.get("source") != "explicit_user_environment_confirmation"
        or not a.get("user_message")
    ):
        raise PermissionError("explicit user environment confirmation required")
    for key, path in (
        ("scene", root / "model/SCENE.json"),
        ("preview", root / "environment_preview_r2/MANIFEST.json"),
        ("plan", root / "PLAN.json"),
    ):
        binding = a.get(key, {})
        if binding.get("path") != str(path) or binding.get("sha256") != sha256_file(
            path
        ):
            raise PermissionError(
                "environment approval does not identify the unchanged displayed room: "
                + key
            )
    if not read_bound_json(root / "STATIC_REVIEW.json")["static_checks_passed"]:
        raise PermissionError("static environment checks failed")
    return {"plan": p, "approval": a}


def require_motion_protocol(root):
    """Future runners call before loading a model/session or creating episode output."""
    root = Path(root)
    approved = require_environment_confirmation(root)
    path = root / "MOTION_PROTOCOL.json"
    if not path.is_file():
        raise PermissionError("separate bounded dynamic protocol has not been frozen")
    p = read_bound_json(path)
    if p.get("environment_approval", {}).get("sha256") != sha256_file(
        root / "ENVIRONMENT_APPROVAL.json"
    ):
        raise PermissionError("dynamic protocol approval binding mismatch")
    limits = approved["plan"]
    if (
        not 0
        < p.get("max_total_physics_steps", 0)
        <= limits["future_max_total_physics_steps"]
    ):
        raise PermissionError("dynamic step budget absent or exceeds approved plan")
    if (
        not 0
        < p.get("max_causal_versions", 0)
        <= limits["future_max_causal_controller_versions"]
    ):
        raise PermissionError("dynamic version budget absent or exceeds approved plan")
    if p.get("conditions") != limits["conditions_to_preflight"]:
        raise PermissionError("three predeclared starting conditions changed")
    dependencies = p.get("dependencies", {})
    if not dependencies:
        raise PermissionError("dynamic implementation/source bindings absent")
    for binding in dependencies.values():
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise PermissionError("dynamic source changed")
    return p
