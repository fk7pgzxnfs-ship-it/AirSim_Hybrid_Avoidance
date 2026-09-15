# Changelog

版本记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 风格。日期依据 `docs/handover.md` 与文件时间戳（确定事实）。

## [v5.6] - 2026-09-15
### 里程碑
修掉「换个点位点刷新预览、等 45 秒后建筑一栋都不出」的根因（Overpass 镜像分级把本机唯一可用的镜像挡在 deadline 之外）；控制台左栏按实际操作顺序重排，UE 启动参数收进折叠区。

### 修复
- **Overpass 分级把可用镜像挡在门外（本次"刷不出来"的根因）**：`fetch_buildings()` 原实现把镜像分两级**串行**跑（一级 `overpass.openstreetmap.fr` + `maps.mail.ru`；二级 `overpass-api.de` + kumi + private.coffee），而 `deadline_s` 由一级独占。一级整体超时后，二级只剩不到 1 秒就被 `if left <= 1.0: break` 跳过，直接抛 `Overpass 全部镜像失败/超时(45s)`。**实测 2026-09-15：`overpass-api.de` 单独查询曼谷 1.49 秒就返回有效数据，却因为排在二级而永远没机会跑。** 现改为**单池并行 hedge**：主池 + 慢镜像一次性全部发出，谁先回有效结果就用谁（`_overpass_race` 本来就是这个语义）；再加**第二轮重复同一池**——公共镜像的慢多半是"这一刻正好在排队"。单次尝试上限 30 秒，给其它镜像留出顶上的时间。
- 删除本机 DNS 已解析不了 / 证书校验失败的镜像，避免每轮白等：`overpass-api.openstreetmap.de`、`overpass.osm24.eu`、`api.openstreetmap.fr/oapi`、`overpass.nchc.org.tw`、`overpass.zoom.earth`、`overpass.osm.rambler.ru`、`overpass.openstreetmap.ru`、`overpass.osm.jp`。
- Overpass 冷却期 600 秒 → 180 秒（`OVERPASS_COOLDOWN_S` 默认值）。
- 前端错误文案人话化：`RuntimeError: Overpass 全部镜像失败/超时(45s): ...`、`...冷却中（还剩 175 秒）` 这类 Python 异常原文不再直接贴给用户；新增 `humanGisErr()` 翻成「OSM 建筑服务器（Overpass）在 N 秒内没有返回有效数据」「本轮全部超时，程序正在冷却 N 秒；点「重试建筑数据」可立刻再试」等。
- 预览等待期加倒计时：新增 `peekEta()`，只在「等 OSM 建筑」这一段显示「最长再等约 N 秒；不想等就到 ② 勾「跳过在线建筑轮廓」」。其余步骤都是秒级，不打扰。
- 预览交互式取建筑的预算 45 秒 → 30 秒（前端 `peekBody()` 显式传 `buildings_deadline_s: 30`）。
- 「重试」按钮此前不清后端冷却，点了会立刻再失败一次，看起来像按钮坏了。新增 `POST /api/gis/overpass/retry`（清 `_OVP` 冷却），画布中央「重试」现在先清冷却再重刷。

### 变更
- `web/static/console.html` 左栏按操作顺序重排为：**怎么用（① 选场景 → ② 连 UE → ③ 起飞）/ 1 选场景 / 2 连接 Unreal Engine / 3 让无人机飞 / 不用 UE 也能做 / 运行控制**。原先把「场景 / 飞行（需 UE）/ 训练与评估（无需 UE）/ 系统 / UE 启动设置」五张卡平铺并列，其中「系统」里混着「停止当前任务」和「自动连接 UE」两个无关动作，新用户看不出先点哪个。
- 「UE 启动设置」（引擎路径 / 工程 / 地图 / 附加参数 / 最长等待秒数）收进 `<details>` 折叠，默认收起。
- ② 卡片新增实时状态行 `#ueCardMsg`：已连接 → 「8990 端口已就绪，可以去 ③ 起飞了」；启动中 → 「通常 1~3 分钟，可以先看右边日志」；未连接 → 「点下面的按钮自动启动工程；已经手动开着 UE 就点「只检查连接」」（附带上次报错）。`自动连接 UE` 按钮在已连接时置灰并显示「已连接 ✓」。

