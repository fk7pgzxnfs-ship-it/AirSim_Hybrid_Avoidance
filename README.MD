# AirSim Hybrid Avoidance - 无人机混合避障导航系统

> **使用说明**：[docs/USER_GUIDE.md](docs/USER_GUIDE.md)（从零开始的操作手册、命令参考与常见问题）

> **v3.1（2026-09-09）**：弹窗集成**场景编辑器**（顶部「控制台 / 场景编辑器」标签页切换，窗口内拖拽编辑场景）；新增**自动连接 UE**——一键启动 UE 进程并等待端口 8990，路径在弹窗「系统」或 `config/ue_launch.json` 配置。

> **v3.0.2（2026-08-22）**：新增独立 Windows 应用 **`AirSim控制台.exe`**（双击即弹，无黑色控制台框，Win11 现代风格）；数据目录 = exe 所在目录，按钮任务自动调用本机 Python 执行飞行/训练脚本。打包复现：`python scripts/tools/build_exe.py`。

> **v3.0.1（2026-08-21）**：`python main.py` 默认弹出 **Windows 原生控制台窗口**（WebView2 内核渲染，Win11 现代风格：场景/飞行/训练评估/系统分类按钮 + 实时日志），替换复古 tkinter 窗口；`--browser` 可回退浏览器。

> **v3.0（2026-08-21）**：支持自定义地图、起点终点与障碍物布局——`python main.py --editor` 网页拖拽编辑场景，`python main.py --scene 场景.yaml --flights 3` 一键飞行；路线 = 起点终点直线。**注意：自定义布局需重训 DRL 模型，v2.1b 模型只适用于默认 100×10 场景。**

> **v2.2（2026-08-21）**：新增统一入口 `main.py`——接上 UE 直接 `python main.py` 就能飞；散落脚本分类整理到 `scripts/`（fly / train / evaluate / diag / tools）。

> **v2.1（2026-08-20）**：修复 DRL 直线段蛇形振荡（左扭右扭）。**纯算法层解决**（奖励塑形：动作平滑惩罚 + 横向偏移惩罚），部署端零改动、零动作滤波。UE 对齐评估：成功率 100%、碰撞 0%、直线段 y 波动 ±0.3m。版本记录见 [CHANGELOG.md](CHANGELOG.md)。

## 📋 项目简介
基于 **Project AirSim（UE 5.7）** 仿真平台的无人机自主避障导航系统，采用 **A* 全局规划 + DRL（DDPG）局部避障 + 势场安全备份** 的三层混合架构。目标场景：**100m×10m 走廊**（x∈[0,100]，y∈[-5,5]）+ 两个 2×2×14m 障碍物（x=30 / x=65），无人机从头飞到尾并全程避障。

v2.1 目标：**消除 v2.0 策略在直线段的蛇形振荡**。v2.0 的 A* 路径本身是直线，但 DRL 策略输出的动作在直线段仍满幅左右切换，部署到 UE fast-physics（直接执行目标速度）后表现为"直线段左扭右扭"。v2.1 通过奖励塑形让策略学会输出平滑动作，**不在部署端加任何动作滤波**（用户明确约束）。

## 🏗️ 核心架构
```
Supervisor（总控循环）
├── Global Planner (A* 算法)      → 全局最优路径规划
├── Local Planner (DRL/DDPG)      → 实时局部避障
├── Safety Monitor (势场法)        → 安全备份与紧急干预
└── ProjectAirSimClient (UE RPC)   → MoveByVelocity / SetPose / LoadScene / LiDAR
```

