# -*- coding: utf-8 -*-
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\13631\Documents\GitHub\AirSim_Hybrid_Avoidance\AirSim Hybrid Avoidance_v1")
from airsim_interface.projectairsim_client import ProjectAirSimClientWrapper
c = ProjectAirSimClientWrapper(drone_name='Drone1', scene_id='SceneDroneClassic', obstacles=[(30.0,0.0,1.0),(65.0,0.0,1.0)])
def P(tag):
    p = c.get_position()
    print(f"{tag}: pos=({p[0]:9.3f},{p[1]:8.3f},{p[2]:8.3f})")

def scenario(name, wait_after_reset):
    print(f"\n===== {name} =====")
    c.reset_position(0.0, 0.0, -0.4)
    time.sleep(wait_after_reset)
    P("after reset+wait")
    c.takeoff(height=-12.0)
    P("after takeoff")
    for i in range(15):
        c.send_velocity(0.0, 0.0, 0.0, duration=0.3)
        if i % 2 == 0 or i >= 10:
            P(f"hover step {i}")
        time.sleep(0.05)
    c.send_velocity(0.0,0.0,0.0,duration=0.3)

scenario("immediate takeoff (wait=0.2)", 0.2)
time.sleep(2.0)
scenario("wait 2s after reset", 2.0)