### 验证（确定事实，本轮实测）
- **修复前**（本机 2026-09-15，上一轮复现）：曼谷 13.7563/100.5018 → 0→48 秒卡在「等待 Overpass 建筑数据」，最终 `Overpass 全部镜像失败/超时(45s): 无响应`，结果只有影像 + 地形、0 栋建筑。
- **修复后** `fetch_buildings()`：曼谷 21.9s → **2966 栋**；柏林 52.52/13.405 17.4s → 527 栋；开罗 30.0444/31.2357 4.3s → 515 栋。
- **修复后端到端** `POST /api/gis/peek`（async + 轮询 `/api/gis/peek/status`，利马 -12.0464/-77.0428，全新未缓存）：19.5s 完成，`footprint_count=1463`、`buildings_ok=true`、`buildings_error` 为空。阶段耗时：DEM 采样约 8s、Overpass 约 3s、走廊 + A* + 渲染约 6s。
- 镜像可用性实测（本机可达的只有这几个）：`overpass-api.de` 1.49s / `overpass.openstreetmap.fr` 3.87s / `maps.mail.ru` 2.10s / `overpass.osm.ch` 1.74s（**区域限定，已排除，不能加**）；`overpass.kumi.systems`、`overpass.private.coffee` 20 秒无响应。
- 影像 / 地形源正常：ArcGIS World_Imagery 1.77s（10523 B）、AWS terrarium DEM 4.37s（104729 B）。
- 页面实测（Edge headless + CDP）：`/console` 渲染「怎么用 / 1 选场景 / 2 连接 Unreal Engine / 3 让无人机飞 / 不用 UE 也能做 / 运行控制 / 日志」7 张卡，`ueCardMsg` 正确显示「UE 已连接，8990 端口已就绪」，场景下拉 16 项，**无 JS 错误**（仅 favicon.ico 404）。`/`（场景编辑器）无 JS 错误，`humanGisErr` / `peekEta` / `retryGisPeek` 均已定义，`peekBody().buildings_deadline_s === 30`。
- 控制台内嵌编辑器 iframe 复核：切到「场景编辑器」标签页后 iframe 自动加载 `gis_-22_95190_-43_21050_RioCorcovado.yaml`（5 秒内 `readyState=complete`、`sceneName` 正确），**上一轮交接记录的"iframe 内不自动加载场景"本轮未能复现**。

### 已知限制
- Overpass 取建筑仍可能要 20 秒上下（取决于此刻哪个公共镜像空闲），这是上游排队时间，本地消不掉；预览里的 DEM 采样约 8 秒也还有优化空间。
- 「全球真实建筑」目前完全依赖 OSM / Overpass 这一条链路，本机可达的公共镜像只有 3 个；镜像全挂时只能降级成纯地形预览。
- 本文件缺少 v5.2 ~ v5.5 的条目（确定事实：`git`/文件里没有对应记录），本次只补 v5.6。

## [v5.1] - 2026-09-11
### 里程碑
修复「左侧改参数、右侧画布不变」；新增**实时预览**——左栏经纬度 / 航程 / 走廊 / 贴图源一改，右侧画布约 1 秒内换成该选区的**真实卫星影像 + 真实建筑轮廓 + 将要生成的走廊/起终点/障碍**，不必等到 3D 瓦片生成完。同时修正底图朝向。

