"""Saved-trace quality worker sharing the exact complete-task evaluator."""
import sys
from pathlib import Path
from .quality_core import evaluate
from .work import E,c,finish
folder=Path(sys.argv[1]);label=sys.argv[2];report=evaluate(folder)
c.write(E/'reports'/(label+'_QUALITY_V4.json'),report);finish(report)
