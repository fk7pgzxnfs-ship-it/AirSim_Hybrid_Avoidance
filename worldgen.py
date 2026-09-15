# -*- coding: utf-8 -*-
"""worldgen.py - v4 场景生成器（随机障碍 + 真实城市一键导入）

功能:
  * 随机障碍物：地图内随机撒点，支持落地柱/悬浮物混合、替换/追加、可达性校验
  * 真实城市导入：按预设或地名(纬度/经度)拉取 OSM 建筑足印 -> 轴对齐盒式建筑集合
    -> 自动生成地图边界与起终点，缓存到 config/city_data/*.json 供离线复用

限制(确定性事实):
  * UE Blocks 5.7 的 LoadScene 只能表达盒式环境物体，无法加载真实地形网格，
    因此"真实城市"= 建筑盒式近似（足印轴对齐外接矩形 + 楼层高度），
    不做 NASA DEM 曲面；逐栋外接矩形会略大于真实轮廓。
  * 本仓库 2D 规划/DRL 把障碍物近似成圆，街区间距很窄时可达性会自动裁剪部分
    建筑(见 trim_buildings_to_reachable)，飞行建议 use_drl:false + astar。
"""
import os
import sys
import io
import json
import math
import random
import time
import argparse
import urllib.parse
import urllib.request

from scene_config import SceneConfig, Obstacle

ROOT = os.environ.get("AIRSIM_ROOT") or os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "config", "city_data")
DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
DEFAULT_NOMINATIM = "https://nominatim.openstreetmap.org/search"
DEFAULT_NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
# Nominatim 在部分网络环境下不可达时的备选地理编码源（无需 API key）
DEFAULT_PHOTON = "https://photon.komoot.io/api/"
DEFAULT_PHOTON_REVERSE = "https://photon.komoot.io/reverse"
# 记住上一次成功的检索源，避免每次都在不可达的源上等待超时
_GEO_HINT = {"search": None, "reverse": None}
USER_AGENT = "AirSimHybridAvoidance/4.0 (local demo)"

# 预置全球城市样例（中心点 + 建议范围）。在线导入走 OSM 建筑数据；
# 首次成功会缓存到 config/city_data，之后可离线一键复用。
PRESETS = [
    {"id": "manhattan_nyc", "name": "纽约-曼哈顿(美)", "lat": 40.7527, "lon": -73.9772, "extent_m": 550},
    {"id": "sanfran_financial", "name": "旧金山-金融区(美)", "lat": 37.7928, "lon": -122.4015, "extent_m": 550},
    {"id": "tokyo_shinjuku", "name": "东京-新宿(日)", "lat": 35.6905, "lon": 139.6999, "extent_m": 650},
    {"id": "london_city", "name": "伦敦-金融城(英)", "lat": 51.5145, "lon": -0.0920, "extent_m": 600},
    {"id": "paris_centrum", "name": "巴黎-歌剧院(法)", "lat": 48.8698, "lon": 2.3340, "extent_m": 600},
    {"id": "hongkong_cwb", "name": "香港-湾仔(中)", "lat": 22.2812, "lon": 114.1824, "extent_m": 550},
    {"id": "singapore_raffles", "name": "新加坡-莱佛士(新)", "lat": 1.2860, "lon": 103.8510, "extent_m": 550},
    {"id": "chicago_loop", "name": "芝加哥-卢普区(美)", "lat": 41.8795, "lon": -87.6295, "extent_m": 600},
    {"id": "sydney_cbd", "name": "悉尼-CBD(澳)", "lat": -33.8688, "lon": 151.2093, "extent_m": 600},
    {"id": "berlin_mitte", "name": "柏林-米特区(德)", "lat": 52.5200, "lon": 13.4050, "extent_m": 600},
]

def cache_path(city_key):
    safe = "".join(c for c in str(city_key or "city") if c.isalnum() or c in "-_")
    return os.path.join(CACHE_DIR, safe + ".json")
def _http_json(url, data=None, timeout=45, method=None):
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def _nominatim_search(place, limit=6, timeout=15):
    q = urllib.parse.urlencode({"q": place, "format": "jsonv2",
                                "limit": int(limit)})
    rows = _http_json(DEFAULT_NOMINATIM + "?" + q, timeout=timeout)
    out = []
    for r in rows or []:
        try:
            out.append({"name": r.get("display_name") or place,
                        "lat": float(r["lat"]), "lon": float(r["lon"]),
                        "type": r.get("type", "")})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _photon_search(place, limit=6, timeout=15):
    """Photon（Komoot，基于 OSM）备选检索；部分网络下 Nominatim 不可达时使用"""
    q = urllib.parse.urlencode({"q": place, "limit": int(limit)})
    d = _http_json(DEFAULT_PHOTON + "?" + q, timeout=timeout)
    out = []
    for f in (d or {}).get("features", []):
        props = f.get("properties") or {}
        coords = ((f.get("geometry") or {}).get("coordinates") or [])
        if len(coords) < 2:
            continue
        parts = [props.get(k) for k in
                 ("street", "district", "city", "state", "country") if props.get(k)]
        label = ", ".join([x for x in [props.get("name")] + parts if x]) or place
        out.append({"name": label, "lat": float(coords[1]), "lon": float(coords[0]),
                    "type": props.get("osm_value") or props.get("type") or ""})
    return out


