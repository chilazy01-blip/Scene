"""Episode-keyed RGB-D access and exact 20 ms command execution."""
from pathlib import Path
import json
import numpy as np

from . import QUALITY_VERSION
from .admission import sha


def command_stream(chunks, timestamps, valid, dt=.02):
    chunks, timestamps, valid = np.asarray(chunks), np.asarray(timestamps), np.asarray(valid)
    if chunks.ndim != 3 or chunks.shape[1:] != (2,43) or timestamps.shape != chunks.shape[:2] or valid.shape != timestamps.shape:
        raise ValueError("invalid_action_shapes")
    if valid.dtype != np.bool_ and not np.isin(valid,[0,1]).all():
        raise ValueError("invalid_action_mask")
    mask = valid.astype(bool)
    flat = mask.ravel()
    if not len(flat) or not flat[0] or np.any(np.diff(flat.astype(int)) > 0):
        raise ValueError("only_trailing_padding_allowed")
    actions, times = chunks[mask], timestamps[mask]
    if not np.isfinite(actions).all() or not np.isfinite(times).all():
        raise ValueError("nonfinite_valid_command")
    if not np.allclose(np.diff(times),dt,rtol=0,atol=1e-9):
        raise ValueError("noncontiguous_command_time")
    for t,q in zip(times,actions):
        yield dict(timestamp=float(t), duration=dt, command=q.copy())


def masked_mse(prediction, target, valid):
    """Ignore invalid tail values even if padding contains NaNs."""
    pred, target, mask = np.asarray(prediction),np.asarray(target),np.asarray(valid,dtype=bool)
    if pred.shape != target.shape or pred.shape[:-1] != mask.shape or pred.shape[-1] != 43 or not mask.any():
        raise ValueError("invalid_loss_shapes_or_empty_mask")
    delta = pred[mask]-target[mask]
    if not np.isfinite(delta).all():
        raise ValueError("nonfinite_valid_loss")
    return float(np.mean(delta*delta))


class EpisodeSidecars:
    """Bind each episode separately; local frame_index is never a global index."""
    def __init__(self, manifest_path, required_quality=QUALITY_VERSION):
        path = Path(manifest_path)
        manifest = json.loads(path.read_text())
        if manifest.get("schema") != "episode-sidecars/v2":
            raise ValueError("unknown_sidecar_schema")
        self.entries = {}
        for entry in manifest["episodes"]:
            eid = entry["episode_id"]
            if eid in self.entries:
                raise ValueError("duplicate_episode_id")
            if entry.get("quality_version") != required_quality or entry.get("accepted") is not True or not entry.get("provenance"):
                raise ValueError("episode_quality_or_provenance_not_admitted")
            file = (path.parent/entry["path"]).resolve()
            if not file.is_relative_to(path.parent.resolve()) or sha(file) != entry["sha256"]:
                raise ValueError("sidecar_binding")
            if not isinstance(entry.get("rows"),int) or entry["rows"] <= 0:
                raise ValueError("invalid_episode_rows")
            self.entries[eid] = dict(entry, resolved_path=file)
        if not self.entries:
            raise ValueError("empty_episode_manifest")

    def read(self, episode_id, frame_index, sensor_time):
        import h5py
        e = self.entries[episode_id]
        if not isinstance(frame_index,(int,np.integer)) or not 0 <= frame_index < e["rows"]:
            raise IndexError("episode_frame_bounds")
        with h5py.File(e["resolved_path"],"r") as f:
            if len(f["trajectory/timestamp"]) != e["rows"] or float(f["trajectory/timestamp"][frame_index]) != float(sensor_time):
                raise ValueError("episode_time_alignment")
            result = {"episode_id":episode_id,"frame_index":int(frame_index),
                      "quality_version":e["quality_version"],"provenance":e["provenance"]}
            for cam in e["cameras"]:
                result["depth_m."+cam] = f["cameras/"+cam+"/depth_m"][frame_index]
                result["depth_valid."+cam] = f["cameras/"+cam+"/valid"][frame_index]
            return result


def validate_split(episodes):
    """Whole episodes and scene families are indivisible across learning splits."""
    seen, groups = set(), {}
    for e in episodes:
        eid, group, split = e["episode_id"], e["scene_family"], e["split"]
        if eid in seen or split not in {"train","validation","test"} or not group:
            raise ValueError("invalid_or_duplicate_split_entry")
        if group in groups and groups[group] != split:
            raise ValueError("scene_family_leakage")
        seen.add(eid); groups[group] = split
    if {e["split"] for e in episodes} != {"train","validation","test"}:
        raise ValueError("independent_splits_missing")
    return True


class RGBDTrainingDataset:
    """Join installed LeRobot rows to per-episode sidecars without global indexing."""
    def __init__(self, root, sidecar_manifest="EPISODES.json", native=None):
        self.root=Path(root)
        self.sidecars=EpisodeSidecars(self.root/sidecar_manifest)
        if native is None:
            from ..typed_reader import TypedLeRobotDataset
            native=TypedLeRobotDataset(self.root)
        self.native=native
        if len(native)!=sum(e["rows"] for e in self.sidecars.entries.values()):
            raise ValueError("public_sidecar_row_count_mismatch")

    def __len__(self):
        return len(self.native)

    def __getitem__(self, index):
        import torch
        row=dict(self.native[index])
        evidence=self.sidecars.read(int(row["episode_index"]),int(row["frame_index"]),float(row["source.sensor_time"]))
        for key,value in evidence.items():
            if key.startswith(("depth_m.","depth_valid.")):
                row["observation."+key]=torch.from_numpy(value)
        row["quality.version"]=evidence["quality_version"]
        row["source.episode_id"]=evidence["episode_id"]
        return row
