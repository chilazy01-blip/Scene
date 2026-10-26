"""Zero-step regression of source-only revision and evidence serialization."""

import ast
import json
from pathlib import Path
import numpy as np
from .report_safe_engine import plain

HERE=Path(__file__).parent


def test_json_numpy_scalar_boundary_preserves_values():
    value={'passed':np.bool_(True),'float':np.float64(.125),'rows':[np.int64(4),np.bool_(False)]}
    assert json.loads(json.dumps(plain(value)))=={'passed':True,'float':.125,'rows':[4,False]}


def test_second_task_only_changes_planning_tolerance():
    original=(HERE/'task.py').read_text();revised=(HERE/'task_v2.py').read_text()
    assert ast.dump(ast.parse(revised))==ast.dump(ast.parse(original.replace('> 0.005','> 0.010')))


def test_audits_and_counterfactuals_never_integrate():
    for name in ('audit.py','audit_v2.py','failure_probe.py','command_probe.py'):
        tree=ast.parse((HERE/name).read_text())
        assert not any(isinstance(n,ast.Attribute) and n.attr in ('mj_step','mj_step1','mj_step2') for n in ast.walk(tree))


def test_no_physical_root_or_object_write_inside_execution_loops():
    for name in ('engine.py','engine_v2.py'):
        tree=ast.parse((HERE/name).read_text())
        for loop in [n for n in ast.walk(tree) if isinstance(n,(ast.For,ast.While))]:
            for statement in ast.walk(loop):
                if isinstance(statement,ast.Assign):
                    for target in statement.targets:
                        lhs=ast.unparse(target)
                        assert not any(part in lhs for part in ('data.qpos','data.qvel','data.time','data.xfrc_applied','data.qfrc_applied'))
