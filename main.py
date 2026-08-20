# -*- coding: utf-8 -*-
'''AirSim Hybrid Avoidance v2.2 - 统一入口

用法:
  python main.py               交互菜单
  python main.py --flights 3   直接连续飞行 3 次（自动 LoadScene + 校验）
  python main.py --single      单次避障飞行
  python main.py --eval        2D 平滑度评估（无需 UE，约 1 分钟）
  python main.py --train       重新训练 DRL 模型（约 25 分钟）
  python main.py --check       检查 UE 连接状态
'''
import io
import os
import sys
import socket
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
UE_PORT = 8990

SCRIPTS = {
    'single': os.path.join(ROOT, 'scripts', 'fly', 'run_hybrid.py'),
    'flights': os.path.join(ROOT, 'scripts', 'fly', 'run_v2_demo.py'),
    'eval': os.path.join(ROOT, 'scripts', 'evaluate', 'evaluate_smoothness.py'),
    'train': os.path.join(ROOT, 'scripts', 'train', 'train_drl_v2.py'),
}


def check_ue(timeout=2.0):
    '''检测 UE 端口是否可连接'''
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


def cmd_single():
    return run_script(
        SCRIPTS['single'],
        ['--goal_x', '100', '--goal_y', '0', '--max_steps', '2000'],
        '单次避障飞行（100m 走廊 + 双障碍物）',
    )


def cmd_flights(n):
    return run_script(
        SCRIPTS['flights'],
        ['--flights', str(n)],
        '连续飞行 %d 次（自动 LoadScene + 校验）' % n,
    )


def cmd_eval():
    return run_script(
        SCRIPTS['eval'],
        ['--vel-tc', '0.1', '--n', '60'],
        '2D 平滑度评估（无需 UE，约 1 分钟）',
    )


def cmd_train():
    return run_script(
        SCRIPTS['train'],
        ['--episodes', '1500'],
        'DRL 重训（约 25 分钟，CPU，会覆盖 ddpg_best.pth）',
    )


def menu():
    while True:
        print('')
        print('AirSim Hybrid Avoidance v2.2')
        print('----------------------------')
        if check_ue():
            print('UE 连接: 正常（端口 %d）' % UE_PORT)
        else:
            print('UE 连接: 未检测到（端口 %d，请先启动 UE；飞行前会自动重试）' % UE_PORT)
        print('')
        print('请选择:')
        print('  1  单次避障飞行')
        print('  2  连续飞行（默认 3 次，自动校验）')
        print('  3  平滑度评估（2D 仿真，无需 UE）')
        print('  4  重新训练 DRL 模型')
        print('  5  检查 UE 连接')
        print('  0  退出')
        print('')
        choice = input('输入序号: ').strip()
        if choice == '1':
            cmd_single()
        elif choice == '2':
            n = input('飞行次数 [3]: ').strip()
            cmd_flights(int(n) if n.isdigit() else 3)
        elif choice == '3':
            cmd_eval()
        elif choice == '4':
            confirm = input('确认重训？会覆盖 ddpg_best.pth（y/N）: ').strip().lower()
            if confirm == 'y':
                cmd_train()
            else:
                print('已取消')
        elif choice == '5':
            print('UE 连接正常' if check_ue() else 'UE 未连接')
        elif choice == '0':
            print('再见')
            break
        else:
            print('无效输入')


def main():
    args = sys.argv[1:]
    if '--flights' in args:
        i = args.index('--flights')
        n = int(args[i + 1]) if i + 1 < len(args) and args[i + 1].isdigit() else 3
        sys.exit(cmd_flights(n))
    if '--single' in args:
        sys.exit(cmd_single())
    if '--eval' in args:
        sys.exit(cmd_eval())
    if '--train' in args:
        sys.exit(cmd_train())
    if '--check' in args:
        print('UE 连接正常' if check_ue() else 'UE 未连接')
        sys.exit(0)
    menu()


if __name__ == '__main__':
    main()