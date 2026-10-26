#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from sage.webui.controller import JobController
    from sage.webui.job_store import JobStore
except ModuleNotFoundError:  # direct ``python sage/webui/server.py`` launch
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from sage.webui.controller import JobController
    from sage.webui.job_store import JobStore


from sage.experiments.codex_trellis_scene_v2.core_domain import (
    DEFAULT_IMAGE_PROVIDER,
    normalize_image_provider,
)


WEBUI_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEBUI_DIR / "static"
WORKSPACE_ROOT = WEBUI_DIR.parents[1]
FLOW_SCRIPT = Path(os.environ.get("SAGE_FLOW_SCRIPT", str(WORKSPACE_ROOT / "sage" / "scripts" / "run_tree_sage_scene.py"))).expanduser()
TEXT_FLOW_SCRIPT = Path(os.environ.get("SAGE_TEXT_FLOW_SCRIPT", str(WORKSPACE_ROOT / "sage" / "scripts" / "run_tree_sage_text_scene.py"))).expanduser()
FLOW_PYTHON = Path(
    os.environ.get("SAGE_FLOW_PYTHON")
    or os.environ.get("SAGE_ORCH_PYTHON")
    or sys.executable
).expanduser()
DEFAULT_SAGE_DATA_ROOT = Path(
    os.environ.get("SAGE_DATA_ROOT", str(WORKSPACE_ROOT.parent / "scene_runs"))
).expanduser()
DEFAULT_WEBUI_DATA_ROOT = Path(
    os.environ.get("SAGE_WEBUI_DATA_ROOT", str(DEFAULT_SAGE_DATA_ROOT / "webui"))
).expanduser().resolve()
JOBS_DIR = Path(os.environ.get("SAGE_WEBUI_JOBS_DIR", str(DEFAULT_WEBUI_DATA_ROOT / "jobs"))).resolve()
JOBS_DB = Path(os.environ.get("SAGE_WEBUI_JOBS_DB", str(DEFAULT_WEBUI_DATA_ROOT / "jobs.sqlite3"))).resolve()
DEFAULT_OUTPUT_ROOT = Path(os.environ.get("SAGE_WEBUI_OUTPUT_ROOT", str(DEFAULT_WEBUI_DATA_ROOT / "runs"))).resolve()
DEFAULT_ASSET_SOURCE_ROOT = Path(os.environ.get("SAGE_WEBUI_ASSET_SOURCE_ROOT", str(DEFAULT_WEBUI_DATA_ROOT / "source_images"))).resolve()
DEFAULT_CODEX_MODEL = os.environ.get("SAGE_CODEX_MODEL", "gpt-5.6-sol")

_STORE: JobStore | None = None
_CONTROLLER: JobController | None = None


def control_plane() -> tuple[JobStore, JobController]:
    global _STORE, _CONTROLLER
    if _STORE is None:
        _STORE = JobStore(JOBS_DB)
        # Non-destructive one-time compatibility import. Historical JSON remains
        # evidence; SQLite becomes authoritative after insertion.
        for path in sorted(JOBS_DIR.glob("*.json")):
            old = read_json_file(path, {})
            if isinstance(old, dict) and old.get("id") and _STORE.get_job(str(old["id"])) is None:
                old.setdefault("createdAt", utc_stamp())
                old.setdefault("status", "created")
                old.setdefault("payload", {})
                old.setdefault("plan", {})
                old.setdefault("warnings", [])
                _STORE.create_job(old)
    if _CONTROLLER is None:
        _CONTROLLER = JobController(
            _STORE, workspace_root=WORKSPACE_ROOT, jobs_dir=JOBS_DIR,
            broker_state=DEFAULT_WEBUI_DATA_ROOT / "heavy_job_broker.json",
        )
    return _STORE, _CONTROLLER


