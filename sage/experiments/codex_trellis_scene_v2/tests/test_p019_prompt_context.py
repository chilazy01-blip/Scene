from __future__ import annotations

import unittest
from types import SimpleNamespace

from sage.server.trellis2_flux_bridge_server import Trellis2BridgeRuntime


# Inputs from the original P019 frozen plan, kept here so the regression does
# not depend on mutable service state or local experiment artifacts.
REFERENCE_SUFFIX = (
    "Seamless pure white background. Centered full-object three-quarter view "
    "with generous empty margins. Photorealistic product reference for 3D "
    "reconstruction, soft even lighting, clear silhouette. No room, floor, "
    "horizon, cast shadow, reflection, platform, pedestal, plinth, base plate, "
    "props, text, or duplicate."
)
SOFA = (
    "One warm beige fabric two-seat sofa with two seat cushions, two back "
    "cushions, two armrests and four separate dark wooden legs. Clearly open "
    "air beneath the seat between legs; no connected lower slab. "
    + REFERENCE_SUFFIX
)
BOOKCASE = (
    "One light oak freestanding bookcase with exactly three empty open "
    "compartments stacked vertically, two side panels and a thin back panel. "
    "All compartment openings are clearly visible; no books, doors, glass, "
    "or extra base. " + REFERENCE_SUFFIX
)
STORAGE_BOX = (
    "One rectangular muted sage woven-fabric storage box with a fitted closed "
    "lid and two small tan leather handles, one on each side. Soft fabric body, "
    "clearly visible fabric weave, no feet or display base. " + REFERENCE_SUFFIX
)

# Exact composed output captured before fixing the light-oak misclassification.
ORIGINAL_PROMPT_END = (
    "White void only: no horizon, floor plane, contact shadow, reflection, "
    "rug, platform, pedestal, plinth, base plate, props, text, or duplicate. "
    "The background must remain visually separate from the entire object silhouette."
)
ORIGINAL_SOFA_PREFIX = (
    "One isolated warm beige fabric two-seat sofa with two seat cushions, "
    "two back cushions, two armrests and four separate dark wooden legs "
    "Clearly open air. seamless pure white background (#FFFFFF); centered "
    "full-object 3/4 view. Show visible separated supports or casters with "
    "white gaps beneath the body. "
)
ORIGINAL_STORAGE_BOX_PREFIX = (
    "One isolated rectangular muted sage woven-fabric storage box with a "
    "fitted closed lid and two small tan leather handles, one on each side "
    "Soft fabric. seamless pure white background (#FFFFFF); centered "
    "full-object 3/4 view. "
)


class P019PromptContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Trellis2BridgeRuntime(SimpleNamespace(
            flux_background_mode="white", flux_retry_count=0,
            flux_profile="flux1-schnell", flux_width=1024, flux_height=1024,
            flux_steps=4, flux_guidance_scale=0.0, flux_max_sequence_length=None,
        ))

    def test_frozen_light_oak_bookcase_does_not_add_a_lamp(self) -> None:
        for attempt in (0, 1):
            with self.subTest(attempt=attempt):
                prompt = self.runtime._compose_flux_prompt(BOOKCASE, attempt=attempt)
                self.assertIn("light oak freestanding bookcase", prompt)
                self.assertNotIn("lamp", prompt)
                self.assertNotIn("lantern", prompt)

    def test_color_and_illumination_descriptions_do_not_allow_a_lamp_base(self) -> None:
        for description in (
            "One light oak freestanding bookcase",
            "One light-oak freestanding bookcase",
            "One light beige cabinet",
            "One light blue storage box",
            "One bookcase photographed in soft even lighting",
            "One cabinet photographed in soft light",
            "One storage box photographed in natural light",
            "One bookcase photographed with ceiling lighting",
            "One box with bright highlights",
            "One lampwork glass vase",
        ):
            for attempt in (0, 1):
                with self.subTest(description=description, attempt=attempt):
                    clause = self.runtime._white_base_prompt_clause(description, attempt)
                    self.assertNotIn("lamp", clause)
                    self.assertNotIn(
                        "A built-in lamp base is allowed",
                        self.runtime._compose_flux_prompt(description, attempt=attempt),
                    )

    def test_explicit_luminaire_nouns_keep_the_lamp_base_clause(self) -> None:
        for noun in (
            "lamp", "lantern", "floor light", "pendant light", "ceiling light",
            "table light", "desk light", "wall light", "floor-light",
            "pendant_light", "CEILING LIGHT", "floor   light",
            "lamps", "lanterns", "wall lights",
        ):
            for attempt in (0, 1):
                with self.subTest(noun=noun, attempt=attempt):
                    prompt = self.runtime._compose_flux_prompt(
                        f"One light beige {noun}", attempt=attempt,
                    )
                    self.assertIn("A built-in lamp base is allowed.", prompt)

    def test_background_light_gray_does_not_allow_a_lamp_base(self) -> None:
        self.runtime.args.flux_background_mode = "gray"
        prompt = self.runtime._compose_flux_prompt("One freestanding bookcase")
        self.assertIn("light gray background", prompt)
        self.assertNotIn("lamp", prompt)

    def test_frozen_sofa_and_storage_box_composed_prompts_are_unchanged(self) -> None:
        for description, original_prefix in (
            (SOFA, ORIGINAL_SOFA_PREFIX),
            (STORAGE_BOX, ORIGINAL_STORAGE_BOX_PREFIX),
        ):
            for attempt, original_retry in (
                (0, ""),
                (1, "Retry without staging geometry. "),
            ):
                with self.subTest(description=description, attempt=attempt):
                    self.assertEqual(
                        self.runtime._compose_flux_prompt(description, attempt=attempt),
                        original_prefix + original_retry + ORIGINAL_PROMPT_END,
                    )

    def test_both_provider_contracts_record_the_changed_prompt_template(self) -> None:
        for provider in ("builtin_imagegen", "flux1-schnell"):
            with self.subTest(provider=provider):
                self.assertEqual(
                    self.runtime.image_provider_contract(provider)["prompt_template_version"],
                    "isolated-white-v2-light-noun",
                )


if __name__ == "__main__":
    unittest.main()
