"""One resource-bounded pipeline job per process; logs and failures remain visible."""
import argparse
import os
from pathlib import Path
import resource


def main():
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MUJOCO_GL"] = "egl"
    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["preview", "engine", "audit", "replay", "force", "render", "delivery", "measure"])
    ap.add_argument("--root", type=Path, required=True)
    a = ap.parse_args(); root = a.root; episode = root / "full"
    if a.action == "preview":
        from .preview import run
        run(root)
    elif a.action == "engine":
        from .engine import run
        run(root, episode, 2200)
    elif a.action == "audit":
        from .audit import audit
        audit(root, episode)
    elif a.action == "replay":
        from .replay import run
        run(root, episode, root / "continuous_replay")
    elif a.action == "force":
        from .force import run
        run(episode)
    elif a.action == "render":
        from .visualize import run
        run(root, root / "actual_video", episode)
    elif a.action == "delivery":
        from .delivery import run
        replay = root / "continuous_replay"
        run(root, episode, root / "actual_video", replay if replay.exists() else None)
    else:
        from .review import measure
        measure(root)


if __name__ == "__main__":
    main()
