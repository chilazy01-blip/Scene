"""Run one explicitly selected fixture under the caller's resource guard."""
import argparse
from pathlib import Path
import traceback

from .contracts import write
from .environment import FrozenTaskEnvironment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("Output already exists; retain the previous attempt")
    env = None
    try:
        env = FrozenTaskEnvironment(args.source, observation_profile="privileged_state")
        env.reset(output)
        while not env.stopped:
            env.step_reference()
        result = env.record()
        print(result["outcome"])
    except Exception as exc:
        if env is not None and not env.recorded:
            if env.engineering is not False:
                env.fail(exc)
            env.close()
        else:
            output.mkdir(parents=True, exist_ok=True)
        write(output / "failure.json", dict(status="infrastructure_error", traceback=traceback.format_exc()))
        raise


if __name__ == "__main__":
    main()
