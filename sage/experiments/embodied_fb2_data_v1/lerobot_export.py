"""Lossless LeRobot export with the pinned official typed training consumer."""
from pathlib import Path
import json
import os

import h5py
import numpy as np
import torch

from .alignment import sha
from .reader import PublicSequence


def public_numeric(source):
    t = source["trajectory"]
    count = len(t["timestamp"])
    result = {
        "observation.state": np.concatenate(
            [t[key][:] for key in ("joint_position", "joint_velocity", "previous_command")], axis=1),
        "action": t["action_chunk"][:].reshape(count, 86),
        "action.valid": t["action_valid"][:].astype(np.int64),
        "source.sensor_time": t["timestamp"][:].reshape(count, 1),
        "source.command_time": t["command_timestamp"][:].reshape(count, 1),
        "source.action_times": t["action_timestamps"][:],
        "outcome.done": t["done"][:].astype(np.int64).reshape(count, 1),
    }
    for name in source["cameras"]:
        for field in ("K", "optical_to_base"):
            result[f"observation.calibration.{name}.{field}"] = source[f"cameras/{name}/{field}"][:].reshape(count, -1)
    return result


def export(binding, destination):
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    from decoupled_wbc.data.exporter import TypedLeRobotDataset

    public = PublicSequence(binding)
    destination = Path(destination)
    assert not destination.exists(), "keep previous export attempts intact"
    repo = "local/fb2-native-g1"
    with h5py.File(public.path, "r") as source:
        values = public_numeric(source)
        features = {key: dict(dtype=str(value.dtype), shape=(value.shape[1],),
                              names=[f"{key}_{i}" for i in range(value.shape[1])])
                    for key, value in values.items()}
        for name in public.cameras:
            features["observation.images."+name] = dict(
                dtype="image", shape=source[f"cameras/{name}/rgb"].shape[1:],
                names=["height", "width", "channels"])
        writer = LeRobotDataset.create(repo_id=repo, root=destination, fps=25,
            robot_type="native G1 full-body simulation", features=features,
            use_videos=False, image_writer_threads=0, video_backend="pyav")
        metadata = dict(schema="native-g1-rgbd-fullbody-command-chunks/v1",
            scope="simulation_training", source_binding=binding,
            state_layout="43 q +43 dq +43 previous position command, native joint order",
            action_layout="reshape86 to2 chronological 43-joint position commands at50Hz",
            position_units="rad", velocity_units="rad/s", action_units="rad",
            valid_mask="last repeated command, if any, is padding with action.valid0",
            timing="source.sensor_time is actual cached sensor time; source.command_time and action_times are actual command clocks; standard LeRobot timestamp is25Hz frame indexing",
            rgb="lossless PNG; typed consumer returns float32 CHW/255",
            depth="exact float32 metric optical depth plus boolean mask in bound HDF5 sidecar",
            actuator_controls="source physics audit sidecar retains actual200Hz mixed native actuator controls and controller configuration; these are not position commands",
            policy_training_performance_verified=False)
        (destination/"meta/scene_source.json").write_text(json.dumps(metadata, indent=2))
        try:
            for i in range(len(public)):
                frame = {key: value[i] for key, value in values.items()}
                frame.update({"observation.images."+name: source[f"cameras/{name}/rgb"][i]
                              for name in public.cameras})
                frame["task"] = "Grasp the box with both hands, lift, carry to the shelf, place and release."
                writer.add_frame(frame)
            writer.save_episode()
        finally:
            writer.stop_image_writer()
        native = TypedLeRobotDataset(repo_id=repo, root=destination, video_backend="pyav")
        assert len(native) == len(public)
        cursor = 0
        for batch in torch.utils.data.DataLoader(native, batch_size=16, num_workers=0):
            count = len(batch["index"])
            for key, expected in values.items():
                actual = batch[key].numpy().reshape(count, -1)
                wanted = expected[cursor:cursor+count]
                assert actual.dtype == wanted.dtype and np.array_equal(actual, wanted), key
            for name in public.cameras:
                actual = batch["observation.images."+name].numpy()
                wanted = source[f"cameras/{name}/rgb"][cursor:cursor+count].transpose(0, 3, 1, 2)
                assert np.array_equal(actual, wanted.astype(np.float32)/255), name
                assert np.array_equal(np.rint(actual*255).astype(np.uint8), wanted), name
            assert np.array_equal(batch["frame_index"].numpy(), np.arange(cursor, cursor+count))
            cursor += count
        assert cursor == len(public)
    manifest = dict(completed=True, rows=len(public), physical_source=binding,
        all_native_numeric_fields_exact=True, all_rgb_pixels_lossless=True,
        depth_sidecar=dict(path=os.path.relpath(public.path, destination), sha256=binding["sha256"]),
        files=[dict(path=str(path.relative_to(destination)), sha256=sha(path))
               for path in sorted(destination.rglob("*")) if path.is_file()])
    (destination/"BINDING.json").write_text(json.dumps(manifest, indent=2))
    joined = NativeRGBD(destination)
    cursor = 0
    with h5py.File(public.path, "r") as source:
        for batch in torch.utils.data.DataLoader(joined, batch_size=16, num_workers=0):
            count = len(batch["index"])
            for name in public.cameras:
                for field in ("depth_m", "valid"):
                    actual = batch[f"observation.{field}.{name}"].numpy()
                    expected = source[f"cameras/{name}/{field}"][cursor:cursor+count]
                    assert actual.dtype == expected.dtype and np.array_equal(actual, expected)
            cursor += count
    assert cursor == len(public)
    result = dict(passed=True, actual_typed_lerobot_reader=True, actual_torch_dataloader=True,
                  all_rows=cursor, rgb_and_numeric_exact=True, depth_and_mask_exact=True,
                  policy_training_performance_verified=False, physics_steps=0, policy_forwards=0)
    (destination/"CONSUMER_VERIFICATION.json").write_text(json.dumps(result, indent=2))
    return result


class NativeRGBD(torch.utils.data.Dataset):
    def __init__(self, root):
        from decoupled_wbc.data.exporter import TypedLeRobotDataset
        self.root = Path(root)
        self.binding = json.loads((self.root/"BINDING.json").read_text())
        assert self.binding["completed"]
        for row in self.binding["files"]:
            if sha(self.root/row["path"]) != row["sha256"]:
                raise ValueError("native_export_hash_mismatch")
        self.sidecar = self.root/self.binding["depth_sidecar"]["path"]
        if sha(self.sidecar) != self.binding["depth_sidecar"]["sha256"]:
            raise ValueError("depth_sidecar_hash_mismatch")
        self.native = TypedLeRobotDataset(repo_id="local/fb2-native-g1", root=self.root, video_backend="pyav")
        assert len(self.native) == self.binding["rows"]

    def __len__(self):
        return len(self.native)

    def __getitem__(self, index):
        row = self.native[index]
        frame = int(row["frame_index"])
        assert int(row["episode_index"]) == 0
        with h5py.File(self.sidecar, "r") as source:
            assert float(row["source.sensor_time"]) == float(source["trajectory/timestamp"][frame])
            for name in source["cameras"]:
                for field in ("depth_m", "valid"):
                    row[f"observation.{field}.{name}"] = torch.from_numpy(source[f"cameras/{name}/{field}"][frame])
        return row
