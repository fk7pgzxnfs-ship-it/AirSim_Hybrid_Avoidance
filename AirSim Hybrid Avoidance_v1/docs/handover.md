# AirSim Hybrid Avoidance - 项目交接文档

> 编写日期：2026-07-31
> 项目状态：**v2 完成（2026-08-19）：100m×10m 走廊 + 双障碍避障，DRL 训练 100% 评估通过，UE 5.7 实机闭环 7 次连续飞行干净；详见 11.7/11.11**
> 接手者请先通读本文档，再逐模块深入代码

---

## 1. 项目概述

一个基于 **AirSim / Project AirSim** 仿真平台的无人机自主避障导航系统，采用**三层混合架构**：

| 层级 | 模块 | 职责 |
|---|---|---|
| 全局规划 | A* 算法 | 在静态占据栅格地图上规划全局最优路径 |
| 局部避障 | DRL（DDPG） | 基于传感器数据实时输出避障速度指令 |
| 安全切换 | 人工势场法 | 当 DRL 输出可能碰撞时接管控制 |

**技术栈：** Python 3.13 + PyTorch + AirSim（同时内嵌 2D 模拟器用于离线开发）

---

## 2. 项目结构总览

```
AirSim Hybrid Avoidance/
│
├── config/                 # 配置文件（集中管理所有参数）
│   ├── default.yaml        #   主配置：算法超参、训练参数、地图定义
│   └── airsim_settings.json #   AirSim 场景/传感器配置（需手动复制到 AirSim 目录）
│
├── airsim/                 # AirSim Python SDK（官方库 1.8.1，未修改）
│
├── airsim_interface/       # 通信接口层：封装 AirSim / 2D 模拟器
│   ├── client.py           #   AirSimClientWrapper（关键：内含 2D 模拟器）
│   ├── sensor_processor.py #   LiDAR/深度图 -> 极坐标/栅格特征
│   └── utils.py            #   坐标变换、四元数 -> yaw 等辅助函数
│
├── planning/               # 传统规划算法
│   ├── grid_map.py         #   二维占据栅格地图
│   ├── a_star.py           #   A* 路径搜索
│   ├── rrt.py              #   RRT（可选，用于对比实验，尚未集成）
│   └── potential_field.py  #   人工势场法（安全切换器核心）
│
├── drl/                    # 深度强化学习模块
│   ├── env.py              #   Gym 环境（DroneEnv）
│   ├── models.py           #   Actor / Critic / CriticTwin
│   ├── trainer.py          #   DDPG 训练循环
│   ├── agent.py            #   推理 Agent（加载权重 -> predict）
│   ├── replay_buffer.py    #   标准 + 优先经验回放
│   └── utils_drl.py        #   OUNoise、RunningMeanStd、seed 工具
│
├── hybrid_controller/      # 混合控制器核心（三层的 glue）
│   ├── supervisor.py       #   主控制循环（决策流程编排）
│   ├── global_planner.py   #   全局路径规划器（A* + 路径点跟踪）
│   ├── local_planner.py    #   局部规划器（DRL 推理 + 状态构建）
│   └── safety_monitor.py   #   安全切换器（三级安全逻辑）
│
├── experiments/            # 实验脚本
│   ├── run_flight.py       #   单次飞行入口
│   ├── batch_evaluation.py #   批量评估
│   ├── analyze_results.py  #   日志统计分析
│   └── visualize.py        #   2D/3D 轨迹可视化
│
├── run_hybrid.py           # 运行混合避障飞行（入口点）
├── train_drl.py            # 训练 DRL 模型
├── evaluate.py             # 批量评估（入口点）
├── test_drone.py           # Project AirSim 直连测试脚本
├── download_release.py     # 查询 GitHub Release 信息
├── setup.py                # pip install 支持
├── requirements.txt        # Python 依赖
│
├── logs/                   # 运行日志
│   ├── flights/            #   飞行轨迹 CSV
│   └── train/              #   训练曲线数据
│
├── models/                 # 模型权重
│   └── drl_agent/          #   DRL 模型保存目录（当前为空）
│
└── docs/                   # 文档
    └── handover.md         #   本文件
```

---

## 3. 架构与关键设计

### 3.1 三层决策流程

Supervisor.run() 每帧执行以下流程：

```
 1. 获取状态（位置、速度、LiDAR、yaw）
 2. GlobalPlanner.get_next_waypoint() -> 当前目标点
 3. 检查是否到达终点 -> 是则降落返回
 4. LocalPlanner.build_state() + get_action() -> DRL 建议动作
 5. SafetyMonitor.check() -> 三级安全判定
 6. 最终指令选择：
    - safety_result safe=False -> 安全切换器指令 (SAFETY)
    - DRL 模型已加载 -> DRL 指令 (DRL)
    - 以上都不满足 -> 纯全局路径跟踪指令 (GLOBAL)
 7. 发送速度指令，记录日志
```

### 3.2 双模式客户端设计

airsim_interface/client.py 中的 AirSimClientWrapper 通过全局变量 USE_REAL_AIRSIM 切换两种模式：

- **USE_REAL_AIRSIM = True**：连接真实 AirSim / Project AirSim，通过 airsim.MultirotorClient 通信
- **USE_REAL_AIRSIM = False**：使用内建 Python 2D 模拟器，不需要 UE 环境

