# -*- coding: utf-8 -*-
"""Plot a v2.1 sample trajectory (vel_tc=0.1, UE-aligned) to inspect straight segments."""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, yaml
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from drl.sim_client import KinematicSimClient, TrainSupervisor
from drl.env import DroneEnv
from drl.agent import DRLAgent

cfg = yaml.safe_load(open("config/default.yaml", encoding="utf-8"))
drl_cfg = cfg["drl"]
phys = cfg["map"]["obstacles_physical"]
client = KinematicSimClient(obstacles=phys, start=cfg["map"]["origin"], obstacle_jitter=0.0,
                            seed=7, vel_time_constant=0.1)
sup = TrainSupervisor(client, start=cfg["map"]["origin"], goal=cfg["map"]["goal"],
                      takeoff_height=cfg["airsim"]["takeoff_height"])
env_cfg = {**drl_cfg["env"], "reward": drl_cfg["reward"], "sleep_step": 0.0}
env = DroneEnv(sup, env_cfg)
agent = DRLAgent(state_dim=drl_cfg["env"]["state_dim"], action_dim=drl_cfg["env"]["action_dim"],
                 hidden_layers=drl_cfg["network"]["hidden_layers"],
                 action_low=drl_cfg["env"]["action_low"], action_high=drl_cfg["env"]["action_high"])
agent.load("models/drl_agent/ddpg_best.pth")
s, _ = env.reset()
done, steps = False, 0
xs, ys, ays, nds = [], [], [], []
while not done and steps < env.max_steps:
    a = agent.predict(s)
    s, r, term, trunc, info = env.step(a)
    done = term or trunc
    p = client.get_position()
    xs.append(p[0]); ys.append(p[1]); ays.append(a[1]); nds.append(s[4])
    steps += 1
xs = np.array(xs); ys = np.array(ys); ays = np.array(ays); nds = np.array(nds)
fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
ax[0].plot(xs, ys, "-o", ms=2, lw=1.2, color="tab:blue"); ax[0].axhline(0, color="gray", ls="--", lw=0.6)
ax[0].axvline(30, color="red", alpha=0.5); ax[0].axvline(65, color="red", alpha=0.5)
ax[0].set_ylabel("y (m)"); ax[0].set_ylim(-5.5, 5.5); ax[0].set_title("v2.1 trajectory (vel_tc=0.1, fixed obstacles)")
ax[1].plot(xs, ys, color="tab:blue", lw=1.0)
ax[1].set_ylabel("y zoom"); ax[1].set_ylim(-1.5, 1.5)
ax[1].axhline(0, color="gray", ls="--", lw=0.6); ax[1].axvline(30, color="red", alpha=0.5); ax[1].axvline(65, color="red", alpha=0.5)
ax[2].plot(xs, ays, color="tab:green", lw=1.0); ax[2].set_ylabel("action_y"); ax[2].set_xlabel("x (m)")
plt.tight_layout(); os.makedirs("logs/train", exist_ok=True)
plt.savefig("logs/train/traj_v21_fixed.png", dpi=110)
print("saved logs/train/traj_v21_fixed.png  steps=%d" % steps)