### 新增
- `gis_tiles.py`：`peek_paths()` / `peek_plan()` / `peek_prune()`。`peek_plan` 复用与 `build_site` 同一套 `dem_sampler` / `fetch_buildings` / `build_planner_scene` / `render_topdown_image`，只算不写 3D 瓦片；结果缓存到 `config/gis_tiles/_peek/<16位md5>/`（`_topdown.png` + `_plan.json` + `_footprints.json`）。
- `web/gis_api.py`：`POST /api/gis/peek`（同步返回预览 JSON）、`GET /api/gis/peek.png?key=`（返回预览影像，`Cache-Control: no-store`）。
- `web/static/index.html`：新增预览态 `peekView`；`mapRect()` / `worldToScreen` / `screenToWorld` 在预览态按预览矩形缩放；`draw()` 的底图与建筑轮廓取自预览数据；画布左下角蓝色信息条显示「预览（未生成）: lat,lon / 走廊 / 障碍 / 建筑轮廓 / A* 可达」。左栏改动 → `markGisDirty()` → `schedulePeek(700ms)` 防抖 → 预览。新增按钮「刷新预览」（强制重算）。
- 画布编辑守卫：预览态下拖拽 / 双击不生效，提示先点「生成真实场景」。

### 变更
- 「用该点导入」（v4.1 的盒式近似路径）改名「生成真实场景（该点）」，改走 v5.0 GIS 3D 路径；旧 2D 盒式入口保留为「盒式导入」/「在线刷新」。
- 新增「真实场景」按钮：按预置城市下拉一键生成真实地形 + 真实建筑。
- 「重绘底图」语义澄清：只按**当前已生成站点**重画底图，不会按左栏新经纬度重算。

### 修复
- 底图 / 叠加层朝向：`draw()` 中影像用 `ctx.transform(0,-RH/iw,-RW/ih,0,x1,y1)` 铺满地图矩形，与 NED→屏幕映射（`screenX=x1-RW*v/ih`、`screenY=y1-RH*u/iw`）一致；修复前左右 / 上下反了。
- **航线方向 / 长度（GIS 场景，v5.0 遗留）**：`worldgen.choose_start_goal()` 原先只会沿 x 取起终点。GIS 场景 x=北、y=东，`auto_layout` 的 `orient="ew"` 表示走廊沿 y，于是航线被横着放在走廊宽度上——地图 160x600m 时实际航线只有 **144m**（应为 584m）。现新增 `axis` 参数（`"x"` 沿 x / `"y"` 沿 y），`build_planner_scene` 按 orient 传入；参数默认 `"x"`，v3/v4 行为不变。
- **空走廊 / 起终点跑出地图（GIS 场景，v5.0 遗留）**：`auto_layout` 原先只按「走廊内建筑数最多」取第一条候选，密集城区会选到没有任何自由车道的走廊 → `choose_start_goal` 返回 None → 触发回退分支把该走廊建筑**全部丢弃**（实测东京新宿 extent=800 得到 0 个障碍），且回退起终点被写死为 `y=0`，在南北向带偏移的走廊里落到地图矩形外。现改为按序尝试最多 24 条候选走廊、取第一条能真正选出起终点的；回退起终点改为取走廊中心线。
- `worldgen._a_star_ok()` 静音 `AStar.plan` 失败时的 `print`（可达性探测属内部行为；候选走廊重试会放大该噪声）。