## ✅ v2.1 验收状态（2026-08-20）
- **根因（确定事实）**：v2.0 策略输出锯齿形动作（基线评估 `mean|Δaction|=2.368`、`action_y_std=1.591`）；训练仿真速度惯性（`vel_time_constant=0.5s`）掩盖振荡，UE fast-physics 直接执行目标速度，振荡指令直接变成蛇形轨迹；奖励无动作变化惩罚，策略学会"能完成任务但动作振荡"的局部最优。
- **修复（算法层，无部署滤波）**：奖励新增 `-0.15×|Δaction|`（动作平滑惩罚）+ `-0.10×|y|`（横向偏移惩罚），训练出平滑策略；另修复部署端 `get_velocity()` 字段解析（`twist.linear`，此前 `linear_velocity` 恒 0）。
- **训练（确定事实）**：1500 轮，最后 100 轮平均奖励 230.2，训练成功率 100%，耗时约 24.5 分钟（CPU）。
- **UE 对齐评估（vel_tc=0.1，60 局随机布局，确定事实）**：成功率 100%（60/60）、碰撞率 0%、平均 166 步、`mean|Δaction|=0.124`、`action_y_std=0.612`、y 符号切换 5.1 次、路径/直线比 1.0312、y 跨度 4.857m。
- **分段分析（确定事实）**：直线段（最近障碍 >8m）y 标准差 **0.30m**、y 跨度 **1.52m**；避障段 y 跨度 4.63m。轨迹图 `logs/train/traj_v21_fixed.png`：直线段 y 在 ±0.3m 内几乎无摆动、避障干脆。
- **UE 实机复核（不确定信息）**：v2.1 模型在 UE 上的实机复核尚未最终完成（曾中断）；建议用 `python main.py --flights 3` 复核一次。

## 🚀 快速开始（v3.0 / UE 5.7 实机）
### 0. 双击 exe 使用（推荐）
- 将 `AirSim控制台.exe` 放在项目根目录（数据目录 = exe 所在目录，config/scenes、scripts、models 需与 exe 同目录）。
- 先启动 UE 5.7（见下方步骤 2），等端口 8990 就绪后，双击 exe 即弹出 Windows 原生窗口（无黑框），选场景 → 点“飞行”即可。
- exe 只是控制台外壳：点击飞行/训练等按钮时，会调用本机系统 Python 后台执行 `scripts/...` 脚本（自动探测 `python`，或设置环境变量 `AIRSIM_PYTHON` 指定）；本机仍需安装 Python 与依赖。
### 1. 安装依赖
```bash
pip install -r requirements.txt
```
### 2. 启动 UE 5.7（空白 GISMap 场景）
```powershell
"D:\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe" "D:/ProjectAirSim-main/unreal/Blocks 5.7/Blocks.uproject" GISMap -game -windowed -ResX=1280 -ResY=720
```
等待端口 **8990** 可连接（约 30–60s）。场景内容（地面 + 障碍物 + 无人机）由脚本通过 LoadScene RPC 自动加载。
### 3. 自定义场景（v3）
```bash
python main.py --editor        # 打开网页场景编辑器（http://127.0.0.1:8787）
python main.py --scene config/scenes/scene_100x10.yaml --check   # 指定场景检查连接
```
- 编辑器内拖拽摆障碍物、拖起点/终点、改地图范围，实时 A* 可达性检查，保存到 `config/scenes/<name>.yaml`。
- 命令行指定场景：`python main.py --scene config/scenes/<name>.yaml --flights 3`（飞行/评估/训练共用同一场景配置）。
- 场景文件也可手写；`python scripts/tools/gen_scene.py --scene xxx.yaml --preview out.png` 生成 UE 场景 jsonc 与 2D 预览图。

### 4. 一键飞行（推荐，统一入口）
```bash
python main.py               # 弹出 Windows 原生控制台窗口（WebView2，推荐）
python main.py --flights 3   # 命令行直跑：连续 3 次飞行 + 自动校验
python main.py --browser     # 备用：浏览器打开控制台
python main.py --menu        # 命令行菜单（高级用户）
python main.py --check       # 检查 UE 连接
```
- 每次飞行前自动 **LoadScene 同配置热重载**（干净重建机器人，规避 SetPose 回弹，见 CHANGELOG v2.0）；轨迹输出到 `logs/flights/flight_<时间戳>.csv`。
- 需要更细控制时可调用底层脚本：
```bash
python scripts/fly/run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000   # 单次飞行（--no-reload 可跳过重载）
python scripts/fly/run_v2_demo.py --flights 3                                # 连续演示
```
### 5. 训练 DRL 模型（如需重训）
```bash
python main.py --train                              # 完整训练（约 25 分钟，CPU）
python scripts/train/train_drl_v2.py --quick        # 冒烟测试
```
训练完成后自动做 60 次无探索评估（含 v2.1 平滑度指标）；最优模型写入 `models/drl_agent/ddpg_best.pth`。重训前建议备份：`Copy-Item models\drl_agent\ddpg_best.pth models\drl_agent\ddpg_best_before_retrain.pth`。
### 6. 平滑度评估与可视化（无需 UE，2D 仿真）
```bash
python main.py --eval                                        # UE 对齐评估（成功率/碰撞/平滑度指标）
python scripts/evaluate/evaluate_smoothness.py --vel-tc 0.1 --n 60
python scripts/evaluate/_analyze_segments.py                 # 直线段/避障段分段分析
python scripts/evaluate/_plot_traj.py                        # 生成样例轨迹图 logs/train/traj_v21_fixed.png
```
### 7. 轨迹可视化
```bash
python experiments/visualize_trajectory.py --csv logs/flights/flight_xxx.csv
```

