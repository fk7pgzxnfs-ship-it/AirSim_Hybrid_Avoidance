# -*- coding: utf-8 -*-
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\13631\Documents\GitHub\AirSim_Hybrid_Avoidance\AirSim Hybrid Avoidance_v1")
from airsim_interface.projectairsim_client import ProjectAirSimClientWrapper
c = ProjectAirSimClientWrapper(drone_name='Drone1', scene_id='SceneDroneClassic', obstacles=[(30.0,0.0,1.0),(65.0,0.0,1.0)])
def ci():
    r = c._request(c._drone_path() + "/GetCollisionInfo", timeout=15)
    if "result" in r:
        return r["result"]
    return r
def P(tag):
    p = c.get_position(); v = c.get_velocity(); col = ci()
    has = col.get("has_collided", col.get("hasCollided", "?")) if isinstance(col, dict) else col
    print(f"{tag}: pos=({p[0]:9.3f},{p[1]:8.3f},{p[2]:8.3f}) vel=({v[0]:6.3f},{v[1]:6.3f},{v[2]:6.3f}) collided={has}")
print("== current state =="); P("cur")
print("== reset to (0,0,-0.4), poll 10x 0.5s ==")
c.reset_position(0.0, 0.0, -0.4)
for i in range(10):
    P(f"  t={i*0.5:.1f}")
    time.sleep(0.5)
print("== takeoff ==")
c.takeoff(height=-12.0)
for i in range(10):
    P(f"  t={i*0.5:.1f}")
    time.sleep(0.5)
print("== hover 5 steps ==")
for i in range(5):
    c.send_velocity(0.0, 0.0, 0.0, duration=0.3)
    P(f"  step{i}")
    time.sleep(0.1)