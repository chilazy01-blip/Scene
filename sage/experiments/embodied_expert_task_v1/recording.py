"""Preserve the exact compiled simulation model alongside portable source files."""
from pathlib import Path
import hashlib
import json
import numpy as np
import mujoco


def model_array_differences(left, right):
    differences = {}
    for name in dir(left):
        if name.startswith("_"):
            continue
        a, b = getattr(left, name), getattr(right, name, None)
        if not isinstance(a, np.ndarray) or not isinstance(b, np.ndarray):
            continue
        if a.shape != b.shape:
            differences[name] = {"shape_left": list(a.shape), "shape_right": list(b.shape)}
        elif not np.array_equal(a, b):
            row = {"different_elements": int(np.count_nonzero(a != b))}
            if np.issubdtype(a.dtype, np.number) and a.size:
                row["max_absolute_error"] = float(np.max(np.abs(a.astype(float)-b.astype(float))))
            differences[name] = row
    return differences


def save_exact_model(model, path):
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mujoco.mj_saveModel(model, str(path), None)
    restored = mujoco.MjModel.from_binary_path(str(path))
    differences = model_array_differences(model, restored)
    receipt = dict(mujoco_version=mujoco.__version__, path=str(path),
                   sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                   model_arrays_equal=not differences, differences=differences,
                   scope="same MuJoCo version binary model fidelity; not task success",
                   source_xml_and_assets_still_required_for_portability=True)
    path.with_suffix(path.suffix + ".json").write_text(json.dumps(receipt, indent=2))
    if differences:
        raise ValueError("compiled model snapshot did not preserve model arrays")
    return receipt
