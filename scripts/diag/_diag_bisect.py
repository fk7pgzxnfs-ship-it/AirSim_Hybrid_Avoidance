# -*- coding: utf-8 -*-
"""Bisect which RPC in flight-2 startup reverts the UE actor to PlayerStart.
Usage: python _diag_bisect.py [with_disable|without_disable]
"""
import io, sys, time, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\13631\Documents\GitHub\AirSim_Hybrid_Avoidance\AirSim Hybrid Avoidance_v1")

mode = sys.argv[1] if len(sys.argv) > 1 else "with_disable"

LOG = r"D:\ProjectAirSim-main\unreal\Blocks 5.7\Saved\Logs\Blocks.log"
MARK = int(sys.argv[2]) if len(sys.argv) > 2 else 0

def collisions_since_mark():
    try:
        with open(LOG, 'rb') as fh:
            fh.seek(MARK)
            text = fh.read().decode('utf-8', errors='replace')
        return {
            "Obstacle1": text.count("Collision detected between 'Frame' and 'Obstacle1'"),
            "Obstacle2": text.count("Collision detected between 'Frame' and 'Obstacle2'"),
            "Ground": text.count("Collision detected between 'Frame' and 'Ground100x10'"),
        }
    except Exception as e:
        return {"err": repr(e)}

from airsim_interface.projectairsim_client import ProjectAirSimClientWrapper
c = ProjectAirSimClientWrapper(drone_name='Drone1', scene_id='SceneDroneClassic',
                               obstacles=[(30.0,0.0,1.0),(65.0,0.0,1.0)])

def P(tag):
    p = c.get_position(); v = c.get_velocity()
    print(f"{time.strftime('%H:%M:%S')} {tag}: pos=({p[0]:9.3f},{p[1]:8.3f},{p[2]:8.3f}) vel=({v[0]:6.2f},{v[1]:6.2f},{v[2]:6.2f})", flush=True)

print(f"mode={mode} mark={MARK} initial_collisions={collisions_since_mark()}", flush=True)
P("connect")

def poll(tag, n, dt=0.5):
    for i in range(n):
        P(f"{tag} t={i*dt:.1f}")
        time.sleep(dt)

if mode == "with_disable":
    print("\n--- step1: DisableApiControl ---", flush=True)
    r = c._request(c._drone_path() + "/DisableApiControl", timeout=15)
    print("rpc:", r, flush=True)
    poll("disable", 6)
    print("collisions:", collisions_since_mark(), flush=True)

    print("\n--- step2: SetPose(0,0,-0.4) ---", flush=True)
    pose = {"translation": {"x": 0.0, "y": 0.0, "z": -0.4},
            "rotation": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
            "frame_id": "DEFAULT_ID"}
    r = c._request(c._drone_path() + "/SetPose", {"pose": pose, "reset_kinematics": True}, timeout=20)
    print("rpc:", r, flush=True)
    poll("setpose", 6)
    print("collisions:", collisions_since_mark(), flush=True)
else:
    print("\n--- step1: SetPose(0,0,-0.4) WITHOUT DisableApiControl ---", flush=True)
    pose = {"translation": {"x": 0.0, "y": 0.0, "z": -0.4},
            "rotation": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
            "frame_id": "DEFAULT_ID"}
    r = c._request(c._drone_path() + "/SetPose", {"pose": pose, "reset_kinematics": True}, timeout=20)
    print("rpc:", r, flush=True)
    poll("setpose", 6)
    print("collisions:", collisions_since_mark(), flush=True)

print("\n--- step3: takeoff ---", flush=True)
c.takeoff(height=-12.0)
poll("takeoff", 4)
print("collisions:", collisions_since_mark(), flush=True)

print("\n--- step4: fly forward 20 steps ---", flush=True)
for step in range(20):
    c.send_velocity(2.0, 0.0, 0.0, duration=0.3)
    if step % 2 == 0 or step >= 16:
        P(f"fly step {step}")
print("collisions:", collisions_since_mark(), flush=True)
print("DONE", flush=True)
