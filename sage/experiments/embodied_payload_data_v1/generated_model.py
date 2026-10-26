"""Load versioned generated models, including byte-preserving gzip/VFS storage."""
import gzip,hashlib
from pathlib import Path
import mujoco
def load_model(path,expected_sha256=None,uncompressed_sha256=None):
    path=Path(path);raw=path.read_bytes()
    if expected_sha256 is not None:assert hashlib.sha256(raw).hexdigest()==expected_sha256
    if path.suffix=='.gz':
        raw=gzip.decompress(raw)
        if uncompressed_sha256 is not None:assert hashlib.sha256(raw).hexdigest()==uncompressed_sha256
        return mujoco.MjModel.from_binary_path('bound_model.mjb',assets={'bound_model.mjb':raw})
    return mujoco.MjModel.from_binary_path(str(path))

