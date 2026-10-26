"""Fresh admission, independent ownership audit, then one complete v2 attempt."""
import argparse
from pathlib import Path
from .engine_v2 import run
from .audit_v2 import audit

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);root=ap.parse_args().root
    run(root,root/'version_02/admission',100)
    assert audit(root,root/'version_02/admission')['control_passed']
    run(root,root/'version_02/full',3000,root/'version_02/admission')
