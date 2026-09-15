# AirSim Hybrid Avoidance v5.6 - 使用说明

> 适用版本：v4.1（2026-09-10）。在 v3.1（场景编辑器进弹窗 + 自动连接 UE）基础上新增：真实城市一键导入（OSM/离线缓存）、悬浮障碍物、随机障碍生成；起于 v2.x 已支持自定义场景与盒式障碍布局。UE 5.7 实机闭环。
> 操作入口：**双击 `AirSim控制台.exe` 弹出 Windows 原生窗口**（WebView2 内核，Win11 现代界面，无黑色控制台框；顶部「控制台 / 场景编辑器」标签页切换，内置**自动连接 UE** 一键启动）；开发模式 `python main.py` 等价弹窗；`--browser` 回退浏览器；`--scene 场景.yaml --flights 3` 命令行直跑。v4 城市/悬浮/随机快速上手见下方「V4 新增功能快速上手」。
> **v5.1 新增（2026-09-11）**：编辑器侧栏参数（经纬度/范围/航程/走廊）一改，右侧画布立刻重画该选区**真实卫星影像 + 真实建筑轮廓 + 走廊布局**预览（`/api/gis/peek`），满意后再点「生成真实场景」写 3D 瓦片；同时修正底图朝向。**v5.0 新增（2026-09-11）**：全球任意地区**真实 DEM 地形 + 真实 OSM 建筑**三维场景（Project AirSim `CustomGIS` quadkey glTF 瓦片，见步骤 2.8）。
> **v4.1 新增（2026-09-10）**：场景编辑器侧栏新增「v4.1 全球任意地区（地图选点）」——内置 OSM 世界地图，点选/拖动标记选任意坐标，或输入地名搜索候选定位，再按范围(m) 一键导入该点周边真实建筑；另支持坐标反查地名与手填经纬度。地名服务 Nominatim → Photon 自动备选，离线降级手填。
> v2.x 背景：v2.2 统一入口 main.py；v2.1 修复直线段蛇形振荡（纯算法层奖励塑形，部署端零改动）。
> 配套文档：`README.md`（总览）、`CHANGELOG.md`（版本记录）、`docs/handover.md`（技术细节与根因分析）。

---

## V4 新增功能快速上手（城市 / 悬浮 / 随机 / 全球地图选点）

三个 v4 入口都在**弹窗 → 「场景编辑器」标签页侧栏顶部**（也可用 CLI 等价，见 3.1.1）：

- **真实城市一键导入**：下拉选预置 10 城市（[缓存]= 已有本地数据可离线用；[在线]= 需接 OSM），可调范围(m)或输入自定义地名。点「一键导入」后后台执行（OSM 拉取→盒式障碍→自动选起始/目标 + A*），完成后自动加载到画布，可拖动调整后「保存」为 `config/scenes/city_*.yaml`。首次成功后缓存在 `config/city_data/`，后续「一键导入」离线即用。
- **全球任意地区地图选点（v4.1 新增）**：侧栏「v4.1 全球任意地区（地图选点）」= Leaflet + OSM 底图。三种用法：① 直接点地图 / 拖标记选点；② 输入地名 → 「搜索」→ 候选下拉选一条；③ 手填经纬度。再填「范围(m)」→ 「用该点导入」。点「反查地名」把当前坐标转成地址文字。导入后与 v4.0 城市流程一致（画布预览 → 保存 yaml）。离线时地图区域会提示降级，仍可手填经纬度或按地名导入。
- **悬浮障碍物**：任意障碍物在列表中把“离地 base_z”设为 &gt;0 就变悬浮（画布蓝色虚线）。**威胁语义（确定事实）**：巡航高度 = |takeoff_height|（默认 12m），威胁带 = 巡航± 2m；悬浮物的垂直区间 [base_z, base_z+height] 与该带相交才会被 A*/避障计入。示例场景：`config/scenes/scene_v4_floating_demo.yaml`（下悬 8.5~11.5m、上悬 13.5~15.5m、落地柱 0~14m）。
- **随机障碍生成**：配数量/悬浮比例(％)/尺寸/高度范围/种子，「追加或替换全部」，点「随机生成」即在当前场景内生成并自动 A* 可达性校验（不可达时回退新增）。注意：高度范围下限建议 ≥ 巡航高度-2m，否则所有障碍都不会被计为威胁而报错（城市场景巡航 20m，建议用 18~26）。
- **城市场景飞行语义**：导入场景默认 `route.mode=astar` + `use_drl=false`，即使本地有 v2.1b 模型也不加载 DRL，全程 A* + 势场飞行。原因：现有模型只在 100×10 双障碍上训练，拿去城市/悬浮/任意起终点布局会频繁触发 SAFETY。若需 DRL 进入新布局，需先 domain randomization 重训。



