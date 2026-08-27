# -*- coding: utf-8 -*-
"""
scene_config.py - v3 场景配置模块
====================================
单一场景文件（YAML）定义地图范围、起点、终点、障碍物与路线，
供飞行（Supervisor）、训练（train_drl_v2）、评估（evaluate_smoothness）、
UE 场景生成（load_scene）共用，替代 v2 分散硬编码。

场景文件示例（config/scenes/scene_100x10.yaml）:
    id: MyScene
    map:
      x_min: 0.0
      x_max: 100.0
      y_min: -5.0
      y_max: 5.0
      resolution: 0.5
    start: [0.0, 0.0]        # 起点 (x, y)
    goal: [100.0, 0.0]       # 终点 (x, y)
    takeoff_height: -12.0
    route:
      mode: line             # line(默认) | astar
    obstacles:
      - name: Obstacle1
        x: 30.0
        y: 0.0
        w: 2.0               # 底面宽度 (m)
        h: 2.0               # 底面深度 (m)
        height: 14.0         # 高度 (m)
"""

import os
import copy
import numpy as np
import yaml

PROJECT_ROOT = os.environ.get("AIRSIM_ROOT") or os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.join(PROJECT_ROOT, "config", "scene_v2_100x10.jsonc")
DEFAULT_SCENES_DIR = os.path.join(PROJECT_ROOT, "config", "scenes")
GENERATED_DIR = os.path.join(PROJECT_ROOT, "config", "scenes", "generated")


class Obstacle:
    """方形柱状障碍物（底面 w x h，高度 height，中心 (x, y)）"""

    def __init__(self, name, x, y, w, h, height):
        self.name = name or "Obstacle"
        self.x = float(x)
        self.y = float(y)
        self.w = float(w)
        self.h = float(h)
        self.height = float(height)

    @property
    def physical_radius(self):
        """物理/LiDAR 等效半径（内切圆）"""
        return max(self.w, self.h) / 2.0

    @property
    def plan_radius(self):
        """规划膨胀半径（A*/势场用，物理半径 + 0.5m 安全裕量）"""
        return self.physical_radius + 0.5

    @property
    def corners(self):
        """底面四角 (x, y) 列表，用于画图与横向距离计算"""
        hw, hh = self.w / 2.0, self.h / 2.0
        return [(self.x - hw, self.y - hh), (self.x + hw, self.y - hh),
                (self.x + hw, self.y + hh), (self.x - hw, self.y + hh)]

    def to_dict(self):
        return {"name": self.name, "x": self.x, "y": self.y,
                "w": self.w, "h": self.h, "height": self.height}

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        name = str(d.pop("name", "Obstacle"))
        x = float(d.pop("x"))
        y = float(d.pop("y"))
        if "radius" in d:  # 兼容圆柱简写：radius -> w=h=2r
            r = float(d.pop("radius"))
            w = h = 2.0 * r
            height = float(d.pop("height", 14.0))
        else:
            w = float(d.pop("w", 2.0))
            h = float(d.pop("h", 2.0))
            height = float(d.pop("height", 14.0))
        return cls(name, x, y, w, h, height)

    def __repr__(self):
        return "Obstacle(%s, %.1f, %.1f, %.1fx%.1fx%.1f)" % (
            self.name, self.x, self.y, self.w, self.h, self.height)