def utc_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sanitize_label(value: Any, fallback: str = "scene") -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = text.strip("._-")
    return text[:80] or fallback


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def read_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def bool_payload(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def int_payload(payload: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(payload.get(key, default))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def float_payload(payload: dict[str, Any], key: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(payload.get(key, default))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def build_flow_plan(payload: dict[str, Any], job_id: str | None = None) -> dict[str, Any]:
    mode = str(payload.get("mode") or "image_to_scene")
    asset_strategy = str(payload.get("assetStrategy") or "generate_from_scratch")
    image_provider = normalize_image_provider(payload.get("imageProvider"))
    scene_name = sanitize_label(payload.get("sceneName"), fallback=mode)
    output_root = Path(str(payload.get("outputRoot") or DEFAULT_OUTPUT_ROOT)).expanduser().resolve()
    if output_root != DEFAULT_OUTPUT_ROOT and DEFAULT_OUTPUT_ROOT not in output_root.parents:
        raise ValueError(f"outputRoot must stay inside allowlisted root: {DEFAULT_OUTPUT_ROOT}")
    output_dir = output_root / f"{scene_name}_{job_id}" if job_id else output_root / f"{scene_name}_<job_id>"
    profile = "plan" if bool_payload(payload, "planOnly", False) else (
        "production" if str(payload.get("deliveryProfile") or "diagnostic") == "production" else "development"
    )
    warnings: list[str] = []
    reserved: list[str] = []

    if mode == "text_to_scene":
        text_prompt = str(payload.get("textPrompt") or payload.get("prompt") or "").strip()
        if not text_prompt:
            warnings.append("缺少 textPrompt；运行文生场景前必须填写文本 prompt。")
        command = [
            str(FLOW_PYTHON),
            str(TEXT_FLOW_SCRIPT),
            "--prompt",
            text_prompt or "<text-prompt>",
            "--output-dir",
            str(output_dir),
            "--profile",
            profile,
            "--asset-strategy",
            asset_strategy,
            "--image-provider",
            image_provider,
            "--asset-pipeline",
            "asset_library" if asset_strategy == "asset_library" else "source_images",
            "--candidate-count",
            str(int_payload(payload, "candidateCount", 3, 1, 8)),
            "--room-texture-search",
            "--trellis-pipeline-type",
            str(payload.get("trellisPipelineType") or "512"),
            "--texture-size",
            str(int_payload(payload, "textureSize", 2048, 256, 4096)),
            "--decimation-target",
            str(int_payload(payload, "decimationTarget", 500000, 10000, 1000000)),
            "--assemble-scene",
        ]
        if bool_payload(payload, "assetStyleConsistency", True):
            command.append("--asset-style-consistency")
        else:
            command.append("--no-asset-style-consistency")
        if bool_payload(payload, "assetStyleQaStrict", False):
            command.append("--asset-style-qa-strict")
        else:
            command.append("--no-asset-style-qa-strict")
        if bool_payload(payload, "trellisPreprocessImage", True):
            command.append("--trellis-preprocess-image")
        else:
            command.append("--no-trellis-preprocess-image")
        raw_room_type = str(payload.get("roomType") or "").strip()
        room_aliases = {
            "bedroom": "bedroom",
            "bed room": "bedroom",
            "卧室": "bedroom",
            "主卧": "bedroom",
            "living_room": "living_room",
            "living room": "living_room",
            "客厅": "living_room",
            "起居室": "living_room",
            "study": "study",
            "office": "study",
            "书房": "study",
            "办公室": "study",
        }
        room_type = room_aliases.get(raw_room_type.lower(), raw_room_type.lower().replace(" ", "_"))
        if room_type:
            if room_type in {"bedroom", "living_room", "study"}:
                command.extend(["--room-type", room_type])
            else:
                warnings.append(f"未知房间类型 {raw_room_type!r}，将由文生 brief 自动判断。")
        style = str(payload.get("styleConstraints") or "").strip()
        if style:
            command.extend(["--style", style])
        human_constraints = str(payload.get("humanConstraintsFile") or "").strip()
        if human_constraints:
            command.extend(["--human-constraints-file", human_constraints])
        if bool_payload(payload, "useCritic", True):
            command.append("--layout-critic")
        else:
            command.append("--no-layout-critic")
        if asset_strategy == "asset_library":
            trellis_library = str(payload.get("trellisAssetLibraryDir") or "").strip()
            alias_file = str(payload.get("reuseAssetAliasFile") or "").strip()
            articulated_library = str(payload.get("articulatedAssetLibraryDir") or "").strip()
            if trellis_library:
                command.extend(["--trellis-asset-library-dir", trellis_library])
            else:
                command.extend(["--trellis-asset-library-dir", "<asset-library-manifest>"])
                warnings.append("选择了资产库模式，但未填写 Trellis2 rigid asset library 路径。")
            if alias_file:
                command.extend(["--reuse-asset-alias-file", alias_file])
            if articulated_library:
                command.extend(["--articulated-asset-library-dir", articulated_library])
                reserved.append("articulated_asset_library")
        else:
            source_image_dir = str(payload.get("assetSourceImageDir") or "").strip()
            if source_image_dir:
                command.extend(["--asset-source-image-dir", source_image_dir])
                warnings.append("assetSourceImageDir 是旧前端兼容输入；V2 资产生成与准入由核心自行管理。")
        return {
            "mode": mode,
            "profile": profile,
            "profileKind": "formal_delivery" if profile == "production" else "diagnostic",
            "implemented": True,
            "assetStrategy": asset_strategy,
            "imageProvider": image_provider,
            "command": command,
            "outputDir": str(output_dir),
            "warnings": warnings,
            "reservedInterfaces": reserved,
        }

    reference_image = str(payload.get("referenceImage") or "").strip()
    if not reference_image:
        warnings.append("缺少 referenceImage；运行图生场景前必须填写参考图路径。")

    command = [
        str(FLOW_PYTHON),
        str(FLOW_SCRIPT),
        "--flux-image",
        reference_image or "<reference-image>",
        "--output-dir",
        str(output_dir),
        "--profile",
        profile,
        "--image-provider",
        image_provider,
        "--no-layout-template-context",
        "--trellis-pipeline-type",
        str(payload.get("trellisPipelineType") or "512"),
        "--texture-size",
        str(int_payload(payload, "textureSize", 2048, 256, 4096)),
        "--decimation-target",
        str(int_payload(payload, "decimationTarget", 500000, 10000, 1000000)),
        "--model",
        DEFAULT_CODEX_MODEL,
    ]

    prompt = str(payload.get("prompt") or "").strip()
    if prompt:
        command.extend(["--prompt", prompt])

    if bool_payload(payload, "trellisPreprocessImage", True):
        command.append("--trellis-preprocess-image")
    else:
        command.append("--no-trellis-preprocess-image")

    if bool_payload(payload, "useCritic", True):
        command.append("--final-visual-critic-agent")
        command.extend(["--final-visual-critic-max-iterations", str(int_payload(payload, "criticIterations", 3, 0, 8))])
        command.extend(["--final-visual-critic-accept-score", str(float_payload(payload, "criticAcceptScore", 0.72, 0.0, 1.0))])
    else:
        command.append("--no-final-visual-critic-agent")

    asset_source_dir = str(payload.get("assetSourceImageDir") or "").strip()
    if asset_source_dir:
        command.extend(["--asset-source-image-dir", asset_source_dir])
    elif asset_strategy == "generate_from_scratch":
        pass

    human_constraints = str(payload.get("humanConstraintsFile") or "").strip()
    if human_constraints:
        command.extend(["--human-constraints-file", human_constraints])

    if asset_strategy == "asset_library":
        trellis_library = str(payload.get("trellisAssetLibraryDir") or "").strip()
        alias_file = str(payload.get("reuseAssetAliasFile") or "").strip()
        if trellis_library:
            command.extend(["--reuse-asset-dir", trellis_library])
            command.append("--partial-reuse-assets")
            if bool_payload(payload, "copyReusedAssets", True):
                command.append("--copy-reused-assets")
        else:
            command.extend(["--reuse-asset-dir", "<asset-library-manifest>"])
            warnings.append("选择了资产库模式，但未填写 Trellis2 rigid asset library 路径。")
        if alias_file:
            command.extend(["--reuse-asset-alias-file", alias_file])
        articulated_library = str(payload.get("articulatedAssetLibraryDir") or "").strip()
        if articulated_library:
            reserved.append("articulated_asset_library")
            warnings.append("铰接物体资产库字段已写入任务，但当前主流程还未接入该数据库。")

    if bool_payload(payload, "planOnly", False):
        command.append("--plan-only")

    if bool_payload(payload, "wholeWindowCurtainCluster", False):
        reserved.append("whole_window_curtain_cluster_asset")
        warnings.append("整体窗帘-窗户团簇资产接口已预留；当前稳定流程仍使用确定性窗帘簇 solver。")

    return {
        "mode": mode,
        "profile": profile,
        "profileKind": "formal_delivery" if profile == "production" else "diagnostic",
        "implemented": True,
        "assetStrategy": asset_strategy,
        "imageProvider": image_provider,
        "command": command,
            "outputDir": str(output_dir),
            "warnings": warnings,
            "reservedInterfaces": reserved,
    }


def config_payload() -> dict[str, Any]:
    return {
        "app": "TreeSAGE Local Control",
        "controlPlane": {"schema": "scene-webui-control-plane/v1", "sqlite": str(JOBS_DB), "journalMode": "WAL", "remoteAccess": False},
        "modes": [
            {"id": "image_to_scene", "label": "图生场景", "enabled": True},
            {"id": "text_to_scene", "label": "文生场景", "enabled": True},
        ],
        "assetStrategies": [
            {"id": "generate_from_scratch", "label": "从 0 生成资产", "enabled": True},
            {"id": "asset_library", "label": "调用资产库", "enabled": True},
        ],
        "imageProviders": [
            {"id": "builtin_imagegen", "label": "内置图生（实际型号未核验）"},
            {"id": "flux1-schnell", "label": "FLUX.1-schnell"},
        ],
        "defaults": {
            "imageProvider": DEFAULT_IMAGE_PROVIDER,
            "flowPython": str(FLOW_PYTHON),
            "flowScript": str(FLOW_SCRIPT),
            "textFlowScript": str(TEXT_FLOW_SCRIPT),
            "outputRoot": str(DEFAULT_OUTPUT_ROOT),
            "assetSourceRoot": str(DEFAULT_ASSET_SOURCE_ROOT),
            "trellisPipelineType": "512",
            "trellisPreprocessImage": True,
            "assetStyleConsistency": True,
            "assetStyleQaStrict": False,
            "roomTextureSearch": True,
            "textureSize": 2048,
            "decimationTarget": 500000,
            "criticIterations": 3,
            "candidateCount": 3,
            "criticAcceptScore": 0.72,
            "codexModel": DEFAULT_CODEX_MODEL,
        },
        "databaseHooks": {
            "trellisRigidAssets": {"connected": False, "field": "trellisAssetLibraryDir"},
            "articulatedAssets": {"connected": False, "field": "articulatedAssetLibraryDir"},
        },
        "api": [
            "GET /api/config",
            "POST /api/jobs/preview",
            "POST /api/jobs",
            "GET /api/jobs",
            "GET /api/jobs/{id}",
            "POST /api/jobs/{id}/cancel",
            "POST /api/jobs/{id}/assets/{candidate}/review",
        ],
    }


class SageWebHandler(SimpleHTTPRequestHandler):
    server_version = "TreeSAGEWebUI/0.1"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length > 1024 * 1024:
            raise ValueError("request body exceeds 1 MiB limit")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/config":
                self.send_json(config_payload())
                return
            if path == "/api/jobs":
                store, controller = control_plane()
                jobs = [controller.refresh(job["id"]) for job in store.list_jobs()]
                self.send_json({"jobs": jobs[:80]})
                return
            if path.startswith("/api/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                store, controller = control_plane()
                job = store.get_job(job_id)
                if not isinstance(job, dict):
                    self.send_json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
                    return
                self.send_json(controller.refresh(job_id))
                return
            if path == "/":
                self.path = "/index.html"
            super().do_GET()
        except Exception as exc:
            self.send_json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/jobs/preview":
                payload = self.read_json()
                self.send_json({"plan": build_flow_plan(payload)})
                return
            if path == "/api/jobs":
                payload = self.read_json()
                job_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
                plan = build_flow_plan(payload, job_id=job_id)
                payload["imageProvider"] = plan["imageProvider"]
                job = {
                    "id": job_id,
                    "status": "created" if plan.get("implemented") else "reserved",
                    "createdAt": utc_stamp(),
                    "payload": payload,
                    "plan": plan,
                    "warnings": plan.get("warnings", []),
                }
                store, controller = control_plane()
                store.create_job(job)
                if bool_payload(payload, "runNow", False) and plan.get("implemented"):
                    job = controller.start(job_id)
                else:
                    job = store.get_job(job_id) or job
                self.send_json(job, HTTPStatus.CREATED)
                return
            if path.startswith("/api/jobs/") and "/assets/" in path and path.endswith("/review"):
                parts = path.strip("/").split("/")
                job_id, candidate_id = parts[2], parts[4]
                payload = self.read_json()
                store, _ = control_plane()
                store.review_asset(job_id, candidate_id, str(payload.get("status") or "pending"), str(payload.get("reviewer") or "local_user"), str(payload.get("notes") or ""))
                self.send_json(store.get_job(job_id))
                return
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = path.split("/")[-2]
                store, controller = control_plane()
                job = store.get_job(job_id)
                if not isinstance(job, dict):
                    self.send_json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
                    return
                self.send_json(controller.cancel(job_id))
                return
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def validate_bind_host(host: str) -> str:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("remote binding is disabled; authentication and CSRF are intentionally not exposed")
    return host


def main() -> None:
    parser = argparse.ArgumentParser(description="TreeSAGE local web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    validate_bind_host(args.host)

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _, controller = control_plane()
    controller.reattach_all()
    server = ThreadingHTTPServer((args.host, args.port), SageWebHandler)
    print(f"TreeSAGE Web UI: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
