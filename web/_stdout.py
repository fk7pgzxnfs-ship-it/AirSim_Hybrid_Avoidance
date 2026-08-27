# -*- coding: utf-8 -*-
"""web/_stdout.py - stdout UTF-8 包装（幂等，整进程只包装一次）

背景：main.py / web/app.py / web/webview_app.py 各自对 sys.stdout 做
TextIOWrapper 包装；重复包装会在旧 wrapper 被垃圾回收时关闭共享 buffer，
后续再访问 sys.stdout.buffer 报 ValueError: I/O operation on closed file。
统一改走本模块 setup_stdout()，保证整进程只包装一次。
"""
import io
import sys

_DONE = False


def setup_stdout():
    """确保 sys.stdout 按 UTF-8 输出；已包装或没有可包装的 buffer 时直接返回。"""
    global _DONE
    if _DONE:
        return
    _DONE = True
    try:
        if sys.stdout is not None and getattr(sys.stdout, 'buffer', None) is not None:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass