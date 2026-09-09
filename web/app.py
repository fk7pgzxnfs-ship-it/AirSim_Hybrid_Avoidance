# -*- coding: utf-8 -*-
"""
web/app.py - v3 网页场景编辑器后端（Flask）
================================================
启动: python main.py --editor  （或 python web/app.py）
功能: 场景列表 / 加载 / 编辑 / 校验(可达性) / 保存 yaml
"""
import os
import sys

from web._stdout import setup_stdout
setup_stdout()

def _detect_root():
    env = os.environ.get("AIRSIM_ROOT")
    if env and os.path.isdir(env):
        return env
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _detect_root()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import glob
import json
import subprocess
import threading
import time

from flask import Flask, request, jsonify, send_from_directory

from scene_config import SceneConfig, DEFAULT_SCENES_DIR
from airsim_interface.projectairsim_client import check_connection

app = Flask(__name__,
            static_folder=os.path.join(ROOT, "web", "static"),
            static_url_path="/static")
SCENES_DIR = DEFAULT_SCENES_DIR
PORT = 8787


def _safe_name(name):
    name = os.path.basename(str(name or ""))
    if not name.endswith(".yaml"):
        name += ".yaml"
    return name


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/scenes")
def list_scenes():
    names = []
    if os.path.isdir(SCENES_DIR):
        for f in sorted(os.listdir(SCENES_DIR)):
            if f.endswith((".yaml", ".yml")):
                names.append(f)
    return jsonify({"scenes": names})


@app.route("/api/scene", methods=["GET"])
def get_scene():
    name = _safe_name(request.args.get("name", ""))
    path = os.path.join(SCENES_DIR, name)
    if not os.path.isfile(path):
        return jsonify({"error": "not found: %s" % name}), 404
    s = SceneConfig.load(path)
    return jsonify({"name": name, "scene": s.to_dict()})


@app.route("/api/scene", methods=["POST"])
def save_scene():
    data = request.get_json(force=True)
    name = _safe_name(data.get("name", "scene.yaml"))
    scene_data = data.get("scene") or data
    s = SceneConfig.from_dict(scene_data)
    errs = s.validate()
    if errs:
        return jsonify({"ok": False, "errors": errs}), 400
    path = os.path.join(SCENES_DIR, name)
    os.makedirs(SCENES_DIR, exist_ok=True)
    s.dump(path)
    return jsonify({"ok": True, "path": path.replace("\\", "/"), "name": name})


@app.route("/api/check", methods=["POST"])
def check_scene():
    data = request.get_json(force=True)
    s = SceneConfig.from_dict(data)
    errs = s.validate()
    if errs:
        return jsonify({"ok": False, "errors": errs,
                        "reachable": False, "message": "; ".join(errs)}), 400
    r = s.check_reachable()
    return jsonify({"ok": True, "reachable": r["reachable"], "message": r["message"]})


def _system_python():
    """任务子进程的 Python 解释器（exe 包装后 sys.executable 不可用）"""
    env_py = os.environ.get("AIRSIM_PYTHON")
    if env_py and os.path.isfile(env_py):
        return env_py
    import shutil
    for cand in ("python.exe", "python"):
        hit = shutil.which(cand)
        if hit:
            return hit
    local = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python")
    if os.path.isdir(local):
        hits = sorted(glob.glob(os.path.join(local, "Python*", "python.exe")))
        if hits:
            return hits[-1]
    return "python"


# =====================================================================
# 控制台（任务执行 + 日志）
# =====================================================================
TASK = {"proc": None, "label": "", "log": [], "lock": threading.Lock(), "code": None}


def _read_stdout(proc):
    try:
        for line in proc.stdout:
            with TASK["lock"]:
                TASK["log"].append(line.rstrip("\n"))
    except Exception:
        pass
    proc.wait()
    with TASK["lock"]:
        TASK["code"] = proc.returncode
        TASK["proc"] = None


# =====================================================================
# UE 自动连接（启动进程 + 等待端口 8990）
# =====================================================================
UE_CFG_FILE = os.path.join(ROOT, "config", "ue_launch.json")
UE_DEFAULTS = {
    "engine_exe": r"D:\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe",
    "project": r"D:\ProjectAirSim-main\unreal\Blocks 5.7\Blocks.uproject",
    "map": "GISMap",
    "extra_args": ["-game", "-windowed", "-ResX=1280", "-ResY=720"],
    "wait_seconds": 180,
}
UE = {"proc": None, "lock": threading.Lock(), "launching": False,
      "started": None, "error": ""}


