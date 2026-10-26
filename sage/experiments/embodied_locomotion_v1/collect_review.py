"""Render the preselected cases; no post-result cherry-picking or physics."""

import argparse
import subprocess
import sys
from pathlib import Path
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    write_json_atomic,
)


def run(root):
    import json

    selection = json.loads((root / "VISUAL_SELECTION.json").read_text())
    for name in selection["selected_before_matrix_completion"]:
        source = root / "matrix_run_01" / name / "full"
        output = root / "review" / name
        if (output / "MANIFEST.json").exists():
            continue
        if not (source / "AUDIT.json").exists():
            raise ValueError("preselected case not completed " + name)
        subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "sage.experiments.embodied_locomotion_v1.render_v3",
                "--run-root",
                str(source),
                "--output-root",
                str(output),
            ],
            check=True,
            timeout=120,
        )
    write_json_atomic(
        root / "review/REVIEW_COMPLETE.json",
        {
            "selected_cases": selection["selected_before_matrix_completion"],
            "physics_steps": 0,
            "note": "actual motion and layout inspection still required; decoder success alone is insufficient",
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
