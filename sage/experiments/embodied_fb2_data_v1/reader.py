"""Read only admitted public RGB-D/action fields from a bound canonical file."""
from pathlib import Path
import json

import h5py
import numpy as np
import torch

from .alignment import sha


class PublicSequence(torch.utils.data.Dataset):
    trajectory_keys = (
        "timestamp", "command_timestamp", "joint_position", "joint_velocity",
        "previous_command", "action_chunk", "action_timestamps", "action_valid", "done")
    camera_keys = ("rgb", "depth_m", "valid", "K", "optical_to_base")

    def __init__(self, binding):
        self.binding = dict(binding)
        self.path = Path(binding["path"])
        if not binding["complete_physical_task"] or not binding["independent_full_task_passed"]:
            raise ValueError("unqualified_physical_source")
        if not binding["capture_complete"] or sha(self.path) != binding["sha256"]:
            raise ValueError("incomplete_or_changed_capture")
        with h5py.File(self.path, "r") as source:
            self.metadata = json.loads(source.attrs["metadata"])
            self.count = len(source["trajectory/timestamp"])
            self.cameras = sorted(source["cameras"])
            assert self.count == binding["rows"] and len(self.cameras) == 2
            assert set(source["trajectory"]) == set(self.trajectory_keys)
            assert source["trajectory/joint_position"].shape == (self.count, 43)
            assert source["trajectory/action_chunk"].shape == (self.count, 2, 43)
            for name in self.cameras:
                assert set(source["cameras"][name]) == set(self.camera_keys)
            assert self.metadata["scope"] == "simulation_training"

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        if not 0 <= index < self.count:
            raise IndexError(index)
        with h5py.File(self.path, "r") as source:
            trajectory = {key: torch.from_numpy(np.asarray(source["trajectory/"+key][index]))
                          for key in self.trajectory_keys}
            cameras = {name: {key: torch.from_numpy(np.asarray(source["cameras/"+name+"/"+key][index]))
                              for key in self.camera_keys} for name in self.cameras}
        return {"trajectory": trajectory, "cameras": cameras}