2D 模拟器包含：简单的运动学积分（pos += vel * dt）、圆形障碍物碰撞检测、模拟 LiDAR 数据、Pygame 可视化窗口

### 3.3 状态空间设计（DRL）

8 维连续状态向量：

| 索引 | 含义 | 说明 |
|---|---|---|
| 0 | dx | 目标相对位置 X |
| 1 | dy | 目标相对位置 Y |
| 2 | vx | 当前速度 X |
| 3 | vy | 当前速度 Y |
| 4 | obs_min_dist | 最近障碍物距离 |
| 5 | obs_min_angle | 最近障碍物角度 |
| 6 | goal_dist | 到目标距离 |
| 7 | goal_angle | 到目标方向角 |

### 3.4 动作空间

2 维连续：[vx, vy]，范围默认 [-2.0, 2.0] m/s，世界坐标系

### 3.5 奖励函数（drl/env.py）

| 事件 | 奖励 |
|---|---|
| 到达终点 | +100 |
| 碰撞 | -50 |
| 每步惩罚 | -0.1 |
| 距离减小 | +1.0 * delta_dist |
| 靠近障碍物（<3m） | -5.0 * (1 - dist/3) |

### 3.6 安全切换器三级逻辑

| 级别 | 条件 | 行为 |
|---|---|---|
| 1 - critical | nearest_dist < safety_distance (1.5m) | 立即切换，势场逃逸方向 * 2.0 紧急速度 |
| 2 - warning | nearest_dist < warning_distance (3.0m) AND 朝向障碍物运动 | 预防性切换 |
| 3 - normal | 以上均不满足 | 正常运行，不干预 |

### 3.7 代码质量备注

- 所有核心模块有完整的 docstring（中英文混合），参数类型标注
- 配置文件 default.yaml 将所有可调参数集中管理，便于实验复现
- 日志系统完整：飞行轨迹 CSV 包含 step、位置、速度、控制模式、最近障碍物距离
- 可视化脚本 experiments/visualize.py 支持 2D/3D 轨迹绘制，带障碍物渲染

---

## 4. 模块详细说明

### 4.1 config/ - 配置文件

**default.yaml** 是唯一的配置来源，所有参数在此定义：

- airsim：IP、端口、起飞高度
- map：地图边界、分辨率、静态障碍物列表（6 个圆形障碍物）
- a_star：启发式权重、是否允许对角移动、最大迭代次数
- potential_field：斥力增益、引力增益、作用范围、安全距离阈值
- global_planner：前视距离、路径点到达阈值、最大速度
- drl：算法选择（ddpg/sac/td3）、网络结构、训练超参数、奖励系数
- model：保存/加载路径
- logging：日志级别、是否保存轨迹

**airsim_settings.json** 是 AirSim 的完整设置文件，配置了 Drone1 无人机（SimpleFlight）、16 通道 LiDAR（30m 范围）、深度相机（256x144）、前置摄像头（960x540）。需要将该文件复制到 %%USERPROFILE%%/Documents/AirSim/settings.json

### 4.2 airsim_interface/ - AirSim 通信层

| 文件 | 核心功能 |
|---|---|
| client.py | AirSimClientWrapper：封装 takeoff、land、get_position、get_velocity、send_velocity、get_lidar_data 等。2D 模式支持 Pygame 可视化。 |
| sensor_processor.py | SensorProcessor：lidar_to_polar() 将 LiDAR 点云转为 16 扇区极坐标距离向量；depth_to_obstacle_grid() 深度图处理；find_nearest_obstacle() |
| utils.py | 坐标变换（world/body）、四元数转 yaw、角度归一化、Vector3r 转 numpy |

> 注意：client.py 中 USE_REAL_AIRSIM 是全局变量，需手动切换

### 4.3 planning/ - 传统规划算法

| 文件 | 核心功能 | 状态 |
|---|---|---|
| grid_map.py | 二维占据栅格地图：add_obstacle、world_to_grid/grid_to_world、inflate_obstacles（scipy 膨胀）、碰撞查询 | 完成 |
| a_star.py | A* 搜索：8/4 方向可配置、欧氏距离启发式、heuristic_weight 可调、最大迭代保护 | 完成 |
| rrt.py | RRT 算法：随机采样 + 步长扩展 + 目标偏置采样 | 已实现但未集成到 Supervisor |
| potential_field.py | 人工势场：引力+斥力合力计算、compute_escape_direction()、is_danger() | 完成 |

### 4.4 drl/ - 深度强化学习模块

| 文件 | 核心功能 | 状态 |
|---|---|---|
| env.py | DroneEnv（继承 gym.Env）：完整的 Gym 接口，reset()、step() | 编码完成 |
| models.py | Actor/Critic/CriticTwin 网络，Xavier 初始化，LayerNorm | 编码完成 |
| trainer.py | DDPGTrainer：完整训练循环，含 target 网络软更新、经验回放、噪声衰减、模型保存/加载 | 编码完成但未跑通过 |
| agent.py | DRLAgent：推理 Agent，load + predict(state) | 编码完成 |
| replay_buffer.py | ReplayBuffer + PrioritizedReplayBuffer | 编码完成 |
| utils_drl.py | OUNoise、GaussianNoise、RunningMeanStd、set_seed 等工具 | 编码完成 |

