# -*- coding: utf-8 -*-
"""gis_tiles.py - v5.0 GIS 3D 瓦片生成器（真实地形 + 真实建筑）

生成 Project AirSim `CustomGIS` 场景所需的 quadkey glTF(.glb) 瓦片：
  - 地形：AWS Terrain Tiles (terrarium) 真实 DEM 高程 -> 三角网
  - 建筑：OpenStreetMap 真实建筑轮廓 + 真实高度 -> 挤出棱柱
  - 贴图：卫星影像（Esri World Imagery）烘焙成瓦片纹理

瓦片契约（来自 Project AirSim 源码，确定事实）：
  - 文件名 <quadkey>.glb，直接放在场景配置的 tiles-dir 根目录
  - Bing Maps quadkey（x=经度索引，y=纬度索引，自北向南）
  - 每个 glb：单 mesh / 单 primitive；POSITION = float32 vec3，必须是 ECEF 米
    （UE 侧 GISRenderer 用 ecef2Ned 转换，见 geodetic_converter.cpp）
  - 必须包含 TEXCOORD_0（float32 vec2）与 indices，否则 UE 侧访问器越界
  - image 0 为 RGBA PNG（UE 侧按 R8G8B8A8 直接 memcpy，通道数必须为 4）

用法:
  python gis_tiles.py build --lat 40.7527 --lon -73.9772 --extent 1200 --lod 17
  python gis_tiles.py build --place "Shanghai Bund" --extent 900 --lod 17 --offline
  python gis_tiles.py info  --site <site_id>
"""
import argparse
import hashlib
import io
import json
import math
import os
import queue
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

ROOT = os.environ.get("AIRSIM_ROOT") or os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "config", "gis_cache")
TILES_ROOT = os.path.join(ROOT, "config", "gis_tiles")
SCENES_DIR = os.path.join(ROOT, "config", "scenes")
USER_AGENT = "AirSimHybridAvoidance/5.0 (local demo)"

DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
IMAGERY_PROVIDERS = {
    "sat": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "topo": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
}
# 一级镜像：2026-09-11 在本机实测可达、且返回全量星球数据（非区域限定）。
# overpass.openstreetmap.fr 由法国 OSM 社区维护，2~4 秒返回，实测 Rio/Tokyo/NYC/Paris 均有数据。
OVERPASS_ENDPOINTS = [
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
# 慢镜像：本机实测常在 20 秒以上才回，排在主池后面并行发出，先到先得，等不到也不影响。
# 注意：不要把 overpass.osm.ch 之类"只含单个国家数据"的实例放进来——它对其它地区会
# 返回合法的空结果，一旦抢先返回就会被当成"该地没有建筑"。
# 另外这批曾经配置过但本机 DNS 已解析不了 / 证书校验失败，已删除，别再加回来：
#   overpass-api.openstreetmap.de, overpass.osm24.eu, api.openstreetmap.fr/oapi,
#   overpass.nchc.org.tw, overpass.zoom.earth, overpass.osm.rambler.ru,
#   overpass.openstreetmap.ru, overpass.osm.jp
OVERPASS_FALLBACK_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# 三个公共镜像全部不可达时（例如跨境网络被拦），不必每次预览都白等一整个 deadline：
# 记下失败时间点，冷却期内直接快速失败，由调用方降级成"纯地形"。
# 冷却只用来避免"连续多次刷新各白等一整个 deadline"。180 秒足够让镜像缓过一口气，
# 又不至于让用户整整 10 分钟都只能看纯地形。
OVERPASS_COOLDOWN_S = float(os.environ.get("AIRSIM_OVERPASS_COOLDOWN_S") or 180.0)
_OVP = {"fail_until": 0.0, "last_err": ""}


def overpass_cooldown_left():
    """大于 0 表示 Overpass 正处于"最近全部镜像不可达"的冷却期（秒）。"""
    return max(0.0, _OVP["fail_until"] - time.time())


def overpass_last_error():
    return _OVP["last_err"]


def overpass_reset():
    """手动清掉冷却（UI 的「重试建筑数据」用）。"""
    _OVP["fail_until"] = 0.0
    _OVP["last_err"] = ""
    _ovp_save()


def _ovp_file():
    return os.path.join(CACHE_DIR, "overpass_status.json")


def _ovp_save():
    """把冷却状态落到磁盘：服务重启后不必再白等一整个 deadline。"""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_ovp_file(), "w", encoding="utf-8") as f:
            json.dump({"fail_until": _OVP["fail_until"],
                       "last_err": _OVP["last_err"]}, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def _ovp_load():
    try:
        with open(_ovp_file(), encoding="utf-8") as f:
            d = json.load(f)
        _OVP["fail_until"] = float(d.get("fail_until") or 0.0)
        _OVP["last_err"] = str(d.get("last_err") or "")
    except Exception:  # noqa: BLE001
        pass


def _ovp_mark_fail(exc):
    _OVP["fail_until"] = time.time() + OVERPASS_COOLDOWN_S
    _OVP["last_err"] = "%s: %s" % (type(exc).__name__, exc)
    _ovp_save()


def _ovp_mark_ok():
    _OVP["fail_until"] = 0.0
    _OVP["last_err"] = ""
    _ovp_save()


_ovp_load()

# ---- WGS84 常数（与 Project AirSim GeodeticConverter 完全一致） ----
SEMI_MAJOR = 6378137.0
SEMI_MINOR = 6356752.3142
ECC2 = 6.69437999014e-3


# =====================================================================
# 1. 通用工具
# =====================================================================
def _http_bytes(url, timeout=60, retries=3, headers=None, data=None):
    last = None
    hdr = {"User-Agent": USER_AGENT}
    if headers:
        hdr.update(headers)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError("GET failed: %s (%s)" % (url, last))


def _cache_path(*parts):
    p = os.path.join(CACHE_DIR, *[str(x) for x in parts])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def _cached_bytes(path, loader):
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()
    data = loader()
    # 临时名带线程号：多人/多请求同时拉同一地点时不会互相写坏同一个 tmp
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return data


# ---- slippy / quadkey ----
def lonlat_to_tile(lat, lon, z):
    """经纬度 -> 浮点瓦片坐标（x=经度索引，y=纬度索引，自北向南）"""
    n = float(1 << z)
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def tile_to_lonlat(x, y, z):
    """瓦片左上角经纬度"""
    n = float(1 << z)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lat, lon


def tile_to_quadkey(x, y, z):
    """与 BingMapsUtils::TileXYToQuadkey 一致"""
    out = []
    for i in range(int(z), 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if int(x) & mask:
            digit += 1
        if int(y) & mask:
            digit += 2
        out.append(str(digit))
    return "".join(out)


def tile_box_lonlat(x, y, z):
    """瓦片经纬度包围盒 (south, west, north, east)"""
    north, west = tile_to_lonlat(x, y, z)
    south, east = tile_to_lonlat(x + 1, y + 1, z)
    return south, west, north, east


def tiles_covering(lat, lon, half_m, z):
    """返回覆盖以 (lat,lon) 为中心、半边长 half_m 的方框的所有瓦片 (x, y, z)"""
    dlat = half_m / 110540.0
    dlon = half_m / (111320.0 * math.cos(math.radians(lat)))
    x0, y0 = lonlat_to_tile(lat + dlat, lon - dlon, z)
    x1, y1 = lonlat_to_tile(lat - dlat, lon + dlon, z)
    out = []
    for ty in range(int(math.floor(y0)), int(math.floor(y1)) + 1):
        for tx in range(int(math.floor(x0)), int(math.floor(x1)) + 1):
            out.append((tx, ty, z))
    return out


# ---- 大地坐标 ----
def geodetic_to_ecef(lat, lon, alt_m):
    """WGS84 大地坐标 -> ECEF 米（等价 GeodeticConverter::geodetic2Ecef）"""
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    xi = math.sqrt(1.0 - ECC2 * math.sin(lat_r) ** 2)
    x = (SEMI_MAJOR / xi + alt_m) * math.cos(lat_r) * math.cos(lon_r)
    y = (SEMI_MAJOR / xi + alt_m) * math.cos(lat_r) * math.sin(lon_r)
    z = (SEMI_MAJOR / xi * (1.0 - ECC2) + alt_m) * math.sin(lat_r)
    return x, y, z


def ecef_to_geodetic(x, y, z):
    """ECEF -> (lat_deg, lon_deg, alt_m)，Bowring 1985 闭式解"""
    a = SEMI_MAJOR
    e2 = ECC2
    b = a * math.sqrt(1.0 - e2)
    ep2 = (a * a - b * b) / (b * b)
    p = math.hypot(x, y)
    lon = math.atan2(y, x)
    if p < 1e-9:
        lat = math.pi / 2.0 if z >= 0 else -math.pi / 2.0
        return math.degrees(lat), math.degrees(lon), abs(z) - b
    theta = math.atan2(z * a, p * b)
    st, ct = math.sin(theta), math.cos(theta)
    lat = math.atan2(z + ep2 * b * st ** 3, p - e2 * a * ct ** 3)
    sn = math.sin(lat)
    nn = a / math.sqrt(1.0 - e2 * sn * sn)
    alt = p / math.cos(lat) - nn
    return math.degrees(lat), math.degrees(lon), alt


def ecef_to_geodetic_array(x, y, z):
    """向量化 ECEF -> (lat_deg, lon_deg, alt_m)"""
    a = SEMI_MAJOR
    e2 = ECC2
    b = a * math.sqrt(1.0 - e2)
    ep2 = (a * a - b * b) / (b * b)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    p = np.hypot(x, y)
    lon = np.arctan2(y, x)
    theta = np.arctan2(z * a, p * b)
    st, ct = np.sin(theta), np.cos(theta)
    lat = np.arctan2(z + ep2 * b * st ** 3, p - e2 * a * ct ** 3)
    sn = np.sin(lat)
    nn = a / np.sqrt(1.0 - e2 * sn * sn)
    alt = p / np.cos(lat) - nn
    return np.degrees(lat), np.degrees(lon), alt


class GeoRef(object):
    """复刻 GeodeticConverter：ECEF <-> NED（home 点）"""

    def __init__(self, home_lat, home_lon, home_alt):
        self.lat = float(home_lat)
        self.lon = float(home_lon)
        self.alt = float(home_alt)
        self.lat_r = math.radians(self.lat)
        self.lon_r = math.radians(self.lon)
        self.home_ecef = geodetic_to_ecef(self.lat, self.lon, self.alt)
        # ecef_to_ned 矩阵用"地心纬度"（与 C++ 实现一致）
        hx, hy, hz = self.home_ecef
        phi_p = math.atan2(hz, math.sqrt(hx * hx + hy * hy))
        self.ecef2ned_m = self._nRe(phi_p, self.lon_r)

    @staticmethod
    def _nRe(lat_r, lon_r):
        s_lat, c_lat = math.sin(lat_r), math.cos(lat_r)
        s_lon, c_lon = math.sin(lon_r), math.cos(lon_r)
        return ((-s_lat * c_lon, -s_lat * s_lon, c_lat),
                (-s_lon, c_lon, 0.0),
                (c_lat * c_lon, c_lat * s_lon, s_lat))

    def ecef_to_ned(self, x, y, z):
        hx, hy, hz = self.home_ecef
        vx, vy, vz = x - hx, y - hy, z - hz
        m = self.ecef2ned_m
        north = m[0][0] * vx + m[0][1] * vy + m[0][2] * vz
        east = m[1][0] * vx + m[1][1] * vy + m[1][2] * vz
        up = m[2][0] * vx + m[2][1] * vy + m[2][2] * vz
        return north, east, -up

    def latlon_to_ned(self, lat, lon, alt_m):
        return self.ecef_to_ned(*geodetic_to_ecef(lat, lon, alt_m))

    def ned_to_ecef(self, north, east, down):
        m = self.ecef2ned_m
        up = -down
        hx, hy, hz = self.home_ecef
        return (hx + m[0][0] * north + m[1][0] * east + m[2][0] * up,
                hy + m[0][1] * north + m[1][1] * east + m[2][1] * up,
                hz + m[0][2] * north + m[1][2] * east + m[2][2] * up)

    def ned_to_latlon(self, north, east, down=0.0):
        """NED(米) -> (lat_deg, lon_deg, alt_m)，ecef_to_ned 的逆"""
        return ecef_to_geodetic(*self.ned_to_ecef(north, east, down))

    def ned_array_to_latlon(self, north, east, down=0.0):
        """向量化 NED -> (lat_deg, lon_deg, alt_m)"""
        m = self.ecef2ned_m
        up = -np.asarray(down, dtype=np.float64)
        north = np.asarray(north, dtype=np.float64)
        east = np.asarray(east, dtype=np.float64)
        hx, hy, hz = self.home_ecef
        x = hx + m[0][0] * north + m[1][0] * east + m[2][0] * up
        y = hy + m[0][1] * north + m[1][1] * east + m[2][1] * up
        z = hz + m[0][2] * north + m[1][2] * east + m[2][2] * up
        return ecef_to_geodetic_array(x, y, z)

    def ecef_array(self, lats, lons, alts):
        """向量化 geodetic -> ECEF，返回 (n,3) float64"""
        lats = np.asarray(lats, dtype=np.float64)
        lons = np.asarray(lons, dtype=np.float64)
        alts = np.asarray(alts, dtype=np.float64)
        lat_r = np.radians(lats)
        lon_r = np.radians(lons)
        xi = np.sqrt(1.0 - ECC2 * np.sin(lat_r) ** 2)
        x = (SEMI_MAJOR / xi + alts) * np.cos(lat_r) * np.cos(lon_r)
        y = (SEMI_MAJOR / xi + alts) * np.cos(lat_r) * np.sin(lon_r)
        z = (SEMI_MAJOR / xi * (1.0 - ECC2) + alts) * np.sin(lat_r)
        return np.stack([x, y, z], axis=-1)


# =====================================================================
# 2. DEM（terrarium）
# =====================================================================
def dem_tile_path(z, x, y):
    return _cache_path("dem", z, "%d_%d.png" % (x, y))


def load_dem_tile(z, x, y, offline=False):
    """返回 256x256 float32 高程（米）"""
    from PIL import Image
    p = dem_tile_path(z, x, y)
    if os.path.isfile(p):
        with open(p, "rb") as f:
            raw = f.read()
    else:
        if offline:
            raise RuntimeError("DEM 缓存缺失 (offline): z%d %d %d" % (z, x, y))
        raw = _http_bytes(DEM_URL.format(z=z, x=x, y=y))
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, p)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    a = np.asarray(img, dtype=np.float32)
    return (a[:, :, 0] * 256.0 + a[:, :, 1] + a[:, :, 2] / 256.0) - 32768.0


def dem_mosaic(z, x0, y0, x1, y1, offline=False, workers=6):
    """拼接 DEM 瓦片，返回 (arr, x0, y0)"""
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    arr = np.zeros((ny * 256, nx * 256), dtype=np.float32)
    keys = [(x0 + i, y0 + j) for j in range(ny) for i in range(nx)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        tiles = list(ex.map(lambda k: load_dem_tile(z, k[0], k[1], offline), keys))
    for idx, (tx, ty) in enumerate(keys):
        i = tx - x0
        j = ty - y0
        arr[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] = tiles[idx]
    return arr, x0, y0


def dem_sampler(lat0, lon0, half_m, z=14, offline=False):
    """返回 f(lat, lon) -> 高程（米）的双线性采样器"""
    dlat = (half_m + 400.0) / 110540.0
    dlon = (half_m + 400.0) / (111320.0 * math.cos(math.radians(lat0)))
    x0f, y0f = lonlat_to_tile(lat0 + dlat, lon0 - dlon, z)
    x1f, y1f = lonlat_to_tile(lat0 - dlat, lon0 + dlon, z)
    arr, x0, y0 = dem_mosaic(z, int(math.floor(x0f)), int(math.floor(y0f)),
                             int(math.floor(x1f)), int(math.floor(y1f)),
                             offline=offline)
    n = float(1 << z)
    lat_r0 = math.radians(lat0)

    def sample(lat, lon):
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        px = (lon + 180.0) / 360.0 * n * 256.0 - x0 * 256.0
        py = (1.0 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2.0 * n * 256.0 - y0 * 256.0
        px = np.clip(px, 0.0, arr.shape[1] - 1.001)
        py = np.clip(py, 0.0, arr.shape[0] - 1.001)
        ix = np.floor(px).astype(np.int64)
        iy = np.floor(py).astype(np.int64)
        fx = px - ix
        fy = py - iy
        v00 = arr[iy, ix]
        v01 = arr[iy, ix + 1]
        v10 = arr[iy + 1, ix]
        v11 = arr[iy + 1, ix + 1]
        return (v00 * (1 - fx) * (1 - fy) + v01 * fx * (1 - fy) +
                v10 * (1 - fx) * fy + v11 * fx * fy)

    _ = lat_r0
    return sample


# =====================================================================
# 3. 卫星影像
# =====================================================================
def imagery_tile_path(provider, z, x, y):
    return _cache_path("imagery", provider, z, "%d_%d.png" % (x, y))


def load_imagery_tile(provider, z, x, y, offline=False, timeout=45):
    p = imagery_tile_path(provider, z, x, y)
    if os.path.isfile(p):
        with open(p, "rb") as f:
            return f.read()
    if offline:
        return None
    url = IMAGERY_PROVIDERS[provider].format(z=z, x=x, y=y)
    raw = _http_bytes(url, timeout=timeout)
    tmp = p + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, p)
    return raw


def imagery_mosaic(provider, z, x0, y0, x1, y1, offline=False, workers=8,
                   tile_px=256, timeout=45):
    """拼接影像瓦片 -> RGBA PIL 图；全部缺失时返回 None"""
    from PIL import Image
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    canvas = Image.new("RGBA", (nx * tile_px, ny * tile_px), (150, 150, 150, 255))
    keys = [(x0 + i, y0 + j) for j in range(ny) for i in range(nx)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        raws = list(ex.map(
            lambda k: load_imagery_tile(provider, z, k[0], k[1], offline, timeout),
            keys))
    got = 0
    for idx, (tx, ty) in enumerate(keys):
        raw = raws[idx]
        if not raw:
            continue
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
        except Exception:  # noqa: BLE001
            continue
        if im.size != (tile_px, tile_px):
            im = im.resize((tile_px, tile_px), Image.LANCZOS)
        canvas.paste(im, ((tx - x0) * tile_px, (ty - y0) * tile_px))
        got += 1
    if got == 0:
        return None
    return canvas


def build_texture(provider, tile_z, tx, ty, tex_px, offline=False):
    """为 1 个瓦片烘焙 RGBA 纹理：上部为卫星影像，底部 12.5% 为墙面渐变带"""
    from PIL import Image
    iz = tile_z + 1
    img_px = tex_px
    base_x, base_y = tx * 2, ty * 2
    mos = imagery_mosaic(provider, iz, base_x, base_y, base_x + 1, base_y + 1,
                         offline=offline, tile_px=256)
    img_h = int(round(tex_px * 0.875))
    if mos is None:
        top = Image.new("RGBA", (img_px, img_h), (120, 125, 118, 255))
    else:
        top = mos.resize((img_px, img_px), Image.LANCZOS).crop((0, 0, img_px, img_h))
    strip = Image.new("RGBA", (img_px, tex_px - img_h))
    px = strip.load()
    h = tex_px - img_h
    for j in range(h):
        t = j / max(1, h - 1)
        c = int(round(205 - 95 * t))
        for i in range(img_px):
            px[i, j] = (c, c, min(255, c + 6), 255)
    out = Image.new("RGBA", (img_px, tex_px))
    out.paste(top, (0, 0))
    out.paste(strip, (0, img_h))
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# =====================================================================
# 4. 建筑（Overpass）
# =====================================================================
def _tag_float(tags, keys, default=None):
    for k in keys:
        v = tags.get(k)
        if not v:
            continue
        num = "".join(ch for ch in str(v).split()[0] if ch.isdigit() or ch in ".")
        try:
            f = float(num)
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f
    return default


def building_height(tags, default_h=12.0, min_h=2.5, max_h=160.0):
    h = _tag_float(tags, ("height", "building:height", "est_height"))
    if h is None:
        levels = _tag_float(tags, ("building:levels", "building:levels:aboveground"))
        if levels is not None:
            h = levels * 3.2
    if h is None:
        kind = str(tags.get("building") or "").lower()
        h = {"house": 7.0, "garage": 3.0, "garages": 3.0, "hut": 3.0,
             "shed": 3.0, "church": 18.0, "cathedral": 30.0,
             "apartments": 22.0, "office": 32.0, "commercial": 18.0,
             "retail": 12.0, "industrial": 12.0, "roof": 3.0}.get(kind, default_h)
    return max(min_h, min(max_h, float(h)))


# OSM 查询框向外取整步长(度)。默认 0 = 不取整：
#   >0 时小幅挪动选点更容易命中同一份 OSM 缓存，但查询框会变大（多拉建筑），
#   且建筑顺序变化会间接影响走廊候选的并列排序，可能让同一地点的生成结果轻微漂移。
OVERPASS_SNAP_DEG = 0.0


def _snap_box(south, west, north, east, step):
    """把查询框向外扩到 step 的整数倍（只会变大，不会漏掉原框内的建筑）"""
    if not step or step <= 0:
        return south, west, north, east
    return (math.floor(south / step) * step, math.floor(west / step) * step,
            math.ceil(north / step) * step, math.ceil(east / step) * step)


def _overpass_validate(raw):
    """校验镜像返回体是否为一份可用的 Overpass 结果。

    公共镜像过载/限流时会返回 HTML 错误页，或 200 + {"remark": "...", "elements": []}。
    这类"HTTP 成功但内容无效"的响应如果抢先返回并落进缓存，会让某个地区永远刷不出
    建筑（表现为几秒秒回、零障碍）。返回 (是否可用, 原因)。
    """
    try:
        doc = json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        return False, "响应不是合法 JSON（%s）" % type(exc).__name__
    if not isinstance(doc, dict):
        return False, "响应结构异常"
    if doc.get("remark"):
        return False, "Overpass 报错：%s" % str(doc["remark"])[:120]
    if "elements" not in doc:
        return False, "响应缺少 elements 字段"
    return True, ""


def _overpass_race(query, endpoints, per_try_timeout, deadline_s, stagger=0.0):
    """并行 hedge：同时向所有镜像以 POST/GET 发同一查询，取最先成功的那份。

    原实现是串行重试（3 镜像 x 2 方式 x 2 重试 x 90s），公共 Overpass 一旦排队/
    限流就会叠加成 550~630 秒；并行发一轮后总耗时 ≈ 最快镜像的响应时间。
    每份响应都过 _overpass_validate，坏响应不会顶替好响应。
    stagger: 依次错开每个 worker 的启动时间（秒），避免同一瞬间把所有镜像都压满。
    返回 (raw_bytes, 命中来源)；全部失败/超时抛 RuntimeError。
    """
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    hdr = {"Content-Type": "application/x-www-form-urlencoded"}
    box = queue.Queue()
    # 打点策略：每个镜像先发一份 POST（错开启动）；GET 兜底只打第一个镜像、
    # 且延迟到 hedge_delay 之后——同一个镜像瞬间收到 POST+GET 两份重查询会被它自己
    # 排队，反而比单发更慢。
    attempts = []
    for i, url in enumerate(endpoints):
        attempts.append((url, "post", stagger * i))
    if endpoints:
        attempts.append((endpoints[0], "get", max(8.0, stagger * len(endpoints))))

    def _worker(url, mode, delay):
        if delay > 0:
            time.sleep(delay)
        try:
            if mode == "post":
                raw = _http_bytes(url, timeout=per_try_timeout, retries=1,
                                  headers=hdr, data=data)
            else:
                raw = _http_bytes(url + "?data=" + urllib.parse.quote(query),
                                  timeout=per_try_timeout, retries=1)
        except Exception as exc:  # noqa: BLE001
            box.put((False, None, url, mode,
                     "%s: %s" % (type(exc).__name__, exc)))
            return
        good, why = _overpass_validate(raw)
        if not good:
            box.put((False, None, url, mode, why))
            return
        box.put((True, raw, url, mode, ""))

    for url, mode, delay in attempts:
        threading.Thread(target=_worker,
                         args=(url, mode, delay), daemon=True).start()

    errs = []
    deadline = time.time() + float(deadline_s)
    for _ in range(len(attempts)):
        remain = deadline - time.time()
        if remain <= 0:
            break
        try:
            ok, raw, url, mode, err = box.get(timeout=remain)
        except queue.Empty:
            break
        if ok:
            return raw, "%s[%s]" % (url, mode)
        errs.append("%s[%s] %s" % (url, mode, err))
    raise RuntimeError("Overpass 全部镜像失败/超时(%.0fs): %s"
                       % (deadline_s, " | ".join(errs[-3:]) if errs else "无响应"))


def fetch_buildings(lat0, lon0, half_m, timeout=90, endpoint=None, offline=False,
                    deadline_s=None, snap_deg=OVERPASS_SNAP_DEG, progress=None):
    """Overpass 拉取建筑轮廓（way + relation multipolygon），返回 list[dict]
    每项: {"poly": [(lat, lon), ...], "outer": [...], "h": m, "min_h": m, "id": str}

    deadline_s: 客户端总共最多等多久（默认 timeout + 15s）。所有镜像并行发出，
    所以这个值就是最坏等待时间；命中缓存时直接返回，不发任何请求。
    """
    dlat = half_m / 110540.0
    dlon = half_m / (111320.0 * math.cos(math.radians(lat0)))
    south, north = lat0 - dlat, lat0 + dlat
    west, east = lon0 - dlon, lon0 + dlon
    south, west, north, east = _snap_box(south, west, north, east, snap_deg)
    bbox = "%.7f,%.7f,%.7f,%.7f" % (south, west, north, east)
    query = ("[out:json][timeout:%d];("
             "way[\"building\"](%s);"
             "relation[\"building\"](%s);"
             ");out tags geom;" % (int(timeout), bbox, bbox))
    key = _cache_path("osm", hashlib.md5(query.encode("utf-8")).hexdigest()[:16] + ".json")
    if deadline_s is None:
        deadline_s = float(timeout) + 15.0
    if endpoint:
        tiers = [[endpoint]]
    else:
        # 单池并行 hedge：主池 + 慢镜像一次性全部发出，谁先回有效结果就用谁。
        # 旧实现是"主池跑完再跑兜底池"，主池一旦整体超时就把 deadline 吃光，
        # 兜底池根本没机会跑（实测 2026-09-15：overpass-api.de 1.5 秒可用，却因为
        # 排在兜底池而被 45 秒 deadline 挡在门外，用户看到的就是"场景刷不出来"）。
        pool = list(OVERPASS_ENDPOINTS)
        pool += [e for e in OVERPASS_FALLBACK_ENDPOINTS if e not in pool]
        # 第二轮重复同一池：公共镜像的慢多半是"这一刻正好在排队"，隔一会儿重发常常就通。
        tiers = [pool, pool]
    t_start = time.time()

    def _load():
        last = None
        for eps in tiers:
            if not eps:
                continue
            left = float(deadline_s) - (time.time() - t_start)
            if left <= 1.0:
                break
            try:
                # 单次尝试不必等满 timeout：>30 秒还没回的镜像对交互式预览已经没意义，
                # 留出的时间让第二轮/其它镜像有机会顶上。
                per_try = max(8.0, min(float(timeout), left, 30.0))
                raw, who = _overpass_race(query, eps, per_try, left,
                                          stagger=0.35)
            except Exception as exc:  # noqa: BLE001
                last = exc
                continue
            if progress:
                try:
                    progress("建筑数据来自 %s" % who)
                except Exception:  # noqa: BLE001
                    pass
            return raw
        raise last or RuntimeError("Overpass 没有配置可用镜像")

    def _discard_cache(reason):
        """删掉本地 OSM 空/坏缓存，避免把一次网络抖动永久固化。

        命中缓存时 _cached_bytes 直接返回，不再联网；若缓存里是"零建筑"或坏响应，
        用户之后每次刷新都会秒回、看不到任何建筑，很像"场景刷不出来"。
        """
        try:
            if os.path.isfile(key):
                os.remove(key)
                sys.stderr.write("[gis_tiles] 丢弃无效的 OSM 缓存 %s（%s）\n"
                                 % (os.path.basename(key), reason))
        except OSError:
            pass

    if offline:
        # 仅用本地缓存：命中就用，没命中就报错，由调用方决定是否降级成纯地形。
        if not os.path.isfile(key):
            raise RuntimeError("offline 模式且本地没有该区域的 OSM 建筑缓存"
                               "（%s）" % os.path.basename(key))
        with open(key, "rb") as f:
            raw = f.read()
    else:
        left = overpass_cooldown_left()
        if left > 0:
            raise RuntimeError("Overpass 最近全部镜像不可达，冷却中"
                               "（还剩 %.0f 秒）：%s" % (left, overpass_last_error()))
        try:
            raw = _cached_bytes(key, _load)
        except Exception as exc:  # noqa: BLE001
            _ovp_mark_fail(exc)
            raise
        _ovp_mark_ok()
    try:
        doc = json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        if not offline:
            _discard_cache("缓存不是合法 JSON")
        raise RuntimeError("OSM 建筑缓存损坏，已删除，请重试")
    elements = doc.get("elements", []) if isinstance(doc, dict) else []
    if not elements and not offline:
        # "这一带确实没有建筑"是合法结果（沙漠/海面），但不该永久落盘：
        # 上游偶发空响应 / 区域限定镜像的假空结果都会长成这个样子。
        _discard_cache("结果为空 elements")

    out = []
    for e in elements:
        tags = e.get("tags") or {}
        if not tags:
            continue
        h = building_height(tags)
        min_h = _tag_float(tags, ("min_height", "building:min_height"), 0.0) or 0.0
        if e.get("type") == "way":
            geom = e.get("geometry") or []
            poly = [(float(p["lat"]), float(p["lon"])) for p in geom if p]
            if len(poly) >= 3:
                out.append({"poly": poly, "h": h, "min_h": min_h,
                            "id": "w%s" % e.get("id")})
        elif e.get("type") == "relation":
            for m in e.get("members") or []:
                if m.get("role") not in ("outer", ""):
                    continue
                geom = m.get("geometry") or []
                poly = [(float(p["lat"]), float(p["lon"])) for p in geom if p]
                if len(poly) >= 3:
                    out.append({"poly": poly, "h": h, "min_h": min_h,
                                "id": "r%s_%s" % (e.get("id"), m.get("ref"))})
    return out


# =====================================================================
# 5. GLB 写入（单 mesh / 单 primitive）
# =====================================================================
def _pad4(b, fill=b"\x00"):
    rem = len(b) % 4
    return b if rem == 0 else b + fill * (4 - rem)


def write_glb(path, positions, uvs, indices, png_bytes):
    pos = np.asarray(positions, dtype="<f4")
    uv = np.asarray(uvs, dtype="<f4")
    idx = np.asarray(indices, dtype="<u4").reshape(-1)
    pos_b = pos.tobytes()
    uv_b = uv.tobytes()
    idx_b = idx.tobytes()
    img_b = png_bytes
    offset = 0
    views = []
    blobs = []
    for data, target in ((pos_b, 34962), (uv_b, 34962), (idx_b, 34963), (img_b, None)):
        pad = (4 - (offset % 4)) % 4
        if pad:
            blobs.append(b"\x00" * pad)
            offset += pad
        v = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            v["target"] = target
        views.append(v)
        blobs.append(data)
        offset += len(data)
    bin_blob = _pad4(b"".join(blobs))
    gltf = {
        "asset": {"version": "2.0", "generator": "AirSimHybridAvoidance gis_tiles v5.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
            "indices": 2, "material": 0, "mode": 4}]}],
        "materials": [{"pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0},
            "metallicFactor": 0.0, "roughnessFactor": 1.0},
            "doubleSided": False}],
        "textures": [{"sampler": 0, "source": 0}],
        "images": [{"bufferView": 3, "mimeType": "image/png"}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987,
                      "wrapS": 33071, "wrapT": 33071}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": int(pos.shape[0]),
             "type": "VEC3", "min": [float(x) for x in pos.min(axis=0)],
             "max": [float(x) for x in pos.max(axis=0)]},
            {"bufferView": 1, "componentType": 5126, "count": int(uv.shape[0]),
             "type": "VEC2"},
            {"bufferView": 2, "componentType": 5125, "count": int(idx.shape[0]),
             "type": "SCALAR"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(bin_blob)}],
    }
    js = _pad4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    total = 12 + 8 + len(js) + 8 + len(bin_blob)
    with open(path, "wb") as f:
        f.write(b"glTF")
        f.write(np.uint32(2).tobytes())
        f.write(np.uint32(total).tobytes())
        f.write(np.uint32(len(js)).tobytes())
        f.write(np.uint32(0x4E4F534A).tobytes())  # JSON
        f.write(js)
        f.write(np.uint32(len(bin_blob)).tobytes())
        f.write(np.uint32(0x004E4942).tobytes())  # BIN
        f.write(bin_blob)
    return total


