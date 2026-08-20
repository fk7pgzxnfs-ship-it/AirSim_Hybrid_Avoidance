# Changelog

版本记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 风格。日期依据 `docs/handover.md` 与文件时间戳（确定事实）。

## [v2.2] - 2026-08-21
### 里程碑
新增统一入口 main.py：接上 UE 后直接 python main.py 即可飞行/评估/重训/查连接；散落脚本分类整理到 scripts/ 子目录（fly / train / evaluate / diag / tools），根目录只保留 main.py 与模块目录。

### 新增
- 统一入口 main.py（项目根）：交互菜单（1 单次飞行 / 2 连续飞行 / 3 平滑度评估 / 4 重训 / 5 检查连接 / 0 退出），启动时自动检测 UE 8990 端口；支持命令行直跑 --flights N / --single / --eval / --train / --check。
- 脚本分类：scripts/fly/（run_hybrid.py、run_v2_demo.py）、scripts/train/（train_drl_v2.py、train_drl.py）、scripts/evaluate/（evaluate.py、evaluate_smoothness.py、_analyze_osc.py、_analyze_segments.py、_plot_traj.py）、scripts/diag/（_diag_*.py 共 8 个）、scripts/tools/（test_drone.py、fly_straight.py、download_release.py、_gen_handover.py）。

