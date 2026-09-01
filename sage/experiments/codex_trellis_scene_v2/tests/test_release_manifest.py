from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from sage.experiments.codex_trellis_scene_v2.release_manifest import (
    _run,
    canonical_hash,
    sha256_file,
    write_json_atomic,
)


class ReleaseManifestTests(unittest.TestCase):
    def test_file_and_canonical_hashes_are_content_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "payload.bin"
            path.write_bytes(b"alpha")
            first = sha256_file(path)
            path.write_bytes(b"beta")
            self.assertNotEqual(first, sha256_file(path))
        self.assertEqual(canonical_hash({"b": 2, "a": 1}), canonical_hash({"a": 1, "b": 2}))

    def test_atomic_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "manifest.json"
            write_json_atomic(path, {"ok": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"ok": True})

    def test_command_capture_preserves_porcelain_leading_space(self) -> None:
        result = _run(
            [
                sys.executable,
                "-c",
                "print(' M tracked.py')",
            ]
        )
        self.assertEqual(result["stdout"], " M tracked.py")


if __name__ == "__main__":
    unittest.main()
