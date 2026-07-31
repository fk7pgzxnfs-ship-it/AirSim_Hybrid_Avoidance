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


def run_single_flight(goal_x: float = 10.0, goal_y: float = 10.0,
                      config_path: str = "config/default.yaml",
                      max_steps: int = 1000) -> dict:
    """
    执行一次单次避障飞行

    Args:
        goal_x: 目标点X
        goal_y: 目标点Y
        config_path: 配置文件路径
        max_steps: 最大步数

    Returns:
        飞行结果字典
    """
    print("=" * 50)
    print(f"AirSim Hybrid Avoidance - 单次飞行")
    print(f"目标点: ({goal_x}, {goal_y})")
    print(f"配置文件: {config_path}")
    print("=" * 50)

    # 初始化 Supervisor
    supervisor = Supervisor(config_path)
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
    parser.add_argument("--goal_x", type=float, default=10.0, help="目标点X坐标")
    parser.add_argument("--goal_y", type=float, default=10.0, help="目标点Y坐标")
    parser.add_argument("--config", type=str, default="config/default.yaml",
                        help="配置文件路径")
    parser.add_argument("--max_steps", type=int, default=1000, help="最大步数")
    args = parser.parse_args()

    run_single_flight(args.goal_x, args.goal_y, args.config, args.max_steps)