### 修复
- 8 个需 import 的脚本 sys.path.insert 修正为指向项目根（os.path.dirname 上溯三层），旧路径在目录迁移后失效。
- scripts/tools/fly_straight.py 第 3 行历史损坏的 docstring 引号修复（"" 改为 """）。

### 变更
- README 重写为 v2.2（统一入口 + 新项目结构 + 命令参考）；USER_GUIDE 同步更新。
- 全部 21 个脚本 py_compile 通过；main.py --check 与 --eval（60 局）实测通过。

### 说明
- v2.2 不改变算法与模型：v2.1b 模型与 v2.1 平滑方案保持不变，仅统一操作入口与目录结构。
- UE 实机复核（不确定信息）：v2.1 模型在 UE 实机上的复核仍未最终完成；可用 python main.py --flights 3 复核。

## [v2.1] - 2026-08-20
### 里程碑
修复 v2.0 DRL 策略在直线段的蛇形振荡（左扭右扭）。**纯算法层解决**（奖励塑形），部署端零改动、无动作滤波。UE 对齐评估（vel_tc=0.1）：成功率 100%、碰撞 0%、直线段 y 标准差 0.30m。

### 根因（确定事实）
- v2.0 策略本身输出锯齿形动作（基线评估 `mean|Δaction|=2.368`、`action_y_std=1.591`），**不是部署特有问题**。
- 训练仿真速度惯性（`vel_time_constant=0.5s`）掩盖振荡：仿真里动作突变被一阶速度跟踪低通，轨迹看起来平滑；UE fast-physics 直接执行目标速度，振荡指令直接变成蛇形轨迹。
- 奖励无动作变化惩罚/横向偏移惩罚，策略学到"能完成任务但动作振荡"的局部最优。
- 次要因素（sim-to-real gap）：部署端 `get_velocity()` 解析 `linear_velocity` 恒 0（UE 端字段为 `twist.linear`），导致部署时 state 的 vx/vy 恒 0。

### 新增
- **奖励塑形（算法层，无部署滤波）**：`drl/env.py` 新增动作平滑惩罚 `-action_smooth_penalty * |a_t - a_{t-1}|` 与横向偏移惩罚 `-lateral_penalty * |y|`；`step()` 计算 `action_change` 传给奖励计算。
- **配置**：`config/default.yaml` 新增 `drl.reward.action_smooth_penalty: 0.15`、`lateral_penalty: 0.10`；`vel_time_constant: 0.5` 保持 v2.0 训练动态（曾试 0.1 对齐 UE，890 轮不收敛、奖励恒 -572 贴墙，已放弃改回 0.5）。
- **评估工具**：`evaluate_smoothness.py`（任意 ckpt × 任意 vel_tc 评估成功率/碰撞/`mean|Δaction|`/`action_y_std`/y 符号切换/路径比/y 跨度）、`_analyze_segments.py`（直线段 nd>8m / 避障段 nd<=8m 分段分析）、`_plot_traj.py`（样例轨迹图）。
- **训练脚本**：`train_drl_v2.py` 支持 `--tag`；训练后自动评估新增平滑度指标；`--tag` 默认值改为 `v21b`。

### 修复
- **部署端速度反馈（sim-to-real 正确性修复）**：`airsim_interface/projectairsim_client.py` 的 `get_velocity()` 优先读 `twist.linear`，兼容旧字段 `linear_velocity`；此前 UE 返回的速度恒 0 导致部署 state 的 vx/vy 恒 0。

### 变更
- **重训结果（v2.1b 最终模型）**：1500 轮训练，最后 100 轮平均奖励 230.2、成功率 100%、耗时约 24.5 分钟（CPU）；训练日志 `logs/train_v21b.log`。
- **UE 对齐评估（vel_tc=0.1，60 局随机布局）**：成功率 100%（60/60）、碰撞率 0%、平均 166 步、`mean|Δaction|=0.124`、`action_y_std=0.612`、y 符号切换 5.1、路径/直线比 1.0312、y 跨度 4.857m。
- **分段分析（vel_tc=0.1）**：直线段（nd>8m）y 跨度 1.52m、y 标准差 0.30m、累计 |dy| 6.7m、y 符号切换 5.1；避障段（nd<=8m）y 跨度 4.63m、y 标准差 1.43m。
- **模型**：`models/drl_agent/ddpg_best.pth` = v2.1b；v2.0 备份 `ddpg_v20_backup.pth`；v2.1a 试训 `ddpg_v21a_smooth010_lat005.pth`。
- 对比 v2.0 基线（UE 对齐评估）：`mean|Δaction|` 2.368→0.124（-95%）、`action_y_std` 1.591→0.612、路径/直线比 1.1305→1.0312、y 跨度 7.534→4.857m。
- 轨迹图 `logs/train/traj_v21_fixed.png`（vel_tc=0.1 固定障碍样例）：直线段 y 基本贴 0，避障干脆。

### 说明
- **UE 实机复核（不确定信息）**：本轮未在 UE 实机重新飞行（UE 未运行）；v2.1 模型建议在 UE 上跑 `run_v2_demo.py --flights 3` 复核一次。
- **剩余限制**：直线段 y 波动已从 ~7.5m 跨度降到 ~1.5m（y_std 0.30m），非绝对零摆动；如需进一步压低可上调两个惩罚系数（注意避障段 y 跨度略增、奖励略降）。
- 失败尝试日志 `logs/train_v21.log`（vel_tc=0.1 不收敛）已删除，保留 `logs/train_v21b.log` 作为最终训练记录。
## [v2.0] - 2026-08-19
### 里程碑
UE 5.7 实机闭环达成：**100m×10m 走廊 + 双障碍物（x=30 / x=65）避障**，DRL 训练 100% 评估通过，7 次连续实机飞行全部干净（x 0→98.8、y∈±4.6、z 巡航保持、Obstacle 碰撞 = 0）。

### 新增
- v2 场景：`config/scene_v2_100x10.jsonc`（env_actor：Ground100x10 覆盖 x∈[-2,106] + Obstacle1/2 各 2×2×14m）；UE 端 `Content/scene_drone_standalone.jsonc` 同步；地图改用空白 GISMap（清除自带杂物）。
- DRL v2 训练流水线：`train_drl_v2.py` + `drl/sim_client.py`（KinematicSimClient 一阶速度跟踪仿真）+ 走廊边界惩罚奖励（`corridor_limit: 4.5 / corridor_penalty: 3.0`）。
- `run_v2_demo.py`：连续 N 次闭环飞行 demo，自动 LoadScene + 校验（到达终点 / 走廊内 / 高度保持 / 障碍碰撞=0），输出 PASS/FAIL 汇总。
- 飞行前默认 LoadScene 同配置热重载（`--no-reload` 可关闭）。

### 修复
- **SetPose 飞行后回弹卡死**：同一 UE 实例连续飞行时，第 2 次开头的 SetPose 复位使 UE actor 滞留地图出生点 (66.5, 0, 14.19m)（与 Obstacle2 重叠），持续碰撞且首次 MoveByVelocity 把运动学拽回（位置跳变 60.8m）。二分实验（`_diag_bisect.py`）确认触发点后，改为**每次飞行前 LoadScene 同配置热重载**干净重建机器人；6 次热重载 + 7 次连续飞行验证通过。详见 `docs/handover.md` 11.11。
- supervisor 到达终点不再调用 Land/Disarm/DisableApiControl（悬停保持），避免飞行后复位触发回弹。
- `load_scene()` 默认路径多跳一级目录导致 `config/scene_v2_100x10.jsonc` 找不到。
- `torch.load(weights_only=False)` 兼容 torch 2.6+（numpy scalar 加载）。
- supervisor 增加瞬移检测：单步位移 >4m 判定回弹并中止飞行（返回 `position_jump_*_restart_ue`）。
- DRL 状态改为相对真实目标点构造（与训练一致，不再用 A* 路点）。

### 变更
- `run_hybrid.py` / `experiments/run_flight.py`：默认飞行前 LoadScene。
- DRL 训练结果（`logs/train/train_v2_console.log`）：1500/1500 episodes，训练成功率 100.00%，最优奖励 259.7，最后 100 轮平均 258.4；**60 次无探索随机布局评估：成功率 100%（60/60）、碰撞率 0%、平均 167 步**。
- 实机闭环结果（`logs/flights/flight_20260819_061127/061230/061333.csv`）：3/3 PASS，每次约 145 步 / 52s / 路径 ~112m，全程 DRL 主导。

## [v1.1] - 2026-08-03
### 修复
- **"点 Play 后无人机不动"排查结论**：MoveByVelocity 为同步阻塞 RPC（响应耗时≈duration 模拟秒）；模拟时钟不稳（实测 0.15x~1.6x）导致 3s 指令实际耗时 >15s，超过 test_drone.py 的 recv_timeout 抛 Timeout 崩溃，表现为"不动"。已加大 recv_timeout 至 60000ms 并新增 GetSimTime 时钟推进自检。
- 地面板 Ground100x10 加长覆盖 x∈[-2,106]（防无人机降落漂移掉出地面边缘后虚空下坠）。
- supervisor.run 起点复位：先复位到地面层（z=-0.4）再 takeoff 真实爬升（避免 SetPose 到巡航高度后水平移动不维持高度）。

### 变更
- UE 5.7 / Project AirSim 对接打通（端口 8990 RPC：EnableApiControl / Arm / MoveByVelocity / Hover / SetPose / LoadScene / GetGroundTruthPose）。

## [v1.0] - 2026-07-31
### 新增
- 三层混合控制器：Supervisor（总控）+ A* 全局规划 + DRL（DDPG）局部避障 + 势场安全备份。
- AirSim 双模式客户端（2D 内建模拟器 / 真实 AirSim）。
- 实验脚本：`evaluate.py`、`experiments/visualize.py`、`analyze_results.py`。
- 交接文档 `docs/handover.md`（架构、配置、已知问题）。

### 说明
- 该版本为初始架构，DRL 未训练、未对接真实 AirSim；2D 模拟器模式仅用于离线开发。