### 验证（确定事实，本轮实测）
- `peek_plan(48.8584,2.2945,1200,600,160)` 首次 24.7s（障碍 128 / 建筑轮廓 997 / A* 可达，key `d3250ad8483aef2e`）；`peek_plan(39.9163,116.3972,...)` 首次 38.1s（障碍 257 / 轮廓 1501）。同参数第二次 0.023s 命中磁盘缓存；只把 `route_len_m` 改 900 时 2.0s（OSM/DEM 已缓存），`map.x_min/x_max` 变为 ±450。
- HTTP：`POST /api/gis/peek` → `ok=true`；`GET /api/gis/peek.png?key=d3250ad8483aef2e` → 200 image/png 275453 字节。
- 前端探针（Edge headless 加载真实页面，iframe 内改输入框）：把 `geoLat/geoLon` 改为 48.8584/2.2945 后画布哈希 294046 → 635674；再把 `gisRouteLen` 改成 900 → 69003；状态栏显示「预览就绪 48.8584, 2.2945」，gisMsg 显示「128 个障碍 / 997 栋真实建筑轮廓 / 走廊 600m x 160m / A* 可达（缓存）」→「120 个障碍 / 993 栋 … 900m x 160m」。**左改右变成立**。
- 朝向校验（同一 iframe，取画布像素 vs `_topdown.png` 像素，3x3 块均值、24x24 采样点）：当前实现 `sx=X1-RW*v, sy=Y1-RH*u` 中位差 **8.7**；水平镜像 65.8 / 垂直镜像 50.5 / 180° 57.0 / 不旋转 54.3 与 53.3。当前实现显著最优。
- 全球任意点实机生成：`POST /api/gis/build {lat:-22.9519, lon:-43.2105, extent_m:900, route_len_m:600, label:"RioCorcovado"}` → `gis_-22_95190_-43_21050_RioCorcovado`，57 瓦片 / 22.8MB / 32.4s；`home_alt_m=528.57`（DEM 实测海拔，非 0）、建筑轮廓 13、走廊内障碍 13、A* 可达；单个地形瓦片 64x64=4096 顶点 / 15876 三角面。证明南半球 + 西经坐标可正常取 DEM 地形与 OSM 建筑。
- 航线方向 / 空走廊修复后复测（`peek_plan` 直调，route_len_m=600）：巴黎埃菲尔 ext=1200 → orient=ns、start(-292,388)/goal(292,388)、航线 584m、起终点在地图内、障碍 128；东京新宿 ext=800 → orient=ew、start(450,-292)/goal(450,292)、航线 584m、障碍 **258**（修复前 0）；新宿 ext=1200 → 障碍 153；里约 ext=900 → 障碍 9；上海外滩 ext=900 → 障碍 41。**6/6 全部起终点落在地图矩形内、航线 584m（= 600 - 2×8m inset）**。
- 已生成 GIS 场景的航线长度复核：修复前 `gis_-22_95190_-43_21050_RioCorcovado.yaml` 与 `gis_35_69050_139_69990_Shinjuku.yaml` 均为 `orient=ew`、地图 160x600m、航线 **144m**；两个站点已按修复后算法重建。

### 未执行 / 限制（不确定信息）
- 未在 UE 实机加载过 v5.0 / v5.1 生成的 GIS 场景（`CustomGIS` + `AGISRenderer` 消费路径只在代码层核对，未跑通）。
- `_peek` 缓存每 key 约 630KB；已加 `peek_prune()`（保留最近 12 个 + 48h TTL，写入新预览时触发，命中时 touch），未做手动清理入口。
- 城市场景默认 `use_drl=false`（DRL 模型泛化不足），避障由 A* + 势场负责。
- 预览影像长边上限 1000px（`width=1000`），extent > 2000m 时清晰度不足。
- 候选走廊重试最多 24 条，密集城区每次预览会多跑数十次 A* 探测（实测新宿 ext=1200 预览约 17s，其中 OSM/DEM 已缓存）；`_peek` 缓存键已加算法版本前缀 `v2`，算法再改需同步 +1 否则旧预览会与新建站点不一致。

## [v5.0] - 2026-09-11
### 里程碑
全球任意地区**真实地形 + 真实建筑**三维场景：按经纬度生成 Project AirSim `CustomGIS` 场景所需的 quadkey glTF 瓦片（DEM 三角网地形 + OSM 建筑挤出 + 卫星影像贴图），UE 端由 `AGISRenderer` 加载。不再走 v4 的「盒式障碍近似」。

### 数据来源（均可公开访问，选型说明）
- 地形 DEM：AWS Terrain Tiles (terrarium) `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`
- 影像：Esri World Imagery / World_Topo_Map
- 建筑：OpenStreetMap Overpass (`overpass-api.de` / `kumi.systems` / `private.coffee` 多镜像)
- 地名：Photon（本机 Nominatim 不可达时自动备选）

