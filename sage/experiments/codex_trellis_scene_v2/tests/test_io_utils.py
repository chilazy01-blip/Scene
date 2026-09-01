from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sage.experiments.codex_trellis_scene_v2.io_utils import (
    run_codex_image_json,
    run_codex_json,
)


def _completed_codex_call(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    response_index = command.index("--output-last-message") + 1
    Path(command[response_index]).write_text('{"ok": true}\n', encoding="utf-8")
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class CodexInputTransportTest(unittest.TestCase):
    def test_large_text_prompt_uses_stdin_instead_of_one_process_argument(self) -> None:
        prompt = "x" * 150_000
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "sage.experiments.codex_trellis_scene_v2.io_utils.subprocess.run",
            side_effect=_completed_codex_call,
        ) as run:
            result = run_codex_json(
                prompt,
                Path(temp_dir),
                stage="large_request",
                model="test-model",
            )

        command = run.call_args.args[0]
        self.assertTrue(result["ok"])
        self.assertEqual(command[-1], "-")
        self.assertNotIn(prompt, command)
        self.assertEqual(run.call_args.kwargs["input"], prompt)

    def test_image_prompt_also_uses_stdin(self) -> None:
        prompt = "inspect image"
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "input.png"
            image_path.write_bytes(b"png")
            with mock.patch(
                "sage.experiments.codex_trellis_scene_v2.io_utils.subprocess.run",
                side_effect=_completed_codex_call,
            ) as run:
                result = run_codex_image_json(
                    prompt,
                    image_path,
                    Path(temp_dir),
                    stage="image_request",
                    model="test-model",
                )

        command = run.call_args.args[0]
        self.assertTrue(result["ok"])
        self.assertEqual(command[-1], "-")
        self.assertNotIn(prompt, command)
        self.assertEqual(run.call_args.kwargs["input"], prompt)


if __name__ == "__main__":
    unittest.main()
