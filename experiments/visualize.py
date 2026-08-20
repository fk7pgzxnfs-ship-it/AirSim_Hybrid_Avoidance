"""
可视化脚本
绘制飞行轨迹（2D/3D）、训练曲线、算法对比图
"""

import sys
import os
import glob
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection
import pandas as pd
import numpy as np
from matplotlib import rcParams

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

rcParams['font.size'] = 12
rcParams['axes.grid'] = True
rcParams['grid.alpha'] = 0.3


def plot_trajectory_3d(log_path: str, obstacles: list = None,
                        save_path: str = None):
    """
    绘制 3D 飞行轨迹（带障碍物立体展示）

    Args:
        log_path: CSV日志路径
        obstacles: 障碍物列表 [[x, y, radius], ...]
        save_path: 图片保存路径
    """
    df = pd.read_csv(log_path)

    fig = plt.figure(figsize=(14, 10))
    ax = fig.add_subplot(111, projection='3d')

    # 默认障碍物
    if obstacles is None:
        obstacles = [
            [-3.0, -3.0, 1.0], [2.0, 4.0, 1.5], [5.0, -2.0, 1.0],
            [-5.0, 5.0, 1.2], [0.0, 8.0, 1.0], [8.0, 0.0, 1.3]
        ]

    # ---- 绘制障碍物（3D圆柱体） ----
    for obs in obstacles:
        ox, oy, radius = obs
        height = 10.0  # 圆柱高度

        # 生成圆柱体表面
        theta = np.linspace(0, 2 * np.pi, 30)
        z_cyl = np.linspace(-height/2, height/2, 10)
        theta_grid, z_grid = np.meshgrid(theta, z_cyl)
        x_grid = ox + radius * np.cos(theta_grid)
        y_grid = oy + radius * np.sin(theta_grid)

        # 绘制圆柱体表面
        ax.plot_surface(x_grid, y_grid, z_grid, alpha=0.4,
                       color='lightcoral', edgecolor='red', linewidth=0.3)

        # 绘制圆柱体顶部和底部圆
        for z_val in [-height/2, height/2]:
            circle_x = ox + radius * np.cos(theta)
            circle_y = oy + radius * np.sin(theta)
            ax.plot(circle_x, circle_y, z_val, 'r-', linewidth=1.5, alpha=0.6)

    # ---- 绘制地面网格 ----
    x_range = np.linspace(-15, 15, 7)
    y_range = np.linspace(-15, 15, 7)
    X, Y = np.meshgrid(x_range, y_range)
    Z = np.zeros_like(X) - 0.1
    ax.plot_wireframe(X, Y, Z, alpha=0.15, color='gray', linewidth=0.5)

    # ---- 绘制飞行轨迹（按模式着色） ----
    for mode, color, label, zorder in [
        ('GLOBAL', 'limegreen', '全局规划模式', 3),
        ('DRL', 'orange', 'DRL控制模式', 4),
        ('SAFETY', 'red', '安全切换模式', 5)
    ]:
        mask = df['mode'] == mode
        if mask.any():
            segment = df[mask]
            ax.plot(segment['x'], segment['y'], segment.get('z', -0.5),
                   color=color, linewidth=2.5, label=label, alpha=0.8, zorder=zorder)
            ax.scatter(segment['x'], segment['y'], segment.get('z', -0.5),
                      c=color, s=15, alpha=0.6, zorder=zorder)

    # ---- 标注起点和终点 ----
    ax.scatter(df['x'].iloc[0], df['y'].iloc[0], -0.5,
              c='green', s=200, marker='o', label='起点', zorder=10,
              edgecolors='black', linewidth=2)
    ax.scatter(df['x'].iloc[-1], df['y'].iloc[-1], -0.5,
              c='gold', s=200, marker='*', label='终点', zorder=10,
              edgecolors='black', linewidth=2)

    # ---- 绘制起飞/降落垂直轨迹 ----
    ax.plot([df['x'].iloc[0], df['x'].iloc[0]],
            [df['y'].iloc[0], df['y'].iloc[0]],
            [-5.0, -0.5], 'g--', alpha=0.5, linewidth=1.5, label='起飞/降落')
    ax.plot([df['x'].iloc[-1], df['x'].iloc[-1]],
            [df['y'].iloc[-1], df['y'].iloc[-1]],
            [-5.0, -0.5], 'g--', alpha=0.5, linewidth=1.5)

    # ---- 设置视角和标签 ----
    ax.set_xlabel('X (m)', fontsize=13, labelpad=10)
    ax.set_ylabel('Y (m)', fontsize=13, labelpad=10)
    ax.set_zlabel('Z (m)', fontsize=13, labelpad=10)
    ax.set_title('无人机3D避障飞行轨迹可视化', fontsize=15, fontweight='bold')

    # 设置视角（45度俯视）
    ax.view_init(elev=30, azim=-45)
    ax.set_xlim(-15, 15)
    ax.set_ylim(-15, 15)
    ax.set_zlim(-6, 5)

    ax.legend(loc='upper left', fontsize=10, framealpha=0.8)

    if save_path:
        plt.savefig(save_path, dpi=200, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        print(f"[3D] 轨迹图保存至: {save_path}")
    else:
        plt.tight_layout()
        plt.show()


def plot_trajectory_2d(log_path: str, obstacles: list = None,
                        save_path: str = None):
    """2D 轨迹图（原版保持向下兼容）"""
    df = pd.read_csv(log_path)
    fig, ax = plt.subplots(figsize=(10, 8))

    if obstacles is None:
        obstacles = [
            [-3.0, -3.0, 1.0], [2.0, 4.0, 1.5], [5.0, -2.0, 1.0],
            [-5.0, 5.0, 1.2], [0.0, 8.0, 1.0], [8.0, 0.0, 1.3]
        ]

    ax.plot(df['x'], df['y'], 'b-', linewidth=2, label='飞行轨迹')

    for mode, color, label in [('GLOBAL', 'green', '全局规划'),
                                ('DRL', 'orange', 'DRL控制'),
                                ('SAFETY', 'red', '安全切换')]:
        mask = df['mode'] == mode
        if mask.any():
            ax.scatter(df.loc[mask, 'x'], df.loc[mask, 'y'],
                      c=color, s=10, alpha=0.6, label=label)

    ax.scatter(df['x'].iloc[0], df['y'].iloc[0],
              c='green', s=100, marker='o', label='起点', zorder=5)
    ax.scatter(df['x'].iloc[-1], df['y'].iloc[-1],
              c='red', s=100, marker='*', label='终点', zorder=5)

    for obs in obstacles:
        circle = patches.Circle(
            (obs[0], obs[1]), obs[2],
            color='gray', alpha=0.5,
            label='障碍物' if obs == obstacles[0] else ''
        )
        ax.add_patch(circle)

    ax.set_xlabel('X (m)')
    ax.set_ylabel('Y (m)')
    ax.set_title('无人机飞行轨迹 (2D俯视图)')
    ax.legend(loc='upper right')
    ax.set_aspect('equal')

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"[2D] 轨迹图保存至: {save_path}")
    else:
        plt.show()


