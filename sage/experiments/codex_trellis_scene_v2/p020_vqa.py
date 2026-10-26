"""Isolated P020 atomic Qwen observations; never a production admission certificate.

Importing, parsing and constructing this module do not import torch or load models.
The caller owns resource admission, persistence, and eligibility for style comparison.
No expected answer, contrast text, crop, retry or probability is sent/invented here.
"""

from __future__ import annotations

import gc
import hashlib
import io
import json
import math
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from .content_chain import content_hash, file_binding


MODEL_ID = "Qwen/Qwen3-VL-2B-Instruct"
MODEL_REVISION = "89644892e4d85e24eaac8bacfd4f463576704203"
SCHEMA = "scene-v2-p020-atomic-vqa/v1"
ATOMIC_PROMPT_VERSION = "p020_atomic_batch_v2"
ATOMIC_PARSER_VERSION = "p020_explicit_quantifier_counterexamples_v1"
OBSERVABILITY = {"visible", "partial", "not_visible", "uncertain"}
UNKNOWN_WORDS = {"unknown", "uncertain", "unclear", "not visible", "not_visible", "cannot determine",
                 "cannot tell", "undetermined", "unobservable", "unsure", "n/a", "无法确定", "看不清"}

ATOMIC_INSTRUCTIONS = """Observe the entire image. Answer ALL questions in the batch,
including questions whose answers are unknown. Do not stop after the first question.
Your response must be one complete JSON object with the single outer key \"answers\".
The value of \"answers\" must be an array, not a single answer object.
Every requested ID must occur exactly once, in the requested order.
Every row must contain id, answer, observability, evidence_bbox and evidence.
Keep each evidence description to at most 12 words. Use concise JSON, no markdown.
Do not infer hidden parts from object stereotypes or from the wording of a question.
Use JSON boolean true/false for yes/no questions, a nonnegative integer for counts,
or a short string for other questions. Counts are unquoted numbers, never strings.
Use null when the answer cannot be determined; still include that question's row.
Observability is one of visible,
partial, not_visible, uncertain. 'visible' means the whole scope needed to decide the
question is visible, not merely that a part of the object can be seen.
An exact count requires complete scope and distinguishable instances; partial views
give no exact count. An absence answer requires visibility of the entire relevant area.
Evidence_bbox is [x_min,y_min,x_max,y_max] in coordinates 0..1000 relative to the
whole displayed image, with positive width and height, or null if not localizable.
For a visible zero count, localize the entire inspected area. Do not invent boxes.
White may be transparency composited for display; it is not evidence of object structure.

This is a FORMAT EXAMPLE for a different two-question task. Its example IDs and
answers are unrelated to the current image. Do not copy them into your response.
BEGIN FORMAT EXAMPLE
{\"answers\":[{\"id\":\"example_count\",\"answer\":2,\"observability\":\"visible\",\"evidence_bbox\":[100,100,900,900],\"evidence\":\"Two example objects are fully visible.\"},{\"id\":\"example_hidden\",\"answer\":null,\"observability\":\"not_visible\",\"evidence_bbox\":null,\"evidence\":\"The relevant surface is hidden.\"}]}
END FORMAT EXAMPLE
"""

STYLE_INSTRUCTIONS = """Compare only the visual style of these two complete images
against the style description below. The first image is LEFT and the second is RIGHT.
Consider material, color and form coherence with the description. Do not use the
display order as a preference. The caller handles hard-requirement eligibility.
Return one JSON object only: {\"winner\":\"left\",\"evidence\":\"visible reasons\"}.
winner must be left, right, tie or unknown. Use tie for no discernible preference;
use unknown when the evidence is insufficient. Do not report a probability.
Style description:
"""


