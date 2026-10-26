"""Load a hash-verified compiled cache of the same canonical native XML."""

from pathlib import Path
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)


def load_model(path):
    import mujoco

    path = Path(path)
    cache = read_bound_json(path.with_name("CACHE.json"))
    for key in ("xml", "binary"):
        b = cache[key]
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("native compiled model cache binding changed")
    if (
        str(path) != cache["xml"]["path"]
        or cache["mujoco_version"] != mujoco.__version__
    ):
        raise ValueError("cache XML or engine mismatch")
    return mujoco.MjModel.from_binary_path(cache["binary"]["path"])
