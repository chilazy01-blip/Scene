const state = {
  config: null,
  mode: "image_to_scene",
};

const $ = (id) => document.getElementById(id);

function setStatus(text) {
  $("runtimeStatus").textContent = text;
}

function fieldValue(id) {
  const node = $(id);
  if (!node) return "";
  if (node.type === "checkbox") return node.checked;
  return node.value.trim();
}

function selectedAssetStrategy() {
  const checked = document.querySelector('input[name="assetStrategy"]:checked');
  return checked ? checked.value : "generate_from_scratch";
}

function collectPayload() {
  const assetSourceImageDir =
    state.mode === "text_to_scene" ? fieldValue("textAssetSourceImageDir") : fieldValue("assetSourceImageDir");
  return {
    mode: state.mode,
    assetStrategy: selectedAssetStrategy(),
    referenceImage: fieldValue("referenceImage"),
    sceneName: fieldValue("sceneName"),
    outputRoot: fieldValue("outputRoot"),
    assetSourceImageDir: assetSourceImageDir,
    humanConstraintsFile: fieldValue("humanConstraintsFile"),
    prompt: fieldValue("prompt"),
    textPrompt: fieldValue("textPrompt"),
    roomType: fieldValue("roomType"),
    styleConstraints: fieldValue("styleConstraints"),
    trellisAssetLibraryDir: fieldValue("trellisAssetLibraryDir"),
    articulatedAssetLibraryDir: fieldValue("articulatedAssetLibraryDir"),
    reuseAssetAliasFile: fieldValue("reuseAssetAliasFile"),
    useCritic: fieldValue("useCritic"),
    criticIterations: fieldValue("criticIterations"),
    candidateCount: fieldValue("candidateCount"),
    criticAcceptScore: fieldValue("criticAcceptScore"),
    trellisPipelineType: fieldValue("trellisPipelineType"),
    textureSize: fieldValue("textureSize"),
    decimationTarget: fieldValue("decimationTarget"),
    trellisPreprocessImage: fieldValue("trellisPreprocessImage"),
    copyReusedAssets: fieldValue("copyReusedAssets"),
    wholeWindowCurtainCluster: fieldValue("wholeWindowCurtainCluster"),
    planOnly: fieldValue("planOnly"),
    deliveryProfile: fieldValue("deliveryProfile"),
    runNow: fieldValue("runNow"),
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `${response.status} ${response.statusText}`);
  }
  return data;
}

function renderWarnings(warnings) {
  const target = $("warnings");
  target.innerHTML = "";
  for (const warning of warnings || []) {
    const item = document.createElement("div");
    item.className = "warning";
    item.textContent = warning;
    target.appendChild(item);
  }
}

function renderPlan(plan) {
  const lines = [];
  lines.push(plan.implemented ? "配置可创建任务" : "当前配置仅预留接口");
  lines.push(`运行用途：${plan.profileKind === "formal_delivery" ? "正式交付" : "诊断"} (${plan.profile || "unknown"})`);
  if (plan.outputDir) lines.push(`输出目录：${plan.outputDir}`);
  if (plan.mode === "text_to_scene" && plan.assetStrategy === "generate_from_scratch") {
    lines.push("资产链路：SceneBrief -> V2 缺失资产合同 -> Trellis2 -> 准入 -> Blender");
  } else if (plan.assetStrategy === "asset_library") {
    lines.push("资产链路：SceneBrief -> 审核资产库 -> V2 布局/验收");
  }
  $("planSummary").textContent = lines.join("\n");
  renderWarnings(plan.warnings || []);
}

async function previewCommand() {
  setStatus("正在检查配置");
  const data = await api("/api/jobs/preview", {
    method: "POST",
    body: JSON.stringify(collectPayload()),
  });
  renderPlan(data.plan || {});
  setStatus("配置检查已更新");
}

async function createJob() {
  setStatus("正在创建任务");
  const job = await api("/api/jobs", {
    method: "POST",
    body: JSON.stringify(collectPayload()),
  });
  renderPlan(job.plan || {});
  await loadJobs();
  setStatus(`任务 ${job.id} 已创建`);
}

