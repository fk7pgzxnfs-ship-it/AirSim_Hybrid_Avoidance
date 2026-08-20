# -*- coding: utf-8 -*-
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\13631\Documents\GitHub\AirSim_Hybrid_Avoidance\AirSim Hybrid Avoidance_v1")
from airsim_interface.projectairsim_client import ProjectAirSimClientWrapper
c = ProjectAirSimClientWrapper(drone_name='Drone1', scene_id='SceneDroneClassic', obstacles=[(30.0,0.0,1.0),(65.0,0.0,1.0)])
print("current:", c.get_position())
print("reset to (0,0,-0.4)")
c.reset_position(0.0, 0.0, -0.4)
for i in range(20):
    p = c.get_position()
    print(f"t={i*0.25:5.2f} pos=({p[0]:9.3f},{p[1]:8.3f},{p[2]:8.3f})")
    time.sleep(0.25)