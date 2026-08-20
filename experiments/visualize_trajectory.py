"""
experiments/visualize_trajectory.py - ????????v2?
??: python experiments/visualize_trajectory.py [--csv logs/flights/flight_xxx.csv]
"""
import sys, os, glob, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_csv(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows:
        return None
    keys = [k for k in rows[0].keys()]
    out = {}
    for k in keys:
        try:
            out[k] = np.array([float(r[k]) for r in rows])
        except ValueError:
            out[k] = np.array([r[k] for r in rows])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.csv:
        files = [args.csv]
    else:
        files = sorted(glob.glob("logs/flights/flight_*.csv"))
    if not files:
        print("no flight csv found")
        return
    path = files[-1]
    data = load_csv(path)
    print("plot:", path)
    if data is None:
        print("empty csv")
        return

    fig, axes = plt.subplots(2, 1, figsize=(10, 7))
    ax = axes[0]
    ax.plot(data["x"], data["y"], "b-", lw=1.5, label="trajectory")
    ax.scatter(data["x"][0], data["y"][0], c="green", s=60, marker="o", label="start")
    ax.scatter(data["x"][-1], data["y"][-1], c="red", s=60, marker="*", label="end")
    # obstacles
    import yaml
    cfg = yaml.safe_load(open("config/default.yaml", encoding="utf-8"))
    for o in cfg["map"]["obstacles_physical"]:
        circle = plt.Circle((o[0], o[1]), o[2], color="gray", alpha=0.6)
        ax.add_patch(circle)
    ax.set_xlim(0, 100)
    ax.set_ylim(-6, 6)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title("v2 corridor 100x10 - trajectory")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)

    ax2 = axes[1]
    ax2.plot(data["x"], data["z"], "r-", lw=1.2)
    ax2.set_xlabel("x (m)")
    ax2.set_ylabel("z (m, NED)")
    ax2.set_title("altitude")
    ax2.grid(alpha=0.3)

    out = args.out or (path.replace(".csv", ".png"))
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print("saved:", out)


if __name__ == "__main__":
    main()
