# -*- coding: utf-8 -*-
"""Read-only analysis: does the trained policy oscillate in the training sim?"""
import io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
from drl.agent import DRLAgent
from drl.sim_client import KinematicSimClient

agent = DRLAgent(state_dim=8, action_dim=2, hidden_layers=[256,256],
                 action_low=[-2.0,-2.0], action_high=[2.0,2.0])
ok = agent.load("models/drl_agent/ddpg_best.pth")
print("loaded:", ok)

sim = KinematicSimClient(obstacles=[(30.0,0.0,1.0),(65.0,0.0,1.0)], seed=42)
sim.reset_position(0.0, 0.0, -12.0)

def get_state():
    pos = sim.get_position()
    vel = sim.get_velocity()
    lidar = sim.get_lidar_data()
    if lidar.shape[0] > 0:
        angles = np.arctan2(lidar[:,1], lidar[:,0])
        dists = np.linalg.norm(lidar[:,:2], axis=1)
        idx = np.argmin(dists)
        nd, na = dists[idx], angles[idx]
    else:
        nd, na = 30.0, 0.0
    dx = 100.0 - pos[0]; dy = 0.0 - pos[1]
    gd = np.sqrt(dx*dx+dy*dy); ga = np.arctan2(dy, dx)
    return np.array([dx, dy, vel[0], vel[1], nd, na, gd, ga], dtype=np.float32)

print("step | action_x action_y | vel_x vel_y | pos_x pos_y | nearest")
for i in range(40):
    s = get_state()
    a = agent.predict(s)
    sim.send_velocity(a[0], a[1], duration=0.3)
    p = sim.get_position(); v = sim.get_velocity()
    print(f"{i+1:4d} | {a[0]:6.2f} {a[1]:6.2f} | {v[0]:6.2f} {v[1]:6.2f} | {p[0]:6.2f} {p[1]:6.2f} | {s[4]:6.2f}")