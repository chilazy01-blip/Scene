from pathlib import Path

from sage.experiments.embodied_data_stability_v1.finalize_s1 import sha256_file


def test_sha256_file(tmp_path: Path):
    path = tmp_path / "evidence.json"
    path.write_bytes(b"evidence")
    assert sha256_file(path) == "ee8250fb76e094b34b471f13a73dbbe51d1ae142e9df59d7c0d31ec20f0a0a8e"
