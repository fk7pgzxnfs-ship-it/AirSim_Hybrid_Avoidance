# -*- coding: utf-8 -*-
"""v2 demo: 100m x 10m corridor + 2 obstacle avoidance, repeated closed-loop flights.

Requirements:
  - UE 5.7 (GISMap, -game) already running, port 8990 open
  - DRL checkpoint models/drl_agent/ddpg_best.pth exists
Every flight reloads the scene via LoadScene RPC first, which cleanly
re-spawns the robot and avoids the SetPose snap-back bug (handover.md 11.10).
"""
import io
import sys
import os
import time
import csv
import glob
import re
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from airsim_interface.projectairsim_client import check_connection
from experiments.run_flight import run_single_flight

UE_LOG = r"D:\ProjectAirSim-main\unreal\Blocks 5.7\Saved\Logs\Blocks.log"
FLIGHTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs", "flights")


def count_obstacle_collisions(since_bytes: int) -> dict:
    """Count Obstacle1/Obstacle2 collision log lines appended after since_bytes."""
    out = {"Obstacle1": 0, "Obstacle2": 0}
    try:
        with open(UE_LOG, "rb") as fh:
            fh.seek(since_bytes)
            tail = fh.read().decode("utf-8", errors="replace")
        for name in out:
            out[name] = tail.count(
                "Collision detected between 'Frame' and '%s'" % name)
    except Exception as e:
        print("[demo] warn: cannot read UE log:", repr(e))
    return out


def log_size() -> int:
    try:
        return os.path.getsize(UE_LOG)
    except Exception:
        return 0


def verify_csv(path: str, goal_x: float, scene=None) -> dict:
    """Verify a flight CSV: reaches goal, stays in corridor, keeps altitude."""
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return {"ok": False, "reason": "empty csv"}
    xs = [float(r["x"]) for r in rows]
    ys = [float(r["y"]) for r in rows]
    zs = [float(r["z"]) for r in rows]
    if scene is not None:
        y_lo, y_hi = scene.y_min - 0.1, scene.y_max + 0.1
    else:
        y_lo, y_hi = -5.1, 5.1
    return {
        "ok": True,
        "steps": len(rows),
        "x_max": max(xs),
        "y_min": min(ys),
        "y_max": max(ys),
        "z_min": min(zs),
        "z_max": max(zs),
        "reached": max(xs) >= goal_x - 3.0,
        "corridor": all(y_lo <= y <= y_hi for y in ys),
        "aloft": all(z < -5.0 for z in zs),
    }


def main():
    parser = argparse.ArgumentParser(description="v2 demo: repeat closed-loop flights")
    parser.add_argument("--flights", type=int, default=3, help="number of flights")
    parser.add_argument("--goal_x", type=float, default=None, help="goal x (default: from scene)")
    parser.add_argument("--goal_y", type=float, default=None, help="goal y (default: from scene)")
    parser.add_argument("--scene", type=str, default=None,
                        help="scene yaml path (v3, e.g. config/scenes/scene_100x10.yaml)")
    parser.add_argument("--max_steps", type=int, default=2000)
    args = parser.parse_args()

    scene = None
    if args.scene:
        from scene_config import SceneConfig
        scene = SceneConfig.load(args.scene)
        if args.goal_x is None:
            args.goal_x = float(scene.goal[0])
        if args.goal_y is None:
            args.goal_y = float(scene.goal[1])
    if args.goal_x is None:
        args.goal_x = 100.0
    if args.goal_y is None:
        args.goal_y = 0.0

    print("=" * 60)
    print("AirSim Hybrid Avoidance v3 demo")
    if scene is not None:
        print("  scene:   %s" % scene.id)
    print("  corridor: %.0fm x %.0fm, obstacles: %d" %
          (scene.x_max - scene.x_min if scene else 100,
           scene.y_max - scene.y_min if scene else 10,
           len(scene.obstacles) if scene else 2))
    print("  flights:  %d, goal: (%.1f, %.1f), max_steps: %d" %
          (args.flights, args.goal_x, args.goal_y, args.max_steps))
    print("=" * 60)

    if not check_connection():
        print("[demo] ERROR: UE not reachable on port 8990.")
        print("  start UE first, e.g.:")
        print("  UnrealEditor.exe Blocks.uproject GISMap -game -windowed -ResX=1280 -ResY=720")
        sys.exit(1)

    summary = []
    for i in range(1, args.flights + 1):
        print("\n" + "-" * 60)
        print("[demo] flight %d/%d start" % (i, args.flights))
        print("-" * 60)
        before = log_size()
        before_flights = set(glob.glob(os.path.join(FLIGHTS_DIR, "flight_2026*.csv")))

        result = run_single_flight(args.goal_x, args.goal_y,
                                   "config/default.yaml", args.max_steps,
                                   reload_scene=True, scene_path=args.scene)

        new_files = sorted(set(glob.glob(os.path.join(FLIGHTS_DIR, "flight_2026*.csv"))) - before_flights)
        csv_path = new_files[-1] if new_files else None
        collisions = count_obstacle_collisions(before)

        ok = result.get("success", False)
        v = {"ok": ok, "csv": os.path.basename(csv_path) if csv_path else None,
             "steps": result.get("steps", 0),
             "time": result.get("time", 0.0),
             "collisions": collisions}
        if ok and csv_path:
            c = verify_csv(csv_path, args.goal_x, scene)
            v["csv_ok"] = c["ok"] and c["reached"] and c["corridor"] and c["aloft"]
            v["x_max"] = c["x_max"]
            v["y_range"] = (c["y_min"], c["y_max"])
            v["z_range"] = (c["z_min"], c["z_max"])
        else:
            v["csv_ok"] = False
            v["reason"] = result.get("reason", "?")

        print("[demo] flight %d result: success=%s steps=%d time=%.1fs collisions=%s csv=%s" %
              (i, ok, v["steps"], v["time"], collisions, v["csv"]))
        summary.append(v)
        time.sleep(2.0)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_ok = True
    for i, v in enumerate(summary, 1):
        flag = "PASS" if (v["ok"] and v.get("csv_ok") and
                          v["collisions"]["Obstacle1"] == 0 and
                          v["collisions"]["Obstacle2"] == 0) else "FAIL"
        if flag == "FAIL":
            all_ok = False
        print("flight %d: %s  steps=%d time=%.1fs x_max=%.1f y=[%.2f,%.2f] z=[%.1f,%.1f] "
              "obs_collisions=%s" %
              (i, flag, v["steps"], v["time"], v.get("x_max", -1),
               v.get("y_range", (0, 0))[0], v.get("y_range", (0, 0))[1],
               v.get("z_range", (0, 0))[0], v.get("z_range", (0, 0))[1],
               v["collisions"]))
    print("=" * 60)
    print("ALL PASS" if all_ok else "SOME FLIGHTS FAILED - see details above")
    sys.exit(0 if all_ok else 2)


if __name__ == "__main__":
    main()
