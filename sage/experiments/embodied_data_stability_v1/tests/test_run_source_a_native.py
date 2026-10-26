from sage.experiments.embodied_data_stability_v1.run_source_a_native import json_safe


class ArrayLike:
    def tolist(self):
        return [1, 2, 3]


class ScalarLike:
    def item(self):
        return 4


def test_json_safe_handles_candidate_numeric_objects_without_importing_runtime():
    assert json_safe({"array": ArrayLike(), "scalar": ScalarLike(), "pair": (True, None)}) == {
        "array": [1, 2, 3],
        "scalar": 4,
        "pair": [True, None],
    }
