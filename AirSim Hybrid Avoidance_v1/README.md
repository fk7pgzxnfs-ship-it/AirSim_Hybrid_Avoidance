# AirSim Hybrid Avoidance - 无人机混合避障导航系统

## 📋 项目简介
基于 AirSim 仿真平台的无人机自主避障导航系统，采用 **A* 全局规划 + DRL 局部避障 + 势场安全备份** 的三层混合架构。全部代码使用 **Python** 实现。

## 🏗️ 核心架构
```
Supervisor（总控循环）
├── Global Planner (A* 算法)     → 全局最优路径规划
├── Local Planner (DRL)          → 实时局部避障（DDPG/SAC）
└── Safety Monitor (势场法)       → 安全备份与紧急干预
```

## 🚀 快速开始
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行混合避障飞行
python run_hybrid.py

# 3. 查看3D轨迹图
python experiments/visualize.py --mode 3d --log logs/flights/xxx.csv

# 4. 训练DRL模型
python train_drl.py

# 5. 批量评估
python evaluate.py --runs 5
```

## 📁 项目结构
```
AirSim Hybrid Avoidance/
├── config/               # 配置文件（参数集中管理）
├── airsim_interface/     # AirSim 通信层
├── planning/             # 传统规划算法（A*, RRT, 势场法）
├── drl/                  # 深度强化学习模块（DDPG）
├── hybrid_controller/    # 混合控制器核心
├── experiments/          # 实验脚本与可视化
├── logs/                 # 运行日志
└── models/               # 模型权重
```

## 📊 技术栈
- **AirSim** - 仿真环境
- **PyTorch** - 深度学习框架
- **A\* 算法** - 全局路径规划
- **DDPG** - 深度确定性策略梯度
- **人工势场法** - 安全备份控制
- **Matplotlib/Pygame** - 可视化

## 📝 论文用途
- 2D/3D 轨迹可视化图表
- 批量实验数据统计
- 算法对比分析
- 可复现的实验配置