def validate_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject malformed contracts before any inference; retain caller order."""
    requirements = contract.get("requirements") if isinstance(contract, dict) else None
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("contract requires a nonempty requirements list")
    by_id: dict[str, dict[str, Any]] = {}
    for item in requirements:
        if not isinstance(item, dict):
            raise ValueError("each requirement must be an object")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in by_id:
            raise ValueError("requirement IDs must be unique nonempty strings")
        if not isinstance(item.get("question"), str) or not item["question"].strip():
            raise ValueError(f"invalid question: {identifier}")
        expected = item.get("expected")
        if type(expected) not in (bool, int, str):
            raise ValueError(f"invalid expected type: {identifier}")
        if type(expected) is int and expected < 0:
            raise ValueError(f"count must be nonnegative: {identifier}")
        if isinstance(expected, str) and not expected.strip():
            raise ValueError(f"empty expected answer: {identifier}")
        if type(item.get("hard")) is not bool:
            raise ValueError(f"hard must be a boolean: {identifier}")
        dependencies = item.get("depends_on")
        if not isinstance(dependencies, list) or any(not isinstance(d, str) for d in dependencies):
            raise ValueError(f"depends_on must be a list of IDs: {identifier}")
        if len(set(dependencies)) != len(dependencies):
            raise ValueError(f"duplicate dependency: {identifier}")
        by_id[identifier] = item
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise ValueError("cyclic requirement dependencies")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in by_id[identifier]["depends_on"]:
            if dependency not in by_id:
                raise ValueError(f"unknown dependency: {dependency}")
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in by_id:
        visit(identifier)
    return deepcopy(requirements)


def _wire_contract(contract: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Opaque IDs prevent semantic identifiers such as no_legs leaking answers."""
    requirements = validate_contract(contract)
    real_to_wire = {item["id"]: f"q{index:03d}" for index, item in enumerate(requirements)}
    wire_to_real = {wire: real for real, wire in real_to_wire.items()}
    for item in requirements:
        item["id"] = real_to_wire[item["id"]]
        item["depends_on"] = [real_to_wire[parent] for parent in item["depends_on"]]
    return {"requirements": requirements}, wire_to_real


def build_atomic_prompt(contract: dict[str, Any]) -> str:
    wire, _ = _wire_contract(contract)
    questions = [{"id": item["id"], "question": item["question"]}
                 for item in wire["requirements"]]
    count = len(questions)
    ids = ", ".join(item["id"] for item in questions)
    return (
        f"BATCH SIZE: {count} questions. Return exactly {count} rows in the answers array.\n"
        + ATOMIC_INSTRUCTIONS
        + f"\nACTUAL QUESTIONS ({count} rows required):\n"
        + json.dumps(questions, ensure_ascii=False, indent=2)
        + f"\n\nAnswer ALL {count} questions now. Return the complete {{\"answers\":[...]}} object.\n"
        + f"Required IDs in order: {ids}.\n"
        + f"The answers array must contain exactly {count} rows. Include null answers when unknown; "
        + "never omit an ID. Finish only after the last requested ID and close the array and object."
    )


def _strict_json(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ValueError("response is not text")
    text = raw.strip()
    # Allow a single JSON fence, but never extract a convenient object from prose.
    match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, flags=re.DOTALL)
    if match:
        text = match.group(1).strip()

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    result = json.loads(text, object_pairs_hook=unique_keys, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("response root must be an object")
    return result


def _valid_bbox(box: Any) -> bool:
    return (
        isinstance(box, list) and len(box) == 4
        and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1000 for v in box)
        and box[0] < box[2] and box[1] < box[3]
    )


