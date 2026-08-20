"""
批量评估入口脚本
运行多组实验并统计结果
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from experiments.batch_evaluation import run_batch


def main():
    """主入口"""
    import argparse
    parser = argparse.ArgumentParser(description="批量评估")
    parser.add_argument("--runs", type=int, default=5, help="每个目标点运行次数")
    parser.add_argument("--config", type=str, default="config/default.yaml",
                        help="配置文件路径")
    parser.add_argument("--max_steps", type=int, default=1000, help="最大步数")
    args = parser.parse_args()

    run_batch(num_runs=args.runs, config_path=args.config,
              max_steps=args.max_steps)


if __name__ == "__main__":
    main()