#### DRL 训练流程（train_drl.py）：

```
加载 default.yaml -> 创建 Supervisor -> 创建 DroneEnv -> 创建 DDPGTrainer
-> 循环 episode：
    env.reset()
    while not done:
        action = actor(state) + noise
        next_state, reward, done, _ = env.step(action)
        replay_buffer.push(...)
        if warmup done: update_network()
    save model every N episodes
```

> 重要：train_drl.py 当前存在训练-推理环境不一致问题。DroneEnv.step() 直接调用 client.send_velocity()，绕过了 Supervisor.run() 中的安全切换逻辑。详见第 7.1 节。

### 4.5 hybrid_controller/ - 混合控制器核心

| 文件 | 核心功能 |
|---|---|
| supervisor.py | Supervisor 类：初始化所有子模块、run(max_steps) 主控制循环、结果统计与日志保存 |
| global_planner.py | GlobalPlanner：plan_path() 调用 A*、get_next_waypoint() 前视目标点、get_velocity_command() 路径跟踪速度指令 |
| local_planner.py | LocalPlanner：build_state() 构建 8 维状态、get_action() 调用 agent 推理 |
| safety_monitor.py | SafetyMonitor：三级安全逻辑、_is_approaching_obstacle() 速度方向与障碍物方向点积检测 |

### 4.6 experiments/ - 实验脚本

| 文件 | 功能 |
|---|---|
| run_flight.py | 单次飞行：创建 Supervisor，设目标点，调用 run()，保存日志 |
| batch_evaluation.py | 批量评估：循环多目标点多次飞行，统计成功率/平均步数/路径长度 |
| analyze_results.py | 日志分析：读取 CSV 计算各项指标，支持多算法对比 |
| visualize.py | 可视化：plot_trajectory_3d()（含 3D 障碍物圆柱体）、plot_trajectory_2d()、plot_training_curve()、plot_comparison() |

---

## 5. 运行指南

### 5.1 环境准备

`ash
# 安装依赖
pip install -r requirements.txt

# 可选：安装为包
pip install -e .

# 可选：安装 Pygame（用于 2D 模拟器可视化）
pip install pygame
`

### 5.2 2D 模拟模式（不需要 UE）

1. 编辑 airsim_interface/client.py 第 12 行：USE_REAL_AIRSIM = False
2. 运行：

`ash
python run_hybrid.py --goal_x 10 --goal_y 10
`

3. 会弹出 Pygame 窗口显示无人机飞行过程

### 5.3 真实 AirSim 模式

1. 将 config/airsim_settings.json 复制到 %%USERPROFILE%%/Documents/AirSim/settings.json
2. 启动 AirSim / Project AirSim Unreal 场景
3. 确保 airsim_interface/client.py 的 USE_REAL_AIRSIM = True
4. 运行：

`ash
python run_hybrid.py
`

### 5.4 训练 DRL 模型

`ash
python train_drl.py
`

模型保存在 models/drl_agent/ddpg_{suffix}.pth，训练曲线保存在 logs/train/rewards.npy

### 5.5 批量评估

`ash
python evaluate.py --runs 10
`

### 5.6 可视化轨迹

`ash
# 3D 轨迹图
python experiments/visualize.py --mode 3d --log logs/flights/flight_xxx.csv

# 2D 轨迹图
python experiments/visualize.py --mode 2d --log logs/flights/flight_xxx.csv
`

---

## 6. 运行状态（已知）

| 项目 | 状态 |
|---|---|
| 2D 模拟器单次飞行 | 可运行（已验证，flight_20260727_035729.csv 为一次实际运行日志） |
| 2D 模拟器 + DRL 训练 | 未完成（参考第 7.1 节的训练-推理环境不一致问题） |
| 真实 AirSim 连接 | 未测试（无 UE 环境） |
| DRL 模型训练 | 未完成（models/drl_agent/ 目录为空，仅含 .gitkeep） |
| 安全切换器逻辑 | 编码完成，未充分测试 |
| RRT 算法集成 | 编码完成，未接入 Supervisor |
| A* 规划 + 全局路径跟踪 | 可运行 |

---

## 7. 已知问题与风险

### 7.1 训练-推理环境不一致（关键风险）

- train_drl.py 中 DroneEnv.step() 直接调用 client.send_velocity()，绕过了 Supervisor.run() 中的安全切换逻辑
- 这意味着 DRL 在训练时从未经历安全切换器的干预，而推理时安全切换器可能会 override DRL 的输出，导致训练与推理的行为分布不同
- **建议修复：** 在 DroneEnv.step() 中复用 SafetyMonitor.check() 逻辑，或者让训练时也跑完整的 Supervisor 流程

### 7.2 2D 模拟器模型过于简化

- 运动学模型仅为简单的 pos += vel * dt，无动力学、无惯性、无加速度限制
- LiDAR 模拟仅返回障碍物中心坐标加噪声，而非真实射线追踪
- 不模拟无人机姿态（roll/pitch），仅 yaw
- 这会导致在模拟器上训练好的 DRL 策略迁移到真实 AirSim 时出现严重的 Sim-to-Real gap

