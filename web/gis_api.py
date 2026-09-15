# -*- coding: utf-8 -*-
"""web/gis_api.py - v5.0 GIS 真实地形 + 真实建筑 后端接口（Flask Blueprint）

前端「v5.0 真实地形 + 真实建筑（GIS 3D 瓦片）」面板使用：
  POST /api/gis/build        生成站点（DEM 地形 + OSM 建筑 + 卫星贴图），后台线程
  GET  /api/gis/status       进度 / 结果场景
  GET  /api/gis/sites        已生成站点列表
  GET  /api/gis/topdown.png  俯视真实影像（画布底图，与场景矩形严格对齐）
  GET  /api/gis/footprints   真实建筑轮廓（NED 坐标多边形）
  POST /api/gis/load         把已生成站点载入编辑器
  POST /api/gis/preview      重绘俯视底图
  POST /api/gis/peek         轻量预览：选区真实影像 + 真实建筑轮廓 + 走廊布局（不建 3D）
  GET  /api/gis/peek.png     预览俯视影像
"""
import json
import os
import re
import threading
import time

from flask import Blueprint, jsonify, request, send_file


def _detect_root():
    env = os.environ.get("AIRSIM_ROOT")
    if env and os.path.isdir(env):
        return env
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _detect_root()
SCENES_DIR = os.path.join(ROOT, "config", "scenes")
TILES_ROOT = os.path.join(ROOT, "config", "gis_tiles")

bp = Blueprint("gis_api", __name__)

TASK = {
    "lock": threading.Lock(),
    "busy": False,
    "progress": 0.0,
    "message": "",
    "error": "",
    "site_id": "",
    "name": "",
    "summary": "",
    "scene": None,
    "manifest": None,
}

# 预览（peek）后台任务表：左栏参数一改就发起，前端轮询进度，避免请求一挂几分钟
PEEK = {
    "lock": threading.Lock(),
    "jobs": {},
    "sem": threading.Semaphore(2),   # 同时最多跑 2 个预览，多余的排队
}
PEEK_KEEP = 40

_SAFE_SITE = re.compile(r"^[A-Za-z0-9_.-]+$")
_MANIFEST_KEYS = ("site_id", "lat", "lon", "home_alt_m", "extent_m", "lod",
                  "rings", "grid", "provider", "tiles_dir", "tiles_lod_min",
                  "tiles_lod_max", "tile_count", "building_total",
                  "building_kept", "building_removed", "planner", "scene_yaml",
                  "start", "goal", "map", "footprints", "bytes_total",
                  "elapsed_s", "generated_at", "preview", "preview_url",
                  "preview_error")


def _safe_site(site):
    site = os.path.basename(str(site or "").strip())
    if not site or not _SAFE_SITE.match(site):
        return ""
    return site


def _scene_path(site):
    return os.path.join(SCENES_DIR, site + ".yaml")


def _site_dir(site):
    return os.path.join(TILES_ROOT, site)