## 0. 直接双击 exe（推荐）

1. 把 `AirSim控制台.exe` 放到一个目录（数据目录 = exe 所在目录；首次使用可直接放项目根）。
2. 确认 exe 同目录下有 `config/scenes`（场景文件）、`scripts`（飞行/训练脚本）、`models/drl_agent`（模型权重）、`web/static`（页面资源）。
3. 启动 UE 5.7（见步骤 2）并等待端口 8990 就绪。
4. 双击 `AirSim控制台.exe`：直接弹出 Windows 原生窗口（无黑色控制台框），选场景 → 点“飞行”即可。

> exe 是“控制台外壳”：点击飞行/训练/评估等按钮时，会调用**本机系统 Python** 在后台执行 `scripts/...` 脚本（自动探测 `python`；也可设置环境变量 `AIRSIM_PYTHON` 指定解释器路径）。因此本机仍需安装 Python 与依赖（`pip install -r requirements.txt`）。
> exe 首次启动约 10–15 秒（onefile 自解压），之后窗口即弹。

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

### 步骤 2.5：自定义场景（v3，可选）
```bash
python main.py --editor
```
- 两种用法：弹窗顶部「场景编辑器」标签页（推荐）；或浏览器打开 http://127.0.0.1:8787。拖拽红框摆障碍物、拖绿点/橙星定起点终点、面板改地图范围与障碍尺寸，点击"可达性检查"确认布局，保存到 `config/scenes/<name>.yaml`。
- 场景文件结构见 `config/scenes/scene_100x10.yaml`（地图 / start / goal / obstacles / route.mode=line）。
- 指定场景运行：所有命令加 `--scene config/scenes/<name>.yaml`。
- **注意**：自定义布局后必须重训模型（见步骤 5），v2.1b 模型只适用默认场景。

### 步骤 2.6：真实城市 / 悬浮 / 随机障碍（v4 / v4.1，可选）
- 弹窗→「场景编辑器」→侧栏「真实城市一键导入」，选预置城市（或自定义地名）→「一键导入」；进度在按钮下方提示，完成后自动加载到画布。
- 需要时用同一侧栏「随机生成障碍物」给当前场景加悬浮物/落地柱，或在障碍物列表手动改“离地 base_z”制作悬浮障碍。
- 点「保存」写入 `config/scenes/city_<id>.yaml`（或自定义名），然后切回「控制台」标签页，在「场景」下拉选择该场景即可飞行（单次/连续）。城市场景自动以 A*路线 + 势场飞行，无需重训模型。

### 步骤 2.7：全球任意地区地图选点（v4.1，可选）

- 侧栏「v4.1 全球任意地区（地图选点）」：地图上单击选点，或拖动标记微调；「纬度 / 经度」输入框同步显示当前坐标。
- **按地名定位**：在「地名」框输入（如 `东京塔`、`Shanghai Bund`）→ 点「搜索」→ 在候选下拉里选一条 → 地图与经纬度自动跳到该点。
- **反查地名**：点「反查地名」把当前选点坐标转成地址文字，用于确认位置。
- **范围(m)**：以选点为圆心、近似正方形街区的范围（默认 500m；越大建筑越多、导入越慢）。
- **用该点导入**：拉取该点周边 OSM 建筑 → 自动选起 / 终点 + A* 路线 → 载入画布（默认 `use_drl=false`，免重训）→ 「保存场景」写入 `config/scenes/`。
- **离线 / 网络不可用**：地图底图不显示时仍可在输入框手填经纬度后点「用该点导入」；若 Overpass 不可达且本地无该点缓存，需先联网成功导入一次。
- 与 v4.0 的 10 个预置城市面板等价，只是坐标任意；两者共用同一套导入 / 缓存 / 画布流程。