def read_glb_summary(path):
    """自检：解析 GLB 头 + JSON chunk，返回摘要"""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:4] != b"glTF":
        raise RuntimeError("not a glb: %s" % path)
    ver = int(np.frombuffer(raw[4:8], dtype="<u4")[0])
    total = int(np.frombuffer(raw[8:12], dtype="<u4")[0])
    if total != len(raw):
        raise RuntimeError("declared length %d != file %d" % (total, len(raw)))
    off = 12
    js = None
    bin_len = 0
    while off < len(raw):
        clen = int(np.frombuffer(raw[off:off + 4], dtype="<u4")[0])
        ctype = raw[off + 4:off + 8]
        body = raw[off + 8:off + 8 + clen]
        if ctype == b"JSON":
            js = json.loads(body.decode("utf-8"))
        elif ctype == b"BIN\x00":
            bin_len = clen
        off += 8 + clen
    prim = js["meshes"][0]["primitives"][0]
    return {
        "version": ver,
        "bytes": len(raw),
        "bin": bin_len,
        "verts": js["accessors"][prim["attributes"]["POSITION"]]["count"],
        "uvs": js["accessors"][prim["attributes"]["TEXCOORD_0"]]["count"],
        "indices": js["accessors"][prim["indices"]]["count"],
        "tris": js["accessors"][prim["indices"]]["count"] // 3,
        "has_texture": len(js.get("images", [])) > 0,
    }
