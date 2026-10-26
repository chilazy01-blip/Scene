from sage.experiments.embodied_data_stability_v1.run_source_a_adapter_smoke import equivalent


def test_equivalent_handles_nested_numeric_evidence():
    left = {"ok": [True, 1.0, {"x": 2.0}]}
    right = {"ok": [True, 1.0 + 1e-10, {"x": 2}]}
    assert equivalent(left, right)
    assert not equivalent(left, {"ok": [True, 1.1, {"x": 2}]})