### 步骤 2.8：真实地形 + 真实建筑（v5.0 / v5.1，可选）

> 和步骤 2.6 / 2.7 的区别：2.6 / 2.7 生成的是**盒式近似**城市（建筑足印拉成方块，无地形）；本步骤生成的是**真实 DEM 高程地形 + 真实 OSM 建筑轮廓**的 3D 瓦片场景。

- 侧栏「v4.1 全球任意地区（地图选点）」选点（点地图 / 拖标记 / 填经纬度 / 地名搜索）。
- **左栏一改，右侧画布立刻重画（v5.1）**：修改经纬度 / 范围(m) / 航程(m) / 走廊宽(m) 或贴图源后约 1 秒，右侧画布换成该选区的真实卫星影像 + 真实建筑轮廓 + 将要生成的走廊、起点 S / 终点 G 与障碍，左下角蓝条显示经纬度、走廊尺寸、障碍数、建筑轮廓数与「A* 可达 / 不可达」。首次拉取约 10~60s，同参数第二次秒开（磁盘缓存）。
- 预览是**只读**的：预览态下在画布上拖拽 / 双击不会编辑，会提示先点「生成真实场景」。点「刷新预览」可强制重算当前预览。
- 满意后点「生成真实场景」写盘：按经纬度生成 DEM 地形三角网 + OSM 建筑棱柱 + 卫星影像贴图，输出到 `config/gis_tiles/<site_id>/`，场景写入 `config/scenes/gis_<lat>_<lon>.yaml`。
- 也可以用「真实场景」按钮（按预置城市下拉）一键生成；「盒式导入」/「在线刷新」是 v4 的旧 2D 盒式路径，保留兼容。
- 生成完成后在「控制台」标签页的场景下拉里选中该 `gis_*.yaml` 即可飞行。**GIS 场景默认 `route.mode=astar` + `use_drl=false`，避障由 A* + 势场负责，不需要重训模型。**
- **命令行等价**：
```bash
python gis_tiles.py build --lat 48.8584 --lon 2.2945 --extent 900      # 生成站点
python gis_tiles.py info --site gis_48_85840_2_29450                 # 查看站点信息
python gis_tiles.py verify --site gis_48_85840_2_29450               # 校验瓦片与场景
python gis_tiles.py preview --site gis_48_85840_2_29450              # 重画顶视底图
```
- **确定事实（本机实测）**：巴黎埃菲尔 9 瓦片 / 5.4MB / 164 建筑 / 67 障碍；东京新宿 41 瓦片 / 16.2MB / 1415 建筑；里约科科瓦多 57 瓦片 / 22.8MB / 32s，DEM 实测海拔 528.57m。南半球 + 西经坐标正常取数。
- **限制条件**：需联网（DEM / 影像 / Overpass 建筑 / 地名）；预览影像长边上限 1000px，范围 > 2000m 时清晰度不足；生成的 GIS 场景尚未在 UE 实机加载验证。

### 步骤 3：飞行（Windows 原生控制台窗口）
```bash
python main.py            # 自动启动本地服务并弹出原生窗口
```
- 窗口自动弹出并加载 http://127.0.0.1:8787/console（Win11 现代风格，自动适配深色模式）：
  - **自动连接 UE**：UE 未启动时点顶栏「自动连接 UE」，自动启动进程并等待端口 8990 就绪（路径在「系统 → UE 启动设置」修改，保存到 config/ue_launch.json）。
  - **场景**：下拉选择场景 / 打开网页编辑器 / 检查 UE 连接
  - **飞行**：单次避障飞行 / 连续飞行 N 次
  - **训练评估**：平滑度评估 / 重新训练模型（需确认）
  - **系统**：停止当前任务 / 查看实时日志
