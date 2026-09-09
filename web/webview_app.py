# -*- coding: utf-8 -*-
"""web/webview_app.py - AirSim v3 Windows 原生弹窗（WebView2 内核渲染 Web 控制台）

两种运行方式:
  1) 开发模式:  python main.py / python web/webview_app.py
      - Flask 服务在本进程线程内启动（不再另起子进程）
      - 数据目录 = 项目根（由 __file__ 推导）
  2) 打包模式:  AirSim控制台.exe（PyInstaller --onefile --noconsole）
      - 窗口独立弹出，无黑色控制台框
      - 数据目录 = exe 所在目录（config/scenes、scripts、models 均在 exe 旁）
      - 任务执行由 web/app.py 调用本机系统 Python 后台运行

说明:
  - 渲染内核使用 Win11 自带 Edge WebView2（pywebview），界面保持现代风格
  - 窗口关闭后进程退出；若 8787 端口已有服务（如旧实例），则直接复用
"""
import io
import os
import socket
import sys
import threading
import time

from web._stdout import setup_stdout
setup_stdout()


def _detect_root():
    """数据根目录：打包模式取 exe 所在目录，开发模式取项目根"""
    env = os.environ.get('AIRSIM_ROOT')
    if env and os.path.isdir(env):
        return env
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _detect_root()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ['AIRSIM_ROOT'] = ROOT

import webview  # noqa: E402

from web.app import app as flask_app  # noqa: E402

PORT = 8787
URL = 'http://127.0.0.1:%d/console' % PORT
WINDOW_TITLE = 'AirSim v3.1 \u63a7\u5236\u53f0'


def _port_open(port, timeout=0.3):
    try:
        s = socket.create_connection(('127.0.0.1', port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _log_error(msg):
    """错误日志写入 logs/webview_error.log（无控制台环境下排查用）"""
    try:
        log_dir = os.path.join(ROOT, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        with io.open(os.path.join(log_dir, 'webview_error.log'), 'a', encoding='utf-8') as f:
            f.write(time.strftime('[%Y-%m-%d %H:%M:%S] ') + msg + '\n')
    except Exception:
        pass


def _serve_flask():
    """用 werkzeug make_server 启动（跳过 click banner，避免标准输出包装后的 fileno 异常）"""
    try:
        from werkzeug.serving import make_server
        server = make_server('127.0.0.1', PORT, flask_app, threaded=True)
        server.serve_forever()
    except Exception as e:
        _log_error('flask thread error: %r' % (e,))


def _ensure_server():
    """8787 无服务则在本进程线程内启动 Flask；返回是否本次启动"""
    if _port_open(PORT):
        return False
    threading.Thread(target=_serve_flask, daemon=True).start()
    for _ in range(80):
        if _port_open(PORT):
            return True
        time.sleep(0.1)
    return False


def open_window():
    """弹出原生窗口并阻塞直到窗口关闭；成功返回 True，异常返回 False"""
    try:
        started = _ensure_server()
        if not started:
            _log_error('ensure_server: port %d already has service or start failed (open=%s)' % (PORT, _port_open(PORT)))
    except Exception as e:
        _log_error('ensure_server error: %r' % (e,))
    try:
        webview.create_window(
            WINDOW_TITLE, URL,
            width=1360, height=860, min_size=(1080, 700),
            background_color='#f3f3f3',
        )
        webview.start()
        return True
    except Exception as e:  # noqa: BLE001 - GUI 环境异常统一回退浏览器
        print('原生窗口启动失败: %s' % e)
        return False


def main():
    ok = open_window()
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
