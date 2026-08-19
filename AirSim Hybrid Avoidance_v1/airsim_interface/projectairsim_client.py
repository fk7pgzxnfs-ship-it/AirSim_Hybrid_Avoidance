"""
projectairsim_client.py - Project AirSim (UE 5.7) ???
========================================================
v2 ??????? + Supervisor/DroneEnv ??????

- ?????? Req0 ??????? RPC ?? dial?? 10 ????
- MoveByVelocity ????? RPC???????? duration ???
- ???????/?????????? + ?? LiDAR?? sim ???
  GetLidarData/GetCollisionInfo RPC?? docs/handover.md 10.x ???
"""

import sys
import time
import json
import math
import os
import socket

SDK_PATH = "D:/ProjectAirSim-main/client/python/projectairsim/src"
if os.path.isdir(SDK_PATH) and SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)

import msgpack
import pynng
import numpy as np

UE_ADDR = "127.0.0.1"
PORT_TOPICS = 8989
PORT_SERVICES = 8990
SCENE_CFG = "D:/ProjectAirSim-main/unreal/Blocks 5.7/Content/scene_drone_classic.jsonc"
ROBOT_CFG = "D:/ProjectAirSim-main/unreal/Blocks 5.7/Content/robot_quadrotor_classic.jsonc"


# ---------------------------------------------------------------------------
# ????? RPC?????? / ??????
# ---------------------------------------------------------------------------
def _rpc(method, params=None, timeout=30.0):
    if params is None:
        params = {}
    with pynng.Req0() as s:
        s.dial("tcp://%s:%d" % (UE_ADDR, PORT_SERVICES), block=False)
        time.sleep(1.0)
        inner = msgpack.packb(params, use_bin_type=True)
        req = {"method": method, "params": {"data": inner}, "version": 1.0, "id": 1}
        req = {k: v.encode() if isinstance(v, str) else v for k, v in req.items()}
        s.send(msgpack.packb(req, use_bin_type=True))
        s.recv_timeout = int(timeout * 1000)
        try:
            resp = s.recv()
        except Exception as e:
            return {"exc": repr(e)}
        data = msgpack.unpackb(resp)
        if "error" in data:
            err = msgpack.unpackb(data["error"]["data"])
            msg = err.get(b"message", err.get("message", b"?"))
            return {"error": msg.decode() if isinstance(msg, bytes) else msg}
        elif "result" in data:
            return {"result": msgpack.unpackb(data["result"]["data"])}
        return data


def check_connection():
    s = socket.socket()
    s.settimeout(2)
    ok = s.connect_ex((UE_ADDR, PORT_SERVICES)) == 0
    s.close()
    return ok


def load_scene(scene_config_path=None):
    """?? RPC ???????scene_config ? JSON ????"""
    if scene_config_path is None:
        scene_config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "scene_v2_100x10.jsonc")
    import commentjson
    cfg = commentjson.load(open(scene_config_path, encoding="utf-8"))
    robot = commentjson.load(open(ROBOT_CFG, encoding="utf-8"))
    for a in cfg.get("actors", []):
        if a.get("type") == "robot":
            a["robot-config"] = robot
    return _rpc("/Sim/LoadScene", {"scene_config": json.dumps(cfg)}, timeout=120)


def check_scene():
    for sid in ["SceneDroneClassic", "SceneBasicDrone", "DefaultScene"]:
        r = _rpc("/Sim/%s/GetRobotIds" % sid)
        if "result" in r:
            return sid, r["result"]
    return None, None


