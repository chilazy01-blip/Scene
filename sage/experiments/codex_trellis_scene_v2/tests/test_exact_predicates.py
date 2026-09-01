from __future__ import annotations

import random
import unittest
from fractions import Fraction

import numpy as np

from sage.experiments.codex_trellis_scene_v2.exact_predicates import (
    get_exact_predicate_backend,
)


def sign(value: Fraction) -> int:
    return (value > 0) - (value < 0)


def orient2d_fraction(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> int:
    values = [
        [Fraction.from_float(float(item)) for item in point] for point in (a, b, c)
    ]
    return sign(
        (values[1][0] - values[0][0]) * (values[2][1] - values[0][1])
        - (values[1][1] - values[0][1]) * (values[2][0] - values[0][0])
    )


def orient3d_fraction(
    a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray
) -> int:
    rows = [
        [
            Fraction.from_float(float(point[index]))
            - Fraction.from_float(float(d[index]))
            for index in range(3)
        ]
        for point in (a, b, c)
    ]
    determinant = (
        rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
        - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
        + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0])
    )
    return sign(determinant)


class ExactPredicateTest(unittest.TestCase):
    def test_native_signs_match_fraction_oracle(self) -> None:
        backend = get_exact_predicate_backend(force_reload=True)
        self.assertIsNotNone(backend)
        generator = random.Random(20260901)
        for _ in range(200):
            points2 = [
                np.asarray([generator.uniform(-10, 10), generator.uniform(-10, 10)])
                for _ in range(3)
            ]
            self.assertEqual(backend.orient2d(*points2), orient2d_fraction(*points2))
            points3 = [
                np.asarray([generator.uniform(-10, 10) for _ in range(3)])
                for _ in range(4)
            ]
            self.assertEqual(backend.orient3d(*points3), orient3d_fraction(*points3))

    def test_near_collinear_sign_survives_float_cancellation(self) -> None:
        backend = get_exact_predicate_backend(force_reload=True)
        self.assertIsNotNone(backend)
        a = np.asarray([0.0, 0.0])
        b = np.asarray([1.0, 1.0])
        c = np.asarray([2.0, 2.0 + 2.0**-50])
        self.assertEqual(backend.orient2d(a, b, c), 1)
        self.assertEqual(backend.orient2d(a, c, b), -1)


if __name__ == "__main__":
    unittest.main()
