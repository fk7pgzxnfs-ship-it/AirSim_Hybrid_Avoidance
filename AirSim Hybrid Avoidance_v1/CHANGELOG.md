# Changelog

版本记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 风格。日期依据 `docs/handover.md` 与文件时间戳（确定事实）。

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