function renderJobs(jobs) {
  const target = $("jobsList");
  target.innerHTML = "";
  if (!jobs.length) {
    const empty = document.createElement("div");
    empty.className = "job";
    empty.textContent = "暂无任务";
    target.appendChild(empty);
    return;
  }
  for (const job of jobs) {
    const item = document.createElement("div");
    item.className = "job";

    const title = document.createElement("strong");
    title.textContent = `${job.id} · ${job.status}`;
    item.appendChild(title);

    const created = document.createElement("span");
    created.textContent = job.createdAt || "";
    item.appendChild(created);

    const profile = document.createElement("span");
    profile.textContent = job.profile === "production" ? "正式交付" : `诊断运行 (${job.profile || "unknown"})`;
    item.appendChild(profile);

    const gate = document.createElement("span");
    const gateData = job.resourceGate || {};
    gate.textContent = gateData.accepted === false
      ? `资源门：等待 · ${(gateData.reasons || []).join(", ")}`
      : gateData.accepted === true ? "资源门：通过" : "资源门：尚未评估";
    item.appendChild(gate);

    if ((job.stages || []).length) {
      const stage = document.createElement("span");
      const done = job.stages.filter((entry) => entry.status === "committed").length;
      stage.textContent = `阶段：${done}/${job.stages.length}`;
      item.appendChild(stage);
    }

    for (const asset of job.assetCandidates || []) {
      const review = document.createElement("div");
      review.className = "asset-review";
      review.textContent = `资产 ${asset.candidate_id} · 生成 ${asset.generation_status} · 人工 ${asset.approval_status}`;
      if (asset.approval_status !== "not_required") {
        for (const status of ["approved", "rejected"]) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "secondary compact";
          button.textContent = status === "approved" ? "批准" : "拒绝";
          button.addEventListener("click", async () => {
            await api(`/api/jobs/${job.id}/assets/${encodeURIComponent(asset.candidate_id)}/review`, {
              method: "POST", body: JSON.stringify({ status, reviewer: "local_user" }),
            });
            await loadJobs();
          });
          review.appendChild(button);
        }
      }
      item.appendChild(review);
    }

    const output = job.plan && job.plan.outputDir ? job.plan.outputDir : "";
    if (output) {
      const code = document.createElement("code");
      code.textContent = output;
      item.appendChild(code);
    }
    target.appendChild(item);
  }
}

async function loadJobs() {
  const data = await api("/api/jobs");
  renderJobs(data.jobs || []);
}

function setMode(mode) {
  state.mode = mode;
  for (const button of document.querySelectorAll("[data-mode]")) {
    button.classList.toggle("active", button.dataset.mode === mode);
  }
  const imageMode = mode === "image_to_scene";
  $("imageSceneFields").classList.toggle("hidden", !imageMode);
  $("textSceneFields").classList.toggle("hidden", imageMode);
  $("formTitle").textContent = imageMode ? "图生场景" : "文生场景";
  $("modeNote").textContent = imageMode
    ? "参考图 soft observation -> SceneRequest/SceneBrief -> V2 核心"
    : "文本 -> SceneRequest/SceneBrief -> V2 核心";
  previewCommand().catch((error) => setStatus(error.message));
}

function applyDefaults(config) {
  const defaults = config.defaults || {};
  $("outputRoot").value = defaults.outputRoot || "";
  $("assetSourceImageDir").placeholder = `${defaults.assetSourceRoot || "/data/xy/SAGE_runs/image2_replacement"}/.../source_images`;
  $("textAssetSourceImageDir").placeholder = `${defaults.assetSourceRoot || "/data/xy/SAGE_runs/image2_replacement"}/.../source_images`;
  $("trellisPipelineType").value = defaults.trellisPipelineType || "512";
  $("textureSize").value = defaults.textureSize || 2048;
  $("decimationTarget").value = defaults.decimationTarget || 500000;
  $("trellisPreprocessImage").checked = defaults.trellisPreprocessImage !== false;
  $("criticIterations").value = defaults.criticIterations || 3;
  $("candidateCount").value = defaults.candidateCount || 3;
  $("criticAcceptScore").value = defaults.criticAcceptScore || 0.72;
}

function bindEvents() {
  for (const button of document.querySelectorAll("[data-mode]")) {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  }
  $("previewCommand").addEventListener("click", () => previewCommand().catch((error) => setStatus(error.message)));
  $("createJob").addEventListener("click", () => createJob().catch((error) => setStatus(error.message)));
  $("refreshJobs").addEventListener("click", () => loadJobs().catch((error) => setStatus(error.message)));
  for (const node of document.querySelectorAll("input, textarea, select")) {
    node.addEventListener("change", () => previewCommand().catch(() => {}));
  }
}

async function boot() {
  bindEvents();
  state.config = await api("/api/config");
  applyDefaults(state.config);
  await previewCommand();
  await loadJobs();
  setStatus("本地服务已连接");
}

boot().catch((error) => {
  setStatus(error.message);
});