### 7.3 代码中的硬编码

- airsim_interface/client.py 中 USE_REAL_AIRSIM 是全局变量，非配置文件控制
- hybrid_controller/supervisor.py 中 self.goal_pos = np.array([10.0, 10.0]) 硬编码默认目标点
- 障碍物列表在 config/default.yaml 和 airsim_interface/client.py（2D 模拟器内）各有一份，需要同步维护
- potential_field.py 的 repulsive_range 默认 3.0m，与 safety_monitor.py 的 warning_distance 默认 3.0m 含义重叠，容易调参混乱

### 7.4 缺少的功能

- 无单元测试（tests/ 目录不存在）
- 无模型评估指标脚本（如碰撞率、偏离路径距离等）
- RRT 算法已实现但未接入 Supervisor
- 无动态障碍物支持
- 日志中未记录 reward 值（仅记录 mode/位置/速度/最近障碍物距离）

### 7.5 版本依赖

- 项目使用 airsim Python 包版本 1.8.1
- requirements.txt 中 airsim 未指定版本号
- test_drone.py 使用 projectairsim 包（新版本 API），与 airsim_interface/client.py 使用的 airsim 包是两套不同的 API
- PyTorch 版本未锁定

### 7.6 代码清理

- 大量 docstring 和日志使用中文 UTF-8 编码，在部分终端可能显示乱码
- experiments/visualize.py 中 plot_trajectory_3d 函数体积较大（约 100 行），可考虑拆分

---

## 8. 待办事项（按优先级排列）

### P0 - 必须修复

- [ ] 修复 DRL 训练流程：解决 train_drl.py 中训练环境绕开安全切换器的问题。方案：让 DroneEnv.step() 内部也经过 SafetyMonitor.check()，或修改训练流程使其运行完整的 Supervisor 流程。

### P1 - 重要

- [ ] 验证真实 AirSim 连接：在有 UE 环境的机器上运行 test_drone.py 和 run_hybrid.py，确认 AirSimClientWrapper 在 USE_REAL_AIRSIM = True 模式下的所有接口正常工作
- [ ] 训练并保存 DRL 模型：跑通 train_drl.py，将训练好的权重存入 models/drl_agent/
- [ ] 将配置参数化：将 USE_REAL_AIRSIM 移到 default.yaml 中，避免修改源码切换模式

### P2 - 推荐

- [ ] 集成 RRT 到 Supervisor：在 global_planner.py 中增加算法选择开关（A* / RRT），用于对比实验
- [ ] 添加单元测试：至少覆盖 a_star、grid_map、potential_field、safety_monitor 的核心逻辑
- [ ] 统一障碍物数据源：消除 default.yaml 和 2D 模拟器中两份障碍物列表的重复维护

### P3 - 长期改进

- [ ] 增强 2D 模拟器：增加动力学模型（加速度限制、惯性）、仿真 LiDAR 射线追踪
- [ ] 动态障碍物支持：扩展 grid_map 和 safety_monitor 支持移动障碍物
- [ ] 实验管理：引入实验配置版本管理，支持自动生成对比图表

---

## 9. 交接清单

| 项目 | 已确认？ |
|---|---|
| 阅读本交接文档 | □ |
| 访问项目代码仓库 | □ |
| 确认 Python 环境和依赖可安装 | □ |
| 在 2D 模拟模式下运行 run_hybrid.py 验证 | □ |
| 配置真实 AirSim 环境（如有 UE） | □ |
| 跑通 DRL 训练流程 | □ |
| 了解已知问题列表 | □ |

---

*文档结束。如有疑问，请查阅对应模块的源码 docstring 或 config/default.yaml 中的参数注释。*


---
## 10. UE 5.7 对接进度（2026-07-31 更新）

### 10.1 当前状态

| 项目 | 状态 |
|---|---|
| UE 5.7 通信 (端口 8990) | ✅ 可用 |
| RPC 基础方法 (GetBuildCommitHash) | ✅ 可用 |
| 场景配置加载 (LoadScene) | ✅ 可用 |
| 场景 RPC 方法 (GetRobotIds) | ❌ 不可用 (需 UE 端配合) |
| Topic/Pub-Sub 系统 | ❌ 不可用 (场景未初始化) |
| 无人机控制 | ❌ 不可用 (场景中无无人机角色) |

### 10.2 已验证的通信协议

- 使用 pynng.Req0 + msgpack 格式与端口 8990 通信
- 请求格式: 参考 projectairsim/client.py 中的 preprocess_request()
- 关键: params 中必须用 {"data": msgpack.packb(params, use_bin_type=True)} 包装
- 必须先 dial(block=False) 并等待 1.5~2 秒再发送请求

### 10.3 已知问题 & 解决方案

**问题: 场景 RPC 方法未注册 / 场景中无无人机**

根本原因:
- UnrealSimLoader::LaunchSimulation() 调用 SimServer->LoadScene("") 加载默认空场景
- 默认场景 (DefaultScene) 不含 actors
- 通过 RPC /Sim/LoadScene 只能更新服务端配置，无法触发 UE 端的 Actor 生成
- 场景方法 (GetRobotIds 等) 需要 UnrealScene::LoadUnrealScene() 在 UE 端注册