### 新增
- `gis_tiles.py`：`dem_sampler` / `fetch_buildings` / `build_terrain` / `add_building` / `write_glb` / `build_site` / `build_planner_scene` / `render_topdown_image` / `build_preview` / `verify_site`，以及 CLI（`build` / `info` / `verify` / `preview` / `buildings`）。
- 瓦片契约按 Project AirSim 源码实现：`<quadkey>.glb`、单 mesh 单 primitive、POSITION 为 ECEF 米、必须含 `TEXCOORD_0` 与 indices、image0 为 RGBA PNG。
- `scene_config.py`：`SceneConfig.is_gis` / `gis` 字段 / `_to_ue_gis_dict()` / `dump_ue_scene()` 输出 `CustomGIS`。
- `web/gis_api.py`：`POST /api/gis/build`（后台线程 + 进度）、`GET /api/gis/status`、`/api/gis/sites`、`/api/gis/topdown.png`、`/api/gis/footprints`、`/api/gis/load`、`/api/gis/preview`。
- 编辑器新增 GIS 面板（范围 / 航程 / 走廊宽 / 贴图源 / 离线模式 / 站点列表 / 顶视预览）。

### 验证（确定事实）
- 已生成站点（`config/gis_tiles/`）：巴黎埃菲尔（9 瓦片 / 5.4MB / 164 建筑 / 67 障碍）、东京新宿（41 瓦片 / 16.2MB / 1415 建筑 / 382 障碍）、上海外滩（50 瓦片 / 16.7MB / 142 建筑）、里约科科瓦多（57 瓦片 / 22.8MB / 13 建筑 / 13 障碍，`home_alt_m=528.57`，v5.1 期生成）。
- 全部 `.py` `py_compile` 通过。

### 未执行 / 限制（不确定信息）
- UE 实机未加载验证。
- 生成耗时随建筑密度上升：新宿 900m 数分钟，郊区 / 山地 30s 级。

## [v4.1] - 2026-09-10
### 里程碑
全球任意地区**地图选点导入**：在弹窗编辑器内嵌 OSM 世界地图，点任意位置/拖动标记选点，或按地名搜索候选后定位，再输入范围(m) 一键导入该点周边真实建筑。相当于把 v4.0 的“10 个预置城市”扩展到“全球任意坐标”。

### 新增
- **地理检索备选源** `worldgen.py`：`geocode_candidates()` 默认按 **Nominatim → Photon（Komoot，也是 OSM 数据、无需 key）**依次尝试，并记住上一次成功的源（`_GEO_HINT`），后续请求直接走可用源；`reverse_geocode()` 同样双源。
- **API** `web/app.py`：`GET /api/geo/search?q=&limit=&provider=`（候选列表）、`GET /api/geo/reverse?lat=&lon=`（坐标反查地名）；`/api/geo/import` 新增 `label`（场景名称使用用户选中的地名）；`import_city()` 新增 `label` 参数。
- **编辑器 UI** `web/static/index.html`：侧栏新增「v4.1 全球任意地区（地图选点）」——Leaflet + OSM 底图、点击选点/可拖拽标记/范围圆、纬经度手填、地名搜索候选下拉、反查地名、「用该点导入」。`startGeoImport(refresh, override)` 支持直接传坐标。
- 底图不可用（离线/CDN 不可达）时自动降级：仍可手填纬经度或用地名搜索导入，不会白屏。

### 变更
- 版本标识 v4 → v4.1（窗口标题、页面 title、main.py 横幅）；预设城市面板保留，新增独立“地图选点”面板（两者共用同一导入/轮询/画布流程）。
- 检索超时：地址搜索 8s、反查 8s（原 30s），避免不可达源长时间卡住界面。

### 验证（确定事实，本轮实测）
- 开发机当前访问 `nominatim.openstreetmap.org` 超时（URLError 10060），Photon 备选可达：`/api/geo/search?q=新宿` 返回 3 个候选（新宿、四谷、新宿駅）；`?q=Shanghai Bund` 首次 10.0s（Nominatim 超时后切 Photon），第二次 1.7s（命中源记忆）。
- `/api/geo/reverse?lat=31.2397&lon=121.49` 首次 12.4s、第二次 1.5s，返回“外滩观光隧道, 外滩街道, 黄浦区, 上海市, 中国”。
- **任意坐标导入成功**：`POST /api/geo/import {lat:31.2397, lon:121.49, extent_m:500, label:"Shanghai Bund"}` → `City_geo_31.23970_121.49000`，obs=3，route=astar，use_drl=false，自动缓存 `config/city_data/geo_*.json`（测试后已清理）。
- 全量 .py `py_compile` 通过（69 个文件、0 失败）；exe 重打包（71MB）后实机冒烟：启动后 8787 就绪，`/` 200 且含 `mapPick` / `btnGeoPickImport` / Leaflet 与 v4.1 标识，`/console` 200 且标题为 `AirSim v4.1 控制台`，`/api/geo/presets` 返回 10 个预置（7 个有离线缓存），`/api/geo/search?q=Tokyo` 200（2.7s、3 条结果，走 Photon）。
- 文档同步：`README.md`（顶部 v4.1 说明 + 快速开始改为 v4.1 + 版本历史表新增 v4.1 行）、`docs/USER_GUIDE.md`（标题与适用版本、新增「步骤 2.7 全球任意地区地图选点」、CLI 表新增 geo API 行、快捷命令 4.6、FAQ 14）。

