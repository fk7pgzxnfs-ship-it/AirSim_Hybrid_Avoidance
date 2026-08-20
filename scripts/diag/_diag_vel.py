# -*- coding: utf-8 -*-
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\13631\Documents\GitHub\AirSim_Hybrid_Avoidance\AirSim Hybrid Avoidance_v1")
from airsim_interface.projectairsim_client import ProjectAirSimClientWrapper

c = ProjectAirSimClientWrapper(drone_name='Drone1', scene_id='SceneDroneClassic', obstacles=[(30.0,0.0,1.0),(65.0,0.0,1.0)])
def P(tag):
    p = c.get_position(); v = c.get_velocity()
    print(f"{tag}: pos=({p[0]:9.3f},{p[1]:8.3f},{p[2]:8.3f}) vel=({v[0]:6.3f},{v[1]:6.3f},{v[2]:6.3f})")

print("reset to (0,0,-0.4)")
c.reset_position(0.0, 0.0, -0.4)
P("after reset")
time.sleep(1.0)
c.takeoff(height=-12.0)
P("after takeoff")
time.sleep(0.5)

print("--- hover hold: 10 x MoveByVelocity(0,0,0,0.3) ---")
for i in range(10):
    t0 = time.time()
    c.send_velocity(0.0, 0.0, 0.0, duration=0.3)
    dt = time.time() - t0
    p = c.get_position()
    print(f"hover step {i}: dt={dt:6.3f} pos=({p[0]:9.3f},{p[1]:8.3f},{p[2]:8.3f})")
    time.sleep(0.05)

print("--- forward: 6 x MoveByVelocity(1,0,0,0.3) ---")
for i in range(6):
    t0 = time.time()
    c.send_velocity(1.0, 0.0, 0.0, duration=0.3)
    dt = time.time() - t0
    p = c.get_position()
    print(f"fwd step {i}: dt={dt:6.3f} pos=({p[0]:9.3f},{p[1]:8.3f},{p[2]:8.3f})")
    time.sleep(0.05)

print("--- forward: 6 x MoveByVelocity(2,0,0,0.3) ---")
for i in range(6):
    t0 = time.time()
    c.send_velocity(2.0, 0.0, 0.0, duration=0.3)
    dt = time.time() - t0
    p = c.get_position()
    print(f"fwd2 step {i}: dt={dt:6.3f} pos=({p[0]:9.3f},{p[1]:8.3f},{p[2]:8.3f})")
    time.sleep(0.05)

print("--- final ---")
P("final")
c.send_velocity(0.0, 0.0, 0.0, duration=0.3)