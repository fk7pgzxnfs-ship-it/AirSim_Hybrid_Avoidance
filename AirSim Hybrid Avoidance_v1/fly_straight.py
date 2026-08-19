#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""
直线飞行脚本: 空地图 100m 长, 无人机从 (0,0) 飞到 (100,0)
用法: python fly_straight.py [--distance 100] [--speed 5]
要求: UE 正在 Play/‐game 状态 (ProjectAirSim, 端口 8990)
"""
import sys, time, os, csv, argparse, socket

SDK_PATH = "D:/ProjectAirSim-main/client/python/projectairsim/src"
if os.path.isdir(SDK_PATH) and SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)
import msgpack, pynng

UE_ADDR = "127.0.0.1"
PORT_SVC = 8990
SCENE_ID = "SceneDroneClassic"
DRONE = "/Sim/" + SCENE_ID + "/robots/Drone1"


def rpc(method, params=None, timeout=30.0, dial_wait=0.8):
    """Req/Rep RPC, 非阻塞轮询接收 (pynng recv_timeout 单位为毫秒, 避免误用)"""
    if params is None:
        params = {}
    with pynng.Req0() as sock:
        sock.dial("tcp://%s:%d" % (UE_ADDR, PORT_SVC), block=False)
        time.sleep(dial_wait)
        inner = msgpack.packb(params, use_bin_type=True)
        req = {"method": method, "params": {"data": inner}, "version": 1.0, "id": 1}
        req = {k: v.encode() if isinstance(v, str) else v for k, v in req.items()}
        sock.send(msgpack.packb(req, use_bin_type=True))
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                resp = sock.recv(block=False)
                data = msgpack.unpackb(resp)
                if "error" in data:
                    err = msgpack.unpackb(data["error"]["data"])
                    msg = err.get(b"message", err.get("message", b"?"))
                    return {"error": msg.decode() if isinstance(msg, bytes) else msg}
                return {"result": msgpack.unpackb(data["result"]["data"])}
            except pynng.TryAgain:
                time.sleep(0.05)
            except Exception as e:
                return {"exc": repr(e)}
        return {"timeout": True}


def get_pos():
    r = rpc(DRONE + "/GetGroundTruthPose", timeout=6)
    if "result" not in r:
        return None
    t = r["result"]["translation"]
    return t["x"], t["y"], t["z"]


def check_ue():
    s = socket.socket(); s.settimeout(2)
    ok = s.connect_ex((UE_ADDR, PORT_SVC)) == 0
    s.close(); return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--distance", type=float, default=100.0)
    ap.add_argument("--speed", type=float, default=5.0)
    ap.add_argument("--height", type=float, default=-12.0)
    ap.add_argument("--segment", type=float, default=4.0)
    args = ap.parse_args()

    print("=" * 60)
    print("  空地图直线飞行: (0,0) -> (%.0f,0), %.0f m" % (args.distance, args.distance))
    print("=" * 60)

    if not check_ue():
        print("[FAIL] UE not running (port %d)" % PORT_SVC)
        sys.exit(1)
    print("[OK] UE connected")

    # 时钟自检
    r1 = rpc("/Sim/" + SCENE_ID + "/GetSimTime", timeout=6)
    time.sleep(2)
    r2 = rpc("/Sim/" + SCENE_ID + "/GetSimTime", timeout=6)
    if "result" in r1 and "result" in r2:
        dt = r2["result"] - r1["result"]
        print("[OK] Sim time advancing (+%.2f s / 2 s real)" % (dt / 1e9))
        if dt <= 0:
            print("[FAIL] 模拟时钟未推进, 无法飞行")
            sys.exit(1)

    pos = get_pos()
    print("[OK] start pos: %.1f, %.1f, %.1f" % pos)

    print("\n--- 起飞 ---")
    rpc(DRONE + "/EnableApiControl")
    rpc(DRONE + "/Arm")
    rpc(DRONE + "/MoveByVelocity", {"vx": 0, "vy": 0, "vz": -3, "duration": 3,
                                   "drivetrain": 0, "yaw_is_rate": False, "yaw": 0}, timeout=30)
    t0 = time.time()
    while time.time() - t0 < 20:
        p = get_pos()
        if p and p[2] < args.height + 3:
            break
        time.sleep(0.3)
    print("[OK] altitude: %.1f m" % get_pos()[2])

    print("\n--- 直线飞行 (%.0f m @ %.0f m/s) ---" % (args.distance, args.speed))
    log = []
    start_t = time.time()
    last_x = 0.0
    while True:
        p = get_pos()
        if p is None:
            print("[WARN] 位置获取失败")
            break
        log.append((time.time() - start_t, p[0], p[1], p[2]))
        if p[0] >= args.distance - 2.0:
            break
        if p[0] < last_x - 2.0:
            print("[WARN] 位置回退, 可能碰撞")
        last_x = p[0]
        r = rpc(DRONE + "/MoveByVelocity", {"vx": args.speed, "vy": 0, "vz": 0,
                                              "duration": args.segment,
                                              "drivetrain": 0, "yaw_is_rate": False, "yaw": 0},
               timeout=60)
        if "result" not in r:
            print("[WARN] MoveByVelocity 异常: %s" % r)
            break

    rpc(DRONE + "/Hover")
    p = get_pos()
    log.append((time.time() - start_t, p[0], p[1], p[2]))
    elapsed = time.time() - start_t
    print("\n[OK] 到达: %.1f, %.1f, %.1f  (用时 %.1f s)" % (p[0], p[1], p[2], elapsed))
    print("[OK] 平均速度: %.2f m/s" % (p[0] / elapsed if elapsed > 0 else 0))

    out = "logs/flights/straight_100m.csv"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "x", "y", "z"])
        for row in log:
            w.writerow(["%.3f" % row[0], "%.3f" % row[1], "%.3f" % row[2], "%.3f" % row[3]])
    print("[OK] 轨迹保存: %s (%d 点)" % (out, len(log)))


if __name__ == "__main__":
    main()
