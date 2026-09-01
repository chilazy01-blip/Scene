from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from .architecture import plan_architecture
from .assets import resolve_assets
from .brief import expand_prompt
from .constraint_scopes import evaluate_constraint_scope_envelopes
from .content_chain import content_hash, file_binding
from .delivery_status import apply_profile_defaults, evaluate_terminal_status
from .io_utils import read_json, write_json
from .planner import codex_layout, codex_repair_layout, rules_layout
from .repair import deterministic_repair
from .runtime import assemble_with_blender, run_mujoco_proxy, write_preview_svg
from .scene_render_acceptance import render_and_evaluate_scene
from .scene_graph import build_typed_scene_graph
from .stage_dag import StageDAG
from .validator import validate_layout


def prepare_output_dir(path: Path, overwrite: bool, resume: bool = False) -> None:
    if overwrite and resume:
        raise ValueError("--overwrite and --resume are mutually exclusive")
    if path.exists() and any(path.iterdir()):
        if resume:
            required = (path / "selected_prompt.txt", path / "run_dag.json")
            missing = [str(item) for item in required if not item.is_file()]
            if missing:
                raise FileNotFoundError(
                    "Cannot resume because required checkpoints are missing: "
                    + ", ".join(missing)
                )
            return
        if not overwrite:
            raise FileExistsError(
                f"Output directory is not empty: {path}; pass --overwrite to replace it"
            )
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def run_pipeline(args: Any) -> dict[str, Any]:
    apply_profile_defaults(args)
    output_dir = Path(args.output_dir).expanduser().resolve()
    resume = bool(getattr(args, "resume", False))
    prepare_output_dir(output_dir, bool(args.overwrite), resume=resume)
    prompt = str(args.prompt or "").strip()
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("--prompt or --prompt-file is required")
    selected_prompt_path = output_dir / "selected_prompt.txt"
    dag = StageDAG(output_dir / "run_dag.json")
    if resume:
        checkpoint_prompt = selected_prompt_path.read_text(encoding="utf-8").strip()
        if checkpoint_prompt != prompt:
            raise ValueError(
                "Resume prompt does not match the interrupted run's selected_prompt.txt"
            )
    else:
        selected_prompt_path.write_text(prompt + "\n", encoding="utf-8")
    expand_inputs = {"prompt": prompt, "prompt_sha256": content_hash(prompt)}
    expand_config = {
        "room_type": args.room_type,
        "mode": str(args.expander),
        "model": str(args.model),
        "hard_min_objects": args.hard_min_scene_objects,
        "target_max_objects": args.target_max_scene_objects,
        "max_auto_inferred_objects": args.max_auto_inferred_assets,
    }
    expand_attempt = dag.begin("expand", inputs=expand_inputs, config=expand_config)
    expanded_path = output_dir / "scene_brief_expanded.json"
    if expand_attempt["reused"]:
        brief = read_json(expanded_path)
    else:
        brief = expand_prompt(
            prompt,
            output_dir,
            room_type_override=args.room_type,
            mode=str(args.expander),
            model=str(args.model),
            hard_min_objects=args.hard_min_scene_objects,
            target_max_objects=args.target_max_scene_objects,
            max_auto_inferred_objects=args.max_auto_inferred_assets,
        )
        write_json(expanded_path, brief)
        dag.commit(
            "expand",
            int(expand_attempt["attempt"]["attempt"]),
            outputs={"selected_prompt": selected_prompt_path, "scene_brief": expanded_path},
        )
    constraint_scope_envelopes = evaluate_constraint_scope_envelopes(brief)
    architecture_inputs = {"brief_hash": content_hash(brief)}
    architecture_config = {
        "floor": getattr(args, "floor_material", None),
        "wall": getattr(args, "wall_material", None),
        "accent_wall": getattr(args, "accent_wall", None),
        "accent_material": getattr(args, "accent_wall_material", None),
        "window_wall": getattr(args, "window_wall", None),
    }
    architecture_attempt = dag.begin(
        "architecture", inputs=architecture_inputs, config=architecture_config
    )
    if architecture_attempt["reused"]:
        architecture_plan = read_json(output_dir / "architecture_plan.json")
        brief = read_json(output_dir / "scene_brief_architecture.json")
    else:
        architecture_plan = plan_architecture(
            brief,
            floor_material_override=getattr(args, "floor_material", None),
            wall_material_override=getattr(args, "wall_material", None),
            accent_wall_override=getattr(args, "accent_wall", None),
            accent_wall_material_override=getattr(args, "accent_wall_material", None),
            window_wall_override=getattr(args, "window_wall", None),
        )
    write_json(
        output_dir / "semantic_grounding.json",
        brief.get("semantic_grounding", {}),
    )
    write_json(
        output_dir / "constraint_scope_grounding.json",
        brief.get("constraint_scope_grounding", {}),
    )
    write_json(
        output_dir / "instance_group_grounding.json",
        brief.get("instance_group_grounding", {}),
    )
    write_json(
        output_dir / "constraint_scope_envelopes.json",
        constraint_scope_envelopes,
    )
    write_json(output_dir / "architecture_plan.json", architecture_plan)
    write_json(output_dir / "scene_brief_architecture.json", brief)
    if not architecture_attempt["reused"]:
        dag.commit(
            "architecture",
            int(architecture_attempt["attempt"]["attempt"]),
            outputs={
                "architecture": output_dir / "architecture_plan.json",
                "scene_brief": output_dir / "scene_brief_architecture.json",
            },
        )
    graph_attempt = dag.begin(
        "scene_graph",
        inputs={"brief_hash": content_hash(brief), "architecture_hash": content_hash(architecture_plan)},
        config={"builder": "typed_scene_graph_v1"},
    )
    if graph_attempt["reused"]:
        brief = read_json(output_dir / "scene_brief.json")
    else:
        brief["scene_graph"] = build_typed_scene_graph(brief, architecture_plan)
    write_json(output_dir / "scene_graph_initial.json", brief["scene_graph"])
    write_json(output_dir / "scene_brief.json", brief)
    if not graph_attempt["reused"]:
        dag.commit(
            "scene_graph",
            int(graph_attempt["attempt"]["attempt"]),
            outputs={
                "scene_graph": output_dir / "scene_graph_initial.json",
                "scene_brief": output_dir / "scene_brief.json",
            },
        )

    asset_config = {
        "mode": str(args.asset_mode),
        "seed": int(args.seed),
        "steps": int(args.steps),
        "texture_size": int(args.texture_size),
        "decimation_target": int(args.decimation_target),
        "pipeline_type": str(args.trellis_pipeline_type),
        "model_fingerprint": str(getattr(args, "trellis_model_fingerprint", "")),
        "code_version": str(getattr(args, "generation_code_version", "")),
    }
    asset_plan_attempt = dag.begin(
        "asset_plan", inputs={"brief_hash": content_hash(brief)}, config=asset_config
    )
    # Asset resolution always executes its content-certificate verification.
    # With valid checkpoints it performs no model generation; skipping this
    # read-only verification would let a replaced GLB bypass P005 on resume.
    asset_report = resolve_assets(
            brief,
            output_dir,
            mode=str(args.asset_mode),
            manifest_path=Path(args.asset_library_manifest).expanduser() if args.asset_library_manifest else None,
            trellis_url=str(args.trellis_url),
            seed=int(args.seed),
            timeout=float(args.asset_timeout),
            steps=int(args.steps),
            texture_size=int(args.texture_size),
            decimation_target=int(args.decimation_target),
            pipeline_type=str(args.trellis_pipeline_type),
            preprocess_image=bool(args.trellis_preprocess_image),
            max_new_assets=int(args.max_new_assets),
            scene_dna_mode=str(getattr(args, "scene_dna_mode", "relation_aware")),
            blender_bin=Path(args.blender_bin).expanduser(),
            scene_dna_multiview=bool(getattr(args, "scene_dna_multiview", True)),
            scene_dna_multiview_resolution=int(getattr(args, "scene_dna_multiview_resolution", 420)),
            scene_dna_semantic_model=getattr(args, "scene_dna_multiview_semantic_model", None),
            scene_dna_semantic_device=str(getattr(args, "scene_dna_multiview_semantic_device", "cpu")),
            resume_staged_assets=resume,
            trellis_model_fingerprint=str(getattr(args, "trellis_model_fingerprint", "unfrozen-local-trellis-model")),
            rmbg_model_fingerprint=str(getattr(args, "rmbg_model_fingerprint", "unfrozen-local-rmbg-model")),
        generation_code_version=str(getattr(args, "generation_code_version", "unfrozen-scene-v2-code")),
    )
    write_json(
        output_dir / "instance_group_asset_resolution.json",
        asset_report.get("instance_group_resolution", {}),
    )
    component_resolution = deepcopy(asset_report.get("component_resolution", []))
    write_json(
        output_dir / "component_resolution.json",
        {
            "schema": "codex_trellis_component_resolution_v1",
            "results": component_resolution,
            "ok": bool(asset_report.get("component_resolution_ok", True)),
            "absorbed_component_count": sum(
                int(item.get("requested_count", 0))
                for item in component_resolution
                if isinstance(item, dict)
                and item.get("action") == "absorbed_into_composite_asset"
            ),
        },
    )
    brief["scene_graph"] = build_typed_scene_graph(brief, architecture_plan)
    write_json(output_dir / "scene_graph_resolved.json", brief["scene_graph"])
    write_json(output_dir / "scene_brief_resolved.json", brief)
    asset_resolution_path = output_dir / "asset_resolution.json"
    generation_plan_path = output_dir / "missing_asset_generation_plan.json"
    if not asset_plan_attempt["reused"]:
        dag.commit(
            "asset_plan",
            int(asset_plan_attempt["attempt"]["attempt"]),
            outputs={
                "asset_resolution": asset_resolution_path,
                "generation_plan": generation_plan_path,
                "scene_brief_resolved": output_dir / "scene_brief_resolved.json",
            },
        )
    asset_generate_attempt = dag.begin(
        "asset_generate",
        inputs={"asset_report_hash": content_hash(asset_report)},
        config=asset_config,
    )
    if not asset_generate_attempt["reused"]:
        generated_outputs = {"asset_resolution": asset_resolution_path}
        staged_dir = output_dir / "assets_staged"
        if staged_dir.is_dir():
            for staged_path in sorted(staged_dir.iterdir()):
                if staged_path.is_file() and staged_path.suffix.lower() in {".glb", ".json"}:
                    generated_outputs[f"staged/{staged_path.name}"] = staged_path
        dag.commit(
            "asset_generate",
            int(asset_generate_attempt["attempt"]["attempt"]),
            outputs=generated_outputs,
        )
    asset_qa_attempt = dag.begin(
        "asset_qa",
        inputs={"asset_report_hash": content_hash(asset_report)},
        config={"ready_for_assembly": bool(asset_report.get("ready_for_assembly"))},
    )
    if not asset_qa_attempt["reused"]:
        dag.commit(
            "asset_qa",
            int(asset_qa_attempt["attempt"]["attempt"]),
            outputs={"asset_resolution": asset_resolution_path},
        )

    plan_path = output_dir / "layout_plan_final.json"
    validation_path = output_dir / "validation_final.json"
    layout_resumed = False
    layout_inputs = {
        "brief_hash": content_hash(brief),
        "asset_report_hash": content_hash(asset_report),
    }
    layout_config = {
        "planner": str(args.planner),
        "model": str(args.model),
        "repair_iterations": int(args.repair_iterations),
        "codex_repair": bool(args.codex_repair),
    }
    layout_attempt = dag.begin("layout", inputs=layout_inputs, config=layout_config)
    if layout_attempt["reused"]:
        checkpoint_plan = read_json(plan_path)
        checkpoint_validation = read_json(validation_path)
        if (
            isinstance(checkpoint_plan, dict)
            and isinstance(checkpoint_plan.get("objects"), list)
            and isinstance(checkpoint_validation, dict)
            and bool(checkpoint_validation.get("ok"))
        ):
            plan = checkpoint_plan
            validation = checkpoint_validation
            layout_resumed = True

    if not layout_resumed:
        if args.planner == "codex":
            plan = codex_layout(brief, output_dir, str(args.model))
        else:
            plan = rules_layout(brief)
        write_json(output_dir / "layout_plan_initial.json", plan)

        validation = validate_layout(plan)
        write_json(output_dir / "validation_00.json", validation)
        for iteration in range(1, int(args.repair_iterations) + 1):
            spatial_pending = int(
                validation.get("metrics", {})
                .get("spatial_relations", {})
                .get("invalid_count", 0)
                or 0
            ) > 0
            if validation["ok"] and not spatial_pending:
                break
            plan = deterministic_repair(plan, iteration=iteration)
            validation = validate_layout(plan)
            write_json(output_dir / f"validation_{iteration:02d}_sdk.json", validation)
            spatial_pending = int(
                validation.get("metrics", {})
                .get("spatial_relations", {})
                .get("invalid_count", 0)
                or 0
            ) > 0
            if validation["ok"] and not spatial_pending:
                break
            if validation["ok"]:
                continue
            if bool(args.codex_repair) and args.planner == "codex":
                plan = codex_repair_layout(
                    plan,
                    validation,
                    output_dir,
                    model=str(args.model),
                    iteration=iteration,
                )
                validation = validate_layout(plan)
                write_json(output_dir / f"validation_{iteration:02d}_codex.json", validation)

    write_json(plan_path, plan)
    if isinstance(plan.get("scene_graph"), dict):
        write_json(output_dir / "scene_graph_final.json", plan["scene_graph"])
    write_json(output_dir / "validation_final.json", validation)
    if not layout_attempt["reused"]:
        dag.commit(
            "layout",
            int(layout_attempt["attempt"]["attempt"]),
            outputs={"layout": plan_path, "validation": validation_path},
        )
    write_json(
        output_dir / "instance_group_resolution.json",
        plan.get(
            "instance_group_resolution",
            {
                "schema": "codex_trellis_instance_group_postprocess_v1",
                "method": "not_run",
                "group_count": len(plan.get("instance_groups", [])),
                "adjusted_count": 0,
                "results": [],
            },
        ),
    )
    preview_path = output_dir / "layout_preview.svg"
    write_preview_svg(plan, preview_path)

    profile = str(getattr(args, "profile", "development"))
    relation_report_path = output_dir / "relation_geometry_audit.json"
    if profile == "production" and not relation_report_path.is_file():
        declared_relations = plan.get("spatial_relations", [])
        declared_relations = declared_relations if isinstance(declared_relations, list) else []
        write_json(
            relation_report_path,
            {
                "schema": "scene-v2-production-relation-geometry-stage/v1",
                "ok": not declared_relations,
                "status": (
                    "not_applicable_no_declared_relations"
                    if not declared_relations
                    else "required_relation_geometry_certificate_missing"
                ),
                "declared_relation_count": len(declared_relations),
            },
        )
    if relation_report_path.is_file():
        relation_attempt = dag.begin(
            "relation_geometry",
            inputs={"layout_hash": content_hash(plan)},
            config={"certificate_schema": "relation_geometry"},
        )
        if not relation_attempt["reused"]:
            dag.commit(
                "relation_geometry",
                int(relation_attempt["attempt"]["attempt"]),
                outputs={"audit": relation_report_path},
            )

    assembly_report = None
    scene_render_acceptance = None
    scene_glb = None
    scene_render = None
    scene_render_front_center = None
    assembly_attempt = None
    render_attempt = None
    if bool(args.assemble):
        if args.asset_mode == "plan" or not asset_report["ready_for_assembly"]:
            raise RuntimeError("Assembly requires --asset-mode reuse or trellis2 with all assets ready")
        scene_glb = output_dir / "scene_codex_trellis_v2.glb"
        scene_render = output_dir / "scene_front_45.png" if bool(args.render_preview) else None
        scene_render_front_center = (
            output_dir / "scene_front_center_45.png" if bool(args.render_preview) else None
        )
        assembly_attempt = dag.begin(
            "assemble",
            inputs={"layout_hash": content_hash(plan), "asset_report_hash": content_hash(asset_report)},
            config={"blender": str(args.blender_bin)},
        )
        if assembly_attempt["reused"]:
            assembly_report = read_json(output_dir / "assembly_report.json")
        else:
            assembly_report = assemble_with_blender(
                plan_path,
                Path(asset_report["asset_dir"]),
                scene_glb,
                blender_bin=Path(args.blender_bin).expanduser(),
                preview_image=scene_render,
                preview_image_center=scene_render_front_center,
            )
            write_json(output_dir / "assembly_report.json", assembly_report)
            dag.commit(
                "assemble",
                int(assembly_attempt["attempt"]["attempt"]),
                outputs={
                    "assembly_report": output_dir / "assembly_report.json",
                    "scene_glb": scene_glb,
                },
            )
        if bool(getattr(args, "scene_render_acceptance", False)):
            render_attempt = dag.begin(
                "render_acceptance",
                inputs={"scene_glb": file_binding(scene_glb)},
                config={"resolution": int(getattr(args, "scene_render_acceptance_resolution", 512))},
            )
            render_report_path = output_dir / "scene_render_acceptance" / "scene_render_acceptance_report.json"
            if render_attempt["reused"]:
                scene_render_acceptance = read_json(render_report_path)
            else:
                scene_render_acceptance = render_and_evaluate_scene(
                    blender_bin=Path(args.blender_bin).expanduser(),
                    scene_glb=scene_glb,
                    plan_path=plan_path,
                    asset_dir=Path(asset_report["asset_dir"]),
                    output_dir=output_dir / "scene_render_acceptance",
                    resolution=int(
                        getattr(args, "scene_render_acceptance_resolution", 512)
                    ),
                )
                dag.commit(
                    "render_acceptance",
                    int(render_attempt["attempt"]["attempt"]),
                    outputs={"report": render_report_path},
                )

    mujoco_report = None
    if bool(args.mujoco_check):
        mujoco_report = run_mujoco_proxy(
            plan,
            output_dir,
            python_bin=Path(args.mujoco_python).expanduser(),
        )
        write_json(output_dir / "mujoco_check.json", mujoco_report)

    summary = {
        "schema": "codex_trellis_scene_v2_summary",
        "output_dir": str(output_dir),
        "resumed": resume,
        "layout_resumed": layout_resumed,
        "prompt": str(output_dir / "selected_prompt.txt"),
        "room_type": brief["room_type"],
        "expansion": brief["expansion"],
        "architecture_plan": str(output_dir / "architecture_plan.json"),
        "semantic_grounding": {
            "report": str(output_dir / "semantic_grounding.json"),
            "mode": brief.get("semantic_grounding", {}).get("mode"),
            "accepted_count": int(
                brief.get("semantic_grounding", {}).get("accepted_count", 0)
            ),
            "rejected_count": int(
                brief.get("semantic_grounding", {}).get("rejected_count", 0)
            ),
            "normalization_count": int(
                brief.get("semantic_grounding", {}).get("normalization_count", 0)
            ),
        },
        "constraint_scopes": {
            "grounding_report": str(output_dir / "constraint_scope_grounding.json"),
            "envelope_report": str(output_dir / "constraint_scope_envelopes.json"),
            "accepted_count": int(
                brief.get("constraint_scope_grounding", {}).get("accepted_count", 0)
            ),
            "rejected_count": int(
                brief.get("constraint_scope_grounding", {}).get("rejected_count", 0)
            ),
            "overlapping_memberships": deepcopy(
                brief.get("constraint_scope_grounding", {}).get(
                    "overlapping_memberships", {}
                )
            ),
            "envelope_status_counts": deepcopy(
                constraint_scope_envelopes.get("status_counts", {})
            ),
            "advisory_only": True,
        },
        "instance_groups": {
            "grounding_report": str(output_dir / "instance_group_grounding.json"),
            "asset_resolution_report": str(
                output_dir / "instance_group_asset_resolution.json"
            ),
            "layout_resolution_report": str(
                output_dir / "instance_group_resolution.json"
            ),
            "group_count": len(brief.get("instance_groups", [])),
            "accepted_count": int(
                brief.get("instance_group_grounding", {}).get(
                    "accepted_count", 0
                )
            ),
            "rejected_count": int(
                brief.get("instance_group_grounding", {}).get(
                    "rejected_count", 0
                )
            ),
            "adjusted_count": int(
                plan.get("instance_group_resolution", {}).get(
                    "adjusted_count", 0
                )
            ),
            "validation": deepcopy(
                validation["metrics"].get("instance_groups", {})
            ),
            "members_remain_independent_instances": True,
        },
        "scene_graph": {
            "schema": brief["scene_graph"].get("schema"),
            "initial": str(output_dir / "scene_graph_initial.json"),
            "resolved": str(output_dir / "scene_graph_resolved.json"),
            "final": (
                str(output_dir / "scene_graph_final.json")
                if isinstance(plan.get("scene_graph"), dict)
                else None
            ),
            "stats": deepcopy(plan.get("scene_graph", brief["scene_graph"]).get("stats", {})),
            "validation": deepcopy(
                plan.get("scene_graph", brief["scene_graph"]).get("validation", {})
            ),
        },
        "component_resolution": {
            "report": str(output_dir / "component_resolution.json"),
            "ok": bool(asset_report.get("component_resolution_ok", True)),
            "absorbed_component_count": sum(
                int(item.get("requested_count", 0))
                for item in component_resolution
                if isinstance(item, dict)
                and item.get("action") == "absorbed_into_composite_asset"
            ),
            "standalone_instances_removed": [
                str(instance_id)
                for item in component_resolution
                if isinstance(item, dict)
                for instance_id in item.get("standalone_instances_removed", [])
            ],
            "status_counts": {
                status: sum(
                    1
                    for item in component_resolution
                    if isinstance(item, dict)
                    and str(item.get("resolution_status") or "unknown") == status
                )
                for status in sorted(
                    {
                        str(item.get("resolution_status") or "unknown")
                        for item in component_resolution
                        if isinstance(item, dict)
                    }
                )
            },
        },
        "asset_mode": args.asset_mode,
        "asset_resolution": str(output_dir / "asset_resolution.json"),
        "scene_dna": {
            "mode": asset_report.get("scene_dna_mode", "relation_aware"),
            "contract": asset_report.get("scene_dna_contract"),
            "contract_hash": asset_report.get("scene_dna_contract_hash"),
            "harmony_certificate": asset_report.get("harmony_certificate"),
            "harmony_certificate_hash": asset_report.get(
                "harmony_certificate_hash"
            ),
            "style_review_required": bool(
                asset_report.get("style_review_required", False)
            ),
            "hard_constraints_remain_authoritative": True,
        },
        "missing_asset_generation_plan": asset_report.get("missing_asset_generation_plan"),
        "asset_prompt_audit": {
            "source_scene_prompt": str(output_dir / "selected_prompt.txt"),
            "generation_plan": asset_report.get("missing_asset_generation_plan"),
            "final_flux_prompts_recorded_in": str(output_dir / "asset_resolution.json"),
        },
        "missing_asset_instances": int(
            asset_report.get("missing_count", 0) + asset_report.get("generated_count", 0)
        ),
        "unique_asset_generations_planned": int(
            asset_report.get("unique_generation_planned_count", 0)
        ),
        "unique_asset_generations": int(asset_report.get("unique_generated_count", 0)),
        "asset_dimension_resolution": asset_report.get("dimension_resolution", {}),
        "architecture_asset_resolution": {
            "reused_count": int(asset_report.get("architecture_reused_count", 0)),
            "fallback_count": int(asset_report.get("architecture_fallback_count", 0)),
            "results": asset_report.get("architecture_results", []),
        },
        "planner": plan["planner"],
        "layout_plan": str(plan_path),
        "validation": str(output_dir / "validation_final.json"),
        "validation_ok": bool(validation["ok"]),
        "hard_violation_count": int(validation["hard_violation_count"]),
        "soft_violation_count": int(validation["soft_violation_count"]),
        "object_count": int(validation["metrics"]["object_count"]),
        "object_budget": brief["object_budget"],
        "compactness_status": validation["metrics"]["compactness_status"],
        "compactness_score": validation["metrics"]["compactness_score"],
        "composition_score": validation["metrics"]["composition"]["score"],
        "composition": validation["metrics"]["composition"],
        "floor_occupancy_ratio": validation["metrics"]["floor_occupancy_ratio"],
        "architecture": validation["metrics"]["architecture"],
        "functional_facing": validation["metrics"]["functional_facing"],
        "spatial_relations": validation["metrics"]["spatial_relations"],
        "constraint_scope_failures": deepcopy(
            validation["metrics"].get("constraint_scope_failures", {})
        ),
        "asset_dimensions": validation["metrics"]["asset_dimensions"],
        "preview": str(preview_path),
        "scene_glb": str(scene_glb) if scene_glb else None,
        "scene_render": str(scene_render) if scene_render else None,
        "scene_render_front_center": (
            str(scene_render_front_center) if scene_render_front_center else None
        ),
        "assembly_ok": assembly_report.get("ok") if assembly_report else None,
        "scene_render_acceptance": (
            str(output_dir / "scene_render_acceptance" / "scene_render_acceptance_report.json")
            if scene_render_acceptance is not None
            else None
        ),
        "scene_render_acceptance_ok": (
            bool(scene_render_acceptance.get("accepted"))
            if isinstance(scene_render_acceptance, dict)
            else None
        ),
        "mujoco_ok": mujoco_report.get("ok") if mujoco_report else None,
    }
    final_hash_audit_path = output_dir / "final_delivery_audit.json"
    relation_report = read_json(relation_report_path) if relation_report_path.is_file() else None
    if profile == "production" and not final_hash_audit_path.is_file():
        hash_inputs = {
            "scene_brief": output_dir / "scene_brief_resolved.json",
            "architecture": output_dir / "architecture_plan.json",
            "scene_graph": output_dir / "scene_graph_resolved.json",
            "asset_resolution": output_dir / "asset_resolution.json",
            "layout": plan_path,
            "validation": output_dir / "validation_final.json",
            "relation_geometry": relation_report_path,
            "scene_glb": scene_glb,
            "render_acceptance": (
                output_dir
                / "scene_render_acceptance"
                / "scene_render_acceptance_report.json"
            ),
            "structural_performance": output_dir / "mujoco_check.json",
        }
        missing_hash_inputs = [
            name
            for name, path in hash_inputs.items()
            if path is None or not Path(path).is_file()
        ]
        write_json(
            final_hash_audit_path,
            {
                "schema": "scene-v2-final-hash-audit/v1",
                "ok": not missing_hash_inputs and bool(
                    isinstance(relation_report, dict) and relation_report.get("ok")
                ),
                "missing": missing_hash_inputs,
                "artifacts": {
                    name: file_binding(Path(path))
                    for name, path in hash_inputs.items()
                    if path is not None and Path(path).is_file()
                },
            },
        )
    final_hash_audit = read_json(final_hash_audit_path) if final_hash_audit_path.is_file() else None
    if final_hash_audit_path.is_file():
        delivery_attempt = dag.begin(
            "delivery_audit",
            inputs={"audit_hash": content_hash(final_hash_audit)},
            config={"schema": "scene-v2-final-hash-audit/v1"},
        )
        if not delivery_attempt["reused"]:
            dag.commit(
                "delivery_audit",
                int(delivery_attempt["attempt"]["attempt"]),
                outputs={"final_delivery_audit": final_hash_audit_path},
            )
    stages = {
        "scene_brief": (output_dir / "scene_brief_resolved.json").is_file(),
        "architecture": (output_dir / "architecture_plan.json").is_file(),
        "typed_scene_graph": (output_dir / "scene_graph_resolved.json").is_file(),
        "asset_plan": (output_dir / "asset_resolution.json").is_file(),
        "assets_ready_and_qa": bool(asset_report.get("ready_for_assembly")),
        "layout": plan_path.is_file(),
        "layout_validation": bool(validation.get("ok")),
        "relation_geometry": bool(isinstance(relation_report, dict) and relation_report.get("ok")),
        "blender_assembly": bool(assembly_report and assembly_report.get("ok")),
        "final_multichannel_render": bool(
            isinstance(scene_render_acceptance, dict)
            and scene_render_acceptance.get("accepted")
        ),
        "structural_performance_check": bool(mujoco_report and mujoco_report.get("ok")),
        "final_hash_audit": bool(
            isinstance(final_hash_audit, dict) and final_hash_audit.get("ok")
        ),
        "benchmark_metrics": bool(validation.get("metrics")),
    }
    terminal = evaluate_terminal_status(
        profile, stages
    )
    summary.update(terminal)
    write_json(output_dir / "run_summary.json", summary)
    if not validation["ok"] and not bool(args.allow_invalid):
        raise RuntimeError(
            f"Layout still has {validation['hard_violation_count']} hard violations; "
            f"see {output_dir / 'validation_final.json'}"
        )
    if (
        isinstance(scene_render_acceptance, dict)
        and not bool(scene_render_acceptance.get("accepted"))
        and not bool(getattr(args, "allow_render_acceptance_failure", False))
    ):
        raise RuntimeError(
            "Final RGB/depth/instance-mask acceptance failed; see "
            f"{output_dir / 'scene_render_acceptance' / 'scene_render_acceptance_report.json'}"
        )
    return summary
