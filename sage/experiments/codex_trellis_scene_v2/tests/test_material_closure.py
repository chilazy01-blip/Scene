from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from ..material_closure import (
    ROUTE_EXACT,
    ROUTE_REGENERATE,
    ROUTE_REMATERIALIZE,
    audit_glb_materials,
    derived_material_cache_key,
    load_material_library,
    publish_derived_material_cache,
    route_material_request,
)


ROOT = Path(__file__).parents[1]
LIBRARY = ROOT / "capabilities" / "p018_material_library_v1.json"


def slot(role: str, family: str, **overrides):
    value = {
        "slot_id": f"slot_{role}",
        "semantic_role": role,
        "allowed_material_families": [family],
        "rematerializable": True,
        "requires_uv": True,
        "uv_available": True,
        "uv_quality": "reviewed",
        "allowed_alpha_modes": ["OPAQUE"],
        "allows_double_sided": True,
        "minimum_texel_density_px_m": 512.0,
    }
    value.update(overrides)
    return value


class MaterialRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packages = load_material_library(LIBRARY)

    def test_exact_reuse_precedes_rematerialization(self) -> None:
        result = route_material_request(
            slot("furniture_wood", "wood"),
            self.packages["light_oak_satin_v1"],
            current_package_id="light_oak_satin_v1",
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["route"], ROUTE_EXACT)

    def test_compatible_wood_and_fabric_use_controlled_path(self) -> None:
        wood = route_material_request(
            slot("furniture_wood", "wood"),
            self.packages["smoked_walnut_satin_v1"],
            current_package_id="light_oak_satin_v1",
        )
        fabric = route_material_request(
            slot("upholstery", "fabric"),
            self.packages["muted_sage_wool_v1"],
            current_package_id="cream_boucle_v1",
        )
        self.assertEqual(wood["route"], ROUTE_REMATERIALIZE)
        self.assertEqual(fabric["route"], ROUTE_REMATERIALIZE)

    def test_cross_semantic_glass_to_upholstery_is_hard_rejected(self) -> None:
        result = route_material_request(
            slot("upholstery", "fabric"), self.packages["clear_glass_v1"]
        )
        self.assertEqual(result["route"], ROUTE_REGENERATE)
        self.assertIn("semantic_slot_role_incompatible", result["hard_gate_failures"])
        self.assertIn("material_family_incompatible", result["hard_gate_failures"])
        self.assertIn("alpha_mode_incompatible", result["hard_gate_failures"])

    def test_textured_rematerialization_without_uv_is_hard_rejected(self) -> None:
        result = route_material_request(
            slot(
                "furniture_wood",
                "wood",
                requires_uv=False,
                uv_available=False,
                uv_quality="missing",
            ),
            self.packages["smoked_walnut_satin_v1"],
        )
        self.assertEqual(result["route"], ROUTE_REGENERATE)
        self.assertIn("textured_package_requires_uv", result["hard_gate_failures"])

    def test_cache_key_invalidates_every_material_input(self) -> None:
        base = dict(
            geometry_hash="g",
            material_package_hash="p",
            slot_binding={"slot": 1},
            uv_transform={"scale": [1, 1]},
            renderer_version="r",
        )
        key = derived_material_cache_key(**base)
        for field, value in (
            ("geometry_hash", "g2"),
            ("material_package_hash", "p2"),
            ("slot_binding", {"slot": 2}),
            ("uv_transform", {"scale": [2, 1]}),
            ("renderer_version", "r2"),
        ):
            modified = dict(base)
            modified[field] = value
            self.assertNotEqual(key, derived_material_cache_key(**modified))

    def test_derivative_cache_is_immutable_and_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.glb"
            derived = root / "derived.glb"
            source.write_bytes(b"source")
            derived.write_bytes(b"derived")
            key = derived_material_cache_key(
                geometry_hash="g",
                material_package_hash="p",
                slot_binding={"slot": 1},
                uv_transform={"scale": [1, 1]},
                renderer_version="r",
            )
            first = publish_derived_material_cache(
                source_glb=source,
                derived_glb=derived,
                cache_root=root / "cache",
                cache_key=key,
                contract={"binding": "reviewed"},
            )
            second = publish_derived_material_cache(
                source_glb=source,
                derived_glb=derived,
                cache_root=root / "cache",
                cache_key=key,
                contract={"binding": "reviewed"},
            )
            self.assertFalse(first["cache_hit"])
            self.assertTrue(second["cache_hit"])
            Path(second["artifact"]).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "stale or corrupt"):
                publish_derived_material_cache(
                    source_glb=source,
                    derived_glb=derived,
                    cache_root=root / "cache",
                    cache_key=key,
                    contract={"binding": "reviewed"},
                )


class GlbAuditTests(unittest.TestCase):
    def test_minimal_factor_only_glb_audits_without_texture(self) -> None:
        document = {
            "asset": {"version": "2.0"},
            "materials": [
                {
                    "name": "factor_only",
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.2, 0.3, 0.4, 1.0],
                        "metallicFactor": 0.0,
                        "roughnessFactor": 0.8,
                    },
                }
            ],
            "meshes": [
                {
                    "primitives": [
                        {"material": 0, "attributes": {"POSITION": 0, "NORMAL": 1}}
                    ]
                }
            ],
        }
        payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
        payload += b" " * ((4 - len(payload) % 4) % 4)
        total = 12 + 8 + len(payload)
        glb = (
            struct.pack("<III", 0x46546C67, 2, total)
            + struct.pack("<II", len(payload), 0x4E4F534A)
            + payload
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.glb"
            path.write_bytes(glb)
            report = audit_glb_materials(path)
        self.assertTrue(report["ok"])
        self.assertEqual(report["material_count"], 1)
        self.assertEqual(report["texture_count"], 0)


if __name__ == "__main__":
    unittest.main()
