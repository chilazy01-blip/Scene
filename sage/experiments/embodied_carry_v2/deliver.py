"""Bind the ordered stage evidence, numeric samples and real-state videos."""

import argparse
import base64
import html
import json
from pathlib import Path
import time
import numpy as np
from .protocol import authorize
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def verify(b):
    if sha256_file(Path(b["path"])) != b["sha256"]:
        raise ValueError("binding changed: " + b["path"])


def deliver(root):
    import mujoco

    authorize(root)
    output = root / "delivery"
    if output.exists():
        raise FileExistsError(output)
    result = read_bound_json(root / "continuation_01/RESULT.json")
    references = read_bound_json(root / "REFERENCE_AUDIT.json")
    qualifier = read_bound_json(
        root / "verification_01/standing_admission/CARRY_AUDIT.json"
    )
    test = json.loads((root / "TEST_RESULTS.json").read_text())
    directories = [root / "attempt_01/standing_admission"] + [
        root / "continuation_01" / name
        for name in (
            "standing_short",
            "standing_full",
            "walking_admission",
            "walking_short",
            "walking_full",
        )
    ]
    costs = {"physics_steps": 0, "sonic_substep_writes": 0, "reported_wall_s": 0.0}
    no_object_external_force = True
    inherited_control_helper = None
    for directory in directories:
        report = read_bound_json(directory / "REPORT.json")
        model = mujoco.MjModel.from_xml_path(report["case_config"]["model_path"])
        pelvis_id = model.body("pelvis").id
        trace = read_bound_json(Path(report["trace"]["path"]))
        samples = trace["warmup_substeps"] + [
            s for row in trace["records"] for s in row["substeps"]
        ]
        for sample in samples:
            external = np.asarray(sample["xfrc_applied"]).copy()
            external[pelvis_id] = 0
            no_object_external_force &= not np.any(external) and not any(
                sample["qfrc_applied"]
            )
        if inherited_control_helper is None:
            prior = Path(report["case_config"]["main_root"])
            previous = read_bound_json(
                prior / "carry/attempt_01/grasp_01/admission/REPORT.json"
            )
            inherited_control_helper = previous["source_bindings"]["carry_control"]
            verify(inherited_control_helper)
        costs["physics_steps"] += report["physics_steps"]
        costs["sonic_substep_writes"] += report["sonic_candidate_actuator_writes"]
        costs["reported_wall_s"] += report["runtime"]["wall_seconds"]
        for b in [report["trace"], *report["source_bindings"].values()]:
            verify(b)
    for b in references["audits"]:
        verify(b)
        if not read_bound_json(Path(b["path"]))["passed"]:
            raise ValueError("failed reference reconstruction")
    stage_audits = []
    for stage in result["outcomes"]:
        verify(stage["report"])
        verify(stage["audit"])
        audited = read_bound_json(Path(stage["audit"]["path"]))
        if (
            not audited["passed"]
            or not all(audited["gates"].values())
            or not all(audited["task_gates"].values())
        ):
            raise ValueError("unaccepted stage")
        stage_audits.append(stage["audit"])
    standing = read_bound_json(root / "continuation_01/standing_full/CARRY_AUDIT.json")
    walking = read_bound_json(root / "continuation_01/walking_full/CARRY_AUDIT.json")
    episodes = []
    for mode in ("standing", "walking"):
        episode = read_bound_json(root / "episodes" / mode / "EPISODE.json")
        for key in ("arrays", "report", "audit", "reference_audit"):
            verify(episode[key])
        with np.load(episode["arrays"]["path"], allow_pickle=False) as arrays:
            if arrays["action_body_target_rad"].shape != (300, 29) or arrays[
                "action_finger_target_rad"
            ].shape != (300, 14):
                raise ValueError("wrong sample shape")
            if not all(np.isfinite(arrays[k]).all() for k in arrays.files) or np.any(
                arrays["quality_external_support_enabled"]
            ):
                raise ValueError("invalid active training samples")
            if not np.allclose(
                np.diff(arrays["episode_time_s"]), 0.02, rtol=0, atol=1e-12
            ):
                raise ValueError("timebase mismatch")
        episodes.append(_file_binding(root / "episodes" / mode / "EPISODE.json"))
    movies = []
    cards = []
    for name, label, count in (
        ("grip_phased", "1. 稳定握持准入（观察期有支撑）", 100),
        ("standing", "2. 六秒无支撑持物站立", 300),
        ("walking", "3. 六秒持物起步—行走—停止", 300),
    ):
        directory = root / "review" / name
        manifest = read_bound_json(directory / "MANIFEST.json")
        for b in [
            manifest["report"],
            manifest["trace"],
            manifest["renderer"],
            manifest["independent_audit"],
            manifest["video_encoder"],
            *manifest["artifacts"].values(),
        ]:
            verify(b)
        if (
            manifest["frames"] != count
            or manifest["physics_steps"] != 0
            or not manifest["task_passed"]
        ):
            raise ValueError("video mismatch")
        encoded = base64.b64encode((directory / "motion.mp4").read_bytes()).decode()
        cards.append(
            f'<section><h2>{html.escape(label)}</h2><video controls loop playsinline preload="metadata" src="data:video/mp4;base64,{encoded}"></video></section>'
        )
        movies.append(_file_binding(directory / "MANIFEST.json"))
    gates = {
        "stable_grip_qualification": qualifier["passed"]
        and qualifier["grip_qualification_passed"],
        "unsupported_standing_6s": standing["passed"],
        "carrying_walk_and_stop_6s": walking["passed"]
        and walking["task_gates"]["locomotion_and_stop"],
        "all_reference_inputs_reconstructed": references["passed"]
        and len(references["audits"]) == 6,
        "all_ordered_stages_passed": result["all_stages_passed"]
        and len(stage_audits) == 5,
        "standard_numeric_exports": len(episodes) == 2,
        "three_actual_state_videos": len(movies) == 3,
        "regression_tests": test["passed"] == 157 and test["failed"] == 0,
        "free_object_never_externally_supported_including_acquisition": bool(
            no_object_external_force
        ),
    }
    if not all(gates.values()):
        raise ValueError("delivery not accepted: " + str(gates))
    output.mkdir()
    lm = walking["metrics"]["locomotion"]["metrics"]
    sm = standing["metrics"]
    wm = walking["metrics"]
    page = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>稳定握持、无支撑站立与持物行走</title><style>body{background:#151b25;color:#edf2f7;font:17px/1.65 system-ui,sans-serif;max-width:1080px;margin:28px auto;padding:0 18px}video{width:100%;background:#000}section{margin:36px 0}td,th{padding:10px;border-bottom:1px solid #46505d;text-align:left}.note{color:#bcc9d7}code{word-break:break-all}</style>'
    page += "<h1>稳定握持 → 无支撑站立保持 → 持物行走</h1><p>三个阶段按顺序通过：只有握持资格通过才放开骨盆支撑，只有无支撑站立通过才进入持物行走。红色圆柱质量50克，是由真实手指接触支撑的自由物体，无焊接、无随动、无物体外力。</p>"
    page += f'<table><tr><th>指标</th><th>结果</th></tr><tr><td>无支撑持物站立</td><td>6秒；保持接触100%；末1秒漂移 {sm["last_second_drift_m"]*1000:.2f} 毫米</td></tr><tr><td>持物前进</td><td>{lm["forward_m"]*100:.1f} 厘米；左脚{lm["cycles"]["left"]}、右脚{lm["cycles"]["right"]}次完整步</td></tr><tr><td>行走中的握持保持</td><td>对向接触100%；最大滑移 {wm["max_relative_slip_m"]*1000:.2f} 毫米</td></tr><tr><td>持物停止后</td><td>末1秒漂移 {lm["hold_drift_m"]*1000:.2f} 毫米；最大速度 {lm["hold_speed_m_s"]*1000:.2f} 毫米/秒</td></tr><tr><td>目标区误差</td><td>{lm["target_error_m"]*100:.2f} 厘米，门限15厘米</td></tr></table>'
    page += '<p class="note">范围：一个自生成布局、一个50克预置掌内圆柱的开发验证。各阶段在独立进程中从初始条件重新取得握持资格，不是一次连续拾取搬运任务，也不是多物体泛化或生产验收。身体为简化外观/collision-lite，手部使用官方mesh；环境用保守碰撞代理。回放均为实际物理状态，右上角是实际手部和自由物体近景。</p>'
    page += "".join(cards)
    page += "<h2>为何与上轮结果不同</h2><p>上轮把闭合过程相对预置位置的位移也当成保持滑移，记录的约46毫米移动仍保留为失败。本轮新协议在执行前固定：允许有限闭合就位，在初始化后0.7秒记录一次实测掌内基准，此后要求连续0.5秒对向接触、低相对速度，再准入主动控制。物体位置从未重置，基准从未随物体移动，保持滑移限制仍为30毫米。</p>"
    page += '<h2>审计、数据与工程记录</h2><p>全部原样SONIC身体命令、官方PD、手指PD、物体状态链、接触距离和力、外力支撑及目标停稳通过独立复核；6个报告合计1200个encoder参考输入重建一致。导出两条6秒主动示范，共600个50Hz样本，身体29维与手指14维顺序明确，本体感知与特权物体/接触标签分开，split未分配。157项回归测试通过。</p><p class="note">保留一次审计工程错误：初版审计没有恢复执行器设置的0.005秒时间步，误用了XML默认0.002秒来计算相对速度。已用新审计版本在新目录复核同一物理轨迹，不重跑、不覆盖原始失败报告。旧行走48条件批次和旧持物失败证据均未修改。无新训练、无下载、未提交。</p>'
    (output / "index.html").write_text(page, encoding="utf-8")
    document = {
        "schema": "ordered-contact-carry-delivery/v2",
        "classification": "accepted_development_staged_carry",
        "gates": gates,
        "protocol": _file_binding(root / "PROTOCOL.json"),
        "continuation": _file_binding(root / "continuation_01/RESULT.json"),
        "qualification": _file_binding(
            root / "verification_01/standing_admission/CARRY_AUDIT.json"
        ),
        "audit_correction": _file_binding(
            root / "verification_01/standing_admission/CORRECTION.json"
        ),
        "stage_audits": stage_audits,
        "reference_audit": _file_binding(root / "REFERENCE_AUDIT.json"),
        "episodes": episodes,
        "videos": movies,
        "page": _file_binding(output / "index.html"),
        "tests": _file_binding(root / "TEST_RESULTS.json"),
        "inherited_control_helper": inherited_control_helper,
        "standing_metrics": sm,
        "walking_metrics": wm,
        "costs": costs,
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "held_out_evaluation": False,
        "preloaded_grasp_not_pickup": True,
        "independent_stage_restarts_not_single_continuous_pickup": True,
        "production_accepted": False,
        "accepted_utc_timestamp": time.time(),
        "implementation": _file_binding(Path(__file__)),
    }
    document["content_sha256_excluding_this_field"] = canonical_sha256(document)
    write_json_atomic(output / "DELIVERY.json", document)
    print({k: document[k] for k in ("classification", "gates", "costs")}, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    deliver(p.parse_args().root)