def _observation(item: dict[str, Any], row: dict[str, Any] | None, reason: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": item["id"], "hard": item["hard"], "expected": item["expected"],
        "quantifier": item.get("quantifier"),
        "answer": None, "observability": "uncertain", "evidence_bbox": None,
        "evidence": "", "verdict": "unknown", "reason": reason, "blocked_by": [],
    }
    if reason or row is None:
        result["reason"] = reason or "missing_answer"
        return result
    required = {"id", "answer", "observability", "evidence_bbox", "evidence"}
    if set(row) != required:
        result["reason"] = "invalid_answer_fields"
        return result
    answer, visibility, box, evidence = (row[key] for key in (
        "answer", "observability", "evidence_bbox", "evidence"))
    # Preserve valid raw observations for audit even if they cannot establish a verdict.
    if type(answer) in (bool, int, str) or answer is None:
        result["answer"] = answer
    if isinstance(visibility, str) and visibility in OBSERVABILITY:
        result["observability"] = visibility
    if isinstance(evidence, str):
        result["evidence"] = evidence
    if box is not None and not _valid_bbox(box):
        result["reason"] = "invalid_evidence_bbox"
        return result
    result["evidence_bbox"] = box
    if not isinstance(visibility, str) or visibility not in OBSERVABILITY:
        result["reason"] = "invalid_observability"
    elif not isinstance(evidence, str) or not evidence.strip():
        result["reason"] = "missing_evidence"
    elif answer is None or (isinstance(answer, str) and answer.strip().casefold() in UNKNOWN_WORDS):
        result["reason"] = "unknown_answer"
    elif type(answer) is not type(item["expected"]) or (type(answer) is int and answer < 0):
        result["reason"] = "invalid_answer_type"
    elif visibility == "partial":
        # A localized witness can disprove absence or exceed an exact count
        # without claiming that the full scope is observed. Inferred quantities
        # and untagged booleans/counts do not have these semantics.
        if (box is not None and item.get("quantifier") == "absence"
                and type(item["expected"]) is bool and item["expected"] is False
                and answer is True):
            result.update(verdict="fail", reason="visible_counterexample")
        elif (box is not None and item.get("quantifier") == "exact_count"
                and type(answer) is int and answer > item["expected"]):
            result.update(verdict="fail", reason="observed_count_lower_bound_exceeds_expected")
        else:
            result["reason"] = "insufficient_observability"
    elif visibility != "visible":
        result["reason"] = "insufficient_observability"
    elif type(answer) is int and box is None:
        result["reason"] = "count_requires_localized_evidence"
    elif item["hard"] and box is None:
        result["reason"] = "hard_requirement_requires_localized_evidence"
    else:
        expected = item["expected"]
        matches = (answer.strip().casefold() == expected.strip().casefold()
                   if isinstance(answer, str) else answer == expected)
        result.update(verdict="pass" if matches else "fail", reason="answer_matches" if matches else "answer_mismatch")
    return result


def parse_atomic_response(raw: str, contract: dict[str, Any]) -> dict[str, Any]:
    """Parse strict observations, explicit quantified counterexamples and DAG blocking."""
    requirements = validate_contract(contract)
    by_id = {item["id"]: item for item in requirements}
    rows: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    errors: list[str] = []
    fatal: str | None = None
    try:
        document = _strict_json(raw)
        if set(document) != {"answers"} or not isinstance(document["answers"], list):
            raise ValueError("response must contain only an answers array")
        for row in document["answers"]:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ValueError("answer row has invalid ID")
            identifier = row["id"]
            if identifier not in by_id:
                raise ValueError(f"unexpected answer ID: {identifier}")
            if identifier in rows:
                duplicates.add(identifier)
            rows[identifier] = row
    except (ValueError, TypeError, RecursionError) as error:
        fatal = "parse_failure"
        errors.append(f"{type(error).__name__}: {error}")
    results: dict[str, dict[str, Any]] = {}

    def evaluate(identifier: str) -> dict[str, Any]:
        if identifier in results:
            return results[identifier]
        item = by_id[identifier]
        reason = fatal or ("duplicate_answer" if identifier in duplicates else None)
        result = _observation(item, rows.get(identifier), reason)
        blocked = [dep for dep in item["depends_on"] if evaluate(dep)["verdict"] != "pass"]
        if blocked:
            result["unblocked_verdict"] = result["verdict"]
            result["unblocked_reason"] = result["reason"]
            result.update(verdict="unknown", reason="blocked_unknown", blocked_by=blocked)
        results[identifier] = result
        return result

    ordered = [evaluate(item["id"]) for item in requirements]
    syntax_reasons = {"missing_answer", "duplicate_answer", "invalid_answer_fields", "invalid_evidence_bbox",
                      "invalid_observability", "invalid_answer_type"}
    for result in ordered:
        reason = result.get("unblocked_reason", result["reason"])
        if reason in syntax_reasons:
            errors.append(f"{result['id']}:{reason}")
    hard = [result for result in ordered if result["hard"]]
    verdict = ("fail" if any(row["verdict"] == "fail" for row in hard) else
               "unknown" if not hard or errors or any(row["verdict"] != "pass" for row in hard) else "pass")
    return {
        "schema": SCHEMA, "method": "B", "verdict_kind": "uncalibrated_vqa_prediction",
        "parser_version": ATOMIC_PARSER_VERSION,
        "requirements": ordered, "verdict": verdict, "accepted": verdict == "pass",
        "acceptance_scope": "vqa_contract_predictions_only_not_asset_admission",
        "parse_ok": not errors, "parse_errors": errors,
        "counts": {state: sum(row["verdict"] == state for row in ordered) for state in ("pass", "fail", "unknown")},
    }