### 未执行 / 限制（不确定信息）
- 地图底图使用 OSM 公共瓦片（需联网，仅交互式少量加载，遵循 OSM 瓦片使用政策）；未做离线底图/自建瓦片服务。
- Nominatim 使用政策要求 ≤1 req/s；界面为按钮手动触发，未做服务端限流（本地单用户场景足够）。
- 导入依赖 Overpass；若 Overpass 不可达，已缓存城市仍可离线导入，未缓存坐标则不可用。

## [v4.0] - 2026-09-10
### 里程碑
弹窗编辑器新增三项 v4 能力：① **真实城市一键导入**（全球预置城市 + OSM 建筑数据，首次在线拉取后离线缓存复用）；② **悬浮障碍物**（障碍物增加离地高度 `base_z`，画布蓝色虚线显示）；③ **随机障碍物生成器**（可配悬浮比例/尺寸/高度/种子，自动 A* 可达性校验，不可达时回退新增障碍）。
场景边界从 v2/v3 的“100×10 走廊”扩展到任意尺寸的“真实街区布局”；城市场景默认 `use_drl: false`，走 A* + 势场，不依赖已有模型，免重训即可飞行。

### 数据来源选型（工程权衡，不走边理论）
- 任务提及 NASA DEM。经评估：本项目避障语义是“固定巡航高度下的二维横向绕飞 + 盒式障碍物”，UE Blocks 无法加载真实地形高程网格；DEM 提供地表高程而非城市障碍，与 12~20m 巡航平面避障不直接匹配。
- v4 改用 **OpenStreetMap（OSM）建筑足印**（Overpass API，10 个预置城市 + Nominatim 地名检索）：建筑足印转 AABB 盒（高度启发式：height/building:height/levels×3 → clamp 3~90m），直接可被 A*/碰撞/控制器/UE LoadScene 使用。首次成功拉取后缓存 `config/city_data/<id>.json`，后续可离线复用。
- 实际城市大小地图使用等角直角投影近似（lonOffset×111320×cosφ、latOffset×110540），建筑简化为盒体近似；这些是设计上的近似，不是 OSM 数据本身的精度保证。

### 新增
- **数据层** `scene_config.py`：`Obstacle` 新增 `base_z`（离地高度）与 `kind`（column/floating/building），`alt_range_m`/`blocks_altitude`（威胁带 = 巡航高度± margin，默认 12m±2m = [10,14]m）；`SceneConfig` 新增 `altitude_margin`/`use_drl`/`geo`；`obstacles_plan/physical` 只返回与巡航高度相交的障碍；`to_ue_dict` 对悬浮物按“底部 base_z + 高度/2 → 反转 NED z”写入 UE actor；`to_preview` 悬浮=蓝色虚线、建筑=灰色不标注名称。
- **场景生成器** `worldgen.py`（项目根新文件）：
  - 预置城市 10 个（纽约/旧金山/东京/伦敦/巴黎/香港/新加坡/芝加哥/悉尼/柏林），路线默认 A* 自动选起始/目标点（中间车道优先，不达时清除直线走廊建筑）；
  - `random_obstacles()`：在当前场景边界内采样落地柱/悬浮物（悬浮默认垂直区间落在巡航高度±1.5m 附近），不压起终点/不重叠，A* 不可达时自动回退新增障碍；
  - CLI：`worldgen.py city --preset <id> [--extent m] [--refresh] [--offline]`、`worldgen.py random --scene <yaml> [--floating 0.3 ...]`、`worldgen.py fix --preset <id>`（离线去重+重选起终点）。
