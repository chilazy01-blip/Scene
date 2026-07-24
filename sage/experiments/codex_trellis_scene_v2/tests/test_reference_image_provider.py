from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sage.experiments.codex_trellis_scene_v2.reference_image_provider import (
    generate_gpt_image2_reference,
)
from sage.experiments.codex_trellis_scene_v2.reference_soft_prior import build_parser


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


class ReferenceImageProviderTest(unittest.TestCase):
    def test_experiment_defaults_to_gpt_image_2_without_silent_fallback(self) -> None:
        args = build_parser().parse_args(["--prompt", "study", "--output-dir", "/tmp/run"])
        self.assertEqual(args.reference_provider, "gpt-image-2")
        self.assertEqual(args.image2_model, "gpt-image-2")

    def test_missing_api_key_fails_before_network_request(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                generate_gpt_image2_reference(
                    "one desk",
                    Path("/tmp/unused-reference.png"),
                    urlopen=lambda *args, **kwargs: self.fail("network was called"),
                )

    def test_direct_provider_writes_png_and_reproducibility_metadata(self) -> None:
        png = b"\x89PNG\r\n\x1a\nfake"
        response = json.dumps(
            {
                "created": 123,
                "data": [{"b64_json": base64.b64encode(png).decode("ascii")}],
            }
        ).encode("utf-8")
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured["authorization"] = request.headers["Authorization"]
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return _FakeResponse(response)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reference.png"
            report = generate_gpt_image2_reference(
                "one desk",
                output,
                api_key="test-secret",
                urlopen=fake_urlopen,
            )
            self.assertEqual(output.read_bytes(), png)
        self.assertEqual(captured["authorization"], "Bearer test-secret")
        self.assertEqual(captured["payload"]["model"], "gpt-image-2")
        self.assertEqual(captured["payload"]["n"], 1)
        self.assertEqual(report["provider"], "openai_image_api")
        self.assertTrue(report["model_request_verified"])
        self.assertNotIn("api_key", report)
        self.assertNotIn("test-secret", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