解决方案:
1. **在 UE 编辑器中手动放置无人机:**
   - 停止 Play
   - 在内容浏览器中搜索 Quadrotor 或 Drone
   - 将 BP_Drone / Quadrotor 蓝图拖入场景
   - 点击 Play
   - 运行 python test_drone.py

2. **或者使用项目自带的场景配置:**
   - Content/scene_drone_classic.jsonc 已定义无人机场景
   - 需要修改 UnrealSimLoader 使其加载此配置 (需编译 C++ 插件)

### 10.4 项目文件说明

| 文件 | 说明 |
|---|---|
| airsim_interface/projectairsim_client.py | 新版适配器，对接 projectairsim API |
| test_drone.py | UE 连接测试脚本 |
| D:/ProjectAirSim-main/unreal/Blocks 5.7/sim_config/ | 场景配置文件目录 (已创建) |
| D:/ProjectAirSim-main/unreal/Blocks 5.7/Content/scene_drone_classic.jsonc | UE 项目自带的场景配置 |
| D:/ProjectAirSim-main/unreal/Blocks 5.7/Content/robot_quadrotor_classic.jsonc | UE 项目自带的无人机配置 |

### 10.5 后续操作步骤

1. 在 UE 编辑器中停止 Play
2. 用内容浏览器找到 Quadrotor 蓝图（在 /Drone/ 目录下）
3. 拖入场景中，放置在 (0, 0, -400) 附近
4. 确保 World Settings 中 GameMode Override = ProjectAirSimGameMode
5. 点击 Play
6. 在本项目目录运行:
   & "C:\ProgramData\anaconda3\python.exe" test_drone.py
7. 如果场景方法可用，再运行完整避障系统:
   & "C:\ProgramData\anaconda3\python.exe" run_hybrid.py


---

---

### 10.6 无人机不动排查结论（2026-08-03）

**症状**: UE 点 Play 后无人机停在原地不动。

**确定事实（已实测验证）**:
- 模拟器服务正常: 端口 8989/8990 监听、无人机自动生成、GetSimTime / GetGroundTruthPose / EnableApiControl / Arm / Hover 均正常响应。
- 控制链路正常: EnableApiControl + Arm + MoveByVelocity 实测可使无人机起飞（z: -2.7 → -15m）并前移（x: +5.8m）。
- MoveByVelocity 是**同步阻塞 RPC**: 响应时间约等于 duration 的模拟秒数，命令执行完才返回。
- 模拟时钟速度不稳定: 实测 0.15x ~ 1.6x（正常应为 ~1x），PIE 启动初期最慢。
- 时钟慢时，3 秒的 MoveByVelocity 实际耗时可能 >15 秒，超过 test_drone.py 的 15s recv_timeout，脚本抛 Timeout 崩溃，表现为“不动”。

**已做修改**:
- test_drone.py: recv_timeout 由 15000ms 加大到 60000ms；新增 GetSimTime 时钟推进自检（不发指令先确认模拟时钟在推进）。

**操作建议**:
- 点 Play 后无人机**不会自动起飞**，必须运行 test_drone.py（或通过 RPC 发指令）才会飞。
- PIE 启动后先等模拟时钟稳定（跑一次 GetSimTime 两次采样，确认持续推进）再发 MoveByVelocity。
- 避免 UE 窗口失焦/最小化导致 PIE 降帧（模拟时钟随 UE tick 波动）。
- 已清理 7/31 遗留的两个 python 僵尸进程（临时脚本循环连接导致日志刷屏）；遗留卡死的 UE -game 实例建议一并关闭。


---
---

# v2 章节：100m×10m 走廊 + 双障碍物避障（UE 5.7 实机闭环）

> 编写日期：2026-08-19（夜间自主开发，用户已授权无确认执行）
> 项目状态：**v2 场景与闭环已跑通；DRL 训练完成后待 UE 闭环验证**

## 11.1 v2 目标与验收标准

- **场景**：100m×10m 走廊（x∈[0,100]，y∈[-5,5]），两个 2×2×14m 立柱障碍物位于 x=30、x=65（中线 y=0）。
- **任务**：无人机从 (0,0) 起飞，飞到 (100,0)，全程不出走廊、不碰撞障碍物。
- **验收**：UE 打开后无人机自动起飞 → 绕开两个障碍物 → 到达终点；DRL（DDPG）模型已训练并参与控制（SAFETY 势场兜底）。

## 11.2 UE 环境（确定事实）

- 使用 UE 5.7 自带**空白地图 GISMap**（不再加载 Blocks 默认城市地图；用户要求去掉地图自带杂物，GISMap 无任何自带建筑）。
- `D:/ProjectAirSim-main/unreal/Blocks 5.7/Config/DefaultEngine.ini` 已改：
  `EditorStartupMap / GameDefaultMap / ServerDefaultMap = /Game/GISMap`（原文件备份 `DefaultEngine.ini.bak_v1`）。
- 启动命令（`-game` 模式，服务端口 8990/8989）：
  `Start-Process 'D:\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe' -ArgumentList '"D:/ProjectAirSim-main/unreal/Blocks 5.7/Blocks.uproject"','GISMap','-game','-windowed','-ResX=1280','-ResY=720'`
