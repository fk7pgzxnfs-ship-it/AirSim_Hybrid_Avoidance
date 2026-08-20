"""
结果分析脚本
读取飞行日志，计算各项指标
"""

import sys
import os
import glob
import pandas as pd
import numpy as np


def analyze_flight_log(log_path: str) -> dict:
    """
    分析单次飞行日志

    Args:
        log_path: CSV日志路径

    Returns:
        分析结果字典
    """
    df = pd.read_csv(log_path)

    stats = {
        'file': os.path.basename(log_path),
        'total_steps': len(df),
        'success': df['mode'].iloc[-1] == 'GLOBAL' if len(df) > 0 else False,
        'avg_speed': np.mean(np.sqrt(df['vx']**2 + df['vy']**2)),
        'safety_interventions': (df['mode'] == 'SAFETY').sum(),
        'drl_interventions': (df['mode'] == 'DRL').sum(),
        'min_obstacle_distance': df['nearest_obs'].min(),
        'avg_obstacle_distance': df['nearest_obs'].mean(),
    }

    # 计算路径长度
    if len(df) > 1:
        dx = df['x'].diff().iloc[1:]
        dy = df['y'].diff().iloc[1:]
        stats['path_length'] = np.sqrt(dx**2 + dy**2).sum()
    else:
        stats['path_length'] = 0.0

    return stats


def analyze_batch(log_dir: str = "logs/flights") -> pd.DataFrame:
    """
    分析目录下所有飞行日志

    Args:
        log_dir: 日志目录

    Returns:
        统计结果 DataFrame
    """
    csv_files = glob.glob(os.path.join(log_dir, "*.csv"))
    if not csv_files:
        print(f"[分析] 未找到日志文件: {log_dir}")
        return pd.DataFrame()

    all_stats = []
    for f in csv_files:
        try:
            stats = analyze_flight_log(f)
            all_stats.append(stats)
        except Exception as e:
            print(f"[分析] 解析失败 {f}: {e}")

    df = pd.DataFrame(all_stats)

    print("\n===== 批量分析结果 =====")
    print(f"分析文件数: {len(df)}")
    print(f"成功率: {df['success'].mean():.2%}")
    print(f"平均步数: {df['total_steps'].mean():.1f}")
    print(f"平均速度: {df['avg_speed'].mean():.2f} m/s")
    print(f"平均路径长度: {df['path_length'].mean():.2f} m")
    print(f"安全干预次数: {df['safety_interventions'].mean():.1f}")
    print(f"最小障碍物距离: {df['min_obstacle_distance'].min():.2f} m")
    print(f"平均障碍物距离: {df['avg_obstacle_distance'].mean():.2f} m")

    return df


def compare_algorithms(alg_dirs: dict) -> pd.DataFrame:
    """
    比较不同算法的实验结果

    Args:
        alg_dirs: {"算法名": "日志目录路径", ...}

    Returns:
        对比结果 DataFrame
    """
    comparison = []
    for name, directory in alg_dirs.items():
        df = analyze_batch(directory)
        if len(df) > 0:
            comparison.append({
                'algorithm': name,
                'success_rate': df['success'].mean(),
                'avg_path_length': df['path_length'].mean(),
                'avg_speed': df['avg_speed'].mean(),
                'avg_safety_interventions': df['safety_interventions'].mean(),
            })

    result_df = pd.DataFrame(comparison)
    print("\n===== 算法对比 =====")
    print(result_df.to_string(index=False))
    return result_df


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="分析飞行日志")
    parser.add_argument("--log_dir", type=str, default="logs/flights",
                        help="日志目录")
    args = parser.parse_args()

    analyze_batch(args.log_dir)