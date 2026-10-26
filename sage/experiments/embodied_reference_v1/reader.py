"""Read source rows explicitly; unknown producer semantics stay unknown.

There is deliberately no transition or native-command conversion here. Matching
dimensions, names, and ranges cannot establish model/frame/time equivalence.
"""
from pathlib import Path
import hashlib

import numpy as np


class ReferenceRows:
    columns = ("observation.state", "action", "timestamp", "episode_index", "frame_index")

    def __init__(self, path, sha256, *, purpose="inspection"):
        self.require_use(purpose)
        self.path = Path(path)
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        if self.sha256 != sha256:
            raise ValueError("source_hash_mismatch")
        import pyarrow.parquet as pq

        table = pq.read_table(self.path, columns=list(self.columns))
        self.arrays = {name: np.asarray(table[name].to_pylist()) for name in self.columns}
        q, u = self.arrays["observation.state"], self.arrays["action"]
        if q.ndim != 2 or u.shape != q.shape or not len(q):
            raise ValueError("invalid_source_row_shapes")
        for key, value in self.arrays.items():
            if value.dtype.kind not in "biuf" or not np.isfinite(value).all():
                raise ValueError("invalid_numeric_column:" + key)
            if len(value) != len(q):
                raise ValueError("inconsistent_row_count")
            if key not in ("observation.state", "action") and value.shape != (len(q),):
                raise ValueError("invalid_scalar_column:" + key)
        episodes = self.arrays["episode_index"]
        frames = self.arrays["frame_index"]
        if np.any(episodes != np.floor(episodes)) or np.any(frames != np.floor(frames)):
            raise ValueError("noninteger_episode_or_frame")
        for ep in np.unique(episodes):
            rows = np.flatnonzero(episodes == ep)
            if np.any(np.diff(rows) != 1) or np.any(np.diff(frames[rows]) != 1):
                raise ValueError("noncontiguous_episode_or_frame")
            if np.any(np.diff(self.arrays["timestamp"][rows]) <= 0):
                raise ValueError("nonmonotonic_timestamp")

    @staticmethod
    def require_use(purpose):
        if purpose != "inspection":
            raise ValueError("reference_has_no_verified_model_timing_task_admission:" + str(purpose))

    def __len__(self):
        return len(self.arrays["action"])

    def __getitem__(self, index):
        # No simulation state, teleop targets, privileged object state, invented
        # task labels, or implied obs-before-action pairing in consumer output.
        return {
            "source_observation": self.arrays["observation.state"][index].copy(),
            "source_action": self.arrays["action"][index].copy(),
            "source_timestamp": self.arrays["timestamp"][index].copy(),
            "source_episode": self.arrays["episode_index"][index].copy(),
            "source_frame": self.arrays["frame_index"][index].copy(),
        }


def diagnose_named_transfer(actions, binding_rows):
    """Conditional numerical diagnostic using an existing pinned Pinocchio order.

    This does not prove that the file was generated with that model/order. All
    columns are tested unchanged; clipping, sign guessing, and reordering to
    make an out-of-range value pass are forbidden.
    """
    actions = np.asarray(actions)
    n = len(binding_rows)
    if actions.ndim != 2 or actions.shape[1] != n or not np.isfinite(actions).all():
        raise ValueError("action_shape_or_nonfinite")
    if sorted(r["pin_q_index"] for r in binding_rows) != list(range(n)):
        raise ValueError("binding_indices_not_bijective")
    if len({r["name"] for r in binding_rows}) != n:
        raise ValueError("binding_names_not_unique")
    rejected = np.zeros(len(actions), dtype=bool)
    joints = []
    for row in binding_rows:
        values = actions[:, row["pin_q_index"]]
        low, high = row["command_lower"], row["command_upper"]
        if not np.isfinite([low, high]).all() or low > high:
            raise ValueError("invalid_binding_range")
        invalid = (values < low) | (values > high)
        rejected |= invalid
        joints.append(dict(name=row["name"], group=row["group"],
                           source_column=row["pin_q_index"], lower=low, upper=high,
                           min=float(values.min()), max=float(values.max()),
                           rejected_rows=int(invalid.sum()),
                           first_rejected_row=int(np.flatnonzero(invalid)[0]) if invalid.any() else None,
                           maximum_excess_rad=float(np.maximum(np.maximum(low-values, values-high), 0).max())))
    return dict(scope="conditional_same_upstream_pin_order_only", source_model_identity_verified=False,
                candidate_rows=len(actions), numerically_in_range_rows=int((~rejected).sum()),
                numerically_rejected_rows=int(rejected.sum()), joints=joints,
                native_replay_admitted=False,
                reasons=["source_dataset_model_and_script_config_missing",
                         "source_to_native_hand_frame_equivalence_unproven",
                         "source_producer_timing_unproven",
                         "full_task_and_camera_qualification_missing"])
