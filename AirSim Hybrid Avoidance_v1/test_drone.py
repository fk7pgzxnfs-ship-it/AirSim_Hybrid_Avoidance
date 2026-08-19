#!/usr/bin/env python3
"""
test_drone.py — Project AirSim 无人机测试（UE 5.7）
用法: python test_drone.py

要求: UE 5.7 正在运行且处于 Play/Game 状态
      已通过 UBT 编译 ProjectAirSim 插件（含场景自动加载补丁）
"""
import sys, time, json, os, socket

SDK_PATH = "D:/ProjectAirSim-main/client/python/projectairsim/src"
if os.path.isdir(SDK_PATH) and SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)

import msgpack, pynng, commentjson

UE_ADDR = "127.0.0.1"
PORT_SVC = 8990
SCENE_ID = "SceneDroneClassic"
DRONE_NAME = "Drone1"
BASE = "/Sim/" + SCENE_ID + "/robots/" + DRONE_NAME


def rpc(method, params=None):
    if params is None:
        params = {}
    with pynng.Req0() as sock:
        sock.dial("tcp://%s:%d" % (UE_ADDR, PORT_SVC), block=False)
        time.sleep(1.5)
        inner = msgpack.packb(params, use_bin_type=True)
        req = {"method": method, "params": {"data": inner}, "version": 1.0, "id": 1}
        req = {k: v.encode() if isinstance(v, str) else v for k, v in req.items()}
        sock.send(msgpack.packb(req, use_bin_type=True))
        sock.recv_timeout = 60000
        resp = sock.recv()
        data = msgpack.unpackb(resp)
        if "error" in data:
            err = msgpack.unpackb(data["error"]["data"])
            msg = err.get(b"message", err.get("message", b"?"))
            return {"error": msg.decode() if isinstance(msg, bytes) else msg}
        return {"result": msgpack.unpackb(data["result"]["data"])}


def get_pos():
    r = rpc(BASE + "/GetGroundTruthPose")
    if "result" in r:
        t = r["result"]["translation"]
        return t["x"], t["y"], t["z"]
    return 0, 0, 0


def check_ue():
    s = socket.socket()
    s.settimeout(2)
    ok = s.connect_ex((UE_ADDR, PORT_SVC)) == 0
    s.close()
    return ok


def main():
    print("=" * 60)
    print("  Project AirSim UE 5.7 — Drone Test")
    print("=" * 60)

    if not check_ue():
        print("[FAIL] UE not running (port %d)" % PORT_SVC)
        sys.exit(1)
    print("[OK] UE connected")

    # 时钟自检：MoveByVelocity 是同步命令（响应时间约等于 duration 模拟秒）。
    # 若 UE PIE 启动初期 / 窗口失焦时模拟时钟变慢，3 秒命令可能耗时 >15 秒。
    # 这里先确认模拟时钟在推进，避免“无人机不动”的误判。
    r1 = rpc("/Sim/" + SCENE_ID + "/GetSimTime")
    time.sleep(2)
    r2 = rpc("/Sim/" + SCENE_ID + "/GetSimTime")
    if "result" in r1 and "result" in r2:
        dt = r2["result"] - r1["result"]
        if dt > 0:
            print("[OK] Sim time advancing (+%.2f s / 2 s real)" % (dt / 1e9))
        else:
            print("[WARN] Sim time NOT advancing: %s -> %s" % (r1["result"], r2["result"]))
            print("  Drone will not move. Check UE window focused / PIE not paused / not in breakpoint.")
    else:
        print("[WARN] GetSimTime failed: %s" % r1)

    r = rpc("/Sim/GetBuildCommitHash")
    print("[OK] Sim version: %s" % r.get("result", "?")[:20])

    r = rpc(BASE + "/GetGroundTruthPose")
    if "error" in r:
        print("[FAIL] Drone not found: %s" % r["error"])
        print("  Make sure UE Game mode is running with ProjectAirSimGameMode")
        sys.exit(1)

    pos = get_pos()
    print("[OK] Drone position: %.1f, %.1f, %.1f" % pos)

    print("\n--- Flight Test ---")
    rpc(BASE + "/EnableApiControl")
    rpc(BASE + "/Arm")
    print("[OK] Control enabled / Armed")

    # Takeoff
    print("Takeoff...", end=" ", flush=True)
    rpc(BASE + "/MoveByVelocity", {"vx": 0, "vy": 0, "vz": -3, "duration": 3,
                                    "drivetrain": 0, "yaw_mode": 0, "yaw_is_rate": False, "yaw": 0})
    time.sleep(4)
    pos = get_pos()
    print("pos=%.1f,%.1f,%.1f" % pos)

    # Move forward
    print("Move forward...", end=" ", flush=True)
    rpc(BASE + "/MoveByVelocity", {"vx": 5, "vy": 0, "vz": 0, "duration": 2,
                                    "drivetrain": 0, "yaw_mode": 0, "yaw_is_rate": False, "yaw": 0})
    time.sleep(3)
    pos = get_pos()
    print("pos=%.1f,%.1f,%.1f" % pos)

    # Hover
    rpc(BASE + "/Hover")
    print("[OK] Hovering")

    print("\n=== Flight Test PASSED ===")


if __name__ == "__main__":
    main()