- UE 启动流程（`UnrealSimLoader.cpp`）会**自动加载** `Content/scene_drone_standalone.jsonc`，因此场景/无人机/地面/障碍物开机即就绪，无需手动 Play 或 LoadScene。

## 11.3 场景与碰撞方案（确定事实）

- 场景真源：`D:/ProjectAirSim-main/unreal/Blocks 5.7/Content/scene_drone_standalone.jsonc`（仓库副本 `config/scene_v2_100x10.jsonc`，原文件备份 `.bak_v1`）。
- 结构：`environment-actors` 下 3 个 `env_actor` + 1 个 `robot`（Drone1）：

| 名称 | 中心 (x,y,z) | 尺寸 scale | 说明 |
|---|---|---|---|
| Ground100x10 | (50, 0, -0.1) | 100×10×0.2 | 地面板，必须存在否则无人机坠落 |
| Obstacle1 | (30, 0, -7) | 2×2×14 | 立柱，z∈[-14,0]，压到地面以下防止钻过 |
| Obstacle2 | (65, 0, -7) | 2×2×14 | 同 Obstacle1 |

- **必须用 `env_actor`（FastPhysics 物理世界）而非 SpawnObject**：SpawnObject 生成物无碰撞，env_actor 在模拟物理层必然与无人机碰撞（UE 实测：无人机在 x≈28.5 被 Obstacle1 挡住无法前进）。
- env_actor JSON 格式：`name` / `type:"env_actor"` / `origin.xyz` / `env-actor-config.links[]`，link 内 `inertial` + `collision` + `visual`；不填 joints 会有 warning 但无害。

## 11.4 通信与客户端（确定事实）

- RPC 协议：`tcp://127.0.0.1:8990`，`pynng.Req0`，消息 `{method, params:{data: msgpack}, version:1.0, id}`；str 值需 encode；响应 `result.data` 为 msgpack bytes。
- **必须用持久单连接**（每次新建 socket 耗时 1~2s）；`recv_timeout` 单位毫秒，持久连接设 300000ms。
- `MoveByVelocity` 是**同步阻塞 RPC**：响应时间 ≈ duration 模拟秒；`SetPose` 需先 `DisableApiControl` 才生效。
- `airsim_interface/projectairsim_client.py` 已重写为 `ProjectAirSimClientWrapper`，接口对齐旧 wrapper：get_position / get_velocity / get_yaw / get_lidar_data / get_collision_info / takeoff / land / send_velocity / send_velocity_body / reset_position / hover / getMultirotorState / is_api_connected / get_obstacles / close。
- **已知限制（确定事实）**：本 sim 无 GetLidarData / GetCollisionInfo RPC；模拟 LiDAR 用**已知障碍物表面采样点**生成机体相对点云（每障碍 12 点，半径 r+0.15，±0.05 噪声）；碰撞判定用已知障碍物几何 + 0.30m 裕量。

## 11.5 规划器修复（确定事实）

- `planning/grid_map.py::world_to_grid`：越界钳制（终点 x=100 之前被误判为占用）。
- `planning/grid_map.py::inflate_obstacles`：scipy `binary_dilation(iterations=0)` 会无限膨胀整图，已加 `if iters<1: return` 防护。
- supervisor 对障碍物做 `inflate_obstacles(0.5)`（规划半径 1.5+0.5）；A* 在 v2 地图规划 200 路点，路径从 y≈2.2 绕过两个障碍物，min dist 到障碍物中心 2.26m。

## 11.6 纯全局+势场闭环验证（确定事实，2026-08-19）

- 命令：`python run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000`
- 结果：**39.32s 到达，success=True，路径 101.45m，109 步**。
- 轨迹：`logs/flights/flight_20260819_020007.csv`，图 `logs/flights/flight_20260819_020007.png`。
- 关键验证：y 全程在 ±5 内；障碍物 1（x=30）处 y≈1.3→2.6，障碍物 2（x=65）处 y≈2.2→2.9；两处都触发过 SAFETY 又被 GLOBAL 接管，无碰撞。
- **部署 DRL 状态一致性修复**：supervisor 原来把 A* 路点（next_waypoint）当 goal 传入 `LocalPlanner.build_state`，与训练（state 相对真实目标点 (100,0)）不一致；已改为传 `self.goal_pos`。

## 11.7 DRL 训练（完成，2026-08-19 04:37）

- 入口：`train_drl_v2.py [--episodes N] [--quick]`。
- 训练仿真：`drl/sim_client.py` `KinematicSimClient`（一阶速度跟踪运动学，模拟 MoveByVelocity 语义，每 episode 障碍物随机抖动 ±1.5m，机体相对合成 LiDAR + 碰撞检测）+ `TrainSupervisor`。
- 算法：DDPG（`drl/trainer.py`），state 8 维（dx,dy,vx,vy,nearest_dist,nearest_angle,goal_dist,goal_angle），action 2 维 [vx,vy]∈[-2,2]，256×256 网络，1500 episodes，warmup 1500 步。
- torch 2.6+ 兼容：`torch.load(..., weights_only=False)`（否则 numpy scalar 无法加载）。
- 冒烟 40 轮：奖励 -21.4、成功率 0%（未训练状态，属正常）。
- 模型路径：`models/drl_agent/ddpg_best.pth`（训练完成覆盖冒烟模型）；日志 `logs/train/train_v2_console.log`（stdout 缓冲可能长时间空白，用 stderr 与模型文件时间戳判断进度）。
- 评估：训练完成后脚本自动做 60 次随机布局无探索评估，输出成功率/碰撞率/平均步数。
- **最终结果（corridor 奖励版，train_v2_console.log）**：1500/1500 episodes，总步数 429801，最优奖励 259.7，最后 100 轮平均奖励 258.4，训练成功率 100.00%，耗时 4860.7s（约 81 分钟）；
  **60 次无探索随机布局评估：成功率 100%（60/60）、碰撞率 0%（0/60）、平均 167.0 步达标**。
