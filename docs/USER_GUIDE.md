# AirSim Hybrid Avoidance v2.2 - 使用说明

> 适用版本：v2.2（2026-08-21）。目标场景：100m×10m 走廊 + 双障碍物（x=30 / x=65）DRL 避障，UE 5.7 实机闭环。
> v2.2 核心：**统一入口 `python main.py`**——接上 UE 直接跑，散落脚本分类到 `scripts/`（fly / train / evaluate / diag / tools）。
> v2.1 核心：修复直线段蛇形振荡（纯算法层奖励塑形，部署端零改动）。
> 配套文档：`README.md`（总览）、`CHANGELOG.md`（版本记录）、`docs/handover.md`（技术细节与根因分析）。

---

## 1. 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows（本项目在 Windows + PowerShell 下验证） |
| UE | 5.7，工程 `D:/ProjectAirSim-main/unreal/Blocks 5.7/Blocks.uproject` |
| Python | 3.13（本机路径 `C:\Users\13631\AppData\Local\Programs\Python\Python313\python.exe`） |
| Python 依赖 | `requirements.txt`（含 msgpack / pynng / commentjson） |
| DRL 模型 | `models/drl_agent/ddpg_best.pth`（v2.1b 最终模型，随仓库保留） |

> 注意：PowerShell 中 `python` 命令可能不可用，下面所有命令可直接替换为完整路径。

---

## 2. 从零开始（完整流程）

### 步骤 1：安装依赖（仅首次）
```bash
pip install -r requirements.txt
```

### 步骤 2：启动 UE 5.7
```powershell
"D:\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe" "D:/ProjectAirSim-main/unreal/Blocks 5.7/Blocks.uproject" GISMap -game -windowed -ResX=1280 -ResY=720
```
- 地图用空白 **GISMap**（无自带杂物），地面/障碍物/无人机由脚本通过 LoadScene RPC 自动加载。
- 等待约 30–60s，确认端口 **8990** 就绪：
```powershell
Test-NetConnection 127.0.0.1 -Port 8990 | Select-Object TcpTestSucceeded
```

### 步骤 3：单次避障飞行（统一入口）
```bash
python main.py            # 交互菜单选 1
python main.py --single   # 或命令行直跑
```
- 内部调用 `scripts/fly/run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000`；脚本会自动：LoadScene 重载场景 → 复位到地面 → takeoff 爬升 → DRL 避障飞向终点 → 悬停保持。
- 成功输出示例：`成功: True，步数 145，耗时 52.42s，路径长度 112.64m`。

### 步骤 4：连续演示（推荐，自动校验）
```bash
python main.py --flights 3   # 或交互菜单选 2
```
- 内部调用 `scripts/fly/run_v2_demo.py --flights 3`。
- 每次飞行前自动 LoadScene（规避 SetPose 回弹），飞行后自动校验并输出 PASS/FAIL：
  - 到达终点（x ≥ 97）
  - y 全程在走廊内（[-5.1, 5.1]）
  - 高度保持（z < -5，未坠落）
  - UE 日志 Obstacle1/2 碰撞 = 0
- 全部 PASS 表示本次演示通过。

### 步骤 5：平滑度复核（可选，无需 UE）
```bash
# 一键评估（UE 对齐：成功率 / 碰撞 / 平滑度指标，60 局，约 1 分钟）
python main.py --eval

# 底层脚本（等价）
python scripts/evaluate/evaluate_smoothness.py --vel-tc 0.1 --n 60

# 直线段 / 避障段分段分析（看直线段 y 波动是否够小）
python scripts/evaluate/_analyze_segments.py

# 生成样例轨迹图 logs/train/traj_v21_fixed.png
python scripts/evaluate/_plot_traj.py
```
- 直线段（最近障碍 >8m）健康值：`y_std` ≤ 0.5m、`y_span` ≤ 2m。当前 v2.1b 模型：`y_std=0.30m`、`y_span=1.52m`。

### 步骤 6：查看结果
- 轨迹 CSV：`logs/flights/flight_<时间戳>.csv`
- 控制台日志：`logs/run_*.log`（demo 输出 `logs/run_v2_demo.log`）
- 轨迹图：
```bash
python experiments/visualize_trajectory.py --csv logs/flights/flight_xxx.csv
```

---

## 3. 命令参考

### 3.1 飞行
| 命令 | 说明 |
|---|---|
| `python main.py` | 交互菜单（1 单次 / 2 连续 / 3 评估 / 4 重训 / 5 检查连接 / 0 退出） |
| `python main.py --single` | 单次闭环飞行（内部调 scripts/fly/run_hybrid.py） |
| `python main.py --flights 3` | 连续 3 次飞行 + 自动校验（内部调 scripts/fly/run_v2_demo.py） |
| `python scripts/fly/run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000` | 底层单次飞行（默认先 LoadScene） |
| `python scripts/fly/run_hybrid.py --no-reload` | 跳过飞行前的 LoadScene（不推荐连续使用，见 FAQ 3） |
| `python scripts/fly/run_v2_demo.py --flights 5 --goal_x 100` | 底层自定义飞行次数/目标 |

