# -*- coding: utf-8 -*-
"""Segment analysis: straight-line vs obstacle-avoidance segments."""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np, yaml
from drl.sim_client import KinematicSimClient, TrainSupervisor
from drl.env import DroneEnv
from drl.agent import DRLAgent

def run(n_eval=60, ckpt="models/drl_agent/ddpg_best.pth", label="", vel_tc=0.1):
    cfg = yaml.safe_load(open("config/default.yaml", encoding="utf-8"))
    drl_cfg = cfg["drl"]
    phys = cfg["map"]["obstacles_physical"]
    client = KinematicSimClient(obstacles=phys, start=cfg["map"]["origin"],
                                obstacle_jitter=1.5, seed=drl_cfg["seed"], vel_time_constant=vel_tc)
    sup = TrainSupervisor(client, start=cfg["map"]["origin"], goal=cfg["map"]["goal"],
                          takeoff_height=cfg["airsim"]["takeoff_height"])
    env_cfg = {**drl_cfg["env"], "reward": drl_cfg["reward"], "sleep_step": 0.0}
    env = DroneEnv(sup, env_cfg)
    agent = DRLAgent(state_dim=drl_cfg["env"]["state_dim"], action_dim=drl_cfg["env"]["action_dim"],
                     hidden_layers=drl_cfg["network"]["hidden_layers"],
                     action_low=drl_cfg["env"]["action_low"], action_high=drl_cfg["env"]["action_high"])
    agent.load(ckpt)
    straight_stats, avoid_stats = [], []
    for i in range(n_eval):
        s, _ = env.reset()
        done, steps = False, 0
        seg, seg_s = [], []  # (x,y,nearest_dist)
        while not done and steps < env.max_steps:
            a = agent.predict(s)
            s, r, term, trunc, info = env.step(a)
            done = term or trunc
            p = client.get_position(); nd = float(s[4])
            seg.append((p[0], p[1], nd))
            steps += 1
        seg = np.array(seg)
        # straight: nearest_dist > 8m; avoid: <= 8m
        for name, mask, bucket in [("straight", seg[:,2] > 8.0, straight_stats),
                                   ("avoid", seg[:,2] <= 8.0, avoid_stats)]:
            if mask.sum() < 3: continue
            yy = seg[mask, 1]
            cum = np.sum(np.abs(np.diff(yy)))
            bucket.append(dict(span=yy.max()-yy.min(), std=yy.std(),
                               cum_dy=cum, n=int(mask.sum()),
                               sw=int(np.sum(np.diff(np.sign(yy[yy!=0])) != 0)) if np.any(yy!=0) else 0))
    def rep(b):
        if not b: return "  (no data)"
        return "  n_seg_pts=%d  y_span=%.2f  y_std=%.2f  cum|dy|=%.1f  y_sw=%.1f" % (
            int(np.mean([r["n"] for r in b])), float(np.mean([r["span"] for r in b])),
            float(np.mean([r["std"] for r in b])), float(np.mean([r["cum_dy"] for r in b])),
            float(np.mean([r["sw"] for r in b])))
    print("="*60); print(f"SEGMENT {label} | vel_tc={vel_tc}")
    print("straight(nd>8m):" + rep(straight_stats))
    print("avoid(nd<=8m):  " + rep(avoid_stats))
    # save one sample trajectory
    np.save(f"logs/train/traj_{label}.npy", seg)

run()
