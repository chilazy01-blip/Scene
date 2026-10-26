"""Fresh audited admission and final reference-feedback complete-task attempt."""
import argparse
from pathlib import Path
from .engine_v3 import run
from .audit_v3 import audit

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);root=ap.parse_args().root
    run(root,root/'version_03/admission',100)
    assert audit(root,root/'version_03/admission')['control_passed']
    run(root,root/'version_03/full',2795,root/'version_03/admission')