- **城市离线缓存** `config/city_data/`（已隨仓库 7 个：manhattan_nyc/tokyo_shinjuku/london_city/hongkong_cwb/singapore_raffles/sanfran_financial/chicago_loop），对应场景 `config/scenes/city_*.yaml`；未缓存预设（巴黎/悉尼/柏林）需在线拉取。
- **Flask API** `web/app.py`：`GET /api/geo/presets`（含 cached 标识）、`POST /api/geo/import`（后台线程）、`GET /api/geo/status`（进度轮询）、`POST /api/obstacles/random`（同步 A* 可达性校验）；场景保存改用 `SceneConfig.to_yaml`（修复此前 yaml 保存失败）。
- **编辑器 UI** `web/static/index.html`：侧栏顶部新增「真实城市一键导入」与「随机生成障碍物」面板；障碍物列表增加离地高度输入（>0 自动为悬浮）；画布悬浮蓝色虚线/`[7,5]`；城市导入完成自动加载到画布可保存。
- **控制器闭环** `hybrid_controller/supervisor.py`：遵守 `scene.use_drl`，为 false 时不加载 DRL Agent，全程 A*/势场路径。
- **示例与图**：`config/scenes/scene_v4_floating_demo.yaml`（悬浮下方 8.5~11.5m + 悬浮上方 13.5~15.5m + 落地柱 0~14m）；`docs/scene_preview_*.png` 3 张（悬浮 demo / 伦敦 / 纽约）。

### 变更
- 全站版本标识升级 v4（窗口标题、页面 title、main.py 字段、文档）；悬浮语义在代码注释/UI tooltip 明确：“垂直区间触及巡航高度±2m 才会被计为避障威胁”。
- 城市场景默认参数：`route.mode=astar`、`use_drl=false`、`takeoff_height=-20`（巡航 20m）、`resolution=1.0`；建筑相互重叠不再报错（足印近似原因）。
- `worldgen.py`地名检索默认改为公共 Nominatim；Overpass 主服务不稳定时自动切换备用镜像（移除证书不匹配的节点）。

### 修复
- `Obstacle` 序列化补上 `base_z`/`kind`（此前进入 to_dict/from_dict 时丢失）；`SceneConfig.to_yaml` 独立实现（此前 dump 路径存在历史错位死代码，导致保存失败）。
- `worldgen.random_obstacles`：当运算时发现不可达时改为从最后一个新增障碍开始回退，而不是直接报错（保留原场景布局）。
- 起始/目标点落在障碍物上的校验改为按物理半径判断；城市导入场景随便打开/保存再不出错。
- **exe 冻结模式下 `/` 与 `/console` 404（本轮打包冒烟发现）**：`index()`/`console_page()` 原用 `send_from_directory("static", ...)`，相对路径按 Flask `root_path` 解析；PyInstaller onefile 下 `root_path` 指向临时解包目录（无 web/static），导致弹窗白页。改为绝对路径 `ROOT/web/static`（exe 旁的数据目录）后正常。

### 验证（确定事实）
- 内置 10 个场景全部 `SceneConfig.validate() == []`（7 个城市 + scene_100x10/scene_test_120x16/scene_v4_floating_demo）；7 个城市场景 `_a_star_ok == True`，起点均在边界 x_min+8。城市障碍数（最新离线 fix 后）：manhattan 12 / tokyo 57 / london 34 / hongkong 16 / singapore 8 / sanfran 34 / chicago 40；场景范围约 380~580m，res=1.0。
- 悬浮 demo：`scene_v4_floating_demo.yaml`生成并读回保存，3 个障碍均进避障列（`blocking_obstacles`），A* 可达。
- Flask smoke（本地 python dev server）：`/api/geo/presets` 返回 10 个预设 + cached 标识；`POST /api/obstacles/random`（floating=0.5）返回 8 个障碍且可达；离线城市导入 manhattan 返回 City_manhattan_nyc；yaml 保存/读回保留 `base_z=10`。
- 65 个 .py 全部 `py_compile` 通过；Flask 端到端 smoke（make_server + HTTP）：`/` `/console` `/api/geo/presets` 200，`POST /api/obstacles/random`（floating 0.5）返回 10 个障碍（4 悬浮），离线城市导入 manhattan 返回 City_manhattan_nyc（obs=12、route=astar、use_drl=false），yaml 保存读回保留 base_z。
- exe 重打（71MB）后实际启动冒烟：程序启动后 8787 就绪；`/api/geo/presets` 返回 10 预设（7 缓存）；`/console` 200 且标题为 AirSim v4；`/` 200 且含 geoPreset 面板；提前终止后 8787 释放。