def geocode_candidates(place, limit=6, endpoint=None, provider=None, timeout=15):
    """地名 -> 候选列表 [{"name","lat","lon","type"}, ...]

    用于界面上的"选一个正确的地方"，而不是盲取第一条。
    默认按 Nominatim -> Photon 依次尝试（两源均为 OSM 数据、无需 key）。
    注意：Nominatim 使用政策要求 <=1 req/s 且带 User-Agent（本模块已带）。
    """
    _SEARCH_FNS = {"nominatim": lambda: _nominatim_search(place, limit, timeout),
                   "photon": lambda: _photon_search(place, limit, timeout)}
    if endpoint:
        providers = [("custom", lambda: _nominatim_search(place, limit, timeout))]
    elif provider in _SEARCH_FNS:
        providers = [(provider, _SEARCH_FNS[provider])]
    else:
        order = ["nominatim", "photon"]
        hint = _GEO_HINT.get("search")
        if hint in order:
            order.remove(hint)
            order.insert(0, hint)
        providers = [(name, _SEARCH_FNS[name]) for name in order]
    last_err = None
    for name, fn in providers:
        try:
            out = fn()
            if out:
                _GEO_HINT["search"] = name
                return out
        except Exception as exc:
            last_err = "%s: %s" % (name, exc)
            continue
    raise RuntimeError("geocode not found: %s (%s)" % (place, last_err))


def geocode(place):
    """OSM Nominatim 地名 -> (lat, lon, display_name)（取最优候选）"""
    best = geocode_candidates(place, limit=1)[0]
    return best["lat"], best["lon"], best["name"]


def reverse_geocode(lat, lon, endpoint=None, timeout=15):
    """坐标 -> 地名（Nominatim 优先，Photon 兜底；用于地图选点后的"这是什么地方"）"""
    lat, lon = float(lat), float(lon)
    if _GEO_HINT.get("reverse") == "photon":
        q0 = urllib.parse.urlencode({"lat": "%.6f" % lat, "lon": "%.6f" % lon})
        d0 = _http_json(DEFAULT_PHOTON_REVERSE + "?" + q0, timeout=timeout)
        f0 = (d0 or {}).get("features") or []
        p0 = (f0[0].get("properties") if f0 else None) or {}
        parts0 = [p0.get(k) for k in
                  ("name", "street", "district", "city", "state", "country") if p0.get(k)]
        if parts0:
            return ", ".join(parts0)
    try:
        q = urllib.parse.urlencode({"lat": "%.6f" % lat, "lon": "%.6f" % lon,
                                    "format": "jsonv2"})
        d = _http_json((endpoint or DEFAULT_NOMINATIM_REVERSE) + "?" + q, timeout=timeout)
        name = (d or {}).get("display_name") if isinstance(d, dict) else None
        if name:
            _GEO_HINT["reverse"] = "nominatim"
            return name
    except Exception:
        if _GEO_HINT.get("reverse") == "nominatim":
            _GEO_HINT["reverse"] = None
    q = urllib.parse.urlencode({"lat": "%.6f" % lat, "lon": "%.6f" % lon})
    d = _http_json(DEFAULT_PHOTON_REVERSE + "?" + q, timeout=timeout)
    feats = (d or {}).get("features") or []
    props = (feats[0].get("properties") if feats else None) or {}
    parts = [props.get(k) for k in
             ("name", "street", "district", "city", "state", "country") if props.get(k)]
    if not parts:
        raise RuntimeError("reverse geocode empty (lat=%.5f lon=%.5f)" % (lat, lon))
    _GEO_HINT["reverse"] = "photon"
    return ", ".join(parts)


def _tag_height(tags, default_h=12.0, min_h=3.0, max_h=90.0):
    raw = None
    for key in ("height", "building:height", "est_height"):
        if key in tags and tags[key]:
            raw = str(tags[key])
            break
    if raw is not None:
        num = "".join(ch for ch in raw.split()[0] if ch.isdigit() or ch in ".")
        try:
            h = float(num)
        except (TypeError, ValueError):
            h = None
        if h and h > 0:
            return max(min_h, min(max_h, h))
    levels = tags.get("building:levels") or tags.get("building:levels:aboveground")
    if levels:
        try:
            return max(min_h, min(max_h, float(levels) * 3.0))
        except (TypeError, ValueError):
            pass
    return default_h