def _read_manifest(site):
    p = os.path.join(_site_dir(site), "_manifest.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _worker(params):
    import gis_tiles
    try:
        def progress(frac, msg):
            with TASK["lock"]:
                TASK["progress"] = float(frac)
                TASK["message"] = str(msg)

        res = gis_tiles.build_site(
            lat=params["lat"], lon=params["lon"],
            extent_m=params["extent_m"], lod=params["lod"],
            rings=params["rings"], grid=params["grid"],
            provider=params["provider"],
            route_len_m=params["route_len_m"],
            route_width_m=params["route_width_m"],
            tag=params.get("tag"), offline=params["offline"],
            workers=params["workers"], progress=progress, preview=True,
            skip_buildings=bool(params.get("skip_buildings")))
        scene = res["scene"]
        man = res["manifest"]
        _pl = man.get("planner") or {}
        _ly = _pl.get("layout") or {}
        _off_m = abs(float(_ly.get("offset_ratio") or 0.0)) * float(
            _pl.get("route_width_m") or 0.0)
        summary = ("%d 瓦片 / %.1f MB / %.0f s / 该区域建筑 %d 栋 / "
                   "走廊内障碍 %d 个（%s 向，横向偏移 %.0f m）") % (
            man["tile_count"], man["bytes_total"] / 1048576.0,
            man["elapsed_s"], man["building_kept"], _pl.get("obstacles") or 0,
            "南北" if _ly.get("orient") == "ns" else "东西", _off_m)
        with TASK["lock"]:
            TASK["scene"] = scene.to_dict()
            TASK["name"] = os.path.basename(res["scene_path"])
            TASK["site_id"] = man["site_id"]
            TASK["summary"] = summary
            TASK["manifest"] = dict((k, man.get(k)) for k in _MANIFEST_KEYS)
            TASK["message"] = "完成：" + summary
            TASK["progress"] = 1.0
            TASK["busy"] = False
    except Exception as exc:
        import traceback
        with TASK["lock"]:
            TASK["error"] = "%s: %s" % (type(exc).__name__, exc)
            TASK["message"] = traceback.format_exc()[-1500:]
            TASK["busy"] = False


@bp.route("/api/gis/build", methods=["POST"])
def gis_build():
    data = request.get_json(force=True) or {}
    lat = data.get("lat")
    lon = data.get("lon")
    if lat is None or lon is None:
        return jsonify({"ok": False, "error": "缺少 lat/lon"}), 400
    with TASK["lock"]:
        if TASK["busy"]:
            return jsonify({"ok": False, "error": "已有生成任务在运行"}), 409
        TASK["busy"] = True
        TASK["progress"] = 0.0
        TASK["message"] = "排队中…"
        TASK["error"] = ""
        TASK["site_id"] = ""
        TASK["name"] = ""
        TASK["summary"] = ""
        TASK["scene"] = None
        TASK["manifest"] = None
    params = {
        "lat": float(lat),
        "lon": float(lon),
        "extent_m": float(data.get("extent_m") or 1200.0),
        "route_len_m": float(data.get("route_len_m") or 600.0),
        "route_width_m": float(data.get("route_width_m") or 160.0),
        "lod": int(data.get("lod") or 17),
        "rings": int(data.get("rings") if data.get("rings") is not None else 2),
        "grid": int(data.get("grid") or 64),
        "provider": data.get("provider") or "sat",
        "offline": bool(data.get("offline")),
        "workers": int(data.get("workers") or 8),
        "tag": data.get("label") or data.get("tag"),
        "skip_buildings": bool(data.get("skip_buildings")),
    }
    threading.Thread(target=_worker, args=(params,), daemon=True).start()
    return jsonify({"ok": True, "message": "生成任务已开始"})


@bp.route("/api/gis/status")
def gis_status():
    with TASK["lock"]:
        return jsonify({"ok": True, "busy": TASK["busy"],
                        "progress": TASK["progress"],
                        "message": TASK["message"], "error": TASK["error"],
                        "site_id": TASK["site_id"], "name": TASK["name"],
                        "summary": TASK["summary"], "scene": TASK["scene"],
                        "manifest": TASK["manifest"]})


@bp.route("/api/gis/sites")
def gis_sites():
    out = []
    if os.path.isdir(TILES_ROOT):
        for d in sorted(os.listdir(TILES_ROOT)):
            man = _read_manifest(d)
            if not man:
                continue
            out.append({
                "site_id": man.get("site_id") or d,
                "lat": man.get("lat"), "lon": man.get("lon"),
                "extent_m": man.get("extent_m"),
                "tile_count": man.get("tile_count"),
                "buildings": man.get("building_kept"),
                "obstacles": (man.get("planner") or {}).get("obstacles"),
                "reachable": (man.get("planner") or {}).get("reachable"),
                "mb": round(float(man.get("bytes_total") or 0) / 1048576.0, 1),
                "generated_at": man.get("generated_at"),
                "scene": os.path.basename(man.get("scene_yaml") or "") or (d + ".yaml"),
                "has_scene": os.path.isfile(_scene_path(d)),
                "has_topdown": os.path.isfile(os.path.join(_site_dir(d), "_topdown.png")),
            })
    out.sort(key=lambda r: str(r.get("generated_at") or ""), reverse=True)
    return jsonify({"ok": True, "sites": out})


@bp.route("/api/gis/topdown.png")
def gis_topdown():
    site = _safe_site(request.args.get("site"))
    if not site:
        return jsonify({"ok": False, "error": "缺少 site"}), 400
    p = os.path.join(_site_dir(site), "_topdown.png")
    if not os.path.isfile(p):
        import gis_tiles
        try:
            gis_tiles.build_preview(site, offline=request.args.get("offline") == "1")
        except Exception as exc:
            return jsonify({"ok": False, "error": "%s" % exc}), 404
    if not os.path.isfile(p):
        return jsonify({"ok": False, "error": "该站点无俯视底图"}), 404
    resp = send_file(p, mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/gis/footprints")
def gis_footprints():
    site = _safe_site(request.args.get("site"))
    if not site:
        return jsonify({"ok": False, "error": "缺少 site"}), 400
    import gis_tiles
    try:
        blds = gis_tiles.load_footprints_ned(site)
    except Exception as exc:
        return jsonify({"ok": False, "error": "%s" % exc}), 500
    return jsonify({"ok": True, "site_id": site,
                    "count": len(blds), "buildings": blds})


@bp.route("/api/gis/load", methods=["POST"])
def gis_load():
    data = request.get_json(force=True) or {}
    site = _safe_site(data.get("site"))
    p = _scene_path(site) if site else ""
    if not p or not os.path.isfile(p):
        return jsonify({"ok": False, "error": "场景不存在: %s" % site}), 404
    from scene_config import SceneConfig
    sc = SceneConfig.load(p)
    return jsonify({"ok": True, "name": os.path.basename(p),
                    "site_id": site, "scene": sc.to_dict()})


@bp.route("/api/gis/preview", methods=["POST"])
def gis_preview():
    data = request.get_json(force=True) or {}
    site = _safe_site(data.get("site"))
    if not site or not os.path.isfile(_scene_path(site)):
        return jsonify({"ok": False, "error": "场景不存在: %s" % site}), 404
    import gis_tiles
    try:
        meta = gis_tiles.build_preview(site, provider=data.get("provider") or None,
                                       width=data.get("width") or None,
                                       offline=bool(data.get("offline")), force=True,
                                       map_override=data.get("map"))
    except Exception as exc:
        return jsonify({"ok": False, "error": "%s" % exc}), 500
    return jsonify({"ok": True, "meta": meta,
                    "url": "/api/gis/topdown.png?site=" + site})


def _peek_job_snapshot(job, with_plan=False):
    out = {"ok": True, "key": job["key"], "state": job["state"],
           "progress": round(float(job["progress"]), 4),
           "message": job["message"], "error": job["error"],
           "elapsed_s": round(time.time() - job["t0"], 1)}
    if with_plan and job["state"] == "done" and job["plan"]:
        out["plan"] = job["plan"]
    return out


def _peek_jobs_prune():
    jobs = PEEK["jobs"]
    if len(jobs) <= PEEK_KEEP:
        return
    done = sorted((j for j in jobs.values() if j["state"] != "running"),
                  key=lambda j: j["t0"])
    for j in done[:max(0, len(jobs) - PEEK_KEEP)]:
        jobs.pop(j["key"], None)


def _peek_start(key, fn):
    """启动（或复用）一个后台预览任务，立刻返回任务记录。"""
    with PEEK["lock"]:
        job = PEEK["jobs"].get(key)
        if job is not None and job["state"] == "running":
            return job
        job = {"key": key, "state": "running", "progress": 0.0,
               "message": "排队中…", "plan": None, "error": "",
               "t0": time.time()}
        PEEK["jobs"][key] = job
        _peek_jobs_prune()

    def _run():
        with PEEK["sem"]:
            def prog(frac, msg):
                job["progress"] = float(frac)
                job["message"] = str(msg)

            try:
                plan = fn(prog)
                job["plan"] = plan
                job["progress"] = 1.0
                job["state"] = "done"
            except Exception as exc:  # noqa: BLE001
                job["error"] = "%s: %s" % (type(exc).__name__, exc)
                job["message"] = job["error"]
                job["state"] = "error"

    threading.Thread(target=_run, daemon=True).start()
    return job


@bp.route("/api/gis/peek", methods=["POST"])
def gis_peek():
    """左栏参数一改就调用：返回该选区的真实影像 + 真实建筑轮廓 + 走廊布局。

    只做俯视影像与走廊布局，不写 3D 瓦片，所以比 /api/gis/build 快得多；
    同参数第二次调用直接命中磁盘缓存。

    body.async = true 时改为后台任务 + 轮询 /api/gis/peek/status：
    首次拉取要联网取 DEM/OSM/影像，可能十几秒到一分钟，同步阻塞会把前端卡住。
    """
    data = request.get_json(force=True) or {}
    try:
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "缺少或非法 lat/lon"}), 400
    if not (-85.0 <= lat <= 85.0) or not (-180.0 <= lon <= 180.0):
        return jsonify({"ok": False, "error": "经纬度越界"}), 400
    import gis_tiles
    kw = dict(
        lat=lat, lon=lon,
        extent_m=float(data.get("extent_m") or 1200.0),
        route_len_m=float(data.get("route_len_m") or 600.0),
        route_width_m=float(data.get("route_width_m") or 160.0),
        provider=data.get("provider") or "sat",
        offline=bool(data.get("offline")),
        width=int(data.get("width") or 1000),
        skip_buildings=bool(data.get("skip_buildings")))
    if data.get("buildings_deadline_s") is not None:
        try:
            kw["buildings_deadline_s"] = max(5.0, float(data["buildings_deadline_s"]))
        except (TypeError, ValueError):
            pass

    if not data.get("async"):
        try:
            return jsonify(gis_tiles.peek_plan(force=bool(data.get("force")), **kw))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False,
                            "error": "%s: %s" % (type(exc).__name__, exc)}), 500

    key = gis_tiles.peek_cache_key(
        lat, lon, kw["extent_m"], kw["route_len_m"], kw["route_width_m"],
        kw["provider"], kw["offline"])
    d, png, plan_path, _fp = gis_tiles.peek_paths(key)
    if bool(data.get("force")):
        pass
    elif os.path.isfile(plan_path) and os.path.isfile(png):
        # 命中磁盘缓存：仍然返回与异步任务相同的应答形状（含 plan 字段），
        # 否则前端会去轮询 /api/gis/peek/status 得到 unknown，然后反复重发。
        t0 = time.time()
        plan = gis_tiles.peek_plan(**kw)
        if plan.get("ok"):
            return jsonify({"ok": True, "key": key, "state": "done",
                            "progress": 1.0, "message": "缓存命中",
                            "cached": True,
                            "elapsed_s": round(time.time() - t0, 1),
                            "plan": plan})

    job = _peek_start(key, lambda prog: gis_tiles.peek_plan(
        progress=prog, force=bool(data.get("force")), **kw))
    snap = _peek_job_snapshot(job, with_plan=True)
    snap["cached"] = False
    return jsonify(snap)


