"""
执行一次完整避障飞行
可从命令行或作为模块调用
"""

import sys
import os
import time
import argparse
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hybrid_controller.supervisor import Supervisor
from airsim_interface.projectairsim_client import load_scene


def run_single_flight(goal_x: float = None, goal_y: float = None,
                      config_path: str = "config/default.yaml",
                      max_steps: int = 1000,
                      reload_scene: bool = True,
                      scene_path: str = None, scene=None) -> dict:
    """
    执行一次单次避障飞行

    Args:
        goal_x: 目标点X
        goal_y: 目标点Y
        config_path: 配置文件路径
        max_steps: 最大步数
        scene_path: 场景 yaml 路径（v3，优先于 goal_x/goal_y）
        scene: SceneConfig 对象（与 scene_path 二选一）

    Returns:
        飞行结果字典
    """
    print("=" * 50)
    print(f"AirSim Hybrid Avoidance - 单次飞行")
    print(f"目标点: ({goal_x}, {goal_y})")
    print(f"配置文件: {config_path}")
    print("=" * 50)

    # v3: 场景优先，goal 参数可覆盖场景终点
    if scene is None and scene_path:
        from scene_config import SceneConfig
        scene = SceneConfig.load(scene_path)
    if scene is not None:
        if goal_x is None:
            goal_x = float(scene.goal[0])
        if goal_y is None:
            goal_y = float(scene.goal[1])
    if goal_x is None:
        goal_x = 10.0
    if goal_y is None:
        goal_y = 10.0

    # 初始化 Supervisor
    if reload_scene:
        if scene is not None:
            r = load_scene(scene_config=scene.to_ue_dict())
        else:
            r = load_scene()
        print("[run_flight] LoadScene:", r)

    supervisor = Supervisor(config_path, scene=scene)
    supervisor.set_goal(goal_x, goal_y)

    # 运行
    result = supervisor.run(max_steps=max_steps)

    # 保存日志
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = f"logs/flights/flight_{timestamp}.csv"
    supervisor.save_log(log_path)

    # 打印结果
    print("\n飞行结果:")
    print(f"  成功: {result.get('success', False)}")
    if 'reason' in result:
        print(f"  原因: {result['reason']}")
    print(f"  步数: {result.get('steps', 0)}")
    print(f"  耗时: {result.get('time', 0):.2f}s")
    print(f"  路径长度: {result.get('path_length', 0):.2f}m")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="执行单次避障飞行")
    parser.add_argument("--goal_x", type=float, default=None, help="目标点X坐标（默认取场景终点）")
    parser.add_argument("--goal_y", type=float, default=None, help="目标点Y坐标（默认取场景终点）")
    parser.add_argument("--config", type=str, default="config/default.yaml",
                        help="配置文件路径")
    parser.add_argument("--scene", type=str, default=None,
                        help="场景 yaml 路径（v3，如 config/scenes/scene_100x10.yaml）")
    parser.add_argument("--max_steps", type=int, default=1000, help="最大步数")
    parser.add_argument("--no-reload", action="store_true",
                        help="skip LoadScene before flight")
    args = parser.parse_args()

    run_single_flight(args.goal_x, args.goal_y, args.config, args.max_steps,
                      reload_scene=not args.no_reload, scene_path=args.scene)