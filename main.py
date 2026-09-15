# -*- coding: utf-8 -*-
"""AirSim Hybrid Avoidance v5.6 - 统一入口

用法:
  python main.py                    弹出 Windows 原生控制台窗口（WebView2 内核，现代界面）
  python main.py --browser          改用浏览器打开控制台（备用）
  python main.py --menu             使用命令行菜单（高级用户）
  python main.py --editor           启动网页场景编辑器（拖拽编辑地图/障碍/起终点）
  python main.py --scene <yaml> --flights 3   指定场景连续飞行
  python main.py --scene <yaml> --single      指定场景单次飞行
  python main.py --scene <yaml> --eval        指定场景平滑度评估（无需 UE）
  python main.py --scene <yaml> --train       指定场景重训 DRL
  python main.py --check             检查 UE 连接
"""
import os
import sys
import socket
import subprocess
import glob
import time

from web._stdout import setup_stdout
setup_stdout()

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
UE_PORT = 8990
SCENES_DIR = os.path.join(ROOT, 'config', 'scenes')

SCRIPTS = {
    'single': os.path.join(ROOT, 'scripts', 'fly', 'run_hybrid.py'),
    'flights': os.path.join(ROOT, 'scripts', 'fly', 'run_v2_demo.py'),
    'eval': os.path.join(ROOT, 'scripts', 'evaluate', 'evaluate_smoothness.py'),
    'train': os.path.join(ROOT, 'scripts', 'train', 'train_drl_v2.py'),
    'editor': os.path.join(ROOT, 'web', 'app.py'),
}
LOG_DIR = os.path.join(ROOT, 'logs')
EDITOR_LOG = os.path.join(LOG_DIR, 'editor_server.log')
EDITOR_PORT = int(os.environ.get('AIRSIM_PORT', '8787') or '8787')