def fetch_buildings_elements(lat, lon, extent_m, endpoint=None, timeout=45):
    """Overpass 拉取方框内 building way 列表（way 几何为 lat/lon 点序列）"""
    half_m = extent_m / 2.0
    dlat = half_m / 110540.0
    dlon = half_m / (111320.0 * math.cos(math.radians(lat)))
    south, north = lat - dlat, lat + dlat
    west, east = lon - dlon, lon + dlon
    query = ("[out:json][timeout:%d];way[\"building\"](%.7f,%.7f,%.7f,%.7f);"
             "out tags geom;" % (int(timeout), south, west, north, east))
    candidates = [endpoint] if endpoint else [
        DEFAULT_ENDPOINT,
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ]
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_err = None
    for url in candidates:
        try:
            return _http_json(url, data=data, timeout=timeout).get("elements", [])
        except Exception as exc:
            last_err = "%s: %s" % (url, exc)
            continue
    raise RuntimeError("Overpass 拉取失败（已尝试多个镜像）: %s" % last_err)


def _dedupe_building_boxes(obstacles):
    """把互相重叠/贴墙的盒式建筑合并为街区块（保留体积、保持街道净空）

    OSM 中连排建筑与 building:part 常共享/交叠边界：直接丢弃会丢楼体，
    这里采用 AABB 迭代并集，同一街区的建筑合并成一个更大的盒式地块。
    """
    boxes = sorted(obstacles, key=lambda o: o.w * o.h, reverse=True)
    changed = True
    guard = 0
    while changed and guard < 400:
        guard += 1
        changed = False
        for i in range(len(boxes)):
            a = boxes[i]
            for j in range(i + 1, len(boxes)):
                b = boxes[j]
                if (abs(a.x - b.x) < (a.w + b.w) / 2.0 - 0.4 and
                        abs(a.y - b.y) < (a.h + b.h) / 2.0 - 0.4):
                    mw = max(a.x + a.w / 2.0, b.x + b.w / 2.0) - min(a.x - a.w / 2.0, b.x - b.w / 2.0)
                    mh = max(a.y + a.h / 2.0, b.y + b.h / 2.0) - min(a.y - a.h / 2.0, b.y - b.h / 2.0)
                    if mw > 90.0 or mh > 90.0:
                        continue
                    x0 = min(a.x - a.w / 2.0, b.x - b.w / 2.0)
                    x1 = max(a.x + a.w / 2.0, b.x + b.w / 2.0)
                    y0 = min(a.y - a.h / 2.0, b.y - b.h / 2.0)
                    y1 = max(a.y + a.h / 2.0, b.y + b.h / 2.0)
                    merged = Obstacle(
                        name=a.name, x=(x0 + x1) / 2.0, y=(y0 + y1) / 2.0,
                        w=x1 - x0, h=y1 - y0, height=max(a.height, b.height),
                        base_z=0.0, kind="building")
                    boxes[i] = merged
                    del boxes[j]
                    changed = True
                    break
            if changed:
                break
    return boxes


def elements_to_obstacles(elements, lat, lon, min_area=20.0, default_h=12.0,
                          min_h=3.0, max_h=90.0, max_side=140.0, prefix="B"):
    """建筑 way -> 本地米制轴对齐盒式障碍。坐标：x=东(米) y=北(米)，原点=查询中心"""
    coslat = math.cos(math.radians(lat))
    out = []
    idx = 0
    for e in elements:
        geom = e.get("geometry") or []
        if len(geom) < 3:
            continue
        xs, ys = [], []
        for p in geom:
            px = (float(p["lon"]) - lon) * 111320.0 * coslat
            py = (float(p["lat"]) - lat) * 110540.0
            xs.append(px)
            ys.append(py)
        if not xs:
            continue
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w, h = x1 - x0, y1 - y0
        if w < 2.0 or h < 2.0 or w * h < min_area:
            continue
        if w > max_side or h > max_side:
            w = min(w, max_side)
            h = min(h, max_side)
        tags = e.get("tags") or {}
        height = _tag_height(tags, default_h=default_h, min_h=min_h, max_h=max_h)
        idx += 1
        out.append(Obstacle(
            name="%s%03d" % (prefix, idx),
            x=(x0 + x1) / 2.0,
            y=(y0 + y1) / 2.0,
            w=w, h=h, height=height,
            base_z=0.0,
            kind="building",
        ))
    return _dedupe_building_boxes(out)

