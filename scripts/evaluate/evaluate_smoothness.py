# -*- coding: utf-8 -*-
"""v2.1: smoothness metrics for DroneEnv episodes (success/collision + smoothness)."""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np, yaml
from drl.sim_client import KinematicSimClient, TrainSupervisor
from drl.env import DroneEnv
from drl.agent import DRLAgent

def run_eval(n_eval=60, ckpt="models/drl_agent/ddpg_best.pth", label="", vel_tc=None, obstacle_jitter=1.5):
    cfg = yaml.safe_load(open("config/default.yaml", encoding="utf-8"))
    drl_cfg = cfg["drl"]
    phys = cfg["map"]["obstacles_physical"]
    client = KinematicSimClient(obstacles=phys, start=cfg["map"]["origin"],
                                obstacle_jitter=obstacle_jitter, seed=drl_cfg["seed"],
                                vel_time_constant=vel_tc if vel_tc is not None else 0.1)
    sup = TrainSupervisor(client, start=cfg["map"]["origin"], goal=cfg["map"]["goal"],
                          takeoff_height=cfg["airsim"]["takeoff_height"])
    env_cfg = {**drl_cfg["env"], "reward": drl_cfg["reward"], "sleep_step": 0.0}
    env = DroneEnv(sup, env_cfg)
    agent = DRLAgent(state_dim=drl_cfg["env"]["state_dim"], action_dim=drl_cfg["env"]["action_dim"],
                     hidden_layers=drl_cfg["network"]["hidden_layers"],
                     action_low=drl_cfg["env"]["action_low"], action_high=drl_cfg["env"]["action_high"])
    agent.load(ckpt)
    rows = []
    for i in range(n_eval):
        s, _ = env.reset()
        done, steps, collided, success = False, 0, False, False
        acts, ys, xs = [], [], []
        while not done and steps < env.max_steps:
            a = agent.predict(s)
            s, r, term, trunc, info = env.step(a)
            done = term or trunc
            p = client.get_position()
            acts.append(a); xs.append(p[0]); ys.append(p[1])
            if info.get("collided"): collided = True
            if info.get("goal_reached"): success = True
            steps += 1
        acts = np.array(acts); ys = np.array(ys); xs = np.array(xs)
        if len(acts) < 2:
            rows.append(dict(success=success, collided=collided, steps=steps, d_action=np.nan,
                             ay_std=np.nan, y_sw=np.nan, path_ratio=np.nan, y_span=np.nan))
            continue
        d_action = float(np.mean(np.linalg.norm(np.diff(acts, axis=0), axis=1)))
        ay_std = float(np.std(acts[:, 1]))
        y_sw = int(np.sum(np.diff(np.sign(ys[ys != 0])) != 0)) if np.any(ys != 0) else 0
        path = float(np.sum(np.sqrt(np.diff(xs)**2 + np.diff(ys)**2)))
        rows.append(dict(success=success, collided=collided, steps=steps, d_action=d_action,
                         ay_std=ay_std, y_sw=y_sw, path_ratio=path/100.0, y_span=float(ys.max()-ys.min())))
    R = rows
    def m(k): return float(np.nanmean([r[k] for r in R]))
    print("="*62)
    print(f"EVAL {label} | n={n_eval} | ckpt={ckpt} | vel_tc={vel_tc}")
    print(f"  success={100*m('success'):.1f}%  collided={100*m('collided'):.1f}%  avg_steps={m('steps'):.1f}")
    print(f"  mean|d_action|={m('d_action'):.3f}  action_y_std={m('ay_std'):.3f}  y_sign_switches={m('y_sw'):.1f}")
    print(f"  path_ratio={m('path_ratio'):.4f}  y_span={m('y_span'):.3f} m")
    return rows

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="models/drl_agent/ddpg_best.pth")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--label", default="")
    ap.add_argument("--vel-tc", type=float, default=None)
    ap.add_argument("--jitter", type=float, default=1.5)
    a = ap.parse_args()
    run_eval(n_eval=a.n, ckpt=a.ckpt, label=a.label, vel_tc=a.vel_tc, obstacle_jitter=a.jitter)