class SceneConfig:
    """场景配置：地图 + 起点/终点 + 障碍物 + 路线"""

    def __init__(self, scene_id, x_min, x_max, y_min, y_max, resolution,
                 start, goal, obstacles=None, takeoff_height=-12.0,
                 route_mode="line", source_path=""):
        self.id = scene_id
        self.x_min = float(x_min)
        self.x_max = float(x_max)
        self.y_min = float(y_min)
        self.y_max = float(y_max)
        self.resolution = float(resolution)
        self.start = np.array([float(start[0]), float(start[1])])
        self.goal = np.array([float(goal[0]), float(goal[1])])
        self.takeoff_height = float(takeoff_height)
        self.route_mode = route_mode if route_mode in ("line", "astar") else "line"
        self.obstacles = list(obstacles or [])
        self.source_path = source_path

    # ---------- 构造 ----------
    @classmethod
    def from_dict(cls, d, source_path=""):
        m = d.get("map", d)  # 兼容 map 直接平铺
        scene_id = str(d.get("id", os.path.splitext(os.path.basename(source_path))[0]
                               if source_path else "MyScene"))
        start = d.get("start", d.get("origin", [m.get("x_min", 0.0), m.get("y_min", 0.0)]))
        goal = d.get("goal", [m.get("x_max", 100.0), m.get("y_max", 0.0)])
        obs = [Obstacle.from_dict(o) for o in d.get("obstacles", [])]
        route = d.get("route", {}) or {}
        return cls(
            scene_id=scene_id,
            x_min=m["x_min"], x_max=m["x_max"],
            y_min=m["y_min"], y_max=m["y_max"],
            resolution=m.get("resolution", 0.5),
            start=start, goal=goal,
            obstacles=obs,
            takeoff_height=d.get("takeoff_height", -12.0),
            route_mode=route.get("mode", "line"),
            source_path=source_path,
        )

    @classmethod
    def from_legacy_config(cls, cfg):
        """从 v2 的 default.yaml（含 map 段）构造场景，兼容旧脚本"""
        m = cfg['map']
        scene_id = cfg.get('airsim', {}).get('scene_id', 'SceneDroneClassic')
        obs_cfg = m.get('obstacles_physical',
                        [[o[0], o[1], 1.0] for o in m.get('obstacles', [])])
        obstacles = []
        for i, o in enumerate(obs_cfg):
            obstacles.append({'name': 'Obstacle%d' % (i + 1),
                              'x': o[0], 'y': o[1], 'radius': o[2], 'height': 14.0})
        return cls.from_dict({
            'id': scene_id,
            'map': m,
            'start': m.get('origin', [m.get('x_min', 0.0), m.get('y_min', 0.0)]),
            'goal': m.get('goal', [m.get('x_max', 100.0), 0.0]),
            'takeoff_height': cfg.get('airsim', {}).get('takeoff_height', -12.0),
            'obstacles': obstacles,
        }, source_path=cfg.get('_source_path', ''))

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)
        return cls.from_dict(d, source_path=os.path.abspath(path))

    # ---------- 属性 ----------
    @property
    def bounds(self):
        return (self.x_min, self.x_max, self.y_min, self.y_max)

    @property
    def obstacles_plan(self):
        """规划障碍 [[x, y, 膨胀半径], ...]"""
        return [[o.x, o.y, o.plan_radius] for o in self.obstacles]

    @property
    def obstacles_physical(self):
        """物理/LiDAR 障碍 [[x, y, 半径], ...]"""
        return [[o.x, o.y, o.physical_radius] for o in self.obstacles]

    def in_bounds(self, x, y):
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    # ---------- 校验 ----------
    def validate(self):
        """返回错误信息列表（空列表 = 通过）"""
        errs = []
        if self.x_max <= self.x_min:
            errs.append("map.x_max 必须大于 map.x_min")
        if self.y_max <= self.y_min:
            errs.append("map.y_max 必须大于 map.y_min")
        if not self.in_bounds(*self.start):
            errs.append("起点 (%s) 超出地图范围" % (self.start.tolist(),))
        if not self.in_bounds(*self.goal):
            errs.append("终点 (%s) 超出地图范围" % (self.goal.tolist(),))
        if np.linalg.norm(self.start - self.goal) < 1.0:
            errs.append("起点与终点距离过近（<1m）")
        seen = set()
        for o in self.obstacles:
            if o.name in seen:
                errs.append("障碍物名称重复: %s" % o.name)
            seen.add(o.name)
            if not self.in_bounds(o.x, o.y):
                errs.append("障碍物 %s (%s) 超出地图范围" % (o.name, (o.x, o.y)))
            for o2 in self.obstacles:
                if o2 is o:
                    continue
                dx = abs(o.x - o2.x)
                dy = abs(o.y - o2.y)
                if dx < (o.w + o2.w) / 2.0 - 1e-6 and dy < (o.h + o2.h) / 2.0 - 1e-6:
                    errs.append("障碍物 %s 与 %s 重叠" % (o.name, o2.name))
        # 起点终点不得压在障碍物上（按物理半径判定）
        for o in self.obstacles:
            r = o.physical_radius + 0.3
            if np.linalg.norm(self.start - [o.x, o.y]) < r:
                errs.append("起点落在障碍物 %s 上" % o.name)
            if np.linalg.norm(self.goal - [o.x, o.y]) < r:
                errs.append("终点落在障碍物 %s 上" % o.name)
        return errs

    # ---------- 可达性检查（A*） ----------
    def check_reachable(self):
        """用膨胀栅格 + A* 检查起点终点是否可达"""
        from planning.grid_map import GridMap
        from planning.a_star import AStar
        gm = GridMap(self.x_min, self.x_max, self.y_min, self.y_max, self.resolution)
        gm.add_obstacle_list(self.obstacles_plan)
        gm.inflate_obstacles(0.5)
        astar = AStar(gm)
        path = astar.plan(tuple(self.start), tuple(self.goal))
        if len(path) == 0:
            return {"reachable": False, "path_len": 0.0,
                    "message": "A* 未找到可达路径：起点被障碍物包围或布局不可达"}
        seg = np.diff(np.array(path), axis=0)
        length = float(np.sum(np.linalg.norm(seg, axis=1)))
        return {"reachable": True, "path_len": length,
                "message": "A* 可达，规划路径长度 %.1f m" % length}

    # ---------- 直线路线 ----------
    def line_points(self, spacing=0.5):
        """起点到终点的直线离散点 (N, 2)"""
        d = np.linalg.norm(self.goal - self.start)
        n = max(int(d / spacing), 1)
        ts = np.linspace(0.0, 1.0, n + 1)
        return self.start[None, :] + ts[:, None] * (self.goal - self.start)[None, :]

    def lateral_distance(self, pos):
        """点到起点-终点直线的横向距离（直线路线语义）"""
        v = self.goal - self.start
        L2 = float(v @ v)
        if L2 < 1e-9:
            return float(np.linalg.norm(np.array(pos[:2]) - self.start))
        t = np.clip((np.array(pos[:2]) - self.start) @ v / L2, 0.0, 1.0)
        proj = self.start + t * v
        return float(np.linalg.norm(np.array(pos[:2]) - proj))

    # ---------- UE 场景生成 ----------
    def to_ue_dict(self, template_path=None):
        """生成 UE LoadScene 可用的场景字典（地面板 + 障碍物 + 机器人）"""
        import commentjson
        tpl_path = template_path or DEFAULT_TEMPLATE
        with open(tpl_path, "r", encoding="utf-8") as f:
            tpl = commentjson.load(f)
        out = copy.deepcopy(tpl)
        out["id"] = self.id

        # 机器人起点（出生点 z 沿用模板，飞行时由 reset_position 重新定位）
        for actor in out.get("actors", []):
            if actor.get("type") == "robot":
                actor["origin"]["xyz"] = "%.3f %.3f %s" % (
                    self.start[0], self.start[1],
                    actor["origin"]["xyz"].split()[2])
                break

        # 环境 actor：地面 + 障碍物
        env = []
        tpl_env = tpl.get("environment-actors", [])
        tpl_ground = next((a for a in tpl_env if "Ground" in a.get("name", "")), None)
        tpl_obs = next((a for a in tpl_env if "Obstacle" in a.get("name", "")), None)

        if tpl_ground is not None:
            ground = copy.deepcopy(tpl_ground)
            cx = (self.x_min + self.x_max) / 2.0
            cy = (self.y_min + self.y_max) / 2.0
            sx = (self.x_max - self.x_min) + 8.0   # 两侧各延伸 4m
            sy = (self.y_max - self.y_min)
            ground["name"] = "Ground%d" % int(round(self.x_max - self.x_min))
            ground["origin"]["xyz"] = "%.3f %.3f -0.1" % (cx, cy)
            for link in ground.get("env-actor-config", {}).get("links", []):
                vis = link.get("visual", {}).get("geometry", {})
                if vis.get("type") == "unreal_mesh":
                    vis["scale"] = "%.3f %.3f 0.2" % (sx, sy)
            env.append(ground)

        if tpl_obs is not None:
            for o in self.obstacles:
                obs = copy.deepcopy(tpl_obs)
                obs["name"] = o.name
                obs["origin"]["xyz"] = "%.3f %.3f %.3f" % (o.x, o.y, -o.height / 2.0)
                scale = "%.3f %.3f %.3f" % (o.w, o.h, o.height)
                for link in obs.get("env-actor-config", {}).get("links", []):
                    # 物理惯性盒
                    geo = link.get("inertial", {}).get("geometry", {})
                    if "box" in geo:
                        geo["box"]["size"] = scale
                    aero = link.get("inertial", {}).get("aerodynamics", {})
                    if "geometry" in aero and "box" in aero.get("geometry", {}):
                        aero["geometry"]["box"]["size"] = scale
                    # 视觉
                    vis = link.get("visual", {}).get("geometry", {})
                    if vis.get("type") == "unreal_mesh":
                        vis["scale"] = scale
                env.append(obs)

        out["environment-actors"] = env
        return out

    def to_ue_jsonc(self, template_path=None):
        """生成 UE 场景 jsonc 字符串"""
        import json
        return json.dumps(self.to_ue_dict(template_path), indent=2,
                          ensure_ascii=False)

    def dump_ue_scene(self, out_path=None):
        """生成 UE 场景文件并返回路径（默认 config/scenes/generated/<id>.jsonc）"""
        os.makedirs(GENERATED_DIR, exist_ok=True)
        if out_path is None:
            safe = "".join(c for c in self.id if c.isalnum() or c in "-_")
            out_path = os.path.join(GENERATED_DIR, safe + ".jsonc")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(self.to_ue_jsonc())
        return out_path

    # ---------- 序列化 ----------
    def to_dict(self):
        return {
            'id': self.id,
            'map': {
                'x_min': float(self.x_min), 'x_max': float(self.x_max),
                'y_min': float(self.y_min), 'y_max': float(self.y_max),
                'resolution': float(self.resolution),
            },
            'start': [float(self.start[0]), float(self.start[1])],
            'goal': [float(self.goal[0]), float(self.goal[1])],
            'takeoff_height': float(self.takeoff_height),
            'route': {'mode': self.route_mode},
            'obstacles': [o.to_dict() for o in self.obstacles],
        }


        d = {
            "id": self.id,
            "map": {
                "x_min": float(self.x_min), "x_max": float(self.x_max),
                "y_min": float(self.y_min), "y_max": float(self.y_max),
                "resolution": float(self.resolution),
            },
            "start": [float(self.start[0]), float(self.start[1])],
            "goal": [float(self.goal[0]), float(self.goal[1])],
            "takeoff_height": float(self.takeoff_height),
            "route": {"mode": self.route_mode},
            "obstacles": [o.to_dict() for o in self.obstacles],
        }
        return yaml.safe_dump(d, allow_unicode=True, sort_keys=False,
                              default_flow_style=False)

    def dump(self, path=None):
        path = path or self.source_path
        if not path:
            raise ValueError("需要指定输出路径")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_yaml())
        self.source_path = os.path.abspath(path)
        return path

    # ---------- 预览图 ----------
    def to_preview(self, out_path=None, title=None):
        """生成 2D 俯视图 PNG（地图/障碍/直线路线/起点终点）"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        from matplotlib.patches import Rectangle, Circle
        # Windows 中文字体（避免预览图中文变方块）
        for _f in ["Microsoft YaHei", "SimHei", "SimSun"]:
            try:
                fm.findfont(_f, fallback_to_default=False)
                plt.rcParams["font.sans-serif"] = [_f]
                break
            except Exception:
                continue
        plt.rcParams["axes.unicode_minus"] = False
        fig, ax = plt.subplots(figsize=(10, 8))
        xr = self.x_max - self.x_min
        yr = self.y_max - self.y_min
        ax.add_patch(Rectangle((self.x_min, self.y_min), xr, yr,
                               fill=False, edgecolor="k", lw=2,
                               label="地图边界"))
        # 网格
        for gx in np.arange(self.x_min, self.x_max, 5.0):
            ax.axvline(gx, color="gray", lw=0.5, alpha=0.5)
        for gy in np.arange(self.y_min, self.y_max, 5.0):
            ax.axhline(gy, color="gray", lw=0.5, alpha=0.5)
        # 障碍物
        for o in self.obstacles:
            ax.add_patch(Rectangle((o.x - o.w / 2, o.y - o.h / 2), o.w, o.h,
                                   facecolor="tab:red", edgecolor="darkred",
                                   alpha=0.85, label="障碍物" if o is self.obstacles[0] else None))
            ax.text(o.x, o.y, o.name, ha="center", va="center",
                    color="white", fontsize=9)
        # 直线路线
        line = self.line_points(spacing=1.0)
        ax.plot(line[:, 0], line[:, 1], "--", color="tab:blue", lw=1.5,
                label="直线路线")
        # 起点/终点
        ax.plot(*self.start, marker="o", ms=10, color="tab:green",
                label="起点 (%s)" % (self.start.tolist(),))
        ax.plot(*self.goal, marker="*", ms=16, color="tab:orange",
                label="终点 (%s)" % (self.goal.tolist(),))
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        ax.set_title(title or "场景预览: %s" % self.id)
        ax.set_aspect("equal")
        ax.legend(loc="upper right")
        ax.grid(False)
        if out_path:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            fig.savefig(out_path, dpi=130, bbox_inches="tight")
            plt.close(fig)
            return out_path
        return fig

    def __repr__(self):
        return "SceneConfig(%s, x[%s,%s] y[%s,%s], %d obs, %s->%s)" % (
            self.id, self.x_min, self.x_max, self.y_min, self.y_max,
            len(self.obstacles), self.start.tolist(), self.goal.tolist())