- 模型：`models/drl_agent/ddpg_best.pth`（config/default.yaml `model.enable: true` 时加载参与控制）。

## 11.8 已知限制与风险

- 模拟 LiDAR 与真实 LiDAR 语义有差距（训练/部署一致，但仍是先验已知障碍物的近似）。
- 训练只在运动学仿真（CPU），UE 动力学（P系数/时钟波动）可能造成 sim-to-real gap；SAFETY 势场作为兜底。
- 模拟时钟随 UE tick 波动（实测 0.15x~1.6x），UE 窗口失焦/最小化会导致 PIE 降帧。
- 同步 MoveByVelocity 使 UE 闭环单步耗时 ≈ 0.3s+，2000 步上限足够（实测全程 109 步）。

## 11.9 复现步骤

1. 启动 UE：见 11.2 命令，等待端口 8990 可连接（`GetSimTime` 两次采样确认时钟推进）。
2. 检查 `config/default.yaml`：`model.enable` 置 `true` 则 DRL 参与控制（`false` 则纯 GLOBAL+SAFETY）。
3. 运行：`python run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000`。
4. 结果在 `logs/flights/flight_<时间戳>.csv`，轨迹可视化：`experiments/visualize_trajectory.py`。

---
## 11.10 夜间补充记录（2026-08-19 02:40）

### 地面板加长（防降落掉落）
- 原地面板 Ground100x10 只覆盖 x∈[0,100]，首次飞行后无人机降落时漂移到 x≈101.4，掉出地面边缘并在虚空中持续下坠（z 不断增大）。
- 已改为：origin (52,0,-0.1)，inertia/visual scale 108×10×0.2 → 地面覆盖 x∈[-2,106]。仓库副本 `config/scene_v2_100x10.jsonc` 与 UE 场景文件已同步。

### 起点复位逻辑（supervisor.run 开头）
- 原 run() 不从起点开始，若上次遗留位置异常（如虚空下坠）会直接继续。已加：
  `self.client.reset_position(self.start_pos[0], self.start_pos[1], -0.4)` → 再 takeoff。
- **关键坑**：reset_position 用 SetPose 直接传送到巡航高度（-12）后再 takeoff，会导致水平 MoveByVelocity 不维持高度（无人机边飞边坠落）；必须先复位到**地面层（-0.4）**，再让 takeoff 走真实爬升（MoveByVelocity vz=-3），控制链路才正常。

### LoadScene 热重载会破坏 MoveByVelocity（确定事实）
- 通过 `/Sim/LoadScene` RPC 热重载场景后，`MoveByVelocity` RPC 返回 **`result: False`**（wrapper 无感知，以为成功），无人机原地不动；且 SetPose 到高空后控制器不维持高度。
- 源码定位：`multirotor_api_base.cpp` 的 MoveByVelocity 返回 `RunFlightCommand(...).IsTimeout()`，False = 命令提前结束（控制器未就绪/命令被拒）。
- 规避：**不要热重载**；场景文件改动后重启 UE 从启动加载（`UnrealSimLoader.cpp` 自动加载 scene_drone_standalone.jsonc）。若已热重载，重新 EnableApiControl + Arm 后水平 MoveByVelocity 可恢复（实测 2:30 后正常）。
- UE 日志（`Saved/Logs/Blocks.log`）热重载时有非致命警告：lidar topic unregistered、`Unrecognized 'lidar_type' value ''`、env_actor joints missing（可忽略）。

### 二次闭环验证（2026-08-19 02:39，修复后）
- `python run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000`：**success=True，108 步，38.97s，路径 101.61m**。
- 轨迹 `logs/flights/flight_20260819_023911.csv` / `.png`：y∈[0,3.23]（走廊 ±5 内），z∈[-13.74,-12.85]（巡航高度稳定），模式统计 GLOBAL×101 + SAFETY×6，两处障碍物均绕行无碰撞。

### DRL 训练状态（截至 02:40）
- 训练进程 PID 2480 运行中（约 200 episodes/15.5min，1500 轮预计 ~03:50 完成）。
- `ddpg_best.pth` 仍为冒烟模型（1:55:29 未更新）：episode 1 之后尚无更高奖励 episode，说明策略尚未突破直线撞障碍模式，属 DDPG 早期正常现象；最终评估成功率 ≥70% 才达标，不达标需调参（噪声、奖励权重、episodes）重训。

---

---
## 11.11 v2 完成状态与连续飞行修复（2026-08-19 06:15）