## 📁 项目结构
```
AirSim Hybrid Avoidance/
├── main.py
├── AirSim控制台.exe           # v3.0.2 独立 Windows 应用（双击即弹，无黑框）                   # v3 统一入口（默认弹出 Windows 原生窗口 + 命令行直跑）
├── scene_config.py             # v3 场景配置模块（加载/校验/可达性/UE 生成/预览）
├── config/                   # 配置：default.yaml（算法参数）；ue_launch.json（UE 启动路径，v3.1）；scenes/ 场景 yaml（v3）+ generated/（生成的 UE jsonc）
├── airsim_interface/         # 通信层：projectairsim_client.py（UE RPC）、sensor_processor.py
├── planning/                 # 传统规划：grid_map.py、a_star.py、potential_field.py
├── drl/                      # DRL：env.py（v2.1 奖励塑形）、agent.py、trainer.py、models.py、sim_client.py（训练仿真）
├── hybrid_controller/        # 混合控制器：supervisor.py、global_planner.py、local_planner.py、safety_monitor.py
├── experiments/              # 实验：run_flight.py、visualize_trajectory.py、analyze_results.py
├── scripts/                  # 可执行脚本分类
│   ├── fly/                  #   飞行：run_hybrid.py（单次）、run_v2_demo.py（连续演示 + 校验）
│   ├── train/                #   训练：train_drl_v2.py、train_drl.py
│   ├── evaluate/             #   评估分析：evaluate_smoothness.py、_analyze_segments.py、_plot_traj.py、_analyze_osc.py、evaluate.py
│   ├── diag/                 #   诊断：_diag_*.py（UE 对接排障用）
│   └── tools/                #   工具：test_drone.py、fly_straight.py、download_release.py、gen_scene.py（v3 场景生成器）、build_exe.py（v3.0.2 exe 打包）
├── web/                      # v3 Web 控制台 + 场景编辑器（Flask 后端 + 现代前端 + WebView2 原生弹窗）
├── logs/                     # 运行日志：flights/（轨迹 CSV）、train/（训练曲线 + 轨迹图）、scene_preview_*.png
├── models/drl_agent/         # DRL 权重（ddpg_best.pth = v2.1b 最终模型；v2.0 备份 ddpg_v20_backup.pth）
└── docs/                     # 文档：handover.md、USER_GUIDE.md
```

## 💡 关键实现说明
- **v2.1 平滑方案（纯算法层）**：在 `drl/env.py` 奖励中新增两项——`action_smooth_penalty`（惩罚相邻动作突变 `|a_t - a_{t-1}|`）与 `lateral_penalty`（惩罚横向偏移 `|y|`），系数见 `config/default.yaml`（`0.15 / 0.10`）。训练后策略在直线段输出近零 `action_y`，避障段仍能果断侧移。**部署端无任何动作滤波/平滑**。
- **训练仿真速度惯性**：`vel_time_constant: 0.5` 与 v2.0 训练动态一致（曾试 0.1 对齐 UE fast-physics，890 轮不收敛已放弃）；UE 对齐评估用 `--vel-tc 0.1` 模拟 fast-physics 行为。
- **飞行间复位**：每次飞行前 `LoadScene` 同配置热重载，机器人被干净重建在场景原点，再走 SetPose + takeoff 真实爬升；规避 UE actor 回弹卡死。
- **DRL 状态/动作**：8 维状态（dx, dy, vx, vy, 最近障碍距离/角度, 目标距离/角度），2 维动作 [vx, vy]∈[-2,2]；奖励含走廊边界惩罚（|y|>4.5 起罚）。
- **安全兜底**：SafetyMonitor 三级逻辑（critical <1.5m 紧急势场逃逸；warning <3.0m 且朝向障碍预防性干预）。
- **到达终点**：悬停保持，不调用 Land/Disarm/DisableApiControl（避免飞行后复位触发回弹）。