def parse_style_response(raw: str) -> dict[str, Any]:
    try:
        document = _strict_json(raw)
        if set(document) != {"winner", "evidence"}:
            raise ValueError("style response requires only winner and evidence")
        winner = document["winner"]
        if not isinstance(winner, str) or winner not in {"left", "right", "tie", "unknown"}:
            raise ValueError("invalid style winner")
        if not isinstance(document["evidence"], str) or not document["evidence"].strip():
            raise ValueError("missing style evidence")
        return {**document, "parse_ok": True, "parse_errors": []}
    except (ValueError, TypeError, RecursionError) as error:
        return {"winner": "unknown", "evidence": "", "parse_ok": False,
                "parse_errors": [f"{type(error).__name__}: {error}"]}


def reconcile_style(forward: dict[str, Any], reverse: dict[str, Any]) -> dict[str, Any]:
    """Map the reverse answer to original identities; never vote by screen position."""
    mapping = {"left": "right", "right": "left", "tie": "tie", "unknown": "unknown"}
    first = forward.get("winner", "unknown")
    second = mapping.get(reverse.get("winner"), "unknown")
    if not forward.get("parse_ok") or not reverse.get("parse_ok") or "unknown" in (first, second):
        winner, reason = "unknown", "insufficient_or_invalid_comparison"
    elif first != second:
        winner, reason = "unknown", "order_disagreement"
    else:
        winner, reason = first, "swap_consistent"
    return {"winner": winner, "reason": reason,
            "forward_winner_original": first, "reverse_winner_original": second,
            "order_disagreement": first != second and "unknown" not in (first, second)}


def prepare_image(image_path: str | Path) -> tuple[Any, dict[str, Any]]:
    """Decode the bound bytes once, orient and composite white without touching disk."""
    from PIL import Image, ImageOps

    path = Path(image_path)
    data = path.read_bytes()
    with Image.open(io.BytesIO(data)) as source:
        original_mode, original_size = source.mode, list(source.size)
        original_orientation = source.getexif().get(274, 1)
        oriented = ImageOps.exif_transpose(source)
        rgba = oriented.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        displayed = Image.alpha_composite(white, rgba).convert("RGB")
    raster_digest = hashlib.sha256(displayed.tobytes()).hexdigest()
    binding = {
        "path": str(path.resolve()), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "original_mode": original_mode, "original_size": original_size,
        "original_exif_orientation": original_orientation,
        "display_transform": "exif_transpose_then_alpha_composite_white_no_crop_no_icc_transform",
        "display_mode": "RGB", "display_size": list(displayed.size),
        "display_pixel_sha256": raster_digest,
    }
    binding["binding_hash"] = content_hash(binding)
    return displayed, binding


