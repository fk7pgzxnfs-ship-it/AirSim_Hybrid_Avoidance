"""
批量评估脚本
循环执行多组实验，统计成功率等指标
"""

import sys
import os
import time
import json
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.run_flight import run_single_flight


def run_batch(config_path: str = "config/default.yaml",
              num_runs: int = 10,
              goal_points: list = None,
              max_steps: int = 1000) -> pd.DataFrame:
    """
    批量运行多次飞行实验

    Args:
        config_path: 配置文件路径
        num_runs: 每个目标点运行次数
        goal_points: 目标点列表 [(x, y), ...]
        max_steps: 最大步数

    Returns:
        实验结果 DataFrame
    """
    if goal_points is None:
        goal_points = [(10.0, 10.0), (8.0, 8.0), (-8.0, 8.0)]

    all_results = []

    print("=" * 60)
    print(f"批量评估开始")
    print(f"配置: {config_path}")
    print(f"目标点: {goal_points}")
    print(f"每组运行: {num_runs} 次")
    print("=" * 60)

    for goal_x, goal_y in goal_points:
        for run_id in range(1, num_runs + 1):
            print(f"\n[Run {run_id}/{num_runs}] 目标: ({goal_x}, {goal_y})")
            try:
                result = run_single_flight(
                    goal_x=goal_x, goal_y=goal_y,
                    config_path=config_path, max_steps=max_steps
                )
                result['goal_x'] = goal_x
                result['goal_y'] = goal_y
                result['run_id'] = run_id
                all_results.append(result)
            except Exception as e:
                print(f"  [错误] {e}")
                all_results.append({
                    'goal_x': goal_x, 'goal_y': goal_y,
                    'run_id': run_id, 'success': False,
                    'reason': str(e), 'steps': 0, 'time': 0, 'path_length': 0
                })

    df = pd.DataFrame(all_results)

    # 保存结果
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    save_path = f"logs/flights/batch_eval_{timestamp}.csv"
    df.to_csv(save_path, index=False)
    print(f"\n批量评估结果已保存: {save_path}")

    # 打印统计摘要
    print("\n===== 评估摘要 =====")
    print(f"总运行次数: {len(df)}")
    print(f"成功次数: {df['success'].sum()}")
    print(f"成功率: {df['success'].mean():.2%}")
    print(f"平均步数: {df['steps'].mean():.1f}")
    print(f"平均耗时: {df['time'].mean():.2f}s")
    print(f"平均路径长度: {df['path_length'].mean():.2f}m")

    return df


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="批量评估")
    parser.add_argument("--runs", type=int, default=5, help="每个目标点运行次数")
    parser.add_argument("--config", type=str, default="config/default.yaml")
    parser.add_argument("--max_steps", type=int, default=1000)
    args = parser.parse_args()

    run_batch(num_runs=args.runs, config_path=args.config,
              max_steps=args.max_steps)