## ⚠️ 已知问题与注意事项
- **SetPose 飞行后回弹**：同一 UE 实例连续飞行时，第 2 次开头的 SetPose 复位会使 UE actor 滞留在地图出生点 (66.5, 0, 14.19m)（与 Obstacle2 重叠）并持续碰撞。**必须用 LoadScene 热重载复位**（详见 `docs/handover.md` 11.11）。
- **热重载连接**：验证场景为"同配置重载 + 每次新进程/新连接"；重载后复用旧客户端连接直接发指令的行为未验证。
- **模拟 LiDAR 与真实 LiDAR** 有语义差距（训练/部署一致，但仍是先验障碍的近似）；SAFETY 势场作为兜底。
- **UE 窗口失焦/最小化**会导致模拟时钟降速（实测 0.15x~1.6x），影响飞行节奏。
- **MoveByVelocity 是同步阻塞 RPC**，响应耗时 ≈ duration 的模拟秒数。
- **v2.1 直线段残留**：直线段 y 波动已从 v2.0 的 ~7.5m 跨度降到 ~1.5m（y_std 0.30m），但非绝对零摆动；若实测仍嫌摆动，可上调 `action_smooth_penalty`/`lateral_penalty`（注意避障段 y 跨度会略增、奖励略降）。
- **v3 模型不通用**：v2.1b 模型只在默认 100×10 + 双障碍分布上训练过；自定义地图/障碍/起终点后必须重训（`python main.py --train`），否则 DRL 大概率失效、SAFETY 兜底频繁介入。
- **本机 PowerShell 中 `python` 可能不可用**，请使用完整路径 `C:\Users\13631\AppData\Local\Programs\Python\Python313\python.exe`。

## 📜 版本历史
| 版本 | 日期 | 里程碑 |
|---|---|---|
| v3.1 | 2026-09-09 | 编辑器集成进弹窗（控制台/场景编辑器标签页）；自动连接 UE（一键启动 + 等待 8990）；UE 路径弹窗内可配置 |
| v3.0.3 | 2026-08-22 | 修复 python main.py 启动崩溃（stdout 重复包装导致 I/O operation on closed file） |
| v3.0.2 | 2026-08-22 | 独立 Windows 应用 AirSim控制台.exe（双击即弹，无黑框）；任务自动调用本机 Python；打包脚本 build_exe.py |
| v3.0.1 | 2026-08-21 | Windows 原生控制台窗口（WebView2 内核，Win11 现代风格）替换 tkinter 复古窗口；`python main.py` 默认弹窗，`--browser` 回退浏览器 |
| v3.0 | 2026-08-21 | 自定义地图/起点终点/障碍物（网页编辑器 + 场景文件驱动）；路线=起点终点直线；UE 场景程序化生成 |
| v2.2 | 2026-08-21 | 统一入口 main.py（一键飞行/评估/重训）；脚本分类整理到 scripts/（fly/train/evaluate/diag/tools） |
| v2.1 | 2026-08-20 | 修复 DRL 直线段蛇形振荡（纯算法层奖励塑形）；UE 对齐评估 100% 成功率/0 碰撞；直线段 y_std 0.30m |
| v2.0 | 2026-08-19 | UE 实机闭环：DRL 100% 评估、100×10 走廊双障碍、7 次连续飞行干净、LoadScene 复位修复 |
| v1.1 | 2026-08-03 | UE 5.7 对接打通："点 Play 不动"排查、地面板加长、起点复位 |
| v1.0 | 2026-07-31 | 初始三层混合架构（A* + DRL + 势场），AirSim 双模式客户端 |

详细变更见 [CHANGELOG.md](CHANGELOG.md)。