# =====================================================================
# 6. 网格构建
# =====================================================================
IMG_V = 0.875          # 纹理上部 87.5% 为影像，下部为墙面渐变带
WALL_UV_TOP = (0.5, 0.878)
WALL_UV_BOT = (0.5, 0.998)


class MeshBuilder(object):
    def __init__(self):
        self.verts = []
        self.uvs = []
        self.tris = []

    def vertex(self, p, uv):
        self.verts.append((float(p[0]), float(p[1]), float(p[2])))
        self.uvs.append((float(uv[0]), float(uv[1])))
        return len(self.verts) - 1

    def tri(self, a, b, c):
        # 正反两面都写：规避 UE 与 glTF 绕序差异导致整片被背面剔除
        self.tris.extend((a, b, c))
        self.tris.extend((c, b, a))

    def quad(self, p0, p1, p2, p3, uv0, uv1, uv2, uv3):
        i0 = self.vertex(p0, uv0)
        i1 = self.vertex(p1, uv1)
        i2 = self.vertex(p2, uv2)
        i3 = self.vertex(p3, uv3)
        self.tri(i0, i1, i2)
        self.tri(i0, i2, i3)

    def arrays(self):
        return (np.asarray(self.verts, dtype=np.float64),
                np.asarray(self.uvs, dtype=np.float64),
                np.asarray(self.tris, dtype=np.int64))


def _poly_area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return 0.5 * s


def _point_in_tri(px, py, ax, ay, bx, by, cx, cy):
    d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by)
    d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy)
    d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay)
    neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (neg and pos)


def triangulate_polygon(poly):
    """耳切三角化（支持凹多边形），返回顶点索引三元组；失败退化扇形"""
    n = len(poly)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]
    idx = list(range(n))
    if _poly_area(poly) < 0.0:
        idx.reverse()
    out = []
    guard = 0
    while len(idx) > 3 and guard < 8 * n * n:
        guard += 1
        clipped = False
        for k in range(len(idx)):
            i0 = idx[(k - 1) % len(idx)]
            i1 = idx[k]
            i2 = idx[(k + 1) % len(idx)]
            ax, ay = poly[i0]
            bx, by = poly[i1]
            cx, cy = poly[i2]
            cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            if cross <= 0.0:
                continue
            bad = False
            for m in idx:
                if m in (i0, i1, i2):
                    continue
                if _point_in_tri(poly[m][0], poly[m][1], ax, ay, bx, by, cx, cy):
                    bad = True
                    break
            if bad:
                continue
            out.append((i0, i1, i2))
            idx.pop(k)
            clipped = True
            break
        if not clipped:
            break
    if len(idx) == 3:
        out.append((idx[0], idx[1], idx[2]))
    if not out:
        for k in range(1, n - 1):
            out.append((0, k, k + 1))
    return out


def build_terrain(mb, tile, grid, sample, georef):
    """瓦片地形网格：grid x grid 顶点"""
    tx, ty, tz = tile
    south, west, north, east = tile_box_lonlat(tx, ty, tz)
    n = int(grid)
    i = np.arange(n, dtype=np.float64)
    lons = west + (east - west) * (i / (n - 1.0))
    lats = north - (north - south) * (i / (n - 1.0))
    lon_g, lat_g = np.meshgrid(lons, lats)          # 行=j(南北), 列=i(东西)
    alts = sample(lat_g.ravel(), lon_g.ravel()).reshape(lat_g.shape)
    ecef = georef.ecef_array(lat_g.ravel(), lon_g.ravel(), alts.ravel())
    ecef = ecef.reshape(n, n, 3)
    vi = np.zeros((n, n), dtype=np.int64)
    for j in range(n):
        for i2 in range(n):
            u = i2 / (n - 1.0)
            v = (j / (n - 1.0)) * IMG_V
            vi[j, i2] = mb.vertex(ecef[j, i2], (u, v))
    for j in range(n - 1):
        for i2 in range(n - 1):
            mb.tri(vi[j, i2], vi[j, i2 + 1], vi[j + 1, i2 + 1])
            mb.tri(vi[j, i2], vi[j + 1, i2 + 1], vi[j + 1, i2])
    return alts


def add_building(mb, poly, base_alts, top_alt, georef, tile, sample):
    """把一个建筑轮廓挤出成棱柱（屋面 + 4 面墙）"""
    tx, ty, tz = tile
    south, west, north, east = tile_box_lonlat(tx, ty, tz)
    lats = np.array([p[0] for p in poly], dtype=np.float64)
    lons = np.array([p[1] for p in poly], dtype=np.float64)
    top_ecef = georef.ecef_array(lats, lons, np.full(len(poly), top_alt))
    base_ecef = georef.ecef_array(lats, lons, np.asarray(base_alts))
    uv = [((lons[k] - west) / (east - west), (north - lats[k]) / (north - south) * IMG_V)
          for k in range(len(poly))]
    roof_idx = []
    for k in range(len(poly)):
        roof_idx.append(mb.vertex(top_ecef[k], uv[k]))
    poly2d = [(lons[k], lats[k]) for k in range(len(poly))]
    for (a, b, c) in triangulate_polygon(poly2d):
        mb.tri(roof_idx[a], roof_idx[b], roof_idx[c])
    n = len(poly)
    for k in range(n):
        k2 = (k + 1) % n
        mb.quad(base_ecef[k], base_ecef[k2], top_ecef[k2], top_ecef[k],
                WALL_UV_BOT, WALL_UV_BOT, WALL_UV_TOP, WALL_UV_TOP)


# =====================================================================
# 7. 站点构建
# =====================================================================
def site_id_for(lat, lon, tag=None):
    base = ("gis_%.5f_%.5f" % (float(lat), float(lon))).replace(".", "_")
    base = "".join(c if (c.isalnum() or c in "._-") else "_" for c in base)
    if tag:
        base += "_" + "".join(c for c in str(tag) if c.isalnum() or c in "_-")
    return base


def _tile_plane(lat, lon, extent_m, lod, rings):
    planes = []
    for r in range(int(rings) + 1):
        level = int(lod) - r
        half = extent_m / 2.0 * (2 ** r)
        planes.append((level, half, tiles_covering(lat, lon, half, level)))
    return planes