class QwenAtomicScorer:
    def __init__(self, model_path: str | Path, device: str = "cuda:0",
                 max_pixels: int = 262144, max_new_tokens: int = 768) -> None:
        if not isinstance(device, str) or not re.fullmatch(r"cpu|cuda:\d+", device):
            raise ValueError("device must be cpu or an explicit cuda:N device")
        if type(max_pixels) is not int or max_pixels < 1024:
            raise ValueError("max_pixels must be an integer >=1024")
        if type(max_new_tokens) is not int or max_new_tokens < 1:
            raise ValueError("max_new_tokens must be a positive integer")
        self.model_path = Path(model_path).expanduser().resolve()
        self.device = device
        self.max_pixels = max_pixels
        self.max_new_tokens = max_new_tokens
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None
        self._model_binding: dict[str, Any] | None = None

    def _load(self) -> None:
        """The runner must have acquired resources before calling this method."""
        if self._model is not None:
            return
        if not self.model_path.is_dir() or not (self.model_path / "config.json").is_file():
            raise FileNotFoundError("local Qwen snapshot is missing")
        if list(self.model_path.glob("*.partial")):
            raise RuntimeError("local Qwen snapshot has incomplete downloads")
        weights = sorted(self.model_path.glob("*.safetensors"))
        if not weights:
            raise FileNotFoundError("local Qwen safetensors weights are missing")
        index_path = self.model_path / "model.safetensors.index.json"
        if index_path.is_file():
            index = json.loads(index_path.read_text())
            if any(not (self.model_path / name).is_file() for name in set(index["weight_map"].values())):
                raise FileNotFoundError("local Qwen weight shard is missing")
        names = {"config.json", "generation_config.json", "model.safetensors.index.json",
                 "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt",
                 "special_tokens_map.json", "added_tokens.json", "preprocessor_config.json",
                 "processor_config.json", "video_preprocessor_config.json", "image_processor_config.json",
                 "chat_template.json", "chat_template.jinja"}
        files = sorted(set(weights) | {self.model_path / name for name in names if (self.model_path / name).is_file()})
        manifest = {path.name: file_binding(path) for path in files}
        import torch
        import transformers
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

        processor = AutoProcessor.from_pretrained(str(self.model_path), local_files_only=True,
                                                trust_remote_code=False, max_pixels=self.max_pixels)
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            str(self.model_path), local_files_only=True, trust_remote_code=False,
            dtype=torch.bfloat16, attn_implementation="sdpa", device_map=None,
        ).to(self.device).eval()
        self._torch, self._processor, self._model = torch, processor, model
        self._model_binding = {
            "model_id": MODEL_ID, "requested_revision": MODEL_REVISION,
            "path": str(self.model_path), "snapshot_directory_name": self.model_path.name,
            "revision_provenance": "caller_acquisition_record; directory_name_is_not_revision_verification",
            "files": manifest, "content_manifest_hash": content_hash(manifest),
            "torch_version": torch.__version__, "transformers_version": transformers.__version__,
            "adapter_source": file_binding(Path(__file__)),
            "dtype": "bfloat16", "attention": "sdpa", "device": self.device, "load_status": "loaded",
        }

    def close(self) -> None:
        torch = self._torch
        self._model = self._processor = self._torch = None
        self._model_binding = None
        gc.collect()
        if torch is not None and self.device.startswith("cuda:") and torch.cuda.is_initialized():
            with torch.cuda.device(self.device):
                torch.cuda.empty_cache()

    def _generate(self, images: list[Any], prompt: str) -> dict[str, Any]:
        started = time.perf_counter()
        self._load()
        load_seconds = time.perf_counter() - started
        contents: list[dict[str, Any]] = []
        for index in range(len(images)):
            label = ("LEFT" if index == 0 else "RIGHT") if len(images) == 2 else "image"
            contents.extend([{"type": "text", "text": f"Image {index + 1}: {label}"}, {"type": "image"}])
        contents.append({"type": "text", "text": prompt})
        rendered_prompt = self._processor.apply_chat_template(
            [{"role": "user", "content": contents}], tokenize=False, add_generation_prompt=True,
        )
        inputs = self._processor(text=[rendered_prompt], images=images, return_tensors="pt",
                                 images_kwargs={"max_pixels": self.max_pixels,
                                                "min_pixels": min(65536, self.max_pixels)})
        grid = inputs.get("image_grid_thw")
        grid_list = grid.tolist() if grid is not None else None
        patch_size = self._model.config.vision_config.patch_size
        if grid_list and any(row[1] * row[2] * patch_size ** 2 > self.max_pixels for row in grid_list):
            raise RuntimeError("processor exceeded the frozen per-image pixel budget")
        inputs = inputs.to(self.device)
        input_count = inputs["input_ids"].shape[1]
        with self._torch.inference_mode():
            output = self._model.generate(**inputs, do_sample=False, num_beams=1,
                                          max_new_tokens=self.max_new_tokens, use_cache=True)
        generated = output[:, input_count:]
        raw = self._processor.batch_decode(generated, skip_special_tokens=True,
                                            clean_up_tokenization_spaces=False)[0]
        return {
            "raw_response": raw, "rendered_prompt": rendered_prompt,
            "rendered_prompt_sha256": hashlib.sha256(rendered_prompt.encode()).hexdigest(),
            "input_token_count": int(input_count), "generated_token_count": int(generated.shape[1]),
            "image_grid_thw": grid_list, "load_seconds": load_seconds,
            "elapsed_seconds": time.perf_counter() - started,
        }

    def _call(self, images: list[Any], prompt: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            trace = self._generate(images, prompt)
        except Exception as error:
            # No retry or fabricated answer, including model-load failure and OOM.
            trace = {"raw_response": "", "error": {"type": type(error).__name__, "message": str(error)},
                     "elapsed_seconds": time.perf_counter() - started}
        trace.update(prompt=prompt, prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                     raw_response_sha256=hashlib.sha256(trace["raw_response"].encode()).hexdigest())
        return trace

    def _binding(self) -> dict[str, Any]:
        return deepcopy(self._model_binding) if self._model_binding else {
            "model_id": MODEL_ID, "requested_revision": MODEL_REVISION,
            "path": str(self.model_path), "load_status": "not_loaded",
        }

    def _settings(self) -> dict[str, Any]:
        return {"device": self.device, "max_pixels_per_image": self.max_pixels,
                "atomic_prompt_version": ATOMIC_PROMPT_VERSION,
                "max_new_tokens": self.max_new_tokens, "do_sample": False,
                "dtype": "bfloat16", "attention": "sdpa", "local_files_only": True,
                "trust_remote_code": False, "crop_count": 0, "retry_count": 0}

    def score(self, image_path: str | Path, contract: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        contract = deepcopy(contract)
        contract_hash = content_hash(contract)
        wire_contract, wire_id_map = _wire_contract(contract)
        prompt = build_atomic_prompt(contract)
        image, binding = prepare_image(image_path)
        try:
            trace = self._call([image], prompt)
        finally:
            image.close()
        result = parse_atomic_response(trace["raw_response"], wire_contract)
        for row in result["requirements"]:
            row["wire_id"] = row["id"]
            row["id"] = wire_id_map[row["id"]]
            row["blocked_by"] = [wire_id_map[parent] for parent in row["blocked_by"]]
        result["wire_parse_errors"] = list(result["parse_errors"])
        result["parse_errors"] = [
            wire_id_map.get(error.split(":", 1)[0], error.split(":", 1)[0])
            + (":" + error.split(":", 1)[1] if ":" in error else "")
            for error in result["parse_errors"]
        ]
        result.update(image=binding, contract_hash=contract_hash, wire_id_map=wire_id_map,
                      model_binding=self._binding(),
                      settings=self._settings(), inference=trace, call_count=1,
                      elapsed_seconds=time.perf_counter() - started)
        result["result_hash"] = content_hash(result)
        return result

    def compare(self, left: str | Path, right: str | Path, style_text: str) -> dict[str, Any]:
        started = time.perf_counter()
        if not isinstance(style_text, str) or not style_text.strip():
            raise ValueError("style_text must be nonempty")
        prompt = STYLE_INSTRUCTIONS + json.dumps(style_text, ensure_ascii=False)
        left_image, left_binding = prepare_image(left)
        try:
            right_image, right_binding = prepare_image(right)
            try:
                forward = self._call([left_image, right_image], prompt)
                reverse = self._call([right_image, left_image], prompt)
            finally:
                right_image.close()
        finally:
            left_image.close()
        parsed_forward = parse_style_response(forward["raw_response"])
        parsed_reverse = parse_style_response(reverse["raw_response"])
        result = {
            "schema": "scene-v2-p020-style-comparison/v1", "method": "B",
            "verdict_kind": "uncalibrated_vqa_preference", "eligibility_checked_by": "caller_not_verified_here",
            **reconcile_style(parsed_forward, parsed_reverse),
            "left_image": left_binding, "right_image": right_binding,
            "style_text": style_text, "style_hash": content_hash(style_text),
            "forward": {**parsed_forward, "inference": forward, "image_order": [left_binding["sha256"], right_binding["sha256"]]},
            "reverse": {**parsed_reverse, "inference": reverse, "image_order": [right_binding["sha256"], left_binding["sha256"]]},
            "model_binding": self._binding(), "settings": self._settings(), "call_count": 2,
            "elapsed_seconds": time.perf_counter() - started,
        }
        result["result_hash"] = content_hash(result)
        return result