def _segment_hits_rect(p0, p1, o, inflate=0.0):
    """直线段是否与矩形（外扩 inflate）相交（用于选航向走廊/清障）"""
    hw, hh = o.w / 2.0 + inflate, o.h / 2.0 + inflate
    x0, x1 = min(p0[0], p1[0]), max(p0[0], p1[0])
    y0, y1 = min(p0[1], p1[1]), max(p0[1], p1[1])
    if x1 < o.x - hw or x0 > o.x + hw or y1 < o.y - hh or y0 > o.y + hh:
        return False
    # 段穿过矩形：轴对齐快速判定，矩形内任一点在段两侧不行则再检查端点/交点
    if (p0[0] - o.x) * (p1[1] - o.y) - (p0[1] - o.y) * (p1[0] - o.x) == 0:
        return True
    for px, py in (p0, p1):
        if o.x - hw <= px <= o.x + hw and o.y - hh <= py <= o.y + hh:
            return True
    # 与矩形四边求交（粗略）
    seg_dx, seg_dy = p1[0] - p0[0], p1[1] - p0[1]
    for cx, cy, w2, h2 in ((o.x, o.y, hw, hh),):
        if seg_dx == 0:
            if abs(p0[0] - o.x) <= hw and y0 <= o.y + hh and y1 >= o.y - hh:
                return True
            return False
        if seg_dy == 0:
            if abs(p0[1] - o.y) <= hh and x0 <= o.x + hw and x1 >= o.x - hw:
                return True
            return False
        for yy in (o.y - hh, o.y + hh):
            tt = (yy - p0[1]) / seg_dy
            if 0 <= tt <= 1 and abs(p0[0] + seg_dx * tt - o.x) <= w2:
                return True
        for xx in (o.x - hw, o.x + hw):
            tt = (xx - p0[0]) / seg_dx
            if 0 <= tt <= 1 and abs(p0[1] + seg_dy * tt - o.y) <= h2:
                return True
    return False


def _point_free(obs, x, y, margin=3.0):
    for o in obs:
        if (abs(x - o.x) <= o.w / 2.0 + margin and
                abs(y - o.y) <= o.h / 2.0 + margin):
            return False
        if math.hypot(x - o.x, y - o.y) <= o.plan_radius + margin:
            return False
    return True


def build_probe_grid(obstacles, x_min, x_max, y_min, y_max, res):
    """把障碍物栅格化一次，供同一走廊内的多次可达性探测复用。

    栅格内容只取决于障碍物与走廊范围，和起终点无关，因此可以复用；
    复用与否不改变任何一次探测的判据。
    """
    from planning.grid_map import GridMap
    gm = GridMap(x_min, x_max, y_min, y_max, res)
    gm.add_obstacle_list([[o.x, o.y, o.plan_radius] for o in obstacles])
    gm.inflate_obstacles(0.5)
    return gm


def _free_space_labels(grid_map):
    """8 连通自由空间连通域标记（0 = 被占用/不可通行）。

    可达性探测只回答"起终点是否连通"，而同一走廊内几十次探测共用一张栅格，
    因此一次性标记连通域后每次探测都是 O(1)，判据与 A* 一致：
    AStar 允许 8 方向移动（对角代价 1.414），这里用 3x3 结构元，8 连通口径相同。
    scipy 不可用时返回 None，调用方自动回退到 A* 探测。
    """
    try:
        import numpy as np
        from scipy.ndimage import label
    except Exception:  # noqa: BLE001
        return None
    labels, _n = label(np.asarray(grid_map.grid) == 0,
                       structure=np.ones((3, 3), dtype=bool))
    return labels


def _a_star_ok(obstacles, x_min, x_max, y_min, y_max, res, start, goal,
               grid_map=None):
    """可达性探测（布尔）。AStar.plan 失败时会 print 提示，探测属内部行为，这里静音。

    grid_map: 可选，build_probe_grid 预建的栅格。同一走廊内多个起终点候选
    共用一张栅格，省掉每次探测的重复栅格化（原本占探测耗时约 12%）。
    """
    import contextlib
    import io as _io
    from planning.a_star import AStar
    gm = grid_map
    if gm is None:
        gm = build_probe_grid(obstacles, x_min, x_max, y_min, y_max, res)
    with contextlib.redirect_stdout(_io.StringIO()):
        n = len(AStar(gm).plan((float(start[0]), float(start[1])),
                               (float(goal[0]), float(goal[1]))))
    return n > 0