def build_site(lat, lon, extent_m=1200.0, lod=17, rings=2, grid=64,
               provider="sat", route_len_m=600.0, route_width_m=160.0,
               tag=None, offline=False, workers=8, progress=None,
               max_buildings=6000, texture_px=None, preview=True,
               auto_layout=True, skip_buildings=False,
               allow_no_buildings=True):
    """生成一个 GIS 站点：3D 瓦片 + 场景 yaml，返回 info dict"""
    from PIL import Image  # noqa: F401  (提前校验依赖)
    lat = float(lat)
    lon = float(lon)
    extent_m = float(extent_m)
    lod = int(lod)
    rings = int(rings)
    t_start = time.time()

    def log(frac, msg):
        if progress:
            try:
                progress(frac, msg)
            except Exception:  # noqa: BLE001
                pass

    log(0.02, "读取 DEM 高程…")
    outer_half = extent_m / 2.0 * (2 ** rings)
    sample = dem_sampler(lat, lon, outer_half, z=15, offline=offline)
    home_alt = float(np.asarray(sample(lat, lon)).reshape(-1)[0])

    log(0.08, "拉取 OSM 建筑轮廓…")
    data_half = max(extent_m / 2.0, route_len_m / 2.0) * 1.08
    buildings_err = ""
    if skip_buildings:
        buildings = []
        buildings_err = "已按设置跳过 OSM 在线建筑轮廓（该站点只含真实地形）"
    else:
        try:
            buildings = fetch_buildings(lat, lon, data_half, offline=offline)
        except Exception as exc:  # noqa: BLE001
            # 与 peek_plan 同样处理：Overpass 不可达时降级成"纯地形"站点，而不是整体失败。
            if not allow_no_buildings:
                raise
            buildings = []
            buildings_err = "%s: %s" % (type(exc).__name__, exc)
            log(0.1, "OSM 建筑数据不可用，按纯地形继续生成 3D 瓦片…")
    if len(buildings) > max_buildings:
        buildings.sort(key=lambda b: -b["h"])
        buildings = buildings[:max_buildings]

    georef = GeoRef(lat, lon, home_alt)

    # ---- 规划场景（NED 走廊，供 A*/势场使用）----
    site_id = site_id_for(lat, lon, tag)
    tiles_dir = os.path.join(TILES_ROOT, site_id)
    os.makedirs(tiles_dir, exist_ok=True)

    log(0.12, "构建规划场景（A* 可达性校验）…")
    scene, keep_ids, planner_info = build_planner_scene(
        buildings, georef, route_len_m, route_width_m, lat, lon, extent_m,
        home_alt, site_id, auto_layout=auto_layout)
    planes = _tile_plane(lat, lon, extent_m, lod, rings)
    jobs = []
    for level, half, keys in planes:
        for (tx, ty, tz) in keys:
            jobs.append((tx, ty, tz, level == lod))
    detail_px = int(texture_px or 512)
    coarse_px = int(texture_px or 256)
    log(0.15, "生成 %d 个瓦片（%d 个含建筑）…" % (
        len(jobs), sum(1 for j in jobs if j[3])))

    bbox_of = {}
    for b in buildings:
        p = b["poly"]
        bbox_of[b["id"]] = (min(x[0] for x in p), min(x[1] for x in p),
                            max(x[0] for x in p), max(x[1] for x in p))
    by_id = {b["id"]: b for b in buildings}

    done = {"n": 0}
    lock = __import__("threading").Lock()
    results = []

    def do_tile(job):
        tx, ty, tz, with_build = job
        south, west, north, east = tile_box_lonlat(tx, ty, tz)
        mb = MeshBuilder()
        n = int(grid) if with_build else max(16, int(grid) // 2)
        build_terrain(mb, (tx, ty, tz), n, sample, georef)
        nb = 0
        if with_build:
            for b in buildings:
                if b["id"] not in keep_ids:
                    continue
                s, w, nn, e = bbox_of[b["id"]]
                if nn < south or s > north or e < west or w > east:
                    continue
                poly = b["poly"]
                plats = np.array([p[0] for p in poly])
                plons = np.array([p[1] for p in poly])
                ground = sample(plats, plons)
                gmin = float(np.min(ground))
                base = gmin + float(b.get("min_h") or 0.0)
                top = base + float(b["h"])
                add_building(mb, poly, np.full(len(poly), base), top,
                             georef, (tx, ty, tz), sample)
                nb += 1
        png = build_texture(provider, tz, tx, ty,
                            detail_px if with_build else coarse_px, offline=offline)
        v, u, t = mb.arrays()
        path = os.path.join(tiles_dir, tile_to_quadkey(tx, ty, tz) + ".glb")
        nbytes = write_glb(path, v, u, t, png)
        with lock:
            done["n"] += 1
            log(0.15 + 0.8 * done["n"] / max(1, len(jobs)),
                "瓦片 %d/%d（%s，建筑 %d）" % (done["n"], len(jobs),
                                              tile_to_quadkey(tx, ty, tz), nb))
        return {"tile": "%d/%d/%d" % (tx, ty, tz),
                "quadkey": tile_to_quadkey(tx, ty, tz),
                "lod": tz, "buildings": nb, "verts": int(v.shape[0]),
                "tris": int(t.shape[0]) // 3, "bytes": int(nbytes)}

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        for r in ex.map(do_tile, jobs):
            results.append(r)

    manifest = {
        "site_id": site_id,
        "lat": lat, "lon": lon,
        "home_alt_m": home_alt,
        "buildings_ok": not buildings_err,
        "buildings_error": buildings_err,
        "extent_m": extent_m, "lod": lod, "rings": rings, "grid": int(grid),
        "provider": provider,
        "tiles_dir": tiles_dir.replace("\\", "/"),
        "tiles_lod_min": lod - rings, "tiles_lod_max": lod,
        "tile_count": len(results),
        "building_total": len(buildings),
        "building_kept": len(keep_ids),
        "building_removed": sorted(set(by_id) - set(keep_ids))[:200],
        "planner": planner_info,
        "scene_yaml": os.path.join(SCENES_DIR, site_id + ".yaml").replace("\\", "/"),
        "start": [float(scene.start[0]), float(scene.start[1])],
        "goal": [float(scene.goal[0]), float(scene.goal[1])],
        "map": {"x_min": scene.x_min, "x_max": scene.x_max,
                "y_min": scene.y_min, "y_max": scene.y_max},
        "footprints": "_footprints.json",
        "bytes_total": int(sum(r["bytes"] for r in results)),
        "elapsed_s": round(time.time() - t_start, 1),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tiles": results,
    }
    with open(os.path.join(tiles_dir, "_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    foot = []
    for bld in buildings:
        if bld["id"] not in keep_ids:
            continue
        foot.append({"id": bld["id"], "h": bld.get("h"),
                     "min_h": bld.get("min_h") or 0.0,
                     "poly": [[round(float(a), 7), round(float(o), 7)]
                              for (a, o) in bld["poly"]]})
    with open(os.path.join(tiles_dir, "_footprints.json"), "w", encoding="utf-8") as f:
        json.dump({"site_id": site_id, "lat": lat, "lon": lon,
                   "home_alt_m": home_alt, "count": len(foot),
                   "buildings": foot, "buildings_error": buildings_err},
                  f, ensure_ascii=False)

    log(0.97, "写入场景 yaml…")
    scene.gis = {
        "scene_type": "CustomGIS",
        "tiles_dir": tiles_dir.replace("\\", "/"),
        "tiles_lod_min": lod - rings,
        "tiles_lod_max": lod,
        "site_id": site_id,
        "provider": provider,
    }
    scene.home_geo_point = {"latitude": lat, "longitude": lon, "altitude": home_alt}
    scene.geo = dict(scene.geo or {})
    scene.geo.update({"gis_site": site_id, "gis_alt_m": round(home_alt, 2),
                      "provider": provider})
    os.makedirs(SCENES_DIR, exist_ok=True)
    scene_path = os.path.join(SCENES_DIR, site_id + ".yaml")
    scene.dump(scene_path)
    manifest["scene_yaml"] = scene_path.replace("\\", "/")
    if preview:
        try:
            log(0.99, "渲染俯视真实影像底图…")
            manifest["preview"] = build_preview(site_id, provider=provider,
                                                offline=offline, force=True)
            manifest["preview_url"] = "/api/gis/topdown.png?site=" + site_id
        except Exception as exc:  # noqa: BLE001
            manifest["preview_error"] = "%s" % exc
    log(1.0, "完成：%d 个瓦片 / %.1f MB / %.0fs" % (
        len(results), manifest["bytes_total"] / 1048576.0, manifest["elapsed_s"]))
    return {"scene": scene, "manifest": manifest, "scene_path": scene_path}


def build_planner_scene(buildings, georef, route_len_m, route_width_m,
                        lat, lon, extent_m, home_alt, site_id,
                        resolution=1.0, auto_layout=True):
    """真实建筑 -> NED 障碍盒子 -> 可飞走廊场景

    返回 (scene, keep_ids, info)：
      keep_ids = 允许渲染进 3D 瓦片的建筑 id 集合。
      被规划层丢弃的建筑（挡在直线航道上/过密被裁掉）同时从瓦片中删除，
      保证"看到什么 = 避开什么"（视觉与规划一致）。
    """
    from scene_config import SceneConfig, Obstacle
    import worldgen

    half_len = route_len_m / 2.0
    half_wid = route_width_m / 2.0
    all_boxes = []
    idx = 0
    for b in buildings:
        poly = b["poly"]
        ns, es = [], []
        for (la, lo) in poly:
            nn, ee, _dd = georef.latlon_to_ned(float(la), float(lo), home_alt)
            ns.append(nn)
            es.append(ee)
        x0, x1 = min(ns), max(ns)
        y0, y1 = min(es), max(es)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        w, hgt = max(1.5, x1 - x0), max(1.5, y1 - y0)
        idx += 1
        name = "B%04d" % idx
        all_boxes.append((name, b["id"], Obstacle(
            name=name, x=cx, y=cy, w=w, h=hgt,
            height=max(1.0, float(b["h"]) + float(b.get("min_h") or 0.0)),
            base_z=0.0, kind="building")))

    # v5.0 自动选走廊：在 "南北向 / 东西向 x 少量横向偏移" 中挑建筑最多的一条，
    # 避免选点在河面/广场/主干道上时得到一条没有障碍物的空走廊。
    def _count(box):
        n = 0
        for (_nm, _bid, o) in all_boxes:
            if (box[0] - 3.0 <= o.x <= box[1] + 3.0
                    and box[2] - 3.0 <= o.y <= box[3] + 3.0):
                n += 1
        return n

    def _slice(box):
        bx0, bx1, by0, by1 = box
        mp, bs = {}, []
        for (_nm, _bid, o) in all_boxes:
            if (bx0 - 40.0 <= o.x <= bx1 + 40.0
                    and by0 - 40.0 <= o.y <= by1 + 40.0):
                mp[_nm] = _bid
                bs.append(o)
        return mp, bs

    def _axis(orient):
        # GIS 场景 x=北、y=东：orient="ns" 走廊沿 x，航线也沿 x；
        # orient="ew" 走廊沿 y，航线必须沿 y（早期版本这里恒按 x 取起终点，导致航线只有走廊宽度那么长）
        return "y" if orient == "ew" else "x"

    if auto_layout:
        cands = []
        for orient in ("ns", "ew"):
            hx = half_len if orient == "ns" else half_wid
            hy = half_wid if orient == "ns" else half_len
            for k in (0.0, 0.6, -0.6, 1.2, -1.2, 1.8, -1.8, 2.4, -2.4):
                ox = (k * route_width_m) if orient == "ew" else 0.0
                oy = (k * route_width_m) if orient == "ns" else 0.0
                box = (ox - hx, ox + hx, oy - hy, oy + hy)
                cands.append((_count(box), orient, k, box))
        cands.sort(key=lambda c: (-c[0], abs(c[2]), 0 if c[1] == "ns" else 1))
    else:
        _box = (-half_len, half_len, -half_wid, half_wid)
        cands = [(_count(_box), "ns", 0.0, _box)]

    # 依次尝试候选走廊，取第一条能真正选出起终点的：避免"建筑最多但塞不进航线"
    # 的走廊被选中后起终点取不到 → 整条走廊建筑被清空 → 0 障碍空场景。
    best = None
    for _cnt, _orient, _k, _box in cands[:24]:
        _mp, _bs = _slice(_box)
        _st, _gl, _tr = worldgen.choose_start_goal(
            _bs, _box[0], _box[1], _box[2], _box[3], resolution,
            axis=_axis(_orient))
        if _st is not None:
            best = (_cnt, _orient, _k, _box, _mp, _bs, _st, _gl, _tr)
            break
    if best is None:
        _cnt, _orient, _k, _box = cands[0]
        best = (_cnt, _orient, _k, _box) + _slice(_box) + (None, None, [])

    count_in_box, orient, offset_ratio, _box, name_to_bid, boxes, start, goal, tried = best
    x_min, x_max, y_min, y_max = _box
    layout = {"orient": orient, "offset_ratio": offset_ratio,
              "buildings": count_in_box}
    dropped = set()
    if start is None:
        for o in boxes:
            dropped.add(o.name)
        boxes = []
        cx = (x_min + x_max) / 2.0
        cy = (y_min + y_max) / 2.0
        if orient == "ew":
            start = (cx, y_min + 8.0)
            goal = (cx, y_max - 8.0)
        else:
            start = (x_min + 8.0, cy)
            goal = (x_max - 8.0, cy)
    else:
        for nm in worldgen.clear_buildings_on_lane(boxes, start, goal):
            dropped.add(nm)
        guard = 0
        while boxes and guard < 60:
            guard += 1
            if worldgen._a_star_ok(boxes, x_min, x_max, y_min, y_max,
                                   resolution, start, goal):
                break
            dropped.add(boxes.pop(0).name)
    reachable = (not boxes) or worldgen._a_star_ok(
        boxes, x_min, x_max, y_min, y_max, resolution, start, goal)

    keep_ids = set(b["id"] for b in buildings)
    for nm in dropped:
        bid = name_to_bid.get(nm)
        if bid is not None:
            keep_ids.discard(bid)

    scene = SceneConfig(
        scene_id="Gis_" + site_id,
        x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max,
        resolution=resolution,
        start=[float(start[0]), float(start[1])],
        goal=[float(goal[0]), float(goal[1])],
        obstacles=boxes,
        takeoff_height=-12.0, route_mode="astar", altitude_margin=2.0,
        use_drl=False,
        geo={"source": "gis-tiles", "center": [lat, lon],
             "extent_m": float(extent_m), "home_alt_m": round(float(home_alt), 2)},
    )
    info = {
        "route_len_m": float(route_len_m),
        "route_width_m": float(route_width_m),
        "layout": layout,
        "obstacles": len(boxes),
        "dropped": len(dropped),
        "reachable": bool(reachable),
        "lane_tried": len(tried),
    }
    return scene, keep_ids, info

def _merc_px(lat, lon, z):
    """经纬度 -> Web Mercator 全局像素坐标（256 px/tile）"""
    n = float(1 << int(z))
    la = np.radians(np.asarray(lat, dtype=np.float64))
    lo = np.asarray(lon, dtype=np.float64)
    px = (lo + 180.0) / 360.0 * n * 256.0
    py = (1.0 - np.arcsinh(np.tan(la)) / math.pi) / 2.0 * n * 256.0
    return px, py


def pick_zoom(lat, m_per_px, zmin=3, zmax=19):
    """按地面分辨率反解 Web Mercator 层级"""
    if not m_per_px or m_per_px <= 0:
        return int(zmax)
    denom = 156543.03392804097 * max(0.05, math.cos(math.radians(lat)))
    z = math.log(denom / float(m_per_px), 2.0)
    return int(max(zmin, min(zmax, round(z))))


def render_topdown_image(lat, lon, home_alt, x_min, x_max, y_min, y_max,
                         width=None, max_px=1600000, provider="sat",
                         offline=False, z=None, workers=8):
    """渲染与 NED 地图矩形严格对齐的俯视影像（真实地形/建筑纹理）

    像素 (u, v) -> NED：
        east  = y_min + (u + 0.5) / W * (y_max - y_min)
        north = x_max - (v + 0.5) / H * (x_max - x_min)
    返回 (PIL.Image RGBA, meta)
    """
    from PIL import Image
    xr = float(x_max) - float(x_min)
    yr = float(y_max) - float(y_min)
    if xr <= 0 or yr <= 0:
        raise ValueError("地图矩形非法: %s" % ((x_min, x_max, y_min, y_max),))
    # W = 列 = 东西向(east, yr)；H = 行 = 南北向(north, xr)
    # 用长边定像素数，另一轴按地理比例换算，保证像素各向同性
    long_side = int(width) if width else 1400
    long_side = max(64, min(4096, long_side))
    if xr >= yr:
        H = long_side
        W = max(32, int(round(long_side * yr / xr)))
    else:
        W = long_side
        H = max(32, int(round(long_side * xr / yr)))
    if W * H > max_px:
        k = math.sqrt(float(max_px) / float(W * H))
        W = max(32, int(W * k))
        H = max(32, int(H * k))
    m_per_px = xr / float(W)
    if z is None:
        z = pick_zoom(lat, m_per_px)
    z = int(max(0, min(20, z)))
    georef = GeoRef(lat, lon, home_alt)
    uu = (np.arange(W, dtype=np.float64) + 0.5) / W
    vv = (np.arange(H, dtype=np.float64) + 0.5) / H
    east = float(y_min) + uu * yr
    north = float(x_max) - vv * xr
    E, N = np.meshgrid(east, north)  # 注意: meshgrid(xgv, ygv) -> (H, W)
    la, lo, _al = georef.ned_array_to_latlon(N, E, 0.0)
    pxs, pys = _merc_px(la, lo, z)
    n = float(1 << z)
    x0 = max(0, int(math.floor(float(np.min(pxs)) / 256.0)))
    y0 = max(0, int(math.floor(float(np.min(pys)) / 256.0)))
    x1 = min(int(n) - 1, int(math.floor(float(np.max(pxs)) / 256.0)))
    y1 = min(int(n) - 1, int(math.floor(float(np.max(pys)) / 256.0)))
    mos = imagery_mosaic(provider, z, x0, y0, x1, y1,
                         offline=offline, workers=workers)
    meta = {"zoom": z, "width": W, "height": H, "m_per_px": round(m_per_px, 4),
            "provider": provider, "degraded": False,
            "tile_range": [x0, y0, x1, y1],
            "tiles": (x1 - x0 + 1) * (y1 - y0 + 1)}
    if mos is None:
        return Image.new("RGBA", (W, H), (120, 125, 118, 255)), meta
    arr = np.asarray(mos.convert("RGB"), dtype=np.float32)
    mh, mw = arr.shape[0], arr.shape[1]
    fx = np.clip(pxs - x0 * 256.0, 0.0, mw - 1.001)
    fy = np.clip(pys - y0 * 256.0, 0.0, mh - 1.001)
    ixf = np.floor(fx).astype(np.int64)
    iyf = np.floor(fy).astype(np.int64)
    dx = (fx - ixf)[..., None]
    dy = (fy - iyf)[..., None]
    out = (arr[iyf, ixf] * (1 - dx) * (1 - dy) + arr[iyf, ixf + 1] * dx * (1 - dy)
           + arr[iyf + 1, ixf] * (1 - dx) * dy + arr[iyf + 1, ixf + 1] * dx * dy)
    return Image.fromarray(out.astype(np.uint8), "RGB").convert("RGBA"), meta


def preview_paths(site_id):
    d = os.path.join(TILES_ROOT, site_id)
    return (os.path.join(d, "_topdown.png"), os.path.join(d, "_topdown.json"))


def build_preview(site_id, provider=None, width=None, offline=False, force=False,
                  map_override=None):
    """为已生成站点渲染俯视底图 -> config/gis_tiles/<site>/_topdown.{png,json}

    map_override: 可选 {x_min,x_max,y_min,y_max}。编辑器左栏改了地图矩形后
    点「重绘底图」时传入，按当前矩形重渲染；不传则用场景 yaml 里的矩形。
    """
    from scene_config import SceneConfig
    png, meta_path = preview_paths(site_id)
    if os.path.isfile(png) and os.path.isfile(meta_path) and not force:
        try:
            with open(meta_path, encoding="utf-8") as f:
                m = json.load(f)
            m["cached"] = True
            return m
        except Exception:  # noqa: BLE001
            pass
    scene_path = os.path.join(SCENES_DIR, site_id + ".yaml")
    if not os.path.isfile(scene_path):
        raise RuntimeError("场景文件不存在: %s" % scene_path)
    sc = SceneConfig.load(scene_path)
    hp = sc.home_geo_point or {}
    if hp.get("latitude") is None:
        raise RuntimeError("场景缺少 home_geo_point，非 GIS 场景: %s" % site_id)
    lat = float(hp["latitude"])
    lon = float(hp["longitude"])
    alt = float(hp.get("altitude") or 0.0)
    if provider is None:
        provider = (sc.gis or {}).get("provider") or "sat"
    x_min, x_max, y_min, y_max = sc.x_min, sc.x_max, sc.y_min, sc.y_max
    if isinstance(map_override, dict):
        try:
            ox0 = float(map_override["x_min"]); ox1 = float(map_override["x_max"])
            oy0 = float(map_override["y_min"]); oy1 = float(map_override["y_max"])
            if ox1 - ox0 > 0 and oy1 - oy0 > 0:
                x_min, x_max, y_min, y_max = ox0, ox1, oy0, oy1
        except (KeyError, TypeError, ValueError):
            pass
    img, meta = render_topdown_image(
        lat, lon, alt, x_min, x_max, y_min, y_max,
        width=width, provider=provider, offline=offline)
    os.makedirs(os.path.dirname(png), exist_ok=True)
    img.save(png, format="PNG", optimize=True)
    meta.update({
        "site_id": site_id, "lat": lat, "lon": lon, "home_alt_m": alt,
        "provider": provider, "png": "_topdown.png", "cached": False,
        "map": {"x_min": x_min, "x_max": x_max,
                "y_min": y_min, "y_max": y_max},
        "extent_m": float((sc.geo or {}).get("extent_m") or 0.0),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta


def peek_cache_key(lat, lon, extent_m=1200.0, route_len_m=600.0,
                   route_width_m=160.0, provider="sat", offline=False):
    """预览缓存键（与 peek_plan 内部完全一致）。后台任务用它去重、前端用它轮询进度。

    前缀是预览算法版本：算法改动后旧缓存自动失效，避免预览与真实生成不一致。
    """
    return hashlib.md5(("v2|%.6f|%.6f|%.1f|%.1f|%.1f|%s|%d" % (
        float(lat), float(lon), float(extent_m), float(route_len_m),
        float(route_width_m), provider,
        int(bool(offline)))).encode("utf-8")).hexdigest()[:16]


def peek_paths(key):
    d = os.path.join(TILES_ROOT, "_peek", key)
    return (d, os.path.join(d, "_topdown.png"), os.path.join(d, "_plan.json"),
            os.path.join(d, "_footprints.json"))


def peek_prune(keep=12, max_age_h=48.0):
    """清理 _peek 预览缓存：只保留最近使用的 keep 个，且丢弃超过 max_age_h 未用的"""
    root = os.path.join(TILES_ROOT, "_peek")
    if not os.path.isdir(root):
        return 0
    now = time.time()
    items = []
    for name in os.listdir(root):
        fp = os.path.join(root, name)
        if not os.path.isdir(fp):
            continue
        try:
            items.append((os.path.getmtime(fp), fp))
        except OSError:
            continue
    items.sort(key=lambda x: -x[0])
    removed = 0
    for idx, (mt, fp) in enumerate(items):
        if idx < int(keep) and (now - mt) < float(max_age_h) * 3600.0:
            continue
        shutil.rmtree(fp, ignore_errors=True)
        removed += 1
    return removed


def peek_plan(lat, lon, extent_m=1200.0, route_len_m=600.0, route_width_m=160.0,
              provider="sat", offline=False, width=1000, force=False,
              max_buildings=6000, progress=None, buildings_deadline_s=45.0,
              skip_buildings=False, allow_no_buildings=True):
    """轻量预览：算出「将要生成的走廊」+ 该地区真实影像 + 真实建筑轮廓

    与 build_site 共用同一套 DEM 采样 / OSM 建筑 / 走廊自动布局算法，
    因此预览矩形、起终点、障碍数 = 真正生成后的结果（差别只是不写 3D 瓦片）。
    结果缓存到 config/gis_tiles/_peek/<key>/，同参数再问一次直接读缓存。
    """
    lat = float(lat)
    lon = float(lon)
    extent_m = float(extent_m)
    route_len_m = float(route_len_m)
    route_width_m = float(route_width_m)
    key = peek_cache_key(lat, lon, extent_m, route_len_m, route_width_m,
                         provider, offline)
    d, png, plan_path, fp_path = peek_paths(key)
    if os.path.isfile(plan_path) and os.path.isfile(png) and not force:
        try:
            with open(plan_path, encoding="utf-8") as f:
                plan = json.load(f)
            plan["footprints"] = []
            if os.path.isfile(fp_path):
                with open(fp_path, encoding="utf-8") as f:
                    plan["footprints"] = json.load(f).get("buildings", [])
            plan["cached"] = True
            try:
                os.utime(d, None)
            except OSError:
                pass
            return plan
        except Exception:  # noqa: BLE001
            pass

    def _prog(frac, msg):
        if progress is None:
            return
        try:
            progress(float(frac), str(msg))
        except Exception:  # noqa: BLE001
            pass

    t0 = time.time()
    _prog(0.05, "采样 DEM 真实地形…")
    half = max(300.0, extent_m / 2.0)
    sample = dem_sampler(lat, lon, half, z=15, offline=offline)
    home_alt = float(np.asarray(sample(lat, lon)).reshape(-1)[0])

    data_half = max(extent_m / 2.0, route_len_m / 2.0) * 1.08
    # Overpass 是这一步里最慢的一段（要等最慢镜像或 deadline），期间进度条会长时间不动，
    # 前端看起来像"卡死/刷不出来"。这里起一个心跳线程按秒刷新阶段文案并缓慢爬升进度。
    _phase = {"v": "buildings"}
    _t_bld = time.time()

    def _hb_prog(frac, msg):
        if _phase["v"] == "buildings":
            _prog(frac, msg)

    def _heartbeat():
        while _phase["v"] == "buildings":
            el = time.time() - _t_bld
            frac = 0.15 + 0.30 * min(1.0, el / max(5.0, float(buildings_deadline_s)))
            _hb_prog(frac, "等待 Overpass 建筑数据… 已等 %.0f 秒"
                           "（多镜像并行，最慢的会在 %.0f 秒后放弃）"
                           % (el, float(buildings_deadline_s)))
            time.sleep(1.0)

    threading.Thread(target=_heartbeat, daemon=True).start()
    buildings_err = ""
    if skip_buildings:
        # 用户显式选择"跳过在线建筑"：不联网，直接按纯地形出预览（秒开）。
        buildings = []
        buildings_err = "已按设置跳过 OSM 在线建筑轮廓（预览只含真实地形）"
        _phase["v"] = "done"
    else:
        _prog(0.15, "拉取 OpenStreetMap 建筑（多镜像并行，通常 20~60 秒）…")
        try:
            buildings = fetch_buildings(lat, lon, data_half, offline=offline,
                                        deadline_s=buildings_deadline_s,
                                        progress=lambda m: _prog(0.45, m))
        except Exception as exc:  # noqa: BLE001
            # Overpass 不可达（内网/跨境网络被拦）不该让整个预览失败：
            # 影像 + DEM 仍然可用，降级成"纯地形、无建筑"预览。
            if not allow_no_buildings:
                raise
            buildings = []
            buildings_err = "%s: %s" % (type(exc).__name__, exc)
            _prog(0.5, "OSM 建筑数据不可用，按纯地形继续生成预览…")
        finally:
            _phase["v"] = "done"
    if len(buildings) > max_buildings:
        buildings.sort(key=lambda b: -b["h"])
        buildings = buildings[:max_buildings]

    _prog(0.62, "自动选走廊 + A* 可达性校验（%d 栋建筑）…" % len(buildings))
    georef = GeoRef(lat, lon, home_alt)
    scene, keep_ids, info = build_planner_scene(
        buildings, georef, route_len_m, route_width_m, lat, lon, extent_m,
        home_alt, site_id_for(lat, lon, "peek"))

    _prog(0.85, "渲染真实影像底图…")
    img, meta = render_topdown_image(
        lat, lon, home_alt, scene.x_min, scene.x_max, scene.y_min, scene.y_max,
        width=width, provider=provider, offline=offline)

    foot = []
    for b in buildings:
        if b["id"] not in keep_ids:
            continue
        poly = []
        for (la, lo) in b["poly"]:
            nn, ee, _dd = georef.latlon_to_ned(float(la), float(lo), 0.0)
            poly.append([round(nn, 2), round(ee, 2)])
        if len(poly) >= 3:
            foot.append({"id": b["id"], "h": b.get("h"),
                         "min_h": b.get("min_h") or 0.0, "poly": poly})

    peek_prune()
    os.makedirs(d, exist_ok=True)
    img.save(png, format="PNG", optimize=True)
    with open(fp_path, "w", encoding="utf-8") as f:
        json.dump({"key": key, "count": len(foot), "buildings": foot,
                   "buildings_error": buildings_err}, f, ensure_ascii=False)

    plan = {
        "ok": True, "key": key, "cached": False,
        "lat": lat, "lon": lon, "home_alt_m": round(home_alt, 2),
        "extent_m": extent_m, "route_len_m": route_len_m,
        "route_width_m": route_width_m, "provider": provider,
        "scene": scene.to_dict(),
        "layout": info.get("layout"), "reachable": info.get("reachable"),
        "obstacle_count": info.get("obstacles"),
        "building_total": len(buildings),
        "footprint_count": len(foot),
        "buildings_ok": not buildings_err,
        "buildings_error": buildings_err,
        "overpass_cooldown_s": round(overpass_cooldown_left(), 1),
        "png_url": "/api/gis/peek.png?key=" + key,
        "meta": meta,
        "elapsed_s": round(time.time() - t0, 2),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if buildings_err:
        # 命中缓存的判定是「_plan.json + png 同时存在」。降级结果只写 png（前端要用它出图）、
        # 不写 _plan.json：下次刷新仍会重新尝试联网抓建筑，不会把"零建筑"固化进磁盘。
        try:
            if os.path.isfile(plan_path):
                os.remove(plan_path)
        except OSError:
            pass
    else:
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False)
    plan["footprints"] = foot
    _prog(1.0, "预览完成（%.1f 秒）" % (time.time() - t0))
    return plan


def footprints_path(site_id):
    return os.path.join(TILES_ROOT, site_id, "_footprints.json")


def load_footprints_ned(site_id):
    """读取 _footprints.json 并把经纬度转换成场景 NED 坐标

    返回 [[x, y, h, min_h], ...] 每个元素是建筑底面多边形。
    前端画布直接用（x=north, y=east，与场景 map 同坐标系）。
    """
    from scene_config import SceneConfig
    fp = footprints_path(site_id)
    if not os.path.isfile(fp):
        return []
    with open(fp, encoding="utf-8") as f:
        data = json.load(f)
    scene_path = os.path.join(SCENES_DIR, site_id + ".yaml")
    if not os.path.isfile(scene_path):
        return []
    sc = SceneConfig.load(scene_path)
    hp = sc.home_geo_point or {}
    georef = GeoRef(float(hp.get("latitude")), float(hp.get("longitude")),
                    float(hp.get("altitude") or 0.0))
    out = []
    for b in data.get("buildings", []):
        poly = []
        for (la, lo) in b.get("poly", []):
            nn, ee, _dd = georef.latlon_to_ned(float(la), float(lo), 0.0)
            poly.append([round(nn, 2), round(ee, 2)])
        if len(poly) >= 3:
            out.append({"id": b.get("id"), "poly": poly,
                        "h": b.get("h"), "min_h": b.get("min_h") or 0.0})
    return out


def quadkey_to_tile(quadkey):
    """quadkey -> (x, y, lod)，TileXYToQuadkey 的逆"""
    x = y = 0
    lod = len(quadkey)
    for i, ch in enumerate(quadkey):
        d = int(ch)
        mask = 1 << (lod - i - 1)
        if d & 1:
            x |= mask
        if d & 2:
            y |= mask
    return x, y, lod


# =====================================================================
# 8. 自检 / CLI
# =====================================================================
def verify_site(site, verbose=True):
    """检查站点瓦片：命名、GLB 结构、ECEF 合理范围"""
    d = os.path.join(TILES_ROOT, site)
    mf_path = os.path.join(d, "_manifest.json")
    if not os.path.isfile(mf_path):
        raise RuntimeError("no manifest: %s" % mf_path)
    with open(mf_path, encoding="utf-8") as f:
        mf = json.load(f)
    georef = GeoRef(mf["lat"], mf["lon"], mf["home_alt_m"])
    hx, hy, hz = georef.home_ecef
    bad = []
    n_tiles = 0
    n_bytes = 0
    n_verts = 0
    n_tris = 0
    max_off = 0.0
    for t in mf.get("tiles", []):
        qk = t["quadkey"]
        path = os.path.join(d, qk + ".glb")
        if not os.path.isfile(path):
            bad.append("%s: 文件缺失" % qk)
            continue
        try:
            info = read_glb_summary(path)
        except Exception as exc:  # noqa: BLE001
            bad.append("%s: GLB 解析失败 %s" % (qk, exc))
            continue
        if info["verts"] != info["uvs"]:
            bad.append("%s: POSITION/TEXCOORD 数量不一致" % qk)
        if info["indices"] % 3 != 0:
            bad.append("%s: 索引数不是 3 的倍数" % qk)
        if not info["has_texture"]:
            bad.append("%s: 缺少纹理" % qk)
        if info["indices"] // 3 != t["tris"]:
            bad.append("%s: 索引数与 manifest 不符" % qk)
        tx, ty, tz = quadkey_to_tile(qk)
        if "%d/%d/%d" % (tx, ty, tz) != t["tile"]:
            bad.append("%s: quadkey 反解不一致" % qk)
        # ECEF 距离抽查
        with open(path, "rb") as f:
            raw = f.read()
        off = 12
        js = None
        while off < len(raw):
            clen = int(np.frombuffer(raw[off:off + 4], dtype="<u4")[0])
            ctype = raw[off + 4:off + 8]
            if ctype == b"JSON":
                js = json.loads(raw[off + 8:off + 8 + clen].decode("utf-8"))
                break
            off += 8 + clen
        acc = js["accessors"][0]
        for idx in (0, 1, 2):
            mn = acc["min"][idx]
            mx = acc["max"][idx]
            home = (hx, hy, hz)[idx]
            max_off = max(max_off, abs(mn - home), abs(mx - home))
        n_tiles += 1
        n_bytes += info["bytes"]
        n_verts += info["verts"]
        n_tris += info["tris"] // 2
    out = {
        "site": site,
        "tiles_ok": n_tiles,
        "tiles_declared": len(mf.get("tiles", [])),
        "bytes": n_bytes,
        "verts": n_verts,
        "tris": n_tris,
        "max_ecef_offset_m": round(float(max_off), 1),
        "problems": bad,
        "planner": mf.get("planner"),
        "lod_min": mf.get("tiles_lod_min"),
        "lod_max": mf.get("tiles_lod_max"),
        "tiles_dir": mf.get("tiles_dir"),
        "scene_yaml": mf.get("scene_yaml"),
    }
    if verbose:
        print("site: %s" % out["site"])
        print("瓦片: %d/%d  ok=%s" % (out["tiles_ok"], out["tiles_declared"],
                                      not bad))
        print("体积: %.2f MB  顶点: %d  三角面: %d" % (
            out["bytes"] / 1048576.0, out["verts"], out["tris"]))
        print("ECEF 与 home 最大偏移: %.1f m" % out["max_ecef_offset_m"])
        print("LOD: %s ~ %s" % (out["lod_min"], out["lod_max"]))
        print("tiles-dir: %s" % out["tiles_dir"])
        print("scene: %s" % out["scene_yaml"])
        if out["planner"]:
            p = out["planner"]
            print("规划: 障碍 %s 个, 可视丢弃 %s 个, A* 可达 %s" % (
                p.get("obstacles"), p.get("dropped"), p.get("reachable")))
        for b in bad[:40]:
            print("  [BAD] %s" % b)
        if len(bad) > 40:
            print("  ... 还有 %d 条" % (len(bad) - 40))
    return out


def cmd_build(argv):
    ap = argparse.ArgumentParser(prog="gis_tiles build",
                                 description="生成 CustomGIS 3D 瓦片站点")
    ap.add_argument("--lat", type=float, default=None)
    ap.add_argument("--lon", type=float, default=None)
    ap.add_argument("--place", default=None, help="地名（在线检索）")
    ap.add_argument("--extent", type=float, default=1200.0, help="详细区边长(m)")
    ap.add_argument("--lod", type=int, default=17, help="详细区瓦片 LOD(14~19)")
    ap.add_argument("--rings", type=int, default=2, help="外扩圈数(每圈 LOD-1, 范围x2)")
    ap.add_argument("--grid", type=int, default=64, help="地形网格顶点数/边")
    ap.add_argument("--provider", default="sat", choices=sorted(IMAGERY_PROVIDERS))
    ap.add_argument("--route-len", type=float, default=600.0)
    ap.add_argument("--route-width", type=float, default=160.0)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-preview", action="store_true",
                    help="跳过俯视真实影像底图渲染")
    args = ap.parse_args(argv)

    lat, lon = args.lat, args.lon
    if lat is None or lon is None:
        if not args.place:
            ap.error("need --lat/--lon or --place")
        import worldgen
        lat, lon, found = worldgen.geocode(args.place)
        print("地名解析: %s -> %.5f, %.5f" % (found, lat, lon))

    def progress(frac, msg):
        print("[%3d%%] %s" % (int(frac * 100), msg), flush=True)

    res = build_site(lat, lon, extent_m=args.extent, lod=args.lod,
                     rings=args.rings, grid=args.grid, provider=args.provider,
                     route_len_m=args.route_len, route_width_m=args.route_width,
                     tag=args.tag, offline=args.offline, workers=args.workers,
                     progress=progress, preview=not args.no_preview)
    m = res["manifest"]
    print("-" * 62)
    print("site_id     : %s" % m["site_id"])
    print("tiles       : %d 个, %.1f MB" % (m["tile_count"],
                                            m["bytes_total"] / 1048576.0))
    print("buildings   : 抓取 %d, 渲染 %d, 从场景剔除 %d" % (
        m["building_total"], m["building_kept"], len(m["building_removed"])))
    print("planner     : 障碍 %d, A* 可达 %s" % (
        m["planner"]["obstacles"], m["planner"]["reachable"]))
    print("home_alt    : %.1f m" % m["home_alt_m"])
    print("tiles-dir   : %s" % m["tiles_dir"])
    print("scene yaml  : %s" % res["scene_path"])
    if m.get("preview"):
        pv = m["preview"]
        print("俯视底图    : %dx%d  z=%s  (%s)" % (
            pv.get("width"), pv.get("height"), pv.get("zoom"),
            "缓存" if pv.get("cached") else "新渲染"))
    elif m.get("preview_error"):
        print("俯视底图    : 跳过 (%s)" % m["preview_error"])
    print("耗时        : %.1f s" % m["elapsed_s"])
    return 0


def cmd_info(argv):
    ap = argparse.ArgumentParser(prog="gis_tiles info")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--site", default=None)
    args = ap.parse_args(argv)
    if args.list or not args.site:
        if not os.path.isdir(TILES_ROOT):
            print("(还没有站点)")
            return 0
        for n in sorted(os.listdir(TILES_ROOT)):
            mf = os.path.join(TILES_ROOT, n, "_manifest.json")
            if not os.path.isfile(mf):
                continue
            with open(mf, encoding="utf-8") as f:
                d = json.load(f)
            print("%-34s %5d tiles %7.1f MB  %.5f,%.5f" % (
                n, d.get("tile_count", 0),
                d.get("bytes_total", 0) / 1048576.0, d.get("lat"), d.get("lon")))
        return 0
    return 0 if verify_site(args.site) else 1


def cmd_verify(argv):
    ap = argparse.ArgumentParser(prog="gis_tiles verify")
    ap.add_argument("--site", required=True)
    args = ap.parse_args(argv)
    out = verify_site(args.site)
    return 1 if out["problems"] else 0


def cmd_preview(argv):
    ap = argparse.ArgumentParser(prog="gis_tiles preview")
    ap.add_argument("--site", required=True)
    ap.add_argument("--provider", default=None, choices=sorted(IMAGERY_PROVIDERS))
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    meta = build_preview(args.site, provider=args.provider, width=args.width,
                         offline=args.offline, force=args.force)
    print("site  : %s" % args.site)
    print("image : %dx%d  z=%s  %.2f m/px" % (
        meta.get("width"), meta.get("height"), meta.get("zoom"),
        meta.get("m_per_px") or 0.0))
    print("tiles : %s  (%s)" % (meta.get("tiles"),
                                "缓存" if meta.get("cached") else "新渲染"))
    print("png   : %s" % preview_paths(args.site)[0])
    return 0


def cmd_buildings(argv):
    """导出真实建筑轮廓（NED），供前端叠加显示"""
    ap = argparse.ArgumentParser(prog="gis_tiles buildings")
    ap.add_argument("--site", required=True)
    args = ap.parse_args(argv)
    out = load_footprints_ned(args.site)
    print("site: %s  建筑: %d" % (args.site, len(out)))
    return 0


def main():
    ap = argparse.ArgumentParser(prog="gis_tiles", description="v5.0 GIS 3D 瓦片生成器")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("build", help="生成站点瓦片 + 场景")
    sub.add_parser("verify", help="校验站点瓦片")
    sub.add_parser("info", help="列出/查看站点")
    sub.add_parser("preview", help="渲染俯视真实影像底图")
    sub.add_parser("buildings", help="导出真实建筑轮廓(NED)")
    args, rest = ap.parse_known_args()
    if args.cmd == "build":
        return cmd_build(rest)
    if args.cmd == "verify":
        return cmd_verify(rest)
    if args.cmd == "info":
        return cmd_info(rest)
    if args.cmd == "preview":
        return cmd_preview(rest)
    if args.cmd == "buildings":
        return cmd_buildings(rest)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())