"""One-shot audited admission then original-case full SONIC29 attempt."""
import argparse
from pathlib import Path
from .audit import audit
from .engine import run

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);root=ap.parse_args().root
    assert audit(root,root/'version_01/admission')['control_passed']
    run(root,root/'version_01/full',3000,root/'version_01/admission')
