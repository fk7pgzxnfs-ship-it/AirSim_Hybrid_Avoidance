"""
混合避障飞行入口脚本
运行完整的三层混合控制器
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from experiments.run_flight import run_single_flight


def main():
    """主入口"""
    import argparse
    parser = argparse.ArgumentParser(description="运行混合避障飞行")
    parser.add_argument("--goal_x", type=float, default=10.0, help="目标X坐标")
    parser.add_argument("--goal_y", type=float, default=10.0, help="目标Y坐标")
    parser.add_argument("--config", type=str, default="config/default.yaml",
                        help="配置文件路径")
    parser.add_argument("--max_steps", type=int, default=1000, help="最大步数")
    parser.add_argument("--no-reload", action="store_true",
                        help="skip LoadScene before flight")
    args = parser.parse_args()

    run_single_flight(args.goal_x, args.goal_y, args.config, args.max_steps,
                      reload_scene=not args.no_reload)


if __name__ == "__main__":
    main()