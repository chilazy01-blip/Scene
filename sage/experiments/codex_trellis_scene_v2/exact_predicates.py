from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


EXACT_PREDICATE_ABI = "scene-v2-expansion-predicates/v1"
EXACT_PREDICATE_CAPABILITY_SCHEMA = "codex_trellis_exact_predicate_capability_v1"
_SOURCE = Path(__file__).with_name("native_exact_predicates.cpp")
_LOCK = threading.Lock()
_CACHED: ExactPredicateBackend | None | bool = False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ExactPredicateBackend:
    library_path: Path
    source_hash: str
    library_hash: str
    compiler: str
    _library: Any

    @property
    def backend_id(self) -> str:
        return "native_expansion_predicates_v1"

    def orient2d(self, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> int:
        values = [np.ascontiguousarray(item, dtype=np.float64) for item in (a, b, c)]
        result = int(
            self._library.scene_v2_orient2d(
                *(
                    item.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
                    for item in values
                )
            )
        )
        if result not in {-1, 0, 1}:
            raise ValueError(
                "native orient2d input is outside the supported finite range"
            )
        return result

    def orient3d(
        self, a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray
    ) -> int:
        values = [np.ascontiguousarray(item, dtype=np.float64) for item in (a, b, c, d)]
        result = int(
            self._library.scene_v2_orient3d(
                *(
                    item.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
                    for item in values
                )
            )
        )
        if result not in {-1, 0, 1}:
            raise ValueError(
                "native orient3d input is outside the supported finite range"
            )
        return result

    def capability(self) -> dict[str, Any]:
        report = {
            "schema": EXACT_PREDICATE_CAPABILITY_SCHEMA,
            "available": True,
            "backend": self.backend_id,
            "abi": EXACT_PREDICATE_ABI,
            "arithmetic": "error_free_binary64_expansions",
            "predicates": ["orient2d", "orient3d"],
            "source_sha256": self.source_hash,
            "library_sha256": self.library_hash,
            "compiler": self.compiler,
            "compiler_flags": [
                "-O2",
                "-std=c++17",
                "-fno-fast-math",
                "-ffp-contract=off",
            ],
            "self_test": "passed",
        }
        report["capability_hash"] = hashlib.sha256(
            json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return report


def _load_library(path: Path, source_hash: str, compiler: str) -> ExactPredicateBackend:
    library = ctypes.CDLL(str(path))
    pointer = ctypes.POINTER(ctypes.c_double)
    library.scene_v2_orient2d.argtypes = [pointer, pointer, pointer]
    library.scene_v2_orient2d.restype = ctypes.c_int
    library.scene_v2_orient3d.argtypes = [pointer, pointer, pointer, pointer]
    library.scene_v2_orient3d.restype = ctypes.c_int
    library.scene_v2_exact_predicate_abi.argtypes = []
    library.scene_v2_exact_predicate_abi.restype = ctypes.c_char_p
    abi = library.scene_v2_exact_predicate_abi().decode("utf-8")
    if abi != EXACT_PREDICATE_ABI:
        raise RuntimeError(f"unexpected exact-predicate ABI: {abi}")
    backend = ExactPredicateBackend(path, source_hash, _sha256(path), compiler, library)
    if (
        backend.orient2d(
            np.array([0.0, 0.0]), np.array([1.0, 1.0]), np.array([2.0, 2.0])
        )
        != 0
    ):
        raise RuntimeError("native orient2d collinearity self-test failed")
    if (
        backend.orient2d(
            np.array([0.0, 0.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0])
        )
        != 1
    ):
        raise RuntimeError("native orient2d sign self-test failed")
    if (
        backend.orient3d(
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
            np.array([0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 1.0]),
        )
        != -1
    ):
        raise RuntimeError("native orient3d sign self-test failed")
    return backend


def build_exact_predicate_backend(output_directory: Path) -> ExactPredicateBackend:
    compiler_path = shutil.which("g++")
    if compiler_path is None:
        raise RuntimeError("g++ is unavailable")
    source_hash = _sha256(_SOURCE)
    output_directory.mkdir(parents=True, exist_ok=True)
    library_path = output_directory / f"libscene_v2_exact_{source_hash[:16]}.so"
    compiler_version = subprocess.run(
        [compiler_path, "--version"], check=True, capture_output=True, text=True
    ).stdout.splitlines()[0]
    if not library_path.exists():
        with tempfile.NamedTemporaryFile(
            prefix=f".{library_path.stem}.",
            suffix=".so",
            dir=output_directory,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            subprocess.run(
                [
                    compiler_path,
                    "-O2",
                    "-std=c++17",
                    "-shared",
                    "-fPIC",
                    "-fno-fast-math",
                    "-ffp-contract=off",
                    str(_SOURCE),
                    "-o",
                    str(temporary_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            os.replace(temporary_path, library_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
    return _load_library(library_path, source_hash, compiler_version)


def get_exact_predicate_backend(
    *, cache_directory: Path | None = None, force_reload: bool = False
) -> ExactPredicateBackend | None:
    """Build/load the native backend, returning None for an honest fallback."""

    global _CACHED
    if os.environ.get("SCENE_V2_DISABLE_EXACT_PREDICATES") == "1":
        return None
    with _LOCK:
        if not force_reload and isinstance(_CACHED, ExactPredicateBackend):
            return _CACHED
        directory = (
            cache_directory or Path(tempfile.gettempdir()) / "scene_v2_exact_predicates"
        )
        try:
            _CACHED = build_exact_predicate_backend(directory)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            _CACHED = None
        return _CACHED if isinstance(_CACHED, ExactPredicateBackend) else None


def exact_predicate_capability(
    *, cache_directory: Path | None = None
) -> dict[str, Any]:
    backend = get_exact_predicate_backend(cache_directory=cache_directory)
    if backend is not None:
        return backend.capability()
    return {
        "schema": EXACT_PREDICATE_CAPABILITY_SCHEMA,
        "available": False,
        "backend": "python_adaptive_triangle_v1",
        "verification_class": "floating_point_verified",
        "reason": "native backend could not be built or was explicitly disabled",
        "source_sha256": _sha256(_SOURCE),
    }