### 未执行 / 限制（不确定信息）
- 未做 DRL domain-randomization 重训（在任意起终点/障碍布局下训练泛化模型）；城市场景默认关 DRL 为故意设计，非遗漏。
- 悬浮/城市场景的真实 UE 飞行未在本轮执行（避免占用重资源）；场景生成与 A*可达性已确认，但等价地上 UE 冲突/UActor 排布还需在真实 UE 中冒烟。
- 巴黎/悉尼/柏林无离线缓存，缺网环境下无法导入；Overpass 在线稳定性、建筑高度启发式均为近似。

## [v3.1] - 2026-09-09
### 里程碑
场景编辑器集成进 Windows 原生弹窗（顶部「控制台 / 场景编辑器」标签页切换，窗口内直接拖拽编辑场景并保存）；弹窗新增「自动连接 UE」——一键启动 UE 进程并自动等待端口 8990，不再需要手动敲命令启动 UE。

### 新增
- **编辑器集成进弹窗**：console 页面顶部标签页懒加载 iframe 内嵌原网页编辑器（`/`），原「打开网页编辑器（新标签页）」按钮改为窗口内切换；切回控制台自动刷新场景列表。
- **自动连接 UE（后端）** `web/app.py`：
  - `POST /api/ue/start`：校验引擎/工程路径后启动 UE（`UnrealEditor.exe <uproject> GISMap -game -windowed -ResX=1280 -ResY=720`），后台线程轮询直至 8990 可连或超时；
  - `POST /api/ue/stop` 停止 UE 进程；`GET/POST /api/ue/config` 读写 UE 启动配置；
  - `GET /api/ue` 返回连接/启动/错误状态；`/api/status` 新增 `ue_launching` / `ue_error` 字段供轮询。
- **UE 启动配置** `config/ue_launch.json`：engine_exe / project / map / extra_args / wait_seconds（默认 180s）；弹窗「系统 → UE 启动设置」可在线修改保存。
- **控制台 UI**：顶栏 UE 状态胶囊旁新增「自动连接 UE」按钮（启动中/已连接自动禁用）；日志区输出启动过程；错误（引擎不存在、启动失败、等待超时）直接提示。

### 变更
- 弹窗默认尺寸 1280x820 → 1360x860（最小 1080x700）；窗口标题 v3.1。
- 场景编辑器按钮行为：不再新开浏览器标签页，改为窗口内标签页切换。

### 验证（确定事实）
- Flask test client：`/` `/console` `/api/status` `/api/ue/config` `/api/ue` 全部 200；`/api/status` 含 `ue_launching`/`ue_error`。
- 启动状态机（以本机 python 模拟 UE 进程）：`/api/ue/start` 200 → `launching/proc_alive=true`（`/api/status.ue_launching=true`）→ `/api/ue/stop` 200 → 全部复位。
- 错误路径：引擎路径不存在时 `/api/ue/start` 返回 400 并提示在「系统」或 `config/ue_launch.json` 修改。
- 配置保存/恢复正常；64 个 .py 全部 py_compile 通过。
- **未执行项（不确定信息）**：真实 UE 启动未在本轮执行（避免占用重资源）；本机 `D:\UE_5.7\...\UnrealEditor.exe` 与 `Blocks.uproject` 已确认存在，默认配置可直接使用。
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