# ---------------------------------------------------------------------------
# ????????Supervisor / DroneEnv ???
# ---------------------------------------------------------------------------
class ProjectAirSimClientWrapper:
    """Project AirSim (UE) ?????????? AirSimClientWrapper ??"""

    def __init__(self, drone_name="Drone1", scene_id="SceneDroneClassic",
                 obstacles=None, addr=UE_ADDR, port=PORT_SERVICES,
                 lidar_range=35.0):
        self.drone_name = drone_name
        self.scene_id = scene_id
        self.addr = addr
        self.port = port
        self.vehicle_name = drone_name
        self.use_real = True
        # ?????: [(x, y, ????)]????? LiDAR ?????
        self.obstacles = [(float(o[0]), float(o[1]), float(o[2]))
                          for o in (obstacles or [(30.0, 0.0, 1.0), (65.0, 0.0, 1.0)])]
        self.lidar_range = lidar_range
        self._sock = None
        self._req_id = 0
        self._connect()

    # ---------------- ???? ----------------
    def _connect(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = pynng.Req0(recv_timeout=300000, send_timeout=30000)
        self._sock.dial("tcp://%s:%d" % (self.addr, self.port), block=False)
        time.sleep(1.0)

    def _drone_path(self):
        return "/Sim/%s/robots/%s" % (self.scene_id, self.drone_name)

    def _request(self, method, params=None, timeout=120.0):
        """???????????????????"""
        if params is None:
            params = {}
        for attempt in (0, 1):
            if self._sock is None:
                self._connect()
            self._req_id += 1
            inner = msgpack.packb(params, use_bin_type=True)
            req = {"method": method, "params": {"data": inner},
                   "version": 1.0, "id": self._req_id}
            req = {k: v.encode() if isinstance(v, str) else v
                   for k, v in req.items()}
            try:
                self._sock.send(msgpack.packb(req, use_bin_type=True))
                resp = self._sock.recv()
                data = msgpack.unpackb(resp)
                if "error" in data:
                    err = msgpack.unpackb(data["error"]["data"])
                    msg = err.get(b"message", err.get("message", b"?"))
                    return {"error": msg.decode() if isinstance(msg, bytes) else msg}
                if "result" in data:
                    return {"result": msgpack.unpackb(data["result"]["data"])}
                return data
            except Exception as e:
                if attempt == 0:
                    self._connect()
                    continue
                return {"exc": repr(e)}
        return {"exc": "unknown"}

    # ---------------- ???? ----------------
    def get_position(self):
        r = self._request(self._drone_path() + "/GetGroundTruthPose", timeout=15)
        if "result" in r:
            t = r["result"]["translation"]
            return np.array([t["x"], t["y"], t["z"]])
        return np.array([0.0, 0.0, -12.0])

    def get_velocity(self):
        r = self._request(self._drone_path() + "/GetGroundTruthKinematics", timeout=15)
        if "result" in r:
            v = r["result"].get("linear_velocity", {})
            return np.array([v.get("x", 0.0), v.get("y", 0.0), v.get("z", 0.0)])
        return np.zeros(3)

    def get_yaw(self):
        r = self._request(self._drone_path() + "/GetGroundTruthPose", timeout=15)
        if "result" in r:
            q = r["result"]["rotation"]
            w, x, y, z = q["w"], q["x"], q["y"], q["z"]
            return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
        return 0.0

    def get_lidar_data(self):
        """?? LiDAR??????????????????????????

        ? sim ??? GetLidarData RPC?? docs/handover.md??
        ???????????????????????? LiDAR ???
        """
        pos = self.get_position()
        points = []
        for ox, oy, r in self.obstacles:
            d = math.hypot(ox - pos[0], oy - pos[1])
            if d > self.lidar_range:
                continue
            n = 12
            for k in range(n):
                ang = 2.0 * math.pi * k / n
                px = ox - pos[0] + (r + 0.15) * math.cos(ang) + np.random.normal(0, 0.05)
                py = oy - pos[1] + (r + 0.15) * math.sin(ang) + np.random.normal(0, 0.05)
                points.append([px, py, 0.0])
        return np.array(points).reshape(-1, 3) if points else np.empty((0, 3))

    def get_collision_info(self):
        pos = self.get_position()
        for ox, oy, r in self.obstacles:
            if math.hypot(ox - pos[0], oy - pos[1]) < r + 0.30:
                return True
        return False

    # ---------------- ?? ----------------
    def takeoff(self, height=-12.0, timeout=60.0):
        self._request(self._drone_path() + "/EnableApiControl", timeout=15)
        self._request(self._drone_path() + "/Arm", timeout=15)
        t0 = time.time()
        while time.time() - t0 < timeout:
            p = self.get_position()
            if p[2] < height + 2.0:
                break
            self._request(self._drone_path() + "/MoveByVelocity",
                          {"vx": 0, "vy": 0, "vz": -3.0, "duration": 2.0,
                           "drivetrain": 0, "yaw_is_rate": False, "yaw": 0},
                          timeout=60)
        self._request(self._drone_path() + "/Hover", timeout=15)
        return True

    def land(self, timeout=60.0):
        r = self._request(self._drone_path() + "/Land",
                          {"timeout_sec": timeout}, timeout=timeout + 10)
        if "error" in r:
            # ???????
            self._request(self._drone_path() + "/MoveByVelocity",
                          {"vx": 0, "vy": 0, "vz": 2.0, "duration": 4.0,
                           "drivetrain": 0, "yaw_is_rate": False, "yaw": 0},
                          timeout=30)
        try:
            self._request(self._drone_path() + "/Disarm", timeout=15)
            self._request(self._drone_path() + "/DisableApiControl", timeout=15)
        except Exception:
            pass
        return True

    def send_velocity(self, vx, vy, vz=0.0, duration=0.3):
        self._request(self._drone_path() + "/MoveByVelocity",
                      {"vx": float(vx), "vy": float(vy), "vz": float(vz),
                       "duration": float(duration),
                       "drivetrain": 0, "yaw_is_rate": False, "yaw": 0},
                      timeout=30 + 60 * duration)
        return True

    def send_velocity_body(self, vx, vy, vz=0.0, duration=0.5):
        yaw = self.get_yaw()
        c, s = math.cos(yaw), math.sin(yaw)
        wx = c * vx - s * vy
        wy = s * vx + c * vy
        return self.send_velocity(wx, wy, vz, duration)

    def hover(self):
        self._request(self._drone_path() + "/Hover", timeout=15)
        return True

    def reset_position(self, x, y, z):
        """SetPose ??? DisableApiControl ????????"""
        self._request(self._drone_path() + "/DisableApiControl", timeout=15)
        pose = {"translation": {"x": float(x), "y": float(y), "z": float(z)},
                "rotation": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
                "frame_id": "DEFAULT_ID"}
        r = self._request(self._drone_path() + "/SetPose",
                          {"pose": pose, "reset_kinematics": True}, timeout=20)
        time.sleep(0.5)
        return "error" not in r

    # ---------------- ?? shim ----------------
    def getMultirotorState(self, vehicle_name=""):
        class _State:
            pass
        class _Kin:
            pass
        class _Vec:
            pass
        class _Ori:
            pass
        p = self.get_position()
        v = self.get_velocity()
        yaw = self.get_yaw()
        pos = _Vec(); pos.x_val, pos.y_val, pos.z_val = p
        vel = _Vec(); vel.x_val, vel.y_val, vel.z_val = v
        ori = _Ori()
        ori.w_val = math.cos(yaw / 2.0)
        ori.x_val = 0.0
        ori.y_val = 0.0
        ori.z_val = math.sin(yaw / 2.0)
        kin = _Kin()
        kin.position = pos
        kin.linear_velocity = vel
        kin.orientation = ori
        st = _State()
        st.kinematics_estimated = kin
        return st

    def get_pose(self):
        return self.getMultirotorState().kinematics_estimated

    def is_api_connected(self):
        try:
            return "result" in self._request("/Sim/GetBuildCommitHash", timeout=15)
        except Exception:
            return False

    def get_obstacles(self):
        return np.array(self.obstacles)

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
