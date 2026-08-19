# AirSim Hybrid Avoidance v2 - 使用说明

> 适用版本：v2.0（2026-08-19）。目标场景：100m×10m 走廊 + 双障碍物（x=30 / x=65）DRL 避障，UE 5.7 实机闭环。
> 配套文档：`README.md`（总览）、`CHANGELOG.md`（版本记录）、`docs/handover.md`（技术细节与根因分析）。

---

## 1. 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows（本项目在 Windows + PowerShell 下验证） |
| UE | 5.7，工程 `D:/ProjectAirSim-main/unreal/Blocks 5.7/Blocks.uproject` |
| Python | 3.13（本机路径 `C:\Users\13631\AppData\Local\Programs\Python\Python313\python.exe`） |
| Python 依赖 | `requirements.txt`（含 msgpack / pynng / commentjson） |
| DRL 模型 | `models/drl_agent/ddpg_best.pth`（已训练，随仓库保留） |

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

### 步骤 3：单次避障飞行
```bash
python run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000
```
- 脚本会自动：LoadScene 重载场景 → 复位到地面 → takeoff 爬升 → DRL 避障飞向终点 → 悬停保持。
- 成功输出示例：`成功: True，步数 145，耗时 52.42s，路径长度 112.64m`。

### 步骤 4：连续演示（推荐，自动校验）
```bash
python run_v2_demo.py --flights 3
```
- 每次飞行前自动 LoadScene（规避 SetPose 回弹），飞行后自动校验并输出 PASS/FAIL：
  - 到达终点（x ≥ 97）
  - y 全程在走廊内（[-5.1, 5.1]）
  - 高度保持（z < -5，未坠落）
  - UE 日志 Obstacle1/2 碰撞 = 0
- 全部 PASS 表示本次演示通过。

### 步骤 5：查看结果
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
| `python run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000` | 单次闭环飞行（默认先 LoadScene） |
| `--no-reload` | 跳过飞行前的 LoadScene（不推荐连续使用，见 FAQ 3） |
| `python run_v2_demo.py --flights 3` | 连续 3 次飞行 + 自动校验 |
| `python run_v2_demo.py --flights 5 --goal_x 100` | 自定义飞行次数/目标 |

### 3.2 训练与评估
| 命令 | 说明 |
|---|---|
| `python train_drl_v2.py --episodes 1500` | 完整训练（约 80 分钟，CPU） |
| `python train_drl_v2.py --quick` | 冒烟测试（几十轮验证链路） |
| `python evaluate.py` | 批量评估入口（旧版，2D 模式） |

> 训练完成后自动做 60 次无探索随机布局评估并打印成功率；最优模型写入 `models/drl_agent/ddpg_best.pth`。

### 3.3 可视化与分析
| 命令 | 说明 |
|---|---|
| `python experiments/visualize_trajectory.py --csv <文件>` | 单条轨迹图（推荐） |
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

### 4.2 UE 日志碰撞检查
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
| `drl.reward.corridor_limit / corridor_penalty` | 走廊边界惩罚 | 4.5 / 3.0 |
| `model.enable` | 是否启用 DRL 参与控制 | true |
| `model.load_checkpoint` | 加载的模型文件 | ddpg_best.pth |

> **改场景配置后必须重启 UE**（重新 LoadScene 并保证干净状态）；仅改 default.yaml 数值（不涉及场景）无需重启。

---

## 6. 常见问题（FAQ）

### 1. 端口 8990 连不上 / 脚本报 connection 错误
- UE 尚未启动完成：等待 30–60s 再试。
- UE 启动失败：检查 UE 进程是否存在（`Get-Process UnrealEditor`）；确认工程路径正确。
- 端口被占用：杀掉旧 UE 进程后重启。

### 2. "点了 Play 之后无人机在原地不动"
- UE 点 Play 后无人机**不会自动起飞**，必须运行 `run_hybrid.py` / `run_v2_demo.py` 发指令。
- 若脚本也表现为"不动"：模拟时钟可能很慢（PIE 启动初期 0.15x~1.6x），MoveByVelocity 是同步阻塞 RPC，多等几秒观察；避免 UE 窗口失焦/最小化。

### 3. 连续飞行时第 2 次出现"position_jump"中止
- 原因：未走 LoadScene 流程时，SetPose 复位会让 UE actor 回弹到地图出生点 (66.5,0,14.19m)（压住 Obstacle2），运动学随后被拽回（跳变 ~60m）。
- 解决：使用默认流程（飞行前 LoadScene）；不要用 `--no-reload` 连续跑多次。

### 4. UE 日志 Obstacle2 碰撞刷屏
- 说明有历史飞行把 actor 卡在了 Obstacle2 里。恢复：关闭 UE → 重新启动 → 再跑脚本（脚本会自动重载干净场景）。

### 5. 轨迹 z 掉到 -0.4（落地）
- 起飞未成功或飞行中掉高。检查 takeoff 高度配置、UE 时钟是否正常、窗口是否最小化。

### 6. 飞行全程 mode=GLOBAL（DRL 没生效）
- 检查 `model.enable: true`；确认 `models/drl_agent/ddpg_best.pth` 存在；查看控制台是否打印"模型加载成功"。

### 7. 本机 PowerShell 中 python 找不到
- 使用完整路径：`C:\Users\13631\AppData\Local\Programs\Python\Python313\python.exe`。

### 8. 训练中途想停止 / 卡死恢复
- 停掉 python 进程即可（训练会自动保存最近 checkpoint 到 `models/drl_agent/`）。
- 无人机卡死恢复：关闭 UE → 重启 UE → 重新运行飞行脚本。

---

## 7. 一页速查

```powershell
# 1. 启动 UE
"D:\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe" "D:/ProjectAirSim-main/unreal/Blocks 5.7/Blocks.uproject" GISMap -game -windowed -ResX=1280 -ResY=720

# 2. 等端口就绪
Test-NetConnection 127.0.0.1 -Port 8990 | Select-Object TcpTestSucceeded

# 3. 单次飞行
python run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000

# 4. 连续演示（自动校验）
python run_v2_demo.py --flights 3

# 5. 训练（如需重训）
python train_drl_v2.py --episodes 1500

# 6. 轨迹可视化
python experiments/visualize_trajectory.py --csv logs/flights/flight_<时间戳>.csv
```

---
*如有异常行为，优先检查 UE 日志（Blocks.log）与飞行 CSV；技术细节见 docs/handover.md 11.11。*