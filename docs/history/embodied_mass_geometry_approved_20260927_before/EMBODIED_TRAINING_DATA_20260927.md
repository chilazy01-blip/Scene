# 条件化仿真训练数据入口

本页说明已交付数据和读取方式；当前进度/授权见[交接](EMBODIED_LONG_RUN_HANDOFF_20260926.md)，后续采集计划见[路线图](EMBODIED_DATA_ROADMAP_20260926.md)。下一MG批仅完成56初态静态预检，未增加本页训练数量。

2026-09-27。可读取的研究数据已经交付：97条成功开发轨迹、261900条100Hz状态/动作转移；其中44条有完整27秒腕部RGB-D，共11880个10Hz时刻及118800步对齐动作。44是97的子集，图像重建、格式导出和压缩副本都不增加任务数。

运行根 `T=/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1`。统一目录为 `T/capability_training_bundle/TRAINING_CATALOG.json`，逐字段验证结果为同目录 `RESULT.json`。原始文件保留在各采集阶段。

## 实际训练读取

在项目依赖环境中使用以下公开读取器。运行脚本时按项目要求使用Python `-I -B`，并显式加入仓库路径。它只缓存当前一条序列，支持Torch DataLoader；默认只取所有序列共同拥有的腕部相机，头部原图仍在原数据中。

```python
import sys
sys.path.insert(0, '/data/wsj/main/scene')
from torch.utils.data import DataLoader
from sage.experiments.embodied_capability_v1.catalog import DevelopmentRGBD

root = '/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1'
data = DevelopmentRGBD(root + '/capability_training_bundle/TRAINING_CATALOG.json')
batch = next(iter(DataLoader(data, batch_size=16, num_workers=0)))
camera = batch['cameras']['d405_rgb']
rgb = camera['rgb']                    # uint8 [B,192,256,3]
depth = camera['depth_m']              # float32 [B,192,256], metres
valid = camera['valid']                # bool [B,192,256]
references = batch['trajectory']['action_reference_chunk']  # float64 [B,10,10]
```

相机公开字段还包括 `K` 与 `optical_to_base`。深度为仿真理想配准值，外参来自机器人FK；不等于真实相机噪声或真实底盘里程计。`episode_index/frame_index`用于追溯，不是模型输入。数据读取器不返回物体真值、质量标签、分割真值或世界相机位姿。

动作每行是10个原生执行器参考量，100Hz、每图10步，按 `action_names/action_units`解释；`action_ctrl_chunk`另含有限出力下内部重力前馈后的控制量。不能把轮子传动速度当任意归一化动作。腕部三轴及头部两轴，共5通道在这批任务中固定，不能宣称覆盖灵巧动作。

## 来源和划分

|来源|可训练成功开发轨迹|完整RGB-D|验证隔离|
|---|---:|---:|---|
|参考能力C|45|6|30留出、3基线均不混入|
|自有书房H|20|6|本阶段20均为事先声明开发|
|生成布局几何D|32|32|8独立验证、8开发失败隔离|
|总计|97|44|视觉W、确认Q及几何确认F均不训练|

原生官方格式入口是 `capability_multimodal/datasets_lerobot` 和 `capability_geometry_collection/observations/datasets_lerobot`，RGB为无损PNG、动作保持原类型；`NativeRGBDChunks`将官方读取结果与绑定的精确HDF5深度拼接。统一读取器复用同一批已审计HDF5，没有再复制大文件。

有状态轨迹的官方目录可能包含失败和验证；必须用目录中的开发episode选择，不要整目录无差别训练。统一入口已检验重复源轨迹、失败任务、绑定改动、稀疏验证、资格越权等7个负例。11880行真实Torch读取跨episode边界逐值逐类型核验通过。

## 已知证据边界

所有新数据仅支持明确假设的有限有效出力/轮阻力仿真研究。外部gravcomp与外加力均关闭，内部重力前馈经有限执行器实现。严格硬件努力/传动来源缺口尚未解决，无真机资格。

D开发产量32/40，原整批产量门未通过；最小g1盒8/8放置失败，保留全部失败。其余4种开发尺寸在原矩阵均4/4通过，但不能把选择成功子集等同整体量产通过。两新布局复用资产和同一任务桌，仅背景/窗墙有变化。

等量图像学习中，多尺寸组初态定位22/24，窄尺寸组3/24（3个模型×8条件）；实际视觉初始化取放随后触发累计3物理无效退出。定位准确度提升不能替代完整任务验收，未来数据扩采也不能依赖这条已关闭的视觉分支。

研究数据可现在读取。下一次训练仍须另设冻结模型、独立评测及计算预算，不能对现有留出反复调参。

2026-09-27独立复验追加：g2–g5、SD01/SD02共24新初态，专家24/24成功，各格3/3。324000积分及64800条官方原生转移核验通过，全部继续作为独立评价，训练总数仍97/44。它支持该明确范围的重复性，不改变原D整体产量门失败或W视觉累计退出。

## 完整无损交付副本已完成

用户授权项目磁盘21→31GiB后，32条几何序列的HDF5从2248430526B压为727202757B（32.34%）。原始文件完整保留；所有HDF5字段/类型/属性完全相同。官方RGB/动作保持字节相同，8640行新深度、掩码、时间实际读取全量通过。

可将上面示例中的目录路径改为 `root + '/capability_lossless_storage/UNIFIED_TRAINING_CATALOG.json'`。它仍是44条原始来源：旧M12条加D32条，其中D的存储路径换为已验证无损副本。每条首、中、尾共132个实际训练读取点与原目录完全相同；完整内容已由打包及原生全量审计覆盖。原统一目录继续可用，97开发/44完整RGB-D和评价划分不变。
