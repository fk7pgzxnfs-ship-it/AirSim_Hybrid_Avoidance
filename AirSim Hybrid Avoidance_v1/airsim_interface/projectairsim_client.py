"""projectairsim_client.py — Project AirSim UE 适配器"""
import sys, time, json, os, asyncio
SDK_PATH = "D:/ProjectAirSim-main/client/python/projectairsim/src"
if os.path.isdir(SDK_PATH) and SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)
import msgpack, pynng, commentjson, numpy as np
from projectairsim import ProjectAirSimClient, World, Drone as ProjectAirSimDrone

UE_ADDR = "127.0.0.1"
PORT_TOPICS = 8989
PORT_SERVICES = 8990
SCENE_CFG = "D:/ProjectAirSim-main/unreal/Blocks 5.7/Content/scene_drone_classic.jsonc"
ROBOT_CFG = "D:/ProjectAirSim-main/unreal/Blocks 5.7/Content/robot_quadrotor_classic.jsonc"

def _rpc(method, params=None):
    if params is None: params = {}
    with pynng.Req0() as s:
        s.dial("tcp://%s:%d" % (UE_ADDR, PORT_SERVICES), block=False)
        time.sleep(1.5)
        inner = msgpack.packb(params, use_bin_type=True)
        req = {"method": method, "params": {"data": inner}, "version": 1.0, "id": 1}
        req = {k: v.encode() if isinstance(v, str) else v for k, v in req.items()}
        s.send(msgpack.packb(req, use_bin_type=True))
        s.recv_timeout = 15000
        resp = s.recv()
        data = msgpack.unpackb(resp)
        if "error" in data:
            err = msgpack.unpackb(data["error"]["data"])
            msg = err.get(b"message", err.get("message", b"?"))
            return {"error": msg.decode() if isinstance(msg, bytes) else msg}
        elif "result" in data:
            return {"result": msgpack.unpackb(data["result"]["data"])}
        return data

def check_connection():
    import socket
    s = socket.socket(); s.settimeout(2)
    ok = s.connect_ex((UE_ADDR, PORT_SERVICES)) == 0
    s.close(); return ok

def load_scene():
    cfg = commentjson.load(open(SCENE_CFG, encoding="utf-8"))
    robot = commentjson.load(open(ROBOT_CFG, encoding="utf-8"))
    for a in cfg.get("actors", []):
        if a.get("type") == "robot": a["robot-config"] = robot
    return _rpc("/Sim/LoadScene", {"scene_config": json.dumps(cfg)})

def check_scene():
    for sid in ["SceneDroneClassic","SceneBasicDrone","DefaultScene"]:
        r = _rpc("/Sim/%s/GetRobotIds" % sid)
        if "result" in r: return sid, r["result"]
    return None, None

class ProjectAirSimClientWrapper:
    def __init__(self, drone_name="Drone1"):
        self.drone_name = drone_name
        self._client = None; self._world = None; self._drone = None
        self._connect()
    def _connect(self):
        if not check_connection():
            raise ConnectionError("UE not running (port %d)" % PORT_SERVICES)
        sid, robots = check_scene()
        if not sid:
            print("[PA] Loading scene...")
            r = load_scene(); time.sleep(2)
            sid, robots = check_scene()
        if not sid:
            raise RuntimeError("No drone in scene. Add BP_Drone in UE editor, then Play.")
        print("[PA] Scene: %s, Robots: %s" % (sid, robots))
        try:
            self._client = ProjectAirSimClient(address=UE_ADDR, port_topics=PORT_TOPICS, port_services=PORT_SERVICES)
            self._client.connect()
            self._world = World(self._client)
            self._drone = ProjectAirSimDrone(self._client, self._world, robots[0] if robots else drone_name)
        except Exception as e:
            print("[PA] SDK connect failed: %s (using RPC fallback)" % e)
    def takeoff(self, height=-5.0, timeout=10.0):
        self._drone.enable_api_control(); self._drone.arm()
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        loop.run_until_complete(self._drone.takeoff_async(timeout_sec=timeout))
        loop.close()
    def land(self):
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        loop.run_until_complete(self._drone.land_async())
        loop.close()
    def get_position(self):
        pose = self._drone.get_ground_truth_pose()
        return np.array([pose.position.x_val, pose.position.y_val, pose.position.z_val])
    def get_velocity(self):
        kin = self._drone.get_ground_truth_kinematics()
        return np.array([kin.linear_velocity.x_val, kin.linear_velocity.y_val, kin.linear_velocity.z_val])
    def send_velocity(self, vx, vy, vz=0.0, duration=0.5):
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        loop.run_until_complete(self._drone.move_by_velocity_async(vx, vy, vz, duration))
        loop.close()
    def send_velocity_body(self, vx, vy, vz=0.0, duration=0.5):
        yaw = 0.0
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        loop.run_until_complete(self._drone.move_by_velocity_body_frame_async(vx, vy, vz, yaw, duration))
        loop.close()
    def get_pose(self):
        return self._drone.get_ground_truth_pose()
    def is_api_connected(self):
        try: return "result" in _rpc("/Sim/GetBuildCommitHash")
        except: return False
    def getMultirotorState(self, vehicle_name=""):
        return self._drone.get_ground_truth_kinematics()