def check_ue(timeout=2.0):
    """检测 UE 端口是否可连接"""
    try:
        s = socket.create_connection(('127.0.0.1', UE_PORT), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def run_script(script, args, label):
    print('')
    print('=' * 55)
    print(label)
    print('=' * 55)
    cmd = [PY, script] + args
    return subprocess.call(cmd, cwd=ROOT)


def list_scenes():
    return sorted(glob.glob(os.path.join(SCENES_DIR, '*.yaml')))


def scene_desc(path):
    try:
        from scene_config import SceneConfig
        s = SceneConfig.load(path)
        return '%s (%.0fx%.0fm, %d 障碍, %s->%s)' % (
            s.id, s.x_max - s.x_min, s.y_max - s.y_min, len(s.obstacles),
            [round(v, 1) for v in s.start], [round(v, 1) for v in s.goal])
    except Exception as e:
        return '加载失败: %s' % e


def pick_scene():
    scenes = list_scenes()
    if not scenes:
        print('未找到场景文件（config/scenes/*.yaml）。先用 python main.py --editor 创建。')
        return None
    print('可用场景:')
    for i, s in enumerate(scenes, 1):
        print('  %d) %s   [%s]' % (i, os.path.relpath(s, ROOT), scene_desc(s)))
    sel = input('选择场景编号 [1]: ').strip()
    idx = int(sel) - 1 if sel.isdigit() and 1 <= int(sel) <= len(scenes) else 0
    return scenes[idx]


def cmd_single(scene_path=None):
    args = []
    if scene_path:
        args += ['--scene', scene_path]
    else:
        args += ['--goal_x', '100', '--goal_y', '0']
    args += ['--max_steps', '2000']
    return run_script(SCRIPTS['single'], args, '单次避障飞行')


def cmd_flights(n, scene_path=None):
    args = ['--flights', str(n)]
    if scene_path:
        args += ['--scene', scene_path]
    return run_script(SCRIPTS['flights'], args,
                      '连续飞行 %d 次（自动 LoadScene + 校验）' % n)


def cmd_eval(scene_path=None):
    args = ['--vel-tc', '0.1', '--n', '60']
    if scene_path:
        args += ['--scene', scene_path]
    return run_script(SCRIPTS['eval'], args, '2D 平滑度评估（无需 UE）')


def cmd_train(scene_path=None):
    args = ['--episodes', '1500']
    if scene_path:
        args += ['--scene', scene_path]
    return run_script(SCRIPTS['train'], args, 'DRL 重训（会覆盖 ddpg_best.pth）')


def _port_open(port, timeout=0.4):
    try:
        s = socket.create_connection(('127.0.0.1', port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _tail_log(path, n=15, offset=0):
    """读取日志文件 offset 之后的最后 n 行（只看本次启动产生的输出）"""
    try:
        with open(path, 'rb') as f:
            f.seek(offset)
            data = f.read()
        lines = [ln for ln in data.decode('utf-8', 'replace').splitlines() if ln.strip()]
        return '\n'.join(lines[-n:])
    except Exception:
        return ''


def _ensure_server(wait_s=25.0):
    """确保 127.0.0.1:<EDITOR_PORT> 有 Flask 服务在跑。

    返回 True = 服务可连接；False = 启动失败/超时。
    失败时打印可操作的排查信息，子进程输出留在 logs/editor_server.log。
    """
    if _port_open(EDITOR_PORT):
        return True

    offset = 0
    log = None
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        if os.path.isfile(EDITOR_LOG):
            offset = os.path.getsize(EDITOR_LOG)
        log = open(EDITOR_LOG, 'ab')
    except OSError as e:
        print('无法写入日志 %s: %s' % (EDITOR_LOG, e))

    if log is not None:
        log.write(('\n%s\n[%s] 启动编辑器服务: %s\n'
                   % ('=' * 58, time.strftime('%Y-%m-%d %H:%M:%S'),
                      SCRIPTS['editor'])).encode('utf-8'))
        log.flush()

    try:
        subprocess.Popen([PY, '-X', 'utf8', SCRIPTS['editor']], cwd=ROOT,
                         stdout=(log if log is not None else subprocess.DEVNULL),
                         stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError as e:
        print('启动编辑器服务失败: %s' % e)
        return False

    print('正在启动编辑器服务 ...', end='')
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if _port_open(EDITOR_PORT):
            print(' 就绪（%.1f 秒）' % (time.time() - t0))
            return True
        time.sleep(0.3)

    print(' 超时')
    print('-' * 58)
    print('编辑器服务未能启动（%.0f 秒内 127.0.0.1:%d 无响应）。'
          % (wait_s, EDITOR_PORT))
    print('页面会一直空白/无法操作，常见原因:')
    print('  1) 缺依赖      pip install -r requirements.txt')
    print('  2) 端口被占用  上一次的进程未退出（换机/重启后仍占用）')
    print('  3) 代码报错    见日志 %s' % os.path.relpath(EDITOR_LOG, ROOT))
    print('-' * 58)
    tail = _tail_log(EDITOR_LOG, 15, offset)
    if tail:
        print('最近日志:')
        print(tail)
        print('-' * 58)
    return False


def _open_url(url):
    try:
        import webbrowser
        webbrowser.open(url)
        return True
    except Exception:
        return False


def _open_native_window():
    """优先弹出 Windows 原生窗口（WebView2 内核）；不可用时返回 False"""
    try:
        from web.webview_app import open_window
    except Exception as e:
        print('原生窗口不可用，回退浏览器: %s' % e)
        return False
    return open_window()


def cmd_console():
    url = 'http://127.0.0.1:%d/console' % EDITOR_PORT
    if _open_native_window():
        return 0
    if not _ensure_server():
        return 1
    print('打开控制台: %s' % url)
    if not _open_url(url):
        print('浏览器未能自动打开，请手动访问上面的地址。')
    return 0


def cmd_console_browser():
    url = 'http://127.0.0.1:%d/console' % EDITOR_PORT
    if not _ensure_server():
        return 1
    print('打开控制台: %s' % url)
    if not _open_url(url):
        print('浏览器未能自动打开，请手动访问上面的地址。')
    return 0


def cmd_editor():
    url = 'http://127.0.0.1:%d/' % EDITOR_PORT
    if not _ensure_server():
        return 1
    print('打开网页场景编辑器: %s' % url)
    if not _open_url(url):
        print('浏览器未能自动打开，请手动访问上面的地址。')
    return 0


def menu(init_scene=None):
    scene_path = init_scene
    while True:
        print('')
        print('=' * 60)
        print(' AirSim Hybrid Avoidance v5.6  -  无人机混合避障导航')
        print('=' * 60)
        # 状态栏
        ue = '已连接 (端口 %d)' % UE_PORT if check_ue() else '未连接（先启动 UE 再飞行）'
        print(' 状态: UE %s' % ue)
        if scene_path:
            print(' 场景: %s   [%s]' % (os.path.relpath(scene_path, ROOT), scene_desc(scene_path)))
        else:
            print(' 场景: 默认 100x10 走廊')
        print(' 新手流程: [1]选场景 - [2]改场景 - [3/4]飞行 - [5]评估 - [6]重训')
        print('-' * 60)
        print(' 【场景】')
        print('   1. 选择场景            查看/切换 config/scenes 下的场景')
        print('   2. 网页场景编辑器      浏览器拖拽编辑地图/障碍物/起终点')
        print(' 【飞行】（需 UE 已启动）')
        print('   3. 单次避障飞行        从起点飞到终点（1 次）')
        print('   4. 连续飞行            连飞 N 次 + 自动校验 PASS/FAIL')
        print(' 【训练与评估】（无需 UE）')
        print('   5. 平滑度评估          2D 仿真 60 局：成功率/碰撞/平滑度')
        print('   6. 重新训练模型        自定义布局后必须重训（覆盖 ddpg_best.pth）')
        print(' 【系统】')
        print('   7. 检查 UE 连接        检测 127.0.0.1:%d' % UE_PORT)
        print('   0. 退出')
        print('-' * 60)
        choice = input(' 输入序号: ').strip()
        if choice == '1':
            picked = pick_scene()
            if picked:
                scene_path = picked
        elif choice == '2':
            cmd_editor()
        elif choice == '3':
            cmd_single(scene_path)
        elif choice == '4':
            n = input(' 飞行次数 [3]: ').strip()
            cmd_flights(int(n) if n.isdigit() else 3, scene_path)
        elif choice == '5':
            cmd_eval(scene_path)
        elif choice == '6':
            confirm = input(' 确认重训？会覆盖 ddpg_best.pth（y/N）: ').strip().lower()
            if confirm == 'y':
                cmd_train(scene_path)
            else:
                print(' 已取消')
        elif choice == '7':
            print(' UE 连接正常' if check_ue() else ' UE 未连接')
        elif choice == '0':
            print(' 再见')
            break
        else:
            print(' 无效输入，请重新输入')
def main():
    args = sys.argv[1:]
    scene_path = None
    if '--scene' in args:
        i = args.index('--scene')
        if i + 1 < len(args):
            scene_path = args[i + 1]
    if '--editor' in args:
        sys.exit(cmd_editor())
    if '--flights' in args:
        i = args.index('--flights')
        n = int(args[i + 1]) if i + 1 < len(args) and args[i + 1].isdigit() else 3
        sys.exit(cmd_flights(n, scene_path))
    if '--single' in args:
        sys.exit(cmd_single(scene_path))
    if '--eval' in args:
        sys.exit(cmd_eval(scene_path))
    if '--train' in args:
        sys.exit(cmd_train(scene_path))
    if '--check' in args:
        print('UE 连接正常' if check_ue() else 'UE 未连接')
        sys.exit(0)
    if '--browser' in args:
        sys.exit(cmd_console_browser())
    if '--menu' in args:
        menu(scene_path)
    else:
        # 默认弹出 Windows 原生窗口（WebView2 内核），失败回退浏览器
        sys.exit(cmd_console())


if __name__ == '__main__':
    main()