### 验收结论（确定事实）
- v2 功能达成：100m×10m 走廊（x∈[0,100]，y∈[-5,5]）+ 障碍物 x=30 / x=65（2×2×14m）+ DRL 避障闭环 + UE 5.7 实机飞行。
- 空地图已用 GISMap（无任何自带杂物），场景内容全部来自 `config/scene_v2_100x10.jsonc`（env_actor：Ground100x10 + Obstacle1/2）。
- 连续飞行验证（2026-08-19 06:00–06:15）：**7 次连续闭环飞行全部干净**——x 0→98.8、y∈±4.6（走廊内）、z 保持巡航（-10~-22）、全程 DRL 主导、Obstacle1/2 碰撞计数 = 0。
  - 前 4 次：`flight_20260819_060254/060415/060604/060713.csv`
  - demo 3 次：`flight_20260819_061127/061230/061333.csv`，`run_v2_demo.py --flights 3` 输出 **3/3 PASS**（每次 145 步 / 52.4s / 路径 ~112m）。

### 新发现的坑：SetPose 回弹卡死（确定事实，二分实验定位）
- 现象：同一 UE 实例连续跑两次 `run_hybrid.py`（飞行间不重载），第 2 次飞行约 13 步（4.6s）时位置跳变 **60.8m** 到地图出生点 (66.5, 0, -0.4)，supervisor 瞬移检测（>4m）中止；UE 日志同时出现 `'Frame' vs 'Obstacle2'` 持续碰撞（z≈1419cm = 出生点高度 14.19m，恰与 Obstacle2 重叠）。
- 二分实验（`_diag_bisect.py`）逐步隔离：
  1. `DisableApiControl`：机体只坠落（x 不变），无回弹。
  2. `SetPose(0,0,-0.4)`：core_sim 运动学读到 (0,0,-0.4) 正常，但 **UE actor 未跟随**，滞留在出生点 (66.5,0,14.19m) 并开始与 Obstacle2 持续碰撞。
  3. 首次 `MoveByVelocity`：运动学被 UE 写回出生点，彻底卡死。
- 机制（源码佐证）：FastPhysics 模式下 `AUnrealRobot::Tick` → `MoveRobotToUnrealPose(bUseCollisionSweep)`，SetPose 的跨障碍瞬移扫描被 Obstacle2 阻挡；DisableApiControl 后机体处于物理态，teleport 不生效，actor 停在 UE 地图 PlayerStart（出生点锚）。
- 单独 SetPose 而不 DisableApiControl 也不行：无人机带着旧控制状态继续前飞，直接撞障碍（`_diag_bisect.py without_disable` 复现：x 一路冲到 63.5 卡在 Obstacle2 前）。

### 修复：每次飞行前 LoadScene（同配置热重载，确定事实）
- **修复方案**：每次飞行前调用 `/Sim/LoadScene` 重载同一场景 `config/scene_v2_100x10.jsonc`，机器人被干净重建在场景原点，之后的 SetPose 复位与首飞一致，不再回弹。
- 已验证：6 次同配置热重载 + 7 次连续飞行全部干净，热重载耗时 ~1.6s。
- **修正 11.10「LoadScene 热重载会破坏 MoveByVelocity」的结论**：该结论来自 02:39 前的特定失败场景（场景内容变更 + 复用旧连接）。本次验证表明**同配置热重载 + 每次新进程/新客户端连接**下 MoveByVelocity 完全正常（`result: True`，7 次飞行无异常）。风险仍然存在：热重载后立即复用旧 wrapper 连接直接发 MoveByVelocity 的行为未覆盖，运行脚本每次都是新连接，不受影响。

### 代码变更（v2 完成版）
- `experiments/run_flight.py`：`run_single_flight(..., reload_scene=True)`，飞行前默认 `load_scene()`；新增 `--no-reload` 开关。
- `run_hybrid.py`：透传 `--no-reload`。
- `airsim_interface/projectairsim_client.py`：修复 `load_scene()` 默认路径（原来多跳一级目录，`config/scene_v2_100x10.jsonc` 找不到）。
- 新增 `run_v2_demo.py`：连续 N 次闭环飞行 demo，自动 LoadScene + 校验轨迹（到达终点 / 走廊内 / 高度保持 / 障碍碰撞=0），输出 PASS/FAIL 汇总。

### v2 操作流程（复现）
1. 启动 UE：`UnrealEditor.exe "D:/ProjectAirSim-main/unreal/Blocks 5.7/Blocks.uproject" GISMap -game -windowed -ResX=1280 -ResY=720`，等端口 8990。
2. 单次飞行：`python run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000`（默认先 LoadScene；`--no-reload` 关闭）。
3. 连续演示：`python run_v2_demo.py --flights 3`。
4. 轨迹在 `logs/flights/flight_<时间戳>.csv`；UE 碰撞检查：`Saved/Logs/Blocks.log` 中 `Collision detected between 'Frame' and 'ObstacleN'` 应为 0。

### 当前 UE 进程状态（2026-08-19 06:15）
- UE 5.7 运行中（GISMap + SceneDroneClassic，端口 8990/8989），场景干净；最后一次 demo 飞行后无人机悬停在终点附近（API 控制保持，未 Land/Disarm——避免触发回弹）。
