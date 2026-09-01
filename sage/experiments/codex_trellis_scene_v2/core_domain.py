"""Shared domain boundary for every Scene entry point.

Front ends may interpret text or an image, but everything after ``SceneRequest``
and ``SceneBrief`` belongs to this package.  Keeping this object deliberately
small prevents a legacy front end from smuggling a second layout algorithm into
the canonical pipeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .content_chain import content_hash, file_binding


REQUEST_SCHEMA = "scene-v2-request/v1"
CORE_STAGE_OWNERSHIP = {
    "front_end": ("SceneRequest", "SceneBrief"),
    "v2_core": (
        "assets",
        "typed_relations",
        "layout",
        "repair",
        "assembly",
        "acceptance",
    ),
}


@dataclass(frozen=True)
class SceneRequest:
    prompt: str
    output_dir: str
    source: Literal["text", "image_reference"] = "text"
    room_type: str | None = None
    profile: str = "development"
    asset_mode: str = "plan"
    reference_image: dict[str, Any] | None = None
    adapter: str = "scene_v2_cli"
    compatibility_notes: tuple[str, ...] = field(default_factory=tuple)
    schema: str = REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("SceneRequest.prompt must not be empty")
        if self.source == "image_reference" and not self.reference_image:
            raise ValueError("image_reference requests require a bound reference image")

    @classmethod
    def create(
        cls,
        *,
        prompt: str,
        output_dir: Path | str,
        source: str = "text",
        room_type: str | None = None,
        profile: str = "development",
        asset_mode: str = "plan",
        reference_image: Path | str | None = None,
        adapter: str = "scene_v2_cli",
        compatibility_notes: tuple[str, ...] = (),
    ) -> "SceneRequest":
        binding = None
        if reference_image is not None:
            path = Path(reference_image).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"reference image not found: {path}")
            binding = {"path": str(path), **file_binding(path)}
        return cls(
            prompt=prompt.strip(),
            output_dir=str(Path(output_dir).expanduser().resolve()),
            source=source,  # type: ignore[arg-type]
            room_type=room_type,
            profile=profile,
            asset_mode=asset_mode,
            reference_image=binding,
            adapter=adapter,
            compatibility_notes=compatibility_notes,
        )

    def as_document(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["core_stage_ownership"] = CORE_STAGE_OWNERSHIP
        payload["content_hash"] = content_hash(payload)
        return payload


def request_from_pipeline_args(args: Any, prompt: str) -> SceneRequest:
    supplied = getattr(args, "scene_request", None)
    if supplied is not None:
        if not isinstance(supplied, SceneRequest):
            raise TypeError("args.scene_request must be a SceneRequest")
        if supplied.prompt != prompt.strip():
            raise ValueError("adapter SceneRequest prompt differs from pipeline prompt")
        return supplied
    return SceneRequest.create(
        prompt=prompt,
        output_dir=args.output_dir,
        room_type=getattr(args, "room_type", None),
        profile=str(getattr(args, "profile", "development")),
        asset_mode=str(getattr(args, "asset_mode", "plan")),
    )
