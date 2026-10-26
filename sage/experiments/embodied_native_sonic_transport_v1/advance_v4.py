"""One disclosed official-hand-interface run, exact reused G1 admission prefix."""
import argparse
from pathlib import Path
from .engine_v4 import run
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);root=ap.parse_args().root
    assert read_bound_json(root/'version_03/admission/AUDIT.json')['control_passed']
    run(root,root/'version_04/full',2200,root/'version_03/admission')