def plot_training_curve(rewards: list, window: int = 10,
                        save_path: str = None):
    """绘制训练奖励曲线"""
    fig, ax = plt.subplots(figsize=(10, 6))
    rewards = np.array(rewards)
    episodes = np.arange(1, len(rewards) + 1)
    ax.plot(episodes, rewards, 'b-', alpha=0.3, label='原始奖励')

    if len(rewards) >= window:
        smooth = np.convolve(rewards, np.ones(window) / window, mode='valid')
        ax.plot(episodes[window-1:], smooth, 'r-', linewidth=2,
               label=f'移动平均 (窗口={window})')

    ax.set_xlabel('Episode')
    ax.set_ylabel('奖励')
    ax.set_title('DRL 训练曲线')
    ax.legend()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    else:
        plt.show()


def plot_comparison(batch_results: dict, save_path: str = None):
    """绘制算法对比柱状图"""
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    metrics = {
        'success_rate': ('成功率', axes[0, 0]),
        'avg_path_length': ('平均路径长度 (m)', axes[0, 1]),
        'avg_speed': ('平均速度 (m/s)', axes[1, 0]),
        'avg_safety_interventions': ('安全干预次数', axes[1, 1])
    }

    data = {}
    for name, source in batch_results.items():
        if isinstance(source, str):
            df = pd.read_csv(source)
        else:
            df = source
        data[name] = df

    for metric, (ylabel, ax) in metrics.items():
        names = list(data.keys())
        values = [d[metric].mean() if metric in d.columns else 0
                 for d in data.values()]
        colors = plt.cm.Set2(np.linspace(0, 1, len(names)))
        bars = ax.bar(names, values, color=colors, alpha=0.7)
        ax.set_ylabel(ylabel)
        ax.set_title(ylabel)

        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2,
                   bar.get_height(), f'{val:.2f}',
                   ha='center', va='bottom', fontsize=10)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    else:
        plt.show()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="可视化工具")
    parser.add_argument("--log", type=str, help="飞行日志CSV路径")
    parser.add_argument("--rewards", type=str, help="训练奖励数据路径")
    parser.add_argument("--mode", type=str, default="3d",
                        choices=["2d", "3d"], help="可视化模式: 2d/3d")
    args = parser.parse_args()

    if args.log:
        if args.mode == "3d":
            plot_trajectory_3d(args.log)
        else:
            plot_trajectory_2d(args.log)
    elif args.rewards:
        rewards = np.load(args.rewards)
        plot_training_curve(rewards.tolist())
    else:
        print("请指定 --log 或 --rewards")