def choose_start_goal(obstacles, x_min, x_max, y_min, y_max, res,
                      inset=8.0, step=2.0, max_tries=6, axis="x"):
    """在走廊两端边界采样安全点，优先直穿较空的车道，再按 A* 可达性确认

    axis="x"：航线沿 x（起终点在 x 两端，落在 y 上扫描）—— v3/v4 与 GIS 南北向走廊；
    axis="y"：航线沿 y（起终点在 y 两端，落在 x 上扫描）—— GIS 东西向走廊。
    """
    def mk(v):
        if axis == "y":
            return (v, y_min + inset), (v, y_max - inset)
        return (x_min + inset, v), (x_max - inset, v)

    _probe = {}

    def _ok(start, goal):
        gm = _probe.get("gm")
        if gm is None:
            gm = build_probe_grid(obstacles, x_min, x_max, y_min, y_max, res)
            _probe["gm"] = gm
            _probe["labels"] = _free_space_labels(gm)
        labels = _probe["labels"]
        if labels is None:
            return _a_star_ok(obstacles, x_min, x_max, y_min, y_max, res,
                              start, goal, grid_map=gm)
        sj, si = gm.world_to_grid(start[0], start[1])
        gj, gi = gm.world_to_grid(goal[0], goal[1])
        ls = labels[si, sj]
        return ls != 0 and ls == labels[gi, gj]

    lo, hi = (x_min, x_max) if axis == "y" else (y_min, y_max)
    lanes = []
    v = lo + 4.0
    while v <= hi - 4.0:
        p0, p1 = mk(v)
        if _point_free(obstacles, p0[0], p0[1]) and _point_free(obstacles, p1[0], p1[1]):
            score = 0
            scan = (p1[1] - p0[1]) if axis == "y" else (p1[0] - p0[0])
            for k in range(2, int(scan), 2):
                x = v if axis == "y" else (p0[0] + k)
                y = (p0[1] + k) if axis == "y" else v
                if not _point_free(obstacles, x, y, margin=2.0):
                    score += 1
            lanes.append((score, v))
        v += step
    # 评分相同的情况下优先建筑群中部车道，避免从地图边缘空带穿过
    if obstacles:
        c = [(o.x if axis == "y" else o.y) for o in obstacles]
        c.sort()
        med = c[len(c) // 2]
    else:
        med = (lo + hi) / 2.0
    lanes.sort(key=lambda t: (abs(t[1] - med), t[0]))
    tried = []
    for score, vv in lanes[:max_tries]:
        start, goal = mk(vv)
        tried.append((vv, score))
        if _ok(start, goal):
            return start, goal, tried
    # 都失败：退回可达性宽松匹配：尝试任意起终点组合（最多再试若干）
    vs = [t[1] for t in lanes[:8]]
    if len(vs) < 2:
        return None, None, tried
    for sv in vs:
        for gv in vs:
            start = mk(sv)[0]
            goal = mk(gv)[1]
            tried.append((sv, gv))
            if _ok(start, goal):
                return start, goal, tried
    return None, None, tried


def clear_buildings_on_lane(obstacles, start, goal, safety=1.5):
    removed = []
    changed = True
    while changed:
        changed = False
        for o in list(obstacles):
            if _segment_hits_rect(start, goal, o, inflate=safety):
                obstacles.remove(o)
                removed.append(o.name)
                changed = True
    return removed

def build_city_scene(obstacles, city_key="city", place_label="", center=None,
                     extent_m=600.0, pad=12.0, resolution=None,
                     takeoff_height=-20.0, source="custom"):
    """把本地米制障碍整理为可飞场景（平移对齐、自动选起终点、A* 可达裁剪）"""
    if not obstacles:
        raise RuntimeError("no building footprint in region")
    xs = [o.x - o.w / 2.0 for o in obstacles] + [o.x + o.w / 2.0 for o in obstacles]
    ys = [o.y - o.h / 2.0 for o in obstacles] + [o.y + o.h / 2.0 for o in obstacles]
    ox = min(xs) - pad
    oy = min(ys) - pad
    for o in obstacles:
        o.x -= ox
        o.y -= oy
    x_min, y_min = 0.0, 0.0
    x_max = max(o.x + o.w / 2.0 for o in obstacles) + pad
    y_max = max(o.y + o.h / 2.0 for o in obstacles) + pad
    span = max(x_max - x_min, y_max - y_min)
    res = resolution or (1.0 if span > 400.0 else 0.5)
    obstacles.sort(key=lambda o: o.w * o.h, reverse=True)
    # 1) 起终点
    start, goal, tried = choose_start_goal(
        obstacles, x_min, x_max, y_min, y_max, res)
    removed_names = []
    if start is None:
        raise RuntimeError("city too dense: no free start/goal lane found")
    # 2) 清除直线走廊上的建筑，避免穿越楼体；仍保留 A* 可达性校验
    removed_names += clear_buildings_on_lane(obstacles, start, goal)
    if not _a_star_ok(obstacles, x_min, x_max, y_min, y_max, res, start, goal):
        # 兜底：按面积从大到小移除阻碍建筑，直到可达（最多若干轮）
        for _ in range(16):
            if not obstacles:
                break
            obstacles.pop(0)
            removed_names.append("big-drop")
            if _a_star_ok(obstacles, x_min, x_max, y_min, y_max, res, start, goal):
                break
    if not _a_star_ok(obstacles, x_min, x_max, y_min, y_max, res, start, goal):
        raise RuntimeError("region too dense: A* unreachable after trimming")
    scene = SceneConfig(
        scene_id="City_" + city_key,
        x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max,
        resolution=res,
        start=list(start), goal=list(goal),
        obstacles=obstacles,
        takeoff_height=takeoff_height,
        route_mode="astar",
        altitude_margin=2.0,
        use_drl=False,
        geo={
            "source": source, "place": place_label, "city_key": city_key,
            "center": list(center or []), "extent_m": float(extent_m),
            "buildings_total": len(obstacles),
            "removed": len(removed_names),
            "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    return scene


def cleanup_city_scene(scene, city_key=None):
    """离线修复：对已缓存/已导入城市场景做去重 + 重选起终点（不访问网络）"""
    geo = scene.geo or {}
    key = city_key or geo.get("city_key") or "city"
    obs = _dedupe_building_boxes(list(scene.obstacles))
    rebuilt = build_city_scene(
        obs, city_key=key,
        place_label=geo.get("place", ""),
        center=geo.get("center"),
        extent_m=geo.get("extent_m", 600.0),
        resolution=scene.resolution,
        takeoff_height=scene.takeoff_height,
        source="offline-cleanup",
    )
    rebuilt.geo.update({"fix_note": "dedupe+relane (offline)"})
    return rebuilt


def cache_scene(scene, city_key):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with io.open(cache_path(city_key), "w", encoding="utf-8") as f:
            json.dump(scene.to_dict(), f, ensure_ascii=False, indent=1)
        return cache_path(city_key)
    except Exception as exc:  # 缓存失败不影响使用
        return "cache_error:%s" % exc


def load_cached_city(city_key):
    p = cache_path(city_key)
    if not os.path.isfile(p):
        return None
    with io.open(p, "r", encoding="utf-8") as f:
        d = json.load(f)
    return SceneConfig.from_dict(d, source_path=p)


def import_city(preset_id=None, place=None, lat=None, lon=None, extent_m=600.0,
                offline_only=False, refresh=False, endpoint=None, timeout=50,
                label=None):
    """一键导入真实城市：优先预置/缓存，其次在线 OSM。返回 (scene, info)"""
    meta = None
    if preset_id:
        for p in PRESETS:
            if p["id"] == preset_id:
                meta = p
                break
        if meta is None:
            raise RuntimeError("unknown preset: %s" % preset_id)
    if lat is None or lon is None:
        if meta is not None:
            lat, lon = meta["lat"], meta["lon"]
            if extent_m <= 0:
                extent_m = meta.get("extent_m", 600.0)
        elif place:
            lat, lon, found = geocode(place)
            place = found
            label = label or found
        else:
            raise RuntimeError("need preset_id or place/lat/lon")
    key = preset_id or ("geo_%.5f_%.5f" % (lat, lon))
    if not refresh:
        cached = load_cached_city(key)
        if cached is not None:
            return cached, {"cached": True, "preset": key}
    if offline_only:
        raise RuntimeError("offline cache missing for %s" % key)
    elements = fetch_buildings_elements(lat, lon, float(extent_m),
                                        endpoint=endpoint, timeout=timeout)
    obs = elements_to_obstacles(elements, lat, lon)
    if len(obs) < 3:
        raise RuntimeError("only %d building(s) found; try larger extent_m" % len(obs))
    label = label or (meta or {}).get("name", "") or (place or key)
    scene = build_city_scene(obs, city_key=key, place_label=label,
                             center=[lat, lon], extent_m=float(extent_m),
                             source="osm-overpass" if endpoint else "osm-overpass")
    cache_scene(scene, key)
    return scene, {"cached": False, "preset": key}

def random_obstacles(scene, count=4, w_min=1.5, w_max=3.0, h_min=1.5, h_max=3.0,
                     height_min=10.0, height_max=16.0, floating_ratio=0.0,
                     margin=2.5, min_gap=2.5, seed=None, replace=False):
    """在场景内随机生成障碍（落地柱 + 可选悬浮物），保证不压起终点、不重叠、
    并通过 A* 可达性检查（必要时候补抛障碍直到可达）。返回 (obstacles, info)"""
    if count <= 0:
        raise RuntimeError("count must be > 0")
    rng = random.Random(seed)
    alt = scene.flight_altitude_m
    if height_max < alt - 2.0:
        raise RuntimeError(
            "height_max(%.1f) 低于巡航高度(%.1f)，全部障碍都不会成为避障威胁；"
            "请把高度上限设到巡航高度+2m 以上" % (height_max, alt))
    existing = list(scene.obstacles) if not replace else []
    base_num = len(existing)
    new_obs = []
    info = {"attempts": 0, "replaced": replace}
    for i in range(count):
        name_i = base_num + i + 1
        for attempt in range(400):
            info["attempts"] += 1
            half_w = rng.uniform(w_min, w_max) / 2.0
            half_h = rng.uniform(h_min, h_max) / 2.0
            cx = rng.uniform(scene.x_min + margin + half_w,
                             scene.x_max - margin - half_w)
            cy = rng.uniform(scene.y_min + margin + half_h,
                             scene.y_max - margin - half_h)
            if (abs(cx - scene.start[0]) < half_w + 1.5 + 0.5 and
                    abs(cy - scene.start[1]) < half_h + 1.5 + 0.5):
                continue
            if (abs(cx - scene.goal[0]) < half_w + 1.5 + 0.5 and
                    abs(cy - scene.goal[1]) < half_h + 1.5 + 0.5):
                continue
            blocked = False
            for o in existing + new_obs:
                if (abs(cx - o.x) < half_w + o.w / 2.0 + min_gap and
                        abs(cy - o.y) < half_h + o.h / 2.0 + min_gap):
                    blocked = True
                    break
            if blocked:
                continue
            floating = rng.random() < floating_ratio
            w = half_w * 2.0
            h = half_h * 2.0
            height = rng.uniform(height_min, height_max)
            if floating:
                height = max(1.2, min(height, 6.0))
                center = rng.uniform(max(0.0, alt - 1.5), alt + 1.5)
                base_z = max(0.0, center - height / 2.0)
                kind = "floating"
            else:
                base_z = 0.0
                kind = "column"
            new_obs.append(Obstacle(
                name="Obstacle%d" % name_i,
                x=round(cx, 2), y=round(cy, 2),
                w=round(w, 2), h=round(h, 2),
                height=round(height, 2), base_z=round(base_z, 2), kind=kind))
            break
        else:
            raise RuntimeError("无法放置第 %d 个障碍（地图太满或间距过大）" % (i + 1))
    all_obs = existing + new_obs
    scene2 = SceneConfig(
        scene_id=scene.id, x_min=scene.x_min, x_max=scene.x_max,
        y_min=scene.y_min, y_max=scene.y_max, resolution=scene.resolution,
        start=scene.start, goal=scene.goal, obstacles=all_obs,
        takeoff_height=scene.takeoff_height, route_mode=scene.route_mode,
        altitude_margin=scene.altitude_margin, use_drl=scene.use_drl,
        geo=scene.geo)
    errs = scene2.validate()
    if errs:
        raise RuntimeError("随机生成校验失败: " + "; ".join(errs))
    base_keep = all_obs[:len(existing)]
    reachable = _a_star_ok(all_obs, scene.x_min, scene.x_max,
                           scene.y_min, scene.y_max, scene.resolution,
                           scene.start, scene.goal)
    if not reachable:
        # 只回退新增障碍（从最后一个开始），保留原有场景布局
        added_tmp = list(all_obs[len(existing):])
        for dropped in range(len(added_tmp)):
            added_tmp.pop()
            trial = base_keep + added_tmp
            if _a_star_ok(trial, scene.x_min, scene.x_max,
                          scene.y_min, scene.y_max, scene.resolution,
                          scene.start, scene.goal):
                all_obs = trial
                info["dropped"] = dropped + 1
                break
    if not _a_star_ok(all_obs, scene.x_min, scene.x_max, scene.y_min, scene.y_max,
                      scene.resolution, scene.start, scene.goal):
        raise RuntimeError("随机障碍后 A* 不可达（已自动回退新增障碍仍失败，说明原场景不可达）")
    if replace:
        info["replaced_old"] = len(existing)
    return all_obs, info

def _write_yaml(scene, path):
    d = scene.to_dict()
    try:
        import yaml
    except ImportError:
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return path
    with io.open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(d, f, allow_unicode=True, sort_keys=False,
                       default_flow_style=False)
    return path


def cmd_random(argv):
    ap = argparse.ArgumentParser(prog="worldgen random", description="随机障碍物生成")
    ap.add_argument("--scene", required=True, help="输入场景 yaml")
    ap.add_argument("--out", default=None, help="输出场景 yaml（默认覆盖输入）")
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--w-min", type=float, default=1.5)
    ap.add_argument("--w-max", type=float, default=3.0)
    ap.add_argument("--h-min", type=float, default=1.5)
    ap.add_argument("--h-max", type=float, default=3.0)
    ap.add_argument("--height-min", type=float, default=10.0)
    ap.add_argument("--height-max", type=float, default=16.0)
    ap.add_argument("--floating", type=float, default=0.0,
                    help="悬浮物比例 0~1（悬浮物垂直区间落在巡航高度附近）")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--replace", action="store_true", help="替换原有障碍而非追加")
    args = ap.parse_args(argv)
    scene = SceneConfig.load(args.scene)
    obs, info = random_obstacles(
        scene, count=args.count, w_min=args.w_min, w_max=args.w_max,
        h_min=args.h_min, h_max=args.h_max,
        height_min=args.height_min, height_max=args.height_max,
        floating_ratio=args.floating, seed=args.seed, replace=args.replace)
    scene2 = SceneConfig(
        scene_id=scene.id, x_min=scene.x_min, x_max=scene.x_max,
        y_min=scene.y_min, y_max=scene.y_max, resolution=scene.resolution,
        start=scene.start, goal=scene.goal, obstacles=obs,
        takeoff_height=scene.takeoff_height, route_mode=scene.route_mode,
        altitude_margin=scene.altitude_margin, use_drl=scene.use_drl, geo=scene.geo)
    out = args.out or args.scene
    _write_yaml(scene2, out)
    print("OK -> %s  total=%d attempts=%d replaced=%s dropped=%s" % (
        out, len(obs), info.get("attempts"), args.replace,
        info.get("dropped", 0)))
    print("浮动物比例: %.2f  巡航高度: %.1fm" % (args.floating, scene.flight_altitude_m))
    return 0


def cmd_city(argv):
    ap = argparse.ArgumentParser(prog="worldgen city", description="真实城市一键导入")
    ap.add_argument("--preset", default=None, help="预置 id（见 --list）")
    ap.add_argument("--place", default=None, help="地名（Nominatim 在线检索）")
    ap.add_argument("--extent", type=float, default=600.0, help="取数边长(m)")
    ap.add_argument("--offline", action="store_true", help="只用本地缓存")
    ap.add_argument("--refresh", action="store_true", help="强制在线刷新缓存")
    ap.add_argument("--out", default=None, help="输出 yaml 路径")
    ap.add_argument("--list", action="store_true", help="列出预置城市")
    args = ap.parse_args(argv)
    if args.list:
        for p in PRESETS:
            print("%-22s %-24s %.5f, %.5f  extent=%dm" % (
                p["id"], p["name"], p["lat"], p["lon"], p.get("extent_m", 600)))
        return 0
    if not args.preset and not args.place:
        ap.error("need --preset or --place")
    scene, info = import_city(
        preset_id=args.preset, place=args.place, extent_m=args.extent,
        offline_only=args.offline, refresh=args.refresh)
    g = scene.geo or {}
    print("scene: %s  cached=%s" % (scene.id, info.get("cached")))
    print("bounds: %.0f x %.0f m  res=%.2f  buildings=%d removed=%d" % (
        scene.x_max - scene.x_min, scene.y_max - scene.y_min,
        scene.resolution, g.get("buildings_total", len(scene.obstacles)),
        g.get("removed", 0)))
    print("start=(%.1f, %.1f) goal=(%.1f, %.1f) route=%s use_drl=%s" % (
        scene.start[0], scene.start[1], scene.goal[0], scene.goal[1],
        scene.route_mode, scene.use_drl))
    if args.out:
        _write_yaml(scene, args.out)
        print("saved -> %s" % args.out)
    else:
        d = scene.to_dict()
        name = "city_%s.yaml" % scene.id.replace("City_", "")
        path = os.path.join(DEFAULT_SCENES_DIR_EXP, name)
        _write_yaml(scene, path)
        print("auto-saved -> %s" % path)
    return 0


DEFAULT_SCENES_DIR_EXP = os.path.join(ROOT, "config", "scenes")


def cmd_fix(argv):
    ap = argparse.ArgumentParser(prog="worldgen fix",
                                 description="离线修复城市缓存场景（去重+重选起终点）")
    ap.add_argument("--preset", required=True)
    args = ap.parse_args(argv)
    scene = load_cached_city(args.preset)
    if scene is None:
        raise SystemExit("no cache for preset %s (run city import once)" % args.preset)
    fixed = cleanup_city_scene(scene, args.preset)
    cache_scene(fixed, args.preset)
    path = os.path.join(DEFAULT_SCENES_DIR_EXP, "city_%s.yaml" % args.preset)
    _write_yaml(fixed, path)
    g = fixed.geo or {}
    print("fixed -> %s  buildings=%d removed=%s start=(%.1f, %.1f) goal=(%.1f, %.1f)" % (
        path, len(fixed.obstacles), g.get("removed"),
        fixed.start[0], fixed.start[1], fixed.goal[0], fixed.goal[1]))
    return 0


def main():
    ap = argparse.ArgumentParser(prog="worldgen", description="v4 场景生成器")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("random", help="随机障碍")
    sub.add_parser("city", help="真实城市导入")
    sub.add_parser("fix", help="离线修复城市缓存")
    args, rest = ap.parse_known_args()
    if args.cmd == "random":
        return cmd_random(rest)
    if args.cmd == "city":
        return cmd_city(rest)
    if args.cmd == "fix":
        return cmd_fix(rest)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())