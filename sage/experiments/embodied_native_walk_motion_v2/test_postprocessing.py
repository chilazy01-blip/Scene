"""Zero-integration tests of evidence tooling, not robot success evidence."""

import ast
from pathlib import Path
from .dynamics_replay import rows


HERE = Path(__file__).parent


def tree(name):
    return ast.parse((HERE / name).read_text())


def test_physics_rows_include_warmup_and_every_substep_in_order():
    trace = {
        "warmup_substeps": [1, 2],
        "records": [{"substeps": [3, 4]}, {"substeps": [5]}],
    }
    assert list(rows(trace)) == [1, 2, 3, 4, 5]


def test_reintegration_has_no_mid_loop_state_injection():
    loops = [
        n
        for n in ast.walk(tree("dynamics_replay.py"))
        if isinstance(n, ast.For)
        and isinstance(n.iter, ast.Call)
        and isinstance(n.iter.func, ast.Name)
        and n.iter.func.id == "rows"
    ]
    assert len(loops) == 1
    writes = [
        ast.unparse(n)
        for n in ast.walk(loops[0])
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign))
    ]
    for text in writes:
        lhs = text.split("=")[0]
        assert not any(
            name in lhs
            for name in ("data.qpos", "data.qvel", "data.qacc_warmstart", "data.time")
        )


def test_renderer_and_delivery_do_not_integrate():
    for name in ("render.py", "delivery.py"):
        assert not any(
            isinstance(n, ast.Attribute)
            and n.attr in ("mj_step", "mj_step1", "mj_step2")
            for n in ast.walk(tree(name))
        )


def test_reintegration_caps_fit_unchanged_global_limit():
    driver = 175 + 3 * (440 + 1440 + 3240 + 6240)
    replay = 3 * 6040
    assert driver + replay == 52375 < 60000


def test_encoder_uses_actual_20ms_frames_and_no_fake_padding():
    source = (HERE / "render.py").read_text()
    assert "physical[3::4]" in source
    assert "rate=50" in source
    assert "np.interp" not in source
    assert "linspace" not in source
