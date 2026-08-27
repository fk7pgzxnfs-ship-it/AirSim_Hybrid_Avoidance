# Changelog

版本记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 风格。日期依据 `docs/handover.md` 与文件时间戳（确定事实）。

## [v3.0.3] - 2026-08-22
### 修复
- **`python main.py` 启动崩溃（ValueError: I/O operation on closed file）**：`main.py`、`web/webview_app.py`、`web/app.py` 三个模块各自对 `sys.stdout` 做 `TextIOWrapper` 包装，重复包装时旧 wrapper 被垃圾回收会关闭共享 buffer，第三个模块再访问 `sys.stdout.buffer` 即抛该异常（表现为"原生窗口不可用，回退浏览器"后二次崩溃）。
- 新增 `web/_stdout.py` 的幂等 `setup_stdout()`（整进程只包装一次），三个模块统一调用；exe 打包模式（sys.stdout 为 None/无 buffer）自动跳过，行为不变。

### 验证（确定事实）
- 复现命令 `python -c "from web.webview_app import open_window"` 原必现崩溃，修复后正常返回；`import main` 正常。
- 同一进程内依次导入 main / web.webview_app / web.app 后，stdout 仍为单个 TextIOWrapper、buffer 未关闭、中文输出正常。
- 64 个 .py 全部 py_compile 通过；exe 重新打包并冒烟测试通过（窗口弹出、8787 就绪、退出释放端口）。
## [v3.0.2] - 2026-08-22
### 里程碑
独立 Windows 应用 **`AirSim控制台.exe`**（PyInstaller 打包）：双击即弹原生窗口（WebView2 内核），**无黑色 Python 控制台框**；数据目录 = exe 所在目录，不需要在命令行输入任何内容。`python main.py` 开发模式仍可用。

### 新增
- **打包脚本** `scripts/tools/build_exe.py`：一键复现 exe 构建（`--onefile --noconsole`，排除 torch/scipy/pygame/pandas/matplotlib/gymnasium/tqdm，产物约 71MB）。
- **exe 运行模式** `web/webview_app.py`：`sys.frozen` 时数据根目录 = exe 所在目录；Flask 在本进程线程内启动（`werkzeug.serving.make_server`），避免直接 `flask_app.run()` 在线程内报 `ValueError: I/O operation on closed file`（click banner 的 stdout.fileno 崩溃）。
- **任务子进程改调本机系统 Python** `web/app.py` `_system_python()`：exe 内无法产子进程执行 `scripts/...`，改为探测 `AIRSIM_PYTHON` → PATH → `%LOCALAPPDATA%\Programs\Python\Python*\python.exe`（取最新）→ 回退 `python`。
- `scene_config.py` 的 `PROJECT_ROOT` 支持 `AIRSIM_ROOT` 环境变量重定向；`web/app.py` 静态目录改为 `ROOT/web/static`（支持 exe 路径模式）。

### 变更
- 使用方式：双击 `AirSim控制台.exe` 即弹出控制台窗口；`config/scenes`、`scripts`、`models`、`web/static` 需与 exe 同目录。
- 开发模式不变：`python main.py` 仍弹出原生窗口（WebView2），`--browser` 回退浏览器。

### 验证（确定事实）
- exe 启动 15 秒内窗口“AirSim v3 控制台”正常弹出（EnumWindows + 截图确认，Win11 现代风格，无黑框）。
- HTTP 全链路：`/console` `/api/status` `/api/scenes` 全部 200；`POST /api/run`（gen_scene.py）子进程执行成功、`/api/log` 增量返回正常。
- 全部 .py py_compile 通过。

## [v3.0.1] - 2026-08-21
### 里程碑
`python main.py` 默认弹出 **Windows 原生控制台窗口**（pywebview + WebView2 内核渲染，Win11 现代风格：圆角卡片、Segoe UI、浅色/深色自动适配），替换 v3.0 的 tkinter 复古窗口；所有操作（选场景/单次/连续飞行/评估/重训/编辑器/检查连接/停止任务）与实时日志都在窗口里完成，不再有命令行 input 交互。

### 新增
- **Web 控制台页面** `web/static/console.html`：顶部状态胶囊（UE 连接/任务运行中）、左侧分类按钮组（场景/飞行/训练评估/系统）、右侧实时日志滚动区；任务进行中自动禁用相关按钮，防止并发任务。
- **控制台后端接口** `web/app.py`：
  - `GET /console`：控制台页面（同时保留 `/` 场景编辑器、`/api/scenes`、`/api/scene`、`/api/check` 旧接口）。
  - `GET /api/status`：UE 连接状态 / 任务运行状态 / 日志长度。
  - `POST /api/run`：在后台子进程执行脚本（stdout 捕获到内存队列），支持任意脚本 + 参数 + 标签。
  - `POST /api/stop`：终止当前运行中的任务。
  - `GET /api/log`：增量拉取日志（`since` 参数）。
- **Windows 原生弹窗启动器** `web/webview_app.py`：`_ensure_server()` 确保 8787 服务在线后，`webview.create_window` 用 Edge WebView2 内核加载 `/console`（1280x820，最小 980x640）；窗口关闭后进程退出。
- **main.py 默认入口变更**：无参数 `python main.py` 优先调用 `_open_native_window()` 弹出原生窗口；若 pywebview 不可用则回退 `webbrowser.open` 浏览器；`--browser` 强制浏览器（备用）；`--menu` 命令行菜单、`--editor` 编辑器、`--scene/--flights/--single/--eval/--train/--check` 直跑不变。
- 依赖新增 `pywebview>=5.0`（requirements.txt）；Win11 自带 Edge WebView2 Runtime，无需额外安装。

