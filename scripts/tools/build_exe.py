# -*- coding: utf-8 -*-
"""
scripts/tools/build_exe.py - 打包 Windows 独立控制台 exe（PyInstaller）
=====================================================================
用法:
    python scripts/tools/build_exe.py

产物:
    dist/AirSim控制台.exe  ->  项目根目录 AirSim控制台.exe（双击即弹，无黑框）

说明:
    - 入口 web/webview_app.py：内嵌 Flask（本进程线程）+ pywebview 原生窗口
    - 数据目录 = exe 所在目录（config/scenes、scripts、models 需放 exe 旁）
    - 必须 --noconsole，否则会出现黑色 Python 控制台框
    - 排除 torch/scipy/pygame/pandas/matplotlib/gymnasium/tqdm：
      exe 只跑 Web 控制台，飞行/训练任务由本机系统 Python 子进程执行
      （见 web/app.py 的 _system_python()），因此无需打包这些重型依赖
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENTRY = os.path.join(ROOT, "web", "webview_app.py")
NAME = "AirSim控制台"
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")
EXCLUDES = ["torch", "scipy", "pygame", "pandas", "matplotlib", "gymnasium", "tqdm"]


def main():
    if not os.path.isfile(ENTRY):
        print("[build_exe] 入口不存在: %s" % ENTRY)
        return 1
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[build_exe] 未安装 PyInstaller，先执行: pip install pyinstaller")
        return 1

    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean", "--onefile", "--noconsole",
           "--name", NAME,
           "--paths", ROOT,
           "--distpath", DIST,
           "--workpath", WORK]
    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]
    cmd.append(ENTRY)

    print("[build_exe] ROOT = %s" % ROOT)
    print("[build_exe] 命令: %s" % " ".join(cmd))
    code = subprocess.call(cmd, cwd=ROOT)
    if code != 0:
        print("[build_exe] PyInstaller 失败 (code=%d)" % code)
        return code

    exe = os.path.join(DIST, NAME + ".exe")
    target = os.path.join(ROOT, NAME + ".exe")
    if os.path.isfile(exe):
        shutil.copy2(exe, target)
        print("[build_exe] 完成: %s (%d MB)" % (target, os.path.getsize(target) // (1024 * 1024)))
    else:
        print("[build_exe] 未找到产物: %s" % exe)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
