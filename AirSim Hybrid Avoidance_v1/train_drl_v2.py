"""
train_drl_v2.py - v2 DRL ????
================================
?????????drl/sim_client.py???? DDPG ?????
??????????? models/drl_agent/?? UE ?????

??: python train_drl_v2.py [--episodes N] [--quick]
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
    ap.add_argument("--episodes", type=int, default=0, help="??????????")
    ap.add_argument("--quick", action="store_true", help="????????????")
    args = ap.parse_args()

    print("=" * 55)
    print("AirSim Hybrid Avoidance v2 - DRL(DDPG) ??")
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

    # ??????????
    phys = config["map"]["obstacles_physical"]
    client = KinematicSimClient(
        obstacles=phys,
        start=config["map"]["origin"],
        obstacle_jitter=1.5,
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
    print("????: %.1f s" % (time.time() - t0))

    # ??????
    os.makedirs("logs/train", exist_ok=True)
    np.save("logs/train/rewards_v2.npy", np.array(trainer.episode_rewards))

    # ?????
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
    for i in range(n_eval):
        s, _ = env.reset()
        done = False
        steps = 0
        while not done and steps < env.max_steps:
            a = agent.predict(s)
            s, r, term, trunc, info = env.step(a)
            done = term or trunc
            steps += 1
            if info.get("collided"):
                collided += 1
            if info.get("goal_reached"):
                success += 1
        steps_sum += steps
    print("=" * 55)
    print("?????????%d ??????:" % n_eval)
    print("  ???: %.0f%%  (%d/%d)" % (100.0 * success / n_eval, success, n_eval))
    print("  ???: %.0f%%  (%d/%d)" % (100.0 * collided / n_eval, collided, n_eval))
    print("  ????: %.1f" % (steps_sum / n_eval))
    print("=" * 55)
    return stats


if __name__ == "__main__":
    main()
