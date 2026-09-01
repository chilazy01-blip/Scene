"""Generate authoritative defaults, schemas, fingerprints and release status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .cli import build_parser
from .content_chain import content_hash, file_binding
from .core_domain import CORE_STAGE_OWNERSHIP, REQUEST_SCHEMA
from .stage_dag import STAGES


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_RELEASE_STATUS = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "p014_verification_20260901_v1/release_status_manifest.json"
)


def parser_defaults() -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for action in build_parser()._actions:
        if not action.dest or action.dest == "help":
            continue
        value = action.default
        if isinstance(value, Path):
            value = str(value)
        if value is not argparse.SUPPRESS:
            defaults[action.dest] = value
    return defaults


def _release_status(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"available": False, "reason": "no verified status manifest supplied"}
    document = json.loads(path.read_text(encoding="utf-8"))
    tiers = document.get("tiers", {})
    return {
        "available": True,
        "source": {"path": str(path.resolve()), **file_binding(path)},
        "release_eligible": bool(document.get("release_eligible")),
        "test_counts_are_machine_generated": bool(document.get("test_counts_are_machine_generated")),
        "tiers": {
            name: {
                "status": value.get("status"),
                "test_count": value.get("test_count"),
                "actual_gpu": value.get("actual_gpu"),
            }
            for name, value in tiers.items()
        },
    }


def build_project_facts(release_status: Path | None = DEFAULT_RELEASE_STATUS) -> dict[str, Any]:
    runtime_lock = PACKAGE_DIR / "runtime_lock.json"
    lock = json.loads(runtime_lock.read_text(encoding="utf-8"))
    facts = {
        "schema": "scene-v2-project-facts/v1",
        "canonical_entry_point": "python -m sage.experiments.codex_trellis_scene_v2",
        "legacy_policy": "compatibility_adapter_only; use --legacy-engine solely for historical reproduction",
        "core_stage_ownership": CORE_STAGE_OWNERSHIP,
        "stage_order": list(STAGES),
        "document_schemas": {
            "SceneRequest": REQUEST_SCHEMA,
            "SceneBrief": "codex_trellis_scene_brief_v2",
            "TypedSceneGraph": "codex_trellis_typed_scene_graph_v1",
            "LayoutPlan": "codex_trellis_layout_plan_v2",
            "RunManifest": "scene-v2-stage-dag/v1",
            "FinalDeliveryAudit": "scene-v2-final-hash-audit/v1",
        },
        "cli_defaults": parser_defaults(),
        "runtime_lock": {"binding": file_binding(runtime_lock), "model": lock.get("model"), "trellis": lock.get("trellis"), "blender": lock.get("blender")},
        "release_status": _release_status(release_status),
    }
    facts["content_hash"] = content_hash(facts)
    return facts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-status", type=Path, default=DEFAULT_RELEASE_STATUS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = json.dumps(build_project_facts(args.release_status), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
