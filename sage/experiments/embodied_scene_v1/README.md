Scene V2 具身仿真第一阶段接口。现有场景生成主链保持原样，本目录是显式调用的独立适配器。

本轮完整证据和上手说明：
`/data/wsj/main/scene_runs/codex_trellis_v2/embodied_phase1_20260913_v1/`。

- `package.py`：从已冻结卧室最终 GLB 和物理绑定导出 MuJoCo 场景、对象清单、语义尺寸审计和两种书桌碰撞。当前导出器限定本轮源卧室，尚非任意 GLB 导入器。
- `models.py`：组合已有 Stretch 2 / robosuite Panda，固定本轮目标、安装位置、成功阈值。`task.json` 是实际执行配置快照，不是供 runner 重新读取的输入。新增任务应显式修改或扩展此层并重新版本化。
- `runner.py`：轮地动力学导航、有限力矩关节控制抓放、真实接触与任务判定；不写运行中位姿，不用焊接抓取。保存完整积分状态及 reset。
- `environment.py`：`reset(seed=0)` / `step(action)` / `observe()` / `render()` / `save()` / `restore()`。这是原型 API，尚未封装成 Gymnasium 训练环境。
- `cameras.py`：Stretch 原生 RGB-D 光学轴绕视线转换 -90°，保留中心和前向，避免输出横转画面；这是派生观测约定，非实机相机标定。
- `diagnostics.py`：书桌空腔的独立碰撞探针。
- `render.py`：重放真实积分状态，输出录像及同步 RGB、深度、实例 ID；外部全景切去南/东墙的显示，机器人相机仍看见四面墙。

运行环境已存在于 `/data/wsj/anaconda3/envs/simgen`，没有升级或重装依赖。主要版本：Python 3.10、MuJoCo 3.3.4、robosuite 1.5.1、NumPy 2.2.6、SciPy 1.15.3、trimesh 4.12.2、Pillow 12.2.0。完整版本在证据目录 `baseline/python_versions.json`。重任务使用证据目录的 `tools/launch.py`，继承 P007 准入、8 逻辑 CPU、12/16 GiB 内存和 900 s 时限；不要直接在无限额会话启动重任务。

以下 CLI 参数可由受控脚本调用：

```bash
python -m sage.experiments.embodied_scene_v1.cli run \
  --package /path/to/package_v3 --output /path/to/new_episode \
  --task pick_place --variant repaired --physics-only
python -m sage.experiments.embodied_scene_v1.cli render \
  --episode /path/to/full_visual_episode --output /path/to/new_presentation
```

输出目录必须是新目录。`--physics-only` 只剥离明确为零质量、零碰撞的 **Scene 视觉几何**；机器人视觉几何可能参与惯性，必须保留。此模式用于状态控制测试，没有完整房间 RGB。相机观测使用完整视觉版本。两个模式的本轮整段状态轨迹已进行逐位比较。

任务角色：29 家具/附件，加门窗两个对象，共31个带 ID 的原场景对象；另加一个有明确来源的独立桌面单书目标。原五本书冻结在已有自由仿真的最终姿态。书桌、家具、门窗作为静态环境；本阶段不覆盖开门、抽屉、全屋动态、四足、实机迁移或策略训练收益。物性与机器人模型惯性属于声明先验，未实测标定。

视觉层保留原场景三角形和最多512像素的基础颜色贴图；没有复现全部 GLB 法线/粗糙度 PBR。此渲染用于机器人诊断，独立外观验收仍按原协议。

机器人来源：

- [MuJoCo Menagerie Stretch 2](https://github.com/google-deepmind/mujoco_menagerie/tree/8161bba264d7fa7c99ca301e91e7fb44737676ad/hello_robot_stretch)，原模型文件、Clear BSD 许可证和逐文件来源保存在场景包及证据目录。
- Panda 来自已安装 robosuite 1.5.1，复制原机器人/夹爪资源，许可证另存 `robots/PANDA_LICENSE`；模型惯性近似保持原值。
- [MuJoCo 3.3.4 Python 接口](https://mujoco.readthedocs.io/en/3.3.4/python.html)。
