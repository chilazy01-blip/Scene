"""Use the pinned upstream writer and typed reader without changing source semantics.

The caller selects the isolated upstream runtime. This module does not install
dependencies, instantiate a simulator, infer joint order, or promote data quality.
"""
import json
from pathlib import Path

import numpy as np

from sage.experiments.embodied_trajectory_v1.dataset import (
    TrajectoryDataset, bound, read, reference, require,
)

SCHEMA = "embodied-lerobot-proprio/v1"
FIELDS = {
    "observation.state": "proprio",
    "action": "action",
    "next.observation.state": "next_proprio",
    "source.time": "time",
    "source.next_time": "next_time",
    "outcome.terminated": "terminated",
    "outcome.truncated": "truncated",
}


def _purpose(purpose, required_modalities):
    require(purpose in ("inspection", "proprio_development"), "purpose_not_qualified")
    require(tuple(required_modalities) == ("proprio",), "camera_or_modality_missing")


def export_trajectory(binding, pin, destination, purpose="proprio_development"):
    """Write one whole, validated saved trajectory; retain N+1 state information.

LeRobot timestamps start at zero. Exact original float64 simulation times are
stored separately, and each row explicitly retains its next observation/time.
"""
    _purpose(purpose, ("proprio",))
    dataset = TrajectoryDataset(binding, pin, purpose=purpose)
    meta = dataset.metadata
    require(not meta["qualified_training"] and not meta["task_success"], "unsupported_qualification")
    destination = Path(destination).resolve()
    require(not destination.exists(), "destination_exists")
    fps = round(1 / meta["dt"])
    require(abs(fps * meta["dt"] - 1) < 1e-12, "noninteger_fps")
    from decoupled_wbc.data.exporter import Gr00tDataExporter
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset

    features = {}
    for key, source_key in FIELDS.items():
        names = (meta["action_names"] if source_key == "action" else
                 meta["proprio_names"] if source_key in ("proprio", "next_proprio") else [source_key])
        dtype = "int64" if source_key in ("terminated", "truncated") else "float64"
        features[key] = dict(dtype=dtype, shape=(len(names),), names=names)
    features["outcome.task_success"] = dict(dtype="int64", shape=(1,), names=["task_success"])
    script_config = dict(schema=SCHEMA, source_binding=reference(binding), metadata=meta,
                         timestamp_semantics="relative row index / fps; exact source times retained separately")
    modality = dict(state={"proprio": {"original_key": "observation.state", "start": 0,
                                      "end": len(meta["proprio_names"])}},
                    action={"native": {"original_key": "action", "start": 0,
                                       "end": len(meta["action_names"])}}, video={}, annotation={})
    writer = Gr00tDataExporter.create(
        save_root=destination, fps=fps, features=features, modality_config=modality,
        task=f"{meta['id']}: {meta['scope']}", script_config=script_config,
        robot_type=meta["embodiment"], overwrite_existing=False,
    )
    writer.meta.info["scene_qualification"] = dict(
        qualified_training=False, task_success=False, camera_present=False,
        scope=meta["scope"], source_status=meta["source_status"], split=meta["split"],
        failure_classes=meta["failure_classes"], learning_effect="unknown",
    )
    for index in range(len(dataset)):
        row = dataset[index]
        frame = {key: np.asarray(row[source_key], dtype=features[key]["dtype"]).reshape(features[key]["shape"])
                 for key, source_key in FIELDS.items()}
        frame["outcome.task_success"] = np.array([0], dtype=np.int64)
        writer.add_frame(frame)
    if meta["failures"]:
        writer.save_episode_as_discarded()
    else:
        writer.save_episode()
    writer.stop_video_writers()
    require(writer.meta.total_frames == len(dataset), "export_length")
    require(not writer.meta.camera_keys, "unexpected_camera")
    manifest = dict(schema=SCHEMA, source_binding=reference(binding), metadata=meta,
                    writer=reference(__import__(Gr00tDataExporter.__module__, fromlist=["__file__"]).__file__),
                    native_dataset=reference(__import__(LeRobotDataset.__module__, fromlist=["__file__"]).__file__),
                    bridge=reference(__file__),
                    files=[dict(relative=str(p.relative_to(destination)), **reference(p))
                           for p in sorted(destination.rglob("*")) if p.is_file()])
    path = destination / "SCENE_BINDING.json"
    path.write_text(json.dumps(manifest, indent=2))
    return reference(path)


class NativeTrajectoryDataset:
    """Read actual native Parquet through the pinned official typed consumer.

    Purpose and camera gates match the source reader. Privileged audit arrays
    were not exported. Failure/control labels are retained in metadata.
    """
    def __init__(self, binding, pin, purpose="proprio_development", required_modalities=("proprio",)):
        _purpose(purpose, required_modalities)
        record = read(dict(path=str(binding), sha256=pin))
        require(record["schema"] == SCHEMA, "schema")
        root = Path(binding).resolve().parent
        for name in ("bridge", "writer", "native_dataset"):
            bound(record[name])
        source = read(record["source_binding"])
        require(record["metadata"] == source["metadata"], "metadata_source_mismatch")
        for item in record["files"]:
            expected = (root / item["relative"]).resolve()
            require(expected.is_relative_to(root) and expected == Path(item["path"]).resolve(), "artifact_path")
            bound(item)
        info = json.loads((root / "meta/info.json").read_text())
        require(info["script_config"]["source_binding"] == record["source_binding"], "source_binding_mismatch")
        require(info["script_config"]["metadata"] == record["metadata"], "native_metadata_mismatch")
        require(not info["scene_qualification"]["qualified_training"], "purpose_not_qualified")
        from decoupled_wbc.data.exporter import TypedLeRobotDataset
        self.native = TypedLeRobotDataset(repo_id="local/scene-development", root=root,
                                         episodes=[0], video_backend="pyav")
        self.metadata = record["metadata"]
        require(len(self.native) == self.metadata["transitions"], "native_length")
        require(not self.native.meta.camera_keys, "unexpected_camera")

    def __len__(self):
        return len(self.native)

    def __getitem__(self, index):
        if not isinstance(index, (int, np.integer)) or not 0 <= index < len(self):
            raise IndexError(index)
        row = self.native[int(index)]
        require(row["outcome.task_success"].item() == 0, "success_label_changed")
        result = {}
        for key, source_key in FIELDS.items():
            value = row[key]
            if source_key in ("terminated", "truncated"):
                value = bool(value.item())
            elif source_key in ("time", "next_time"):
                value = value.reshape(())
            result[source_key] = value
        return result