### 3.2 训练与评估
| 命令 | 说明 |
|---|---|
| `python main.py --train` | 完整训练（约 25 分钟，CPU；内部调 scripts/train/train_drl_v2.py） |
| `python main.py --eval` | 一键平滑度评估（60 局，无需 UE） |
| `python scripts/train/train_drl_v2.py --episodes 1500` | 完整训练（`--tag` 默认 `v21b`） |
| `python scripts/train/train_drl_v2.py --episodes 1500 --tag mytag` | 自定义输出标签（rewards_<tag>.npy） |
| `python scripts/train/train_drl_v2.py --quick` | 冒烟测试（几十轮验证链路） |
| `python scripts/evaluate/evaluate_smoothness.py --vel-tc 0.1 --n 60` | v2.1 平滑度评估（UE 对齐动态） |
| `python scripts/evaluate/evaluate_smoothness.py --ckpt models/drl_agent/ddpg_v20_backup.pth --vel-tc 0.1` | 对比其他 ckpt |
| `python scripts/evaluate/evaluate.py` | 批量评估入口（旧版，2D 模式） |

> 训练完成后自动做 60 次无探索随机布局评估并打印成功率与平滑度指标；最优模型写入 `models/drl_agent/ddpg_best.pth`。
> `--vel-tc` 是评估用的速度惯性时间常数：UE fast-physics 行为接近 `0.1`（直接执行目标速度），训练动态为 `0.5`。用 `0.1` 评估更贴近部署表现。

### 3.3 可视化与分析
| 命令 | 说明 |
|---|---|
| `python scripts/evaluate/_analyze_segments.py` | 直线段/避障段分段统计（y_std、y_span、y 符号切换） |
| `python scripts/evaluate/_plot_traj.py` | 生成样例轨迹图（3 面板：轨迹 / y 放大 / action_y） |
| `python experiments/visualize_trajectory.py --csv <文件>` | 单条飞行轨迹图 |
| `python experiments/visualize.py --mode 3d --log <文件>` | 旧版可视化入口 |

---

## 4. 结果文件说明

### 4.1 轨迹 CSV 字段（logs/flights/）
`step, x, y, z, vx, vy, mode, nearest_obs, action_x, action_y`

| 字段 | 含义 | 健康值 |
|---|---|---|
| x / y | 位置（m，NED） | x: 0→~98.8；y: [-5, 5] |
| z | 高度（m，NED 负值向上） | 巡航约 -13 ~ -22，不应接近 -0.4 |
| mode | 控制模式 | DRL 主导；SAFETY 出现表示势场兜底介入 |
| nearest_obs | 最近障碍距离（模拟 LiDAR） | 正常 ≥ 1.5m |

> 直线段"丝滑"判断：看 y 列在 x∈(5,25) 与 x∈(40,60) 区间是否基本贴 0（波动 <0.5m），且 action_y 列是否近 0（不再满幅 ±2 切换）。

### 4.2 训练/评估产物（logs/train/、logs/）
| 文件 | 说明 |
|---|---|
| `logs/train_v21b.log` | v2.1b 最终训练日志（1500 轮） |
| `logs/train/rewards_v21b.npy` | v2.1b 训练奖励曲线 |
| `logs/train/traj_v21_fixed.png` | v2.1 样例轨迹图（vel_tc=0.1） |

### 4.3 UE 日志碰撞检查
```powershell
Select-String -Path "D:\ProjectAirSim-main\unreal\Blocks 5.7\Saved\Logs\Blocks.log" -Pattern "Collision detected between 'Frame' and 'Obstacle" | Measure-Object
```
- 正常飞行：无 Obstacle 碰撞（只有少量 `Ground100x10` 接地记录）。
- 日志时间戳为 **UTC**（比本地时间晚 8 小时）；碰撞 z 单位为 **cm**。

---

## 5. 配置修改指南（config/default.yaml）

| 配置 | 作用 | 当前值 |
|---|---|---|
| `airsim.port` | UE RPC 端口 | 8990 |
| `airsim.takeoff_height` | 起飞巡航高度（NED） | -12.0 |
| `map.x_min/x_max` | 走廊 X 范围 | 0 / 100 |
| `map.y_min/y_max` | 走廊 Y 范围（半宽 5m） | -5 / 5 |
| `map.goal` | 终点 | [100, 0] |
| `map.obstacles` | 规划用障碍 [x, y, 半径] | [30,0,1.5]、[65,0,1.5] |
| `map.obstacles_physical` | LiDAR/碰撞用障碍半径 | [30,0,1.0]、[65,0,1.0] |
| `potential_field.safety_distance` | 势场安全距离 | 2.5 |
| `drl.vel_time_constant` | 训练仿真速度惯性（s） | 0.5（训练动态，勿改） |
| `drl.reward.corridor_limit / corridor_penalty` | 走廊边界惩罚 | 4.5 / 3.0 |
| `drl.reward.action_smooth_penalty` | v2.1 动作平滑惩罚系数 | 0.15 |
| `drl.reward.lateral_penalty` | v2.1 横向偏移惩罚系数 | 0.10 |
| `model.enable` | 是否启用 DRL 参与控制 | true |
| `model.load_checkpoint` | 加载的模型文件 | ddpg_best.pth |

