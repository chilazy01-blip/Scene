"""Serialize shared-ledger mutations; per-episode physics and files remain independent."""
import fcntl
from pathlib import Path
from .protocol import authorize,make_task,project_target,read_bound_json,safe_save,_file_binding,spent_steps
from .protocol import reserve as unlocked_reserve


def reserve(root,output,ceiling):
    p=authorize(root)
    with (Path(p['ledger_root'])/'COST.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        return unlocked_reserve(root,output,ceiling)
