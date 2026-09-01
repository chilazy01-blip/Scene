"""Content-addressed stage DAG with atomic attempt records."""

from __future__ import annotations

import json
import resource
import tempfile
import time
from pathlib import Path
from typing import Any

from .content_chain import content_hash, file_binding


STAGES = (
    "expand",
    "architecture",
    "scene_graph",
    "asset_plan",
    "asset_generate",
    "asset_qa",
    "layout",
    "relation_geometry",
    "assemble",
    "render_acceptance",
    "delivery_audit",
)
DEPENDENCIES = {
    stage: (() if index == 0 else (STAGES[index - 1],))
    for index, stage in enumerate(STAGES)
}


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def _latest_committed(stage_record: dict[str, Any]) -> dict[str, Any] | None:
    for attempt in reversed(stage_record.get("attempts", [])):
        if attempt.get("status") == "committed":
            return attempt
    return None


def _resource_snapshot() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    memory_current = Path("/sys/fs/cgroup/memory.current")
    return {
        "process_peak_rss_kib": int(usage.ru_maxrss),
        "process_user_seconds": float(usage.ru_utime),
        "process_system_seconds": float(usage.ru_stime),
        "cgroup_memory_current_bytes": (
            int(memory_current.read_text(encoding="utf-8").strip())
            if memory_current.is_file()
            else None
        ),
    }


class StageDAG:
    def __init__(self, path: Path) -> None:
        self.path = path
        if path.is_file():
            self.value = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.value = {
                "schema": "scene-v2-stage-dag/v1",
                "stage_order": list(STAGES),
                "stages": {stage: {"dependencies": list(DEPENDENCIES[stage]), "attempts": []} for stage in STAGES},
            }

    def _save(self) -> None:
        _atomic_json(self.path, self.value)

    def _dependency_outputs(self, stage: str) -> dict[str, str | None]:
        result = {}
        for dependency in DEPENDENCIES[stage]:
            latest = _latest_committed(self.value["stages"][dependency])
            result[dependency] = latest.get("output_key") if latest else None
        return result

    def _input_key(self, stage: str, inputs: dict[str, Any], config: dict[str, Any]) -> str:
        return content_hash({"stage": stage, "inputs": inputs, "config": config, "dependencies": self._dependency_outputs(stage)})

    @staticmethod
    def _outputs_current(attempt: dict[str, Any]) -> bool:
        for item in attempt.get("outputs", {}).values():
            path = Path(str(item.get("path") or ""))
            if not path.is_file() or file_binding(path) != {"bytes": item.get("bytes"), "sha256": item.get("sha256")}:
                return False
        return bool(attempt.get("outputs"))

    def begin(self, stage: str, *, inputs: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        if stage not in STAGES:
            raise ValueError(f"unknown stage: {stage}")
        record = self.value["stages"][stage]
        input_key = self._input_key(stage, inputs, config)
        latest = _latest_committed(record)
        if latest and latest.get("input_key") == input_key and self._outputs_current(latest):
            return {"reused": True, "attempt": latest}
        index = STAGES.index(stage)
        for downstream in STAGES[index:]:
            downstream_record = self.value["stages"][downstream]
            committed = _latest_committed(downstream_record)
            if committed:
                downstream_record["invalidated_by"] = {"stage": stage, "input_key": input_key, "at": time.time()}
        attempt = {
            "schema": "scene-v2-stage-attempt/v1",
            "attempt": len(record["attempts"]) + 1,
            "status": "running",
            "input_key": input_key,
            "inputs": inputs,
            "config": config,
            "dependency_output_keys": self._dependency_outputs(stage),
            "started_at": time.time(),
        }
        record["attempts"].append(attempt)
        self._save()
        return {"reused": False, "attempt": attempt}

    def commit(
        self,
        stage: str,
        attempt_number: int,
        *,
        outputs: dict[str, Path],
        resource_peak: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempt = self.value["stages"][stage]["attempts"][attempt_number - 1]
        if attempt.get("status") != "running":
            raise RuntimeError("only a running attempt can commit")
        bindings = {name: {"path": str(path.resolve()), **file_binding(path)} for name, path in sorted(outputs.items())}
        attempt.update(status="committed", outputs=bindings, output_key=content_hash(bindings), completed_at=time.time(), duration_seconds=time.time() - float(attempt["started_at"]), resource_peak=resource_peak or _resource_snapshot())
        self.value["stages"][stage].pop("invalidated_by", None)
        self._save()
        return attempt

    def fail(self, stage: str, attempt_number: int, error: str) -> None:
        attempt = self.value["stages"][stage]["attempts"][attempt_number - 1]
        attempt.update(status="failed", error=str(error), completed_at=time.time(), duration_seconds=time.time() - float(attempt["started_at"]))
        self._save()

    def can_reuse(self, stage: str, *, inputs: dict[str, Any], config: dict[str, Any]) -> bool:
        latest = _latest_committed(self.value["stages"][stage])
        return bool(latest and latest.get("input_key") == self._input_key(stage, inputs, config) and self._outputs_current(latest))
