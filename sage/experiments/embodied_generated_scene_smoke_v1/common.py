from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


WORKSPACE = Path("/data/wsj/main")
SCENE_REPO = WORKSPACE / "scene"
RUN_ROOT = (
    WORKSPACE
    / "scene_runs/codex_trellis_v2/embodied_generated_scene_smoke_20261015_v4"
)
SOURCE_A_RUN = (
    WORKSPACE
    / "scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/"
    "full_body_milestone/feasibility_guard_v4/prepared/payload_data_20261009/"
    "native_parallel_12h_20261011"
)
SOURCE = SOURCE_A_RUN / "branches/A/source"
SOURCE_CONTRACT = SOURCE_A_RUN / "branches/A/SOURCE_CONTRACT.json"
REFERENCE_S3 = (
    WORKSPACE
    / "scene_runs/codex_trellis_v2/embodied_data_stability_s3_20261014_v1/"
    "source_a_task_smoke_01"
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    def default(item: Any) -> Any:
        if isinstance(item, Path):
            return str(item)
        if hasattr(item, "tolist"):
            return item.tolist()
        if hasattr(item, "item"):
            return item.item()
        raise TypeError(f"not JSON serializable: {type(item).__name__}")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=default)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