@bp.route("/api/gis/peek/status")
def gis_peek_status():
    """轮询预览进度：state = running / done / error / unknown。"""
    key = _safe_site(request.args.get("key"))
    if not key:
        return jsonify({"ok": False, "error": "缺少 key"}), 400
    with PEEK["lock"]:
        job = PEEK["jobs"].get(key)
        if job is None:
            return jsonify({"ok": True, "key": key, "state": "unknown"})
        return jsonify(_peek_job_snapshot(job, with_plan=True))


@bp.route("/api/gis/overpass/retry", methods=["POST"])
def gis_overpass_retry():
    """清掉 Overpass 的"全部镜像不可达"冷却，让用户能立刻再试一次建筑数据。

    冷却是为了不让人连续刷新时每次都白等一整个 deadline；但用户明确点"重试"时
    就应该立刻放行，否则重试会秒失败，看起来像按钮坏了。
    """
    import gis_tiles
    gis_tiles.overpass_reset()
    return jsonify({"ok": True, "cooldown_s": round(gis_tiles.overpass_cooldown_left(), 1)})


@bp.route("/api/gis/peek.png")
def gis_peek_png():
    key = _safe_site(request.args.get("key"))
    if not key:
        return jsonify({"ok": False, "error": "缺少 key"}), 400
    p = os.path.join(TILES_ROOT, "_peek", key, "_topdown.png")
    if not os.path.isfile(p):
        return jsonify({"ok": False, "error": "预览不存在或已过期"}), 404
    resp = send_file(p, mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp