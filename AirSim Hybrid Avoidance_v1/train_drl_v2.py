"""
train_drl_v2.py - v2.1 DRL 训练脚本
====================================
基于 drl/sim_client.py 的轻量 2D 仿真训练 DDPG 策略，
输出模型到 models/drl_agent/ 供 UE 部署使用。

v2.1 变更：
- 奖励新增动作平滑惩罚 + 横向偏移惩罚，消除直线段蛇形振荡（纯算法层，无部署滤波）
- 训练仿真速度惯性保持 vel_time_constant=0.5（与 v2.0 一致；UE 对齐评估用 --vel-tc 0.1）
- 支持 --tag 指定输出标签（默认 v21b）

用法: python train_drl_v2.py [--episodes N] [--quick] [--tag TAG]
"""
import sys
import os
import time
import argparse
import yaml
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
from drl.sim_client import KinematicSimClient, TrainSupervisor
from drl.env import DroneEnv
from drl.trainer import DDPGTrainer
from drl.utils_drl import set_seed
from drl.agent import DRLAgent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=0, help="覆盖训练轮数")
    ap.add_argument("--quick", action="store_true", help="快速冒烟测试")
    ap.add_argument("--tag", default="v21b", help="模型文件标签")
    args = ap.parse_args()

    print("=" * 55)
    print("AirSim Hybrid Avoidance v2.1 - DRL(DDPG) 训练")
    print("=" * 55)

    config = yaml.safe_load(open("config/default.yaml", encoding="utf-8"))
    drl_cfg = config["drl"]
    set_seed(drl_cfg["seed"])

    if args.quick:
        drl_cfg["training"]["episodes"] = 40
        drl_cfg["training"]["warmup_steps"] = 200
        drl_cfg["training"]["batch_size"] = 64

    if args.episodes:
        drl_cfg["training"]["episodes"] = args.episodes

    # 创建训练仿真（v2.1: 速度惯性对齐 UE fast-physics）
    phys = config["map"]["obstacles_physical"]
    client = KinematicSimClient(
        obstacles=phys,
        start=config["map"]["origin"],
        obstacle_jitter=1.5,
        vel_time_constant=drl_cfg.get("vel_time_constant", 0.1),
        seed=drl_cfg["seed"],
    )
    sup = TrainSupervisor(
        client,
        start=config["map"]["origin"],
        goal=config["map"]["goal"],
        takeoff_height=config["airsim"]["takeoff_height"],
    )

    env_config = {**drl_cfg["env"], "reward": drl_cfg["reward"], "sleep_step": 0.0}
    env = DroneEnv(sup, env_config)

    trainer = DDPGTrainer(env, drl_cfg)
    t0 = time.time()
    stats = trainer.train()
    print("训练耗时: %.1f s" % (time.time() - t0))

    # 保存训练曲线
    os.makedirs("logs/train", exist_ok=True)
    np.save("logs/train/rewards_%s.npy" % args.tag, np.array(trainer.episode_rewards))

    # 无探索评估（成功率 + v2.1 平滑度指标）
    agent = DRLAgent(
        state_dim=drl_cfg["env"]["state_dim"],
        action_dim=drl_cfg["env"]["action_dim"],
        hidden_layers=drl_cfg["network"]["hidden_layers"],
        action_low=drl_cfg["env"]["action_low"],
        action_high=drl_cfg["env"]["action_high"],
    )
    ckpt = os.path.join(config["model"]["save_dir"], "ddpg_best.pth")
    agent.load(ckpt)

    n_eval = 60
    success, collided, steps_sum = 0, 0, 0
    d_action_list, ay_std_list, y_sw_list, path_ratio_list, y_span_list = [], [], [], [], []
    for i in range(n_eval):
        s, _ = env.reset()
        done = False
        steps = 0
        acts, xs, ys = [], [], []
        while not done and steps < env.max_steps:
            a = agent.predict(s)
            s, r, term, trunc, info = env.step(a)
            done = term or trunc
            p = client.get_position()
            acts.append(a); xs.append(p[0]); ys.append(p[1])
            steps += 1
            if info.get("collided"):
                collided += 1
            if info.get("goal_reached"):
                success += 1
        steps_sum += steps
        if len(acts) >= 2:
            acts = np.array(acts); xs = np.array(xs); ys = np.array(ys)
            d_action_list.append(np.mean(np.linalg.norm(np.diff(acts, axis=0), axis=1)))
            ay_std_list.append(np.std(acts[:, 1]))
            y_sw_list.append(int(np.sum(np.diff(np.sign(ys[ys != 0])) != 0)) if np.any(ys != 0) else 0)
            path = np.sum(np.sqrt(np.diff(xs) ** 2 + np.diff(ys) ** 2))
            path_ratio_list.append(path / 100.0)
            y_span_list.append(float(ys.max() - ys.min()))
    print("=" * 55)
    print("无探索评估 %d 局结果:" % n_eval)
    print("  成功率: %.0f%%  (%d/%d)" % (100.0 * success / n_eval, success, n_eval))
    print("  碰撞率: %.0f%%  (%d/%d)" % (100.0 * collided / n_eval, collided, n_eval))
    print("  平均步数: %.1f" % (steps_sum / n_eval))
    if d_action_list:
        print("  mean|Δaction|: %.3f" % np.mean(d_action_list))
        print("  action_y_std: %.3f" % np.mean(ay_std_list))
        print("  y 符号切换: %.1f" % np.mean(y_sw_list))
        print("  路径/直线比: %.4f" % np.mean(path_ratio_list))
        print("  y 跨度: %.3f m" % np.mean(y_span_list))
    print("=" * 55)
    return stats


if __name__ == "__main__":
    main()