- 任务执行中相关按钮自动禁用，可随时“停止当前任务”；日志增量实时滚动显示。
- 命令行直跑等价：`python main.py --single` / `python main.py --flights 3`（加 `--scene 场景.yaml` 指定场景）。
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
- 局限（确定事实）：碰撞统计只匹配 UE 日志中名为 `Obstacle1`/`Obstacle2` 的 actor；自定义/城市场景的障碍物名不同（如 BldgN），它们的 UE 碰撞不会计入该 PASS 字段，请结合轨迹 CSV 与 UE 日志综合判断。

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
| `python main.py` | 弹出 Windows 原生控制台窗口（WebView2 内核，现代界面，推荐；自动启动本地服务 http://127.0.0.1:8787/console） |
| python main.py --browser | 备用：浏览器打开控制台 |
| （弹窗）自动连接 UE | 一键启动 UE 进程并等待端口 8990；路径见「系统 → UE 启动设置」/ config/ue_launch.json |
| （弹窗）场景编辑器标签页 | 控制台顶部标签页直接编辑场景，无需另开浏览器 |
| `python main.py --menu` | 命令行菜单（高级用户） |
| `python main.py --editor` | 启动网页场景编辑器（http://127.0.0.1:8787） |
| `python main.py --scene <yaml> --flights 3` | 指定场景连续飞行（v3） |
| `python main.py --single` | 单次闭环飞行（内部调 scripts/fly/run_hybrid.py） |
| `python main.py --flights 3` | 连续 3 次飞行 + 自动校验（默认场景） |
| `python scripts/fly/run_hybrid.py --goal_x 100 --goal_y 0 --max_steps 2000` | 底层单次飞行（默认先 LoadScene） |
| `python scripts/fly/run_hybrid.py --no-reload` | 跳过飞行前的 LoadScene（不推荐连续使用，见 FAQ 3） |
| `python scripts/fly/run_v2_demo.py --flights 5 --goal_x 100` | 底层自定义飞行次数/目标 |

### 3.1.1 v4 场景生成 CLI（worldgen.py）
| 命令 | 说明 |
|---|---|
| `python worldgen.py city --list` | 列出预置城市（10 个） |
| `python worldgen.py city --preset manhattan_nyc` | 导入纽约-曼哈顿（优先离线缓存），自动保存 `config/scenes/city_manhattan_nyc.yaml` |
| `python worldgen.py city --preset london_city --extent 700 --refresh` | 指定范围并强制 OSM 在线刷新缓存 |
| `python worldgen.py city --place "Manhattan" --extent 600` | 自定义地名（Nominatim 在线检索） |
| `python worldgen.py city --preset paris_centrum --offline` | 离线模式：无本地缓存则报错（巴黎/悉尼/柏林未隤仓库） |
| `python worldgen.py fix --preset chicago_loop` | 离线修复缓存场景（去重 + 重选起终点，不访网络） |
| `python worldgen.py random --scene config/scenes/scene_100x10.yaml --count 6 --floating 0.5` | 随机障碍（50% 悬浮），自动 A* 可达性校验，默认覆盖原场景；`--out other.yaml` 写新文件 |
| `/api/geo/search?q=<地名>` / `/api/geo/reverse?lat=&lon=` | v4.1 地名候选搜索 / 坐标反查（编辑器地图选点用；任意经纬度无 CLI 等价参数，走网页或 API） |

### 3.2 训练与评估
| 命令 | 说明 |
|---|---|
| `python main.py --train` | 完整训练（约 25 分钟，CPU；内部调 scripts/train/train_drl_v2.py） |
| `python scripts/tools/gen_scene.py --scene <yaml> --preview out.png` | 场景生成器：yaml → UE jsonc + 2D 预览图（v3） |
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

### 3.4 打包 exe（开发者）
| 命令 | 说明 |
|---|---|
| `pip install pyinstaller` | 安装打包工具（可选，仅打包时用） |
| `python scripts/tools/build_exe.py` | 一键打包，产物 `dist/AirSim控制台.exe` 并复制到项目根 |

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

### 9. 自定义场景后无人机飞得乱（频繁 SAFETY 介入）
- 原因（确定事实）：v2.1b 模型只在默认 100×10 + 双障碍分布上训练，换布局后策略失效，势场兜底频繁抢方向盘。
- 解决：`python main.py --train` 在新场景上重训（奖励已场景化：横向偏差 + 地图边界惩罚）；训练完成后评估验证。