def _load_ue_cfg():
    cfg = dict(UE_DEFAULTS)
    try:
        with open(UE_CFG_FILE, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def _save_ue_cfg(cfg):
    try:
        os.makedirs(os.path.dirname(UE_CFG_FILE), exist_ok=True)
        with open(UE_CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _ue_runtime():
    """只读运行态（不碰文件 IO），供 /api/status 轮询使用"""
    with UE["lock"]:
        p = UE["proc"]
        alive = p is not None and p.poll() is None
        return {"launching": UE["launching"] or alive,
                "proc_alive": alive, "error": UE["error"]}


def _ue_wait(proc, cfg):
    wait_s = float(cfg.get("wait_seconds") or 180)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if proc.poll() is not None:
            with UE["lock"]:
                UE["launching"] = False
                UE["error"] = "UE 进程提前退出 (code=%s)" % proc.returncode
            return
        if check_connection():
            with UE["lock"]:
                UE["launching"] = False
                UE["started"] = None
                UE["error"] = ""
            return
        time.sleep(1.0)
    with UE["lock"]:
        UE["launching"] = False
        UE["error"] = "等待连接超时（%ds），请确认 UE 正常启动" % int(wait_s)


@app.route("/api/ue")
def ue_info():
    cfg = _load_ue_cfg()
    rt = _ue_runtime()
    return jsonify({"connected": check_connection(), "launching": rt["launching"],
                    "proc_alive": rt["proc_alive"], "error": rt["error"],
                    "config": cfg})


@app.route("/api/ue/start", methods=["POST"])
def ue_start():
    if check_connection():
        return jsonify({"ok": True, "connected": True, "message": "UE 已连接（端口 8990）"})
    with UE["lock"]:
        if UE["launching"] or (UE["proc"] is not None and UE["proc"].poll() is None):
            return jsonify({"ok": False, "error": "UE 正在启动中，请稍候"}), 409
    cfg = _load_ue_cfg()
    exe = str(cfg.get("engine_exe") or "")
    proj = str(cfg.get("project") or "")
    if not os.path.isfile(exe):
        return jsonify({"ok": False,
                        "error": "引擎不存在: %s（可在控制台「系统」里设置 UE 路径，或编辑 config/ue_launch.json）" % exe}), 400
    if not os.path.isfile(proj):
        return jsonify({"ok": False, "error": "工程不存在: %s" % proj}), 400
    cmd = [exe, proj, str(cfg.get("map") or "GISMap")] + list(cfg.get("extra_args") or [])
    try:
        proc = subprocess.Popen(
            cmd, cwd=os.path.dirname(exe) or None,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        return jsonify({"ok": False, "error": "启动 UE 失败: %r" % e}), 500
    with UE["lock"]:
        UE["proc"] = proc
        UE["launching"] = True
        UE["started"] = time.time()
        UE["error"] = ""
    threading.Thread(target=_ue_wait, args=(proc, cfg), daemon=True).start()
    wait_s = int(cfg.get("wait_seconds") or 180)
    return jsonify({"ok": True, "connected": False,
                    "message": "正在启动 UE，等待端口 8990（最长 %d 秒）..." % wait_s})


@app.route("/api/ue/stop", methods=["POST"])
def ue_stop():
    with UE["lock"]:
        p = UE["proc"]
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "没有运行中的 UE 进程"}, 400)


@app.route("/api/ue/config", methods=["GET"])
def ue_config_get():
    return jsonify(_load_ue_cfg())


@app.route("/api/ue/config", methods=["POST"])
def ue_config_save():
    cfg = _load_ue_cfg()
    data = request.get_json(force=True) or {}
    for k in ("engine_exe", "project", "map"):
        if k in data:
            cfg[k] = str(data[k] or "").strip()
    if "wait_seconds" in data:
        try:
            cfg["wait_seconds"] = int(data["wait_seconds"])
        except (TypeError, ValueError):
            pass
    if "extra_args" in data:
        cfg["extra_args"] = [str(a) for a in (data["extra_args"] or [])]
    ok = _save_ue_cfg(cfg)
    return jsonify({"ok": ok, "config": cfg})

@app.route("/console")
def console_page():
    return send_from_directory("static", "console.html")


@app.route("/api/status")
def api_status():
    with TASK["lock"]:
        running = TASK["proc"] is not None and TASK["proc"].poll() is None
        label = TASK["label"] if running else ""
        code = TASK["code"]
        log_len = len(TASK["log"])
    rt = _ue_runtime()
    return jsonify({"ue": check_connection(), "ue_launching": rt["launching"],
                    "ue_error": rt["error"], "running": running,
                    "label": label, "code": code, "log_len": log_len})


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(force=True)
    script = data.get("script", "")
    args = data.get("args", []) or []
    label = data.get("label", "")
    script_path = os.path.join(ROOT, script)
    if not os.path.isfile(script_path):
        return jsonify({"ok": False, "error": "脚本不存在: %s" % script}), 400
    with TASK["lock"]:
        if TASK["proc"] is not None and TASK["proc"].poll() is None:
            return jsonify({"ok": False, "error": "已有任务在运行"}), 409
        TASK["log"] = ["=" * 60, label, "=" * 60]
        TASK["code"] = None
        TASK["label"] = label
        p = subprocess.Popen(
            [_system_python(), script_path] + args, cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        TASK["proc"] = p
    threading.Thread(target=_read_stdout, args=(p,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    with TASK["lock"]:
        p = TASK["proc"]
    if p is not None and p.poll() is None:
        try:
            p.terminate()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": False, "error": "没有运行中的任务"})


@app.route("/api/log")
def api_log():
    since = request.args.get("since", 0, type=int)
    with TASK["lock"]:
        lines = TASK["log"][since:]
        total = len(TASK["log"])
    return jsonify({"lines": lines, "total": total})


if __name__ == "__main__":
    print("AirSim v3 控制台/编辑器: http://127.0.0.1:%d  (Ctrl+C 停止)" % PORT)
    app.run(host="127.0.0.1", port=PORT, debug=False)
