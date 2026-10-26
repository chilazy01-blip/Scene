from __future__ import annotations

import unittest

from sage.experiments.codex_trellis_scene_v2.architecture import plan_architecture
from sage.experiments.codex_trellis_scene_v2.policies import room_policy


def brief(prompt: str, styles: list[str], room_type: str = "living_room") -> dict:
    policy = room_policy(room_type)
    return {
        "room_type": room_type,
        "room": policy["room"],
        "architecture": policy["architecture"],
        "original_prompt": prompt,
        "expanded_description": prompt,
        "styles": styles,
    }


class ArchitectureStyleProfileTests(unittest.TestCase):
    def test_warm_contemporary_coordinates_shell_and_openings(self) -> None:
        document = brief(
            "a warm contemporary living room with light oak and cream boucle",
            ["warm contemporary", "light oak"],
        )
        report = plan_architecture(document)
        architecture = report["architecture"]
        self.assertEqual(
            architecture["wall_finish"]["default"]["material_id"],
            "soft_beige_limewash",
        )
        self.assertEqual(
            architecture["wall_finish"]["overrides"]["north"]["material_id"],
            "vertical_light_oak_slat",
        )
        self.assertEqual(
            architecture["doors"][0]["finish_profile"]["profile_id"],
            "warm_oak_brass",
        )
        self.assertEqual(
            architecture["windows"][0]["finish_profile"]["profile_id"],
            "dark_bronze",
        )

    def test_industrial_profile_uses_brick_and_steel(self) -> None:
        report = plan_architecture(
            brief("an industrial loft living room", ["industrial"])
        )
        architecture = report["architecture"]
        self.assertEqual(
            next(iter(architecture["wall_finish"]["overrides"].values()))[
                "material_id"
            ],
            "soft_red_brick",
        )
        self.assertEqual(
            architecture["doors"][0]["finish_profile"]["profile_id"],
            "charcoal_steel",
        )
        self.assertEqual(
            architecture["windows"][0]["finish_profile"]["profile_id"],
            "charcoal_steel",
        )

    def test_explicit_materials_remain_authoritative(self) -> None:
        report = plan_architecture(
            brief("a warm contemporary room", ["warm contemporary"]),
            wall_material_override="blue_gray_matte_paint",
            accent_wall_override="west",
            accent_wall_material_override="natural_linen_wallpaper",
        )
        finish = report["architecture"]["wall_finish"]
        self.assertEqual(finish["default"]["material_id"], "blue_gray_matte_paint")
        self.assertEqual(
            finish["overrides"]["west"]["material_id"],
            "natural_linen_wallpaper",
        )


if __name__ == "__main__":
    unittest.main()