> **改惩罚系数后需重训**（`action_smooth_penalty`/`lateral_penalty` 只影响训练奖励，不影响部署）。
> **改场景配置后必须重启 UE**（重新 LoadScene 并保证干净状态）；仅改 default.yaml 数值（不涉及场景）无需重启。

---

## 6. 常见问题（FAQ）

### 1. 端口 8990 连不上 / 脚本报 connection 错误
- UE 尚未启动完成：等待 30–60s 再试。
- UE 启动失败：检查 UE 进程是否存在（`Get-Process UnrealEditor`）；确认工程路径正确。
- 端口被占用：杀掉旧 UE 进程后重启。

### 2. "点了 Play 之后无人机在原地不动"
- UE 点 Play 后无人机**不会自动起飞**，必须运行 `main.py`（内部调用 `scripts/fly/run_hybrid.py` / `scripts/fly/run_v2_demo.py`）发指令。
- 若脚本也表现为"不动"：模拟时钟可能很慢（PIE 启动初期 0.15x~1.6x），MoveByVelocity 是同步阻塞 RPC，多等几秒观察；避免 UE 窗口失焦/最小化。

### 3. 连续飞行时第 2 次出现"position_jump"中止
- 原因：未走 LoadScene 流程时，SetPose 复位会让 UE actor 回弹到地图出生点 (66.5,0,14.19m)（压住 Obstacle2），运动学随后被拽回（跳变 ~60m）。
- 解决：使用默认流程（飞行前 LoadScene）；不要用 `--no-reload` 连续跑多次。

### 4. 无人机在直线段还是左扭右扭（蛇形）
- v2.1 已用纯算法层修复（奖励塑形：`action_smooth_penalty` + `lateral_penalty`），部署端没有任何动作滤波。
- 如果用的是旧模型：确认 `models/drl_agent/ddpg_best.pth` 是 v2.1b（时间戳 2026-08-20），v2.0 模型备份在 `ddpg_v20_backup.pth`。
- 若仍嫌摆动：可上调 `action_smooth_penalty`/`lateral_penalty` 后重训（注意避障段 y 跨度会略增、奖励略降）。

### 5. UE 日志 Obstacle2 碰撞刷屏
- 说明有历史飞行把 actor 卡在了 Obstacle2 里。恢复：关闭 UE → 重新启动 → 再跑脚本（脚本会自动重载干净场景）。

### 6. 轨迹 z 掉到 -0.4（落地）
- 起飞未成功或飞行中掉高。检查 takeoff 高度配置、UE 时钟是否正常、窗口是否最小化。

### 7. 飞行全程 mode=GLOBAL（DRL 没生效）
- 检查 `model.enable: true`；确认 `models/drl_agent/ddpg_best.pth` 存在；查看控制台是否打印"模型加载成功"。

### 8. 本机 PowerShell 中 python 找不到
- 使用完整路径：`C:\Users\13631\AppData\Local\Programs\Python\Python313\python.exe`。

### 9. 训练中途想停止 / 卡死恢复
- 停掉 python 进程即可（训练会自动保存最近 checkpoint 到 `models/drl_agent/`）。
- 无人机卡死恢复：关闭 UE → 重启 UE → 重新运行飞行脚本。

---

## 7. 一页速查

```powershell
# 1. 启动 UE
"D:\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe" "D:/ProjectAirSim-main/unreal/Blocks 5.7/Blocks.uproject" GISMap -game -windowed -ResX=1280 -ResY=720

# 2. 等端口就绪
Test-NetConnection 127.0.0.1 -Port 8990 | Select-Object TcpTestSucceeded

# 3. 一键飞行（交互菜单或命令行直跑）
python main.py
python main.py --flights 3

# 4. 检查 UE 连接
python main.py --check

# 5. 平滑度复核（无需 UE）
python main.py --eval

# 6. 训练（如需重训）
python main.py --train

# 7. 轨迹可视化
python experiments/visualize_trajectory.py --csv logs/flights/flight_<时间戳>.csv
```

---
*如有异常行为，优先检查 UE 日志（Blocks.log）与飞行 CSV；技术细节见 docs/handover.md 11.11（v2.0 回弹）与 11.12（v2.1 平滑修复）。*