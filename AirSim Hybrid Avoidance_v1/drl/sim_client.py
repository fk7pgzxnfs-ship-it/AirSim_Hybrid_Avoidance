"""
drl/sim_client.py - ?? 2D ?????????DRL ????
========================================================
? ProjectAirSimClientWrapper ???????????????
?? <1ms?????? DDPG ???

???????????????????????
        ????? duration ????? UE MoveByVelocity ?????
????? episode ????????? ?1.5m???????????
"""

import math
import time
import numpy as np


class KinematicSimClient:
    """?? 2D ??????DroneEnv ????"""

    def __init__(self, obstacles=None, start=(0.0, 0.0, -12.0),
                 lidar_range=35.0, max_speed=3.0, vel_time_constant=0.5,
                 obstacle_jitter=1.5, noise_std=0.05, seed=42):
        # ????? [x, y, ????]
        self.base_obstacles = [(float(o[0]), float(o[1]), float(o[2]))
                               for o in (obstacles or [(30.0, 0.0, 1.0), (65.0, 0.0, 1.0)])]
        self.obstacles = list(self.base_obstacles)
        self.start = np.array(start, dtype=float)
        self.lidar_range = lidar_range
        self.max_speed = max_speed
        self.vel_time_constant = vel_time_constant
        self.obstacle_jitter = obstacle_jitter
        self.noise_std = noise_std
        self.rng = np.random.default_rng(seed)

        self._pos = np.array([0.0, 0.0, -12.0])
        self._vel = np.zeros(3)
        self._yaw = 0.0
        self._collided = False
        self.use_real = False

    # ---- ??? ----
    def get_obstacles(self):
        return np.array([[o[0], o[1], o[2]] for o in self.obstacles])

    def _randomize_obstacles(self):
        """? episode ????????????????????????"""
        new = []
        for ox, oy, r in self.base_obstacles:
            jx = self.rng.uniform(-self.obstacle_jitter, self.obstacle_jitter)
            jy = self.rng.uniform(-self.obstacle_jitter, self.obstacle_jitter)
            nx = min(max(ox + jx, 5.0), 95.0)
            ny = min(max(oy + jy, -3.0), 3.0)
            new.append((nx, ny, r))
        self.obstacles = new

    # ---- ?? ----
    def get_position(self):
        return self._pos.copy()

    def get_velocity(self):
        return self._vel.copy()

    def get_yaw(self):
        return self._yaw

    def get_lidar_data(self):
        """??????????? UE ???????"""
        points = []
        for ox, oy, r in self.obstacles:
            d = math.hypot(ox - self._pos[0], oy - self._pos[1])
            if d > self.lidar_range:
                continue
            n = 12
            for k in range(n):
                ang = 2.0 * math.pi * k / n
                px = ox - self._pos[0] + (r + 0.15) * math.cos(ang) +                      self.rng.normal(0, self.noise_std)
                py = oy - self._pos[1] + (r + 0.15) * math.sin(ang) +                      self.rng.normal(0, self.noise_std)
                points.append([px, py, 0.0])
        return np.array(points).reshape(-1, 3) if points else np.empty((0, 3))

    def get_collision_info(self):
        for ox, oy, r in self.obstacles:
            if math.hypot(ox - self._pos[0], oy - self._pos[1]) < r + 0.30:
                return True
        return False

    # ---- ?? ----
    def send_velocity(self, vx, vy, vz=0.0, duration=0.3):
        cmd = np.array([vx, vy, vz], dtype=float)
        cmd[:2] = np.clip(cmd[:2], -self.max_speed, self.max_speed)
        dt = max(duration, 1e-4)
        # ??????
        alpha = dt / (self.vel_time_constant + dt)
        self._vel = self._vel + alpha * (cmd - self._vel)
        self._pos = self._pos + self._vel * dt
        if abs(self._vel[0]) > 0.05 or abs(self._vel[1]) > 0.05:
            self._yaw = math.atan2(self._vel[1], self._vel[0])
        # ????
        self._pos[1] = np.clip(self._pos[1], -5.0, 5.0)
        self._pos[0] = np.clip(self._pos[0], -1.0, 101.0)
        self._collided = self.get_collision_info()
        return True

    def send_velocity_body(self, vx, vy, vz=0.0, duration=0.5):
        c, s = math.cos(self._yaw), math.sin(self._yaw)
        return self.send_velocity(c * vx - s * vy, s * vx + c * vy, vz, duration)

    def hover(self):
        return True

    def takeoff(self, height=-12.0, timeout=60.0):
        self._pos[2] = height
        return True

    def land(self, timeout=60.0):
        self._pos[2] = 0.0
        self._vel[:] = 0.0
        return True

    def reset_position(self, x, y, z):
        self._randomize_obstacles()
        self._pos = np.array([x, y, z], dtype=float)
        self._vel = np.zeros(3)
        self._yaw = 0.0
        self._collided = False
        return True

    # ---- ?? shim ----
    def getMultirotorState(self, vehicle_name=""):
        class _S:
            pass
        class _K:
            pass
        class _V:
            pass
        class _O:
            pass
        pos = _V(); pos.x_val, pos.y_val, pos.z_val = self._pos
        vel = _V(); vel.x_val, vel.y_val, vel.z_val = self._vel
        ori = _O(); ori.w_val = math.cos(self._yaw / 2); ori.x_val = 0.0
        ori.y_val = 0.0; ori.z_val = math.sin(self._yaw / 2)
        kin = _K(); kin.position = pos; kin.linear_velocity = vel; kin.orientation = ori
        st = _S(); st.kinematics_estimated = kin
        return st

    def get_pose(self):
        return self.getMultirotorState().kinematics_estimated

    def is_api_connected(self):
        return True

    def close(self):
        pass


class TrainSupervisor:
    """?? Supervisor ???????? DroneEnv ?????"""

    def __init__(self, client, start=(0.0, 0.0, -12.0), goal=(100.0, 0.0),
                 takeoff_height=-12.0):
        self.client = client
        self.start_pos = np.array(start[:2])
        self.goal_pos = np.array(goal[:2])
        self.cfg = {"airsim": {"takeoff_height": takeoff_height}}
