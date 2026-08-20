# -*- coding: utf-8 -*-
import io, sys, time, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\13631\Documents\GitHub\AirSim_Hybrid_Avoidance\AirSim Hybrid Avoidance_v1")
from airsim_interface.projectairsim_client import ProjectAirSimClientWrapper

LOG = r"D:\ProjectAirSim-main\unreal\Blocks 5.7\Saved\Logs\Blocks.log"
START_SIZE = 0
try:
    START_SIZE = len(open(LOG, encoding='utf-8-sig', errors='replace').read())
except Exception:
    pass

def new_collisions(tag):
    try:
        with open(LOG, encoding='utf-8-sig', errors='replace') as fh:
            data = fh.read()
    except Exception:
        return -1
    return data.count("Collision detected between 'Frame' and 'Obstacle2'")

c = ProjectAirSimClientWrapper(drone_name='Drone1', scene_id='SceneDroneClassic',
                               obstacles=[(30.0,0.0,1.0),(65.0,0.0,1.0)])
def P(tag):
    p = c.get_position(); v = c.get_velocity()
    print(f"{time.strftime('%H:%M:%S')} {tag}: pos=({p[0]:9.3f},{p[1]:8.3f},{p[2]:8.3f}) vel=({v[0]:6.2f},{v[1]:6.2f},{v[2]:6.2f})", flush=True)

base = new_collisions("init")
print(f"baseline Obstacle2 collisions so far: {base}", flush=True)

# 1) reset
print("\n=== 1. reset to (0,0,-0.4) ===", flush=True)
c.reset_position(0.0, 0.0, -0.4)
for i in range(6):
    P(f"reset t={i*0.5}")
    time.sleep(0.5)

# 2) takeoff
print("\n=== 2. takeoff to -12 ===", flush=True)
c.takeoff(height=-12.0)
for i in range(4):
    P(f"takeoff t={i*0.5}")
    time.sleep(0.5)

# 3) fly forward to x>=90
print("\n=== 3. fly forward vx=2.0 ===", flush=True)
for step in range(200):
    p = c.get_position()
    if p[0] >= 90.0:
        print(f"reached x={p[0]:.1f} at step {step}", flush=True)
        break
    c.send_velocity(2.0, 0.0, 0.0, duration=0.3)
    if step % 10 == 0:
        P(f"fly step {step}")
P("fly done")

# 4) hover hold
print("\n=== 4. hover at goal ===", flush=True)
for i in range(6):
    c.send_velocity(0.0, 0.0, 0.0, duration=0.3)
    if i % 2 == 0:
        P(f"hover {i}")
print("collisions after hover:", new_collisions("hover") - base, flush=True)

# 5) A: disconnect (close socket), wait, reconnect, poll
print("\n=== 5. A: disconnect client, wait 6s ===", flush=True)
c.close()
time.sleep(6.0)
c2 = ProjectAirSimClientWrapper(drone_name='Drone1', scene_id='SceneDroneClassic',
                                obstacles=[(30.0,0.0,1.0),(65.0,0.0,1.0)])
for i in range(6):
    P(f"after-disc t={i*0.5}")
    time.sleep(0.5)
print("collisions after disconnect:", new_collisions("disc") - base, flush=True)

# 6) B: DisableApiControl
print("\n=== 6. B: DisableApiControl ===", flush=True)
r = c2._request(c2._drone_path() + "/DisableApiControl", timeout=15)
print("rpc:", r, flush=True)
for i in range(6):
    P(f"after-disable t={i*0.5}")
    time.sleep(0.5)
print("collisions after DisableApiControl:", new_collisions("disable") - base, flush=True)

# 7) C: SetPose directly (no DisableApiControl this time)
print("\n=== 7. C: SetPose(0,0,-0.4) ===", flush=True)
pose = {"translation": {"x": 0.0, "y": 0.0, "z": -0.4},
        "rotation": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
        "frame_id": "DEFAULT_ID"}
r = c2._request(c2._drone_path() + "/SetPose", {"pose": pose, "reset_kinematics": True}, timeout=20)
print("rpc:", r, flush=True)
for i in range(12):
    P(f"after-setpose t={i*0.5}")
    time.sleep(0.5)
print("collisions after SetPose:", new_collisions("setpose") - base, flush=True)

# 8) D: re-enable + arm + takeoff
print("\n=== 8. D: EnableApiControl + Arm + takeoff ===", flush=True)
try:
    c2.takeoff(height=-12.0)
except Exception as e:
    print("takeoff exc:", repr(e), flush=True)
for i in range(6):
    P(f"after-takeoff2 t={i*0.5}")
    time.sleep(0.5)
print("collisions after takeoff2:", new_collisions("takeoff2") - base, flush=True)
print("\nDONE", flush=True)
