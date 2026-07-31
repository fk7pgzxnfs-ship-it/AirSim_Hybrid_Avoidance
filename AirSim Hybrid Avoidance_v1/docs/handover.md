# AirSim Hybrid Avoidance - 项目交接文档

> 编写日期：2026-07-31
> 项目状态：**核心架构完成，DRL 训练未跑通，未对接真实 AirSim**
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