### 修复
- 旧 Flask 服务进程常驻导致 `/console` 等新增路由 404（代码热更新后旧进程未重启）；重启服务后全链路验证通过。

### 变更
- 删除 `gui.py`（tkinter 复古界面，用户明确弃用）；`web/` 由“场景编辑器”扩展为“Web 控制台 + 场景编辑器”。
- 文档（README / USER_GUIDE / CHANGELOG）同步更新：`python main.py` 说明改为“弹出 Windows 原生控制台窗口（WebView2，推荐）”。

### 验证（确定事实）
- 全链路 HTTP 实测：`/console` 200、`/` 200、`/api/status` 200（UE 8990 已连接）、`/api/scenes` 200、`/api/run` 启动子进程成功、`/api/log` 增量返回日志、`/api/stop` 正常响应。
- 原生窗口实测（确定事实）：启动 `web/webview_app.py` 后进程持续运行，Windows 窗口“AirSim v3 控制台”正常弹出并加载界面（截图验证），8787 服务复用正常。
- 全部 .py 文件 py_compile 通过。

## [v3.0] - 2026-08-21
### 里程碑
支持自定义地图、起点终点与障碍物布局（v3 标准：路线 = 起点终点直线）；新增网页场景编辑器与统一场景文件（yaml），飞行/训练/评估/UE 场景全部由一份场景配置驱动。UE 实机验证：程序生成场景 LoadScene 成功，直线路线闭环飞行 PASS。

### 新增
- **场景配置文件** `config/scenes/<name>.yaml`：定义地图范围（矩形）、起点/终点、障碍物列表（位置/底面 w×h/高度）、路线模式（line 默认 / astar）、巡航高度；新增 `scene_config.py`（加载/校验/可达性检查/直线路线/UE 场景生成/预览图）。
- **网页场景编辑器** `web/`：`python main.py --editor` 启动本地编辑器（http://127.0.0.1:8787），Canvas 拖拽摆障碍、拖起点/终点、改地图范围与障碍尺寸，实时可达性检查（A*）、保存 yaml。依赖新增 Flask。
- **场景生成器** `scripts/tools/gen_scene.py`：yaml -> UE jsonc（地面板 + 障碍物 + 无人机自动生成，替换手写 21KB jsonc），LoadScene RPC 上传，UE 端零改动；可选生成 2D 预览图。
- **main.py 场景支持**：`--scene <yaml>` 全局透传（--flights/--single/--eval/--train）；交互菜单新增"选择场景"与"网页场景编辑器"入口。
- **Windows 原生控制台（gui.py）**：`python main.py` 默认弹出 tkinter 窗口（按钮操作：选场景/单次/连续飞行/评估/重训/编辑器/检查连接/停止任务，实时日志），替代命令行 input 交互；`--menu` 保留命令行菜单。
- **默认场景迁移**：`config/scenes/scene_100x10.yaml`（与 v2 布局一致）+ 示例 `scene_test_120x16.yaml`（120x16、3 障碍、斜向起终点）。

### 修复
- 去硬编码：`drl/sim_client.py` 障碍物/边界/随机化范围改为从场景推导（默认值兼容 v2）；`drl/env.py` 走廊惩罚改为"到起点终点直线的横向距离 + 地图矩形边界"（自定义起终点时不再依赖 y=0 假设）；`supervisor.py` 从场景读地图/障碍/起终点/高度，scene_id 与场景文件一致；`load_scene()` 支持直接传场景 dict。
- `global_planner` 新增直线路线模式（route.mode=line）：path = 起点终点直线离散点，仍保留 A* 可达性检查（障碍围死终点时提前报错）。
- `scripts/tools/fly_straight.py` 第 3 行历史损坏的 docstring 引号修复。

### 变更
- `run_hybrid.py` / `run_v2_demo.py` / `train_drl_v2.py` / `evaluate_smoothness.py` 均支持 `--scene`；`run_v2_demo` 校验改用场景边界；评估/训练的 path_ratio 改用场景直线长度。
- README / USER_GUIDE 更新为 v3 流程（编辑器 + --scene 为主）。

### 验证（确定事实）
- 60 个 .py 全部 py_compile 通过；`main.py --eval --scene scene_100x10.yaml` 60 局：success 100%、collided 0%、mean|Δaction|=0.124（与 v2.1b 一致，链路未被破坏）。
- UE 实机：默认场景与自定义场景（SceneTest120x16）LoadScene 均成功；`main.py --scene scene_100x10.yaml --flights 1` 实机飞行 PASS（145 步、52.5s、路径 104.05m、障碍碰撞 0、直线路线模式生效）。

### 说明
- **模型不通用（确定事实）**：v2.1b 模型只在"100x10 + 2 个固定障碍"分布上训练；自定义布局（改地图/障碍/起终点）需重训，否则 DRL 大概率失效（SAFETY 兜底频繁介入）。domain randomization 重训（v3.2，随机起终点/障碍布局提升泛化）另行进行。
- 训练奖励已场景化（横向偏差 + 边界惩罚），为新布局重训做好铺垫。

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