### 10. 训练中途想停止 / 卡死恢复
- 停掉 python 进程即可（训练会自动保存最近 checkpoint 到 `models/drl_agent/`）。
- 无人机卡死恢复：关闭 UE → 重启 UE → 重新运行飞行脚本。

### 11. 城市导入失败（only N building(s) found / 网络超时 / “导入失败”）
- **only N building(s) found**：该范围内 OSM 建筑数据太少（＜3），把范围(m) 调大重试；或该区域本身就是空况，换预置城市。
- **网络超时/无法访问 Overpass**：安装网络后重试，或选 [缓存] 标识的城市（离线不需网络）。团队可用 `config/city_data/` 提前缓存后分发。
- **“A* unreachable”过密区域**：该范围建筑太密，调小范围或换中心点。

### 12. 随机生成报错“height_max 低于巡航高度” / 城市场景中无法随机添障碍
- 威胁带 = 巡航高度±2m；若高度范围全部低于“巡航-2m”，生成的障碍不会进避障列表，程序会拒绝并提示。
- 100×10 场景（巡航 12m）默认 10~16 可用；城市场景（巡航 20m）把高度范围改为 **18~26** 再生成。
- 悬浮障碍的垂直区间自动落在巡航高度±1.5m 附近，不需手动设 base_z。

### 13. 城市/悬浮场景飞行时 mode 为 GLOBAL / A* 而非 DRL（是否正常）
- 正常。城市场景默认 `use_drl=false`，统一由 A* 全局路径 + 势场安全网飞行；而不是 v2 的 DDPG 局部避障。如果你跟着 v2.1 手册以为必须看到 DRL 模式，请以场景中 `use_drl` 字段为准。


### 14. 地图底图不显示 / 地名搜索转圈（v4.1）

- 底图瓦片来自 OSM 公共瓦片，需联网；离线时地图区域为空白，但**经纬度手填 + 「用该点导入」仍可用**。
- 地名搜索 / 反查走 `nominatim.openstreetmap.org`，失败自动切 `photon.komoot.io`。本机实测 Nominatim 常超时（URLError 10060）：首次搜索约 8~12s，之后切到 Photon 约 1.5~2s（进程内记住可用源）。
- 若两者都不可达：已缓存城市（`config/city_data/`）仍可离线导入；未缓存过的坐标需联网。

---

### 15. 改了左侧经纬度/航程，右侧画布没反应（v5.1）

- 正常行为：改经纬度 / 范围(m) / 航程(m) / 走廊宽(m) / 贴图源后，右侧画布应在约 1 秒内重画为**该选区预览**，右下角状态栏显示「预览就绪 lat, lon」，侧栏 gisMsg 显示障碍数 / 建筑轮廓数 / A* 可达。
- 若一直不动：① 首次拉取要 10~60s（影像 + OSM + DEM），先看状态栏是否停在「预览中 …」；② 断网 / 离线模式下拉不到影像会提示「预览影像加载失败」；③ 预览只认 `geoLat` / `geoLon` 输入框和地图选点，若地图选点未成功（`pickSetMsg` 有报错）则经纬度为空、不会预览。
- 预览是**只读**的，不是已生成站点；点「生成真实场景」才写盘建 3D 瓦片。「重绘底图」只重画**当前已生成站点**的底图，不会按新经纬度重算——要按新经纬度重算，请点「刷新预览」或「生成真实场景」。

---

### 16. 点「刷新预览」一直转、建筑一栋都不出（或报 "Overpass ... 失败/超时"）（v5.6）

**先说结论**：这不是程序坏了，是公共 OSM 建筑服务器（Overpass）这一条链路的问题。影像和地形是另外两个源，通常正常。

