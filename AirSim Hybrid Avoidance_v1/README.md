# AirSim Hybrid Avoidance - 无人机混合避障导航系统

> **使用说明**：[docs/USER_GUIDE.md](docs/USER_GUIDE.md)（从零开始的操作手册、命令参考与常见问题）

> **v2.0（2026-08-19）**：100m×10m 走廊 + 双障碍物避障，DRL 训练评估 100%，UE 5.7 实机闭环 7 次连续飞行干净。版本记录见 [CHANGELOG.md](CHANGELOG.md)。

## 📋 项目简介
基于 **Project AirSim（UE 5.7）** 仿真平台的无人机自主避障导航系统，采用 **A* 全局规划 + DRL（DDPG）局部避障 + 势场安全备份** 的三层混合架构。v2 目标场景：**100m×10m 走廊**（x∈[0,100]，y∈[-5,5]）+ 两个 2×2×14m 障碍物（x=30 / x=65），无人机从头飞到尾并全程避障。

## 🏗️ 核心架构
```
Supervisor（总控循环）
├── Global Planner (A* 算法)      → 全局最优路径规划
├── Local Planner (DRL/DDPG)      → 实时局部避障
├── Safety Monitor (势场法)        → 安全备份与紧急干预
└── ProjectAirSimClient (UE RPC)  → MoveByVelocity / SetPose / LoadScene / LiDAR
```

## ✅ v2 验收状态（2026-08-19）
- **DRL 训练完成**：1500 轮，训练成功率 100%；60 次无探索随机布局评估**成功率 100%（60/60）、碰撞率 0%、平均 167 步**。
- **UE 5.7 实机闭环**：7 次连续飞行全部干净——x 0→98.8、y 全程走廊内（±4.6）、z 保持巡航、Obstacle1/2 碰撞计数 = 0；`run_v2_demo.py --flights 3` 输出 **3/3 PASS**（每次约 145 步 / 52s / 路径 ~112m）。
- 模型：`models/drl_agent/ddpg_best.pth`（`config/default.yaml` 中 `model.enable: true` 时参与控制）。

## 🚀 快速开始（v2 / UE 5.7 实机）

### 1. 安装依赖
```bash
pip install -r requirements.txt
# Project AirSim 客户端额外依赖（已列入 requirements.txt）
pip install msgpack pynng commentjson
```

### 2. 启动 UE 5.7（空白 GISMap 场景）
```powershell
"D:\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe" "D:/ProjectAirSim-main/unreal/Blocks 5.7/Blocks.uproject" GISMap -game -windowed -ResX=1280 -ResY=720
```
等待端口 **8990** 可连接（约 30–60s）。场景内容（地面 + 障碍物 + 无人机）由 `run_hybrid.py` / `run_v2_demo.py` 通过 LoadScene RPC 自动加载。

### 3. 单次避障飞行
```bash
python run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000
```
- 默认每次飞行前先 **LoadScene 同配置热重载**（干净重建机器人，规避 SetPose 回弹，见 CHANGELOG v2.0）；`--no-reload` 可关闭。
- 轨迹输出到 `logs/flights/flight_<时间戳>.csv`。

### 4. 连续演示（N 次飞行 + 自动校验）
```bash
python run_v2_demo.py --flights 3
```
每次飞行自动：LoadScene → 闭环飞行 → 校验（到达终点 / 走廊内 / 高度保持 / 障碍碰撞 = 0），输出 PASS/FAIL 汇总。

### 5. 训练 DRL 模型
```bash
python train_drl_v2.py --episodes 1500   # 完整训练
python train_drl_v2.py --quick            # 冒烟测试
```
训练完成后自动做 60 次无探索评估；最优模型写入 `models/drl_agent/ddpg_best.pth`。

### 6. 轨迹可视化
```bash
python experiments/visualize_trajectory.py --csv logs/flights/flight_xxx.csv
```

## 📁 项目结构
```
AirSim Hybrid Avoidance/
├── config/                    # 配置：default.yaml（主配置）、scene_v2_100x10.jsonc（v2 场景）
├── airsim_interface/          # 通信层：projectairsim_client.py（UE RPC）、sensor_processor.py
├── planning/                  # 传统规划：grid_map.py、a_star.py、potential_field.py
├── drl/                       # DRL：env.py、agent.py、trainer.py、models.py、sim_client.py（训练仿真）
├── hybrid_controller/         # 混合控制器：supervisor.py、global_planner.py、local_planner.py、safety_monitor.py
├── experiments/               # 实验：run_flight.py、visualize_trajectory.py、analyze_results.py
├── logs/                      # 运行日志：flights/（轨迹 CSV）、train/（训练曲线）
├── models/drl_agent/          # DRL 权重（ddpg_best.pth）
├── run_hybrid.py              # v2 单次闭环飞行入口
├── run_v2_demo.py             # v2 连续演示入口（自动 LoadScene + 校验）
├── train_drl_v2.py            # v2 DRL 训练入口
└── docs/handover.md           # 完整交接文档（含 11.11 根因分析与复现）
```

## 📝 关键实现说明
- **飞行间复位**：每次飞行前 `LoadScene` 同配置热重载，机器人被干净重建在场景原点，再走 SetPose + takeoff 真实爬升；这是规避 UE actor 回弹卡死的核心手段。
- **DRL 状态/动作**：8 维状态（dx, dy, vx, vy, 最近障碍距离/角度, 目标距离/角度），2 维动作 [vx, vy]∈[-2,2]；奖励含走廊边界惩罚（|y|>4.5 起罚）。
- **安全兜底**：SafetyMonitor 三级逻辑（critical <1.5m 紧急势场逃逸；warning <3.0m 且朝向障碍预防性干预）。
- **到达终点**：悬停保持，不调用 Land/Disarm/DisableApiControl（避免飞行后复位触发回弹）。

## ⚠️ 已知问题与注意事项
- **SetPose 飞行后回弹**：同一 UE 实例连续飞行时，第 2 次开头的 SetPose 复位会使 UE actor 滞留在地图出生点 (66.5, 0, 14.19m)（与 Obstacle2 重叠）并持续碰撞，运动学随后被拽回。**必须用 LoadScene 热重载复位**（详见 `docs/handover.md` 11.11）。
- **热重载连接**：验证场景为"同配置重载 + 每次新进程/新连接"；重载后复用旧客户端连接直接发指令的行为未验证。
- **模拟 LiDAR 与真实 LiDAR** 有语义差距（训练/部署一致，但仍是先验障碍的近似）；SAFETY 势场作为兜底。
- **UE 窗口失焦/最小化**会导致模拟时钟降速（实测 0.15x~1.6x），影响飞行节奏。
- **MoveByVelocity 是同步阻塞 RPC**，响应耗时 ≈ duration 的模拟秒数。
- 本机 PowerShell 中 `python` 可能不可用，请使用完整路径 `C:\Users\13631\AppData\Local\Programs\Python\Python313\python.exe`。

## 📋 版本历史
| 版本 | 日期 | 里程碑 |
|---|---|---|
| v2.0 | 2026-08-19 | UE 实机闭环：DRL 100% 评估、100×10 走廊双障碍、7 次连续飞行干净、LoadScene 复位修复 |
| v1.1 | 2026-08-03 | UE 5.7 对接打通："点 Play 不动"排查、地面板加长、起点复位 |
| v1.0 | 2026-07-31 | 初始三层混合架构（A* + DRL + 势场），AirSim 双模式客户端 |

详细变更见 [CHANGELOG.md](CHANGELOG.md)。