- 现象：进度停在「等待 Overpass 建筑数据… 已等 N 秒」，最后画布只有影像 + 地形，红字提示不含建筑轮廓。
- 判断方法：控制台左栏「网络数据源自检」会逐个探数据源，能看出是哪个源不可达。
- **v5.6 已修的根因**：Overpass 镜像原先分两级串行请求，一级（法国站 / mail.ru）把 45 秒预算吃完后，二级（含本机唯一 1.5 秒可用的 `overpass-api.de`）根本没机会发请求。现在改成**所有镜像一次性并行发出、谁先返回有效结果用谁，失败还会再来一轮**。
- 现在还要等多久：新点位（没缓存过）通常 **3~25 秒**；已缓存点位 1~3 秒。等待时界面会显示「最长再等约 N 秒」。
- 还取不到怎么办：
  1. 点画布中央的「重试」（会先清后端的 Overpass 冷却再重刷；冷却默认 180 秒，期间直接跳过联网）。
  2. 到 ② 卡片勾上「跳过在线建筑轮廓」→ 预览只用真实影像 + 真实地形，秒出。
  3. 换网络 / 开代理后再点「刷新预览」，会自动补齐建筑。

### 17. 打开控制台后不知道该先点哪里（v5.6）

控制台左栏已按操作顺序排好，从上往下点即可：

1. **怎么用**：一句话说明。
2. **① 选场景**：下拉选场景 → 「打开场景编辑器」可改地图 / 路线 / 障碍。
3. **② 连接 Unreal Engine**：点「自动连接 UE」，它会启动 UE 并等 8990 端口（通常 1~3 分钟）；已经手动开着 UE 就点「只检查连接」。卡片里的状态行会直接告诉你"能不能起飞"。引擎路径 / 地图 / 启动参数在下面的折叠项里，一般不用改。
4. **③ 让无人机飞**：单次避障飞行 / 连续飞行。这一步需要 ② 已连接。
5. **不用 UE 也能做**：平滑度评估（纯 2D 仿真）、重新训练模型。
6. **运行控制**：停止当前任务。

## 7. 一页速查

```powershell
# 1. 启动 UE
"D:\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe" "D:/ProjectAirSim-main/unreal/Blocks 5.7/Blocks.uproject" GISMap -game -windowed -ResX=1280 -ResY=720

# 2. 等端口就绪
Test-NetConnection 127.0.0.1 -Port 8990 | Select-Object TcpTestSucceeded

# 3. 打开控制台（推荐：双击 AirSim控制台.exe；等价命令行）
python main.py                    # 弹出窗口：选场景、飞行、评估、重训都在按钮里

# 4. 自定义场景（可选）
python main.py --editor           # 弹窗内编辑器（或浏览器 http://127.0.0.1:8787），保存到 config/scenes/<name>.yaml

# 4.5 v4 城市 / 悬浮 / 随机（可选；也可在编辑器侧栏点按钮）
python worldgen.py city --preset manhattan_nyc          # 导入纽约-曼哈顿（离线缓存）
python worldgen.py random --scene config/scenes/scene_100x10.yaml --count 6 --floating 0.5
# 4.6 v4.1 全球任意地区（也可在编辑器侧栏「用该点导入」；任意经纬度无 CLI 参数，走网页或 API）
python worldgen.py city --place "Shanghai Bund" --extent 500

# 4.7 v5 真实地形 + 真实建筑（也可在编辑器侧栏「生成真实场景」/「真实场景」）
python gis_tiles.py build --lat 48.8584 --lon 2.2945 --extent 900
python gis_tiles.py info --site gis_48_85840_2_29450
python gis_tiles.py verify --site gis_48_85840_2_29450

# 5. 命令行直跑（指定场景或默认）
python main.py --scene config/scenes/scene_100x10.yaml --flights 3
python main.py --flights 3

# 6. 检查 UE 连接
python main.py --check

# 7. 平滑度复核（无需 UE）
python main.py --scene config/scenes/scene_100x10.yaml --eval

# 8. 训练（自定义布局后必须重训）
python main.py --scene config/scenes/你的场景.yaml --train

# 9. 轨迹可视化
python experiments/visualize_trajectory.py --csv logs/flights/flight_<时间戳>.csv
```

---
*如有异常行为，优先检查 UE 日志（Blocks.log）与飞行 CSV；技术细节见 docs/handover.md 11.11（v2.0 回弹）与 11.12（v2.1 平滑修复）。*