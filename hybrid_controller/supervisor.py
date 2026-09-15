"""
??????? (v2 / UE 5.7)
??????(A*) + ????(DRL) + ????(??)???????
"""

import sys
import os

# ?????????? sys.path??????????
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import time
import numpy as np
import yaml

from airsim_interface.projectairsim_client import ProjectAirSimClientWrapper
from airsim_interface.sensor_processor import SensorProcessor
from hybrid_controller.global_planner import GlobalPlanner
from hybrid_controller.local_planner import LocalPlanner
from hybrid_controller.safety_monitor import SafetyMonitor
from planning.grid_map import GridMap
from planning.potential_field import PotentialField


class Supervisor:
    """?????????????"""

    def __init__(self, config_path: str = "config/default.yaml",
                 scene_path: str = None, scene=None):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.cfg = yaml.safe_load(f)

        # v3: 场景配置（地图/起点/终点/障碍物/路线）优先来自场景文件；
        # 未指定时从 default.yaml 的 map 段构造（兼容旧调用）
        if scene is not None:
            self.scene = scene
        elif scene_path:
            from scene_config import SceneConfig
            self.scene = SceneConfig.load(scene_path)
        else:
            from scene_config import SceneConfig
            self.scene = SceneConfig.from_legacy_config(self.cfg)

        # 训练桩/评估等通过 cfg['airsim']['takeoff_height'] 取高度，保持兼容
        self.cfg.setdefault('airsim', {})['takeoff_height'] = self.scene.takeoff_height

        self._init_modules()
        self.flight_log = []
        self.step_count = 0
        self.is_running = False

    def _init_modules(self) -> None:
        cfg = self.cfg
        scene = self.scene

        # 物理障碍物/碰撞LiDAR: [x, y, 等效半径]（v3 从场景推导）
        physical_obstacles = scene.obstacles_physical

        # UE 客户端（scene_id 必须与场景文件 id 一致，LoadScene 上传用）
        self.client = ProjectAirSimClientWrapper(
            drone_name=cfg['airsim']['vehicle_name'],
            scene_id=scene.id,
            obstacles=physical_obstacles,
            addr=cfg['airsim']['ip'],
            port=cfg['airsim']['port'],
        )

        # 栅格地图：用规划障碍物（膨胀半径）填充
        self.grid_map = GridMap(
            x_min=scene.x_min, x_max=scene.x_max,
            y_min=scene.y_min, y_max=scene.y_max,
            resolution=scene.resolution
        )
        self.grid_map.add_obstacle_list(scene.obstacles_plan)
        self.grid_map.inflate_obstacles(0.5)

        # 传感器
        self.sensor_processor = SensorProcessor(max_range=35.0, num_sectors=16)

        # 全局规划器
        gp_cfg = cfg['global_planner']
        self.global_planner = GlobalPlanner(
            grid_map=self.grid_map,
            lookahead_distance=gp_cfg['lookahead_distance'],
            waypoint_reach_threshold=gp_cfg['waypoint_reach_threshold'],
            max_speed=gp_cfg['max_speed'],
            route_mode=scene.route_mode
        )

        # DRL 局部规划器
        drl_cfg = cfg['drl']
        agent = None
        # v4: 场景可声明 use_drl: false -> 纯 A* 飞行（城市/自定义布局在
        # 未针对性重训前可选用，避免未训练模型扰动航线）
        ckpt = cfg['model'].get('load_checkpoint', '')
        if cfg['model'].get('enable', True) and scene.use_drl and ckpt:
            ckpt_path = os.path.join(cfg['model'].get('save_dir', 'models/drl_agent'), ckpt)
            if os.path.exists(ckpt_path):
                from drl.agent import DRLAgent
                agent = DRLAgent(
                    state_dim=drl_cfg['env']['state_dim'],
                    action_dim=drl_cfg['env']['action_dim'],
                    hidden_layers=drl_cfg['network']['hidden_layers'],
                    action_low=drl_cfg['env']['action_low'],
                    action_high=drl_cfg['env']['action_high'],
                )
                agent.load(ckpt_path)
        self.local_planner = LocalPlanner(
            agent=agent,
            action_dim=drl_cfg['env']['action_dim'],
            action_low=drl_cfg['env']['action_low'],
            action_high=drl_cfg['env']['action_high']
        )

        # 势场/安全监控
        pf_cfg = cfg['potential_field']
        potential_field = PotentialField(
            repulsive_gain=pf_cfg['repulsive_gain'],
            attractive_gain=pf_cfg['attractive_gain'],
            repulsive_range=pf_cfg['repulsive_range']
        )
        self.safety_monitor = SafetyMonitor(
            safety_distance=pf_cfg['safety_distance'],
            potential_field=potential_field
        )

        # 起点/终点/边界（v3 从场景读）
        self.start_pos = np.array(scene.start[:2])
        self.goal_pos = np.array(scene.goal[:2])
        self.y_min = scene.y_min
        self.y_max = scene.y_max
        self.x_min = scene.x_min
        self.x_max = scene.x_max
    def set_goal(self, goal_x: float, goal_y: float) -> None:
        self.goal_pos = np.array([goal_x, goal_y])


    def _clamp_to_corridor(self, action: np.ndarray) -> np.ndarray:
        """限制在 10m 走廊内（含惯性越界后的强回拉）"""
        a = action.copy()
        p = self.client.get_position()
        margin = 1.5
        # y 方向：上墙（y_max=5）
        if p[1] > self.y_max - margin:
            a[1] = min(a[1], 0.0)                 # 不向外推
            if p[1] > self.y_max - 0.4:
                a[1] = min(a[1], -1.5)            # 越界过深，强制拉回
        # y 方向：下墙（y_min=-5）
        if p[1] < self.y_min + margin:
            a[1] = max(a[1], 0.0)
            if p[1] < self.y_min + 0.4:
                a[1] = max(a[1], 1.5)
        # x 方向：终点墙（x_max=100）
        if p[0] > self.x_max - margin:
            a[0] = min(a[0], 0.0)
            if p[0] > self.x_max - 0.4:
                a[0] = min(a[0], -1.5)
        # x 方向：起点墙（x_min=0）
        if p[0] < self.x_min + 0.5 and a[0] < 0:
            a[0] = max(a[0], 0.0)
        return a

    def run(self, max_steps: int = 2000) -> dict:
        # 每次运行前复位到地面层，再走真实起飞流程（保证可重复执行）
        self.client.reset_position(self.start_pos[0], self.start_pos[1], -0.4)
        time.sleep(1.0)
        p0 = self.client.get_position()
        if np.linalg.norm(p0[:2] - self.start_pos) > 1.5:
            self.client.reset_position(self.start_pos[0], self.start_pos[1], -0.4)
            time.sleep(1.0)
            p0 = self.client.get_position()
        if np.linalg.norm(p0[:2] - self.start_pos) > 1.5:
            return {"success": False, "reason": "reset_failed_drone_stuck_restart_ue", "steps": 0, "time": 0.0}
        self.client.takeoff(height=self.cfg['airsim']['takeoff_height'])
        time.sleep(0.5)

        # ??????
        current_pos = self.client.get_position()
        if not self.global_planner.plan_path(current_pos, self.goal_pos):
            return {"success": False, "reason": "??????"}

        self.is_running = True
        self.step_count = 0
        start_time = time.time()
        prev_pos = None

        while self.is_running and self.step_count < max_steps:
            self.step_count += 1

            # ---- 1. ???? ----
            current_pos = self.client.get_position()
            velocity = self.client.get_velocity()

            # v2 anomaly: jump > 4m in one 0.3s step => UE actor snapped back
            if prev_pos is not None:
                jump = np.linalg.norm(current_pos[:2] - prev_pos[:2])
                if jump > 4.0:
                    try:
                        self.client.send_velocity(0, 0)
                    except Exception:
                        pass
                    return {"success": False, "reason": "position_jump_%.1fm_restart_ue" % jump,
                            "steps": self.step_count, "time": time.time() - start_time}
            prev_pos = current_pos.copy()

            lidar_points = self.client.get_lidar_data()
            yaw = self.client.get_yaw()

            # ---- 2. ?????????? ----
            next_waypoint = self.global_planner.get_next_waypoint(current_pos)

            # ????????
            if self.global_planner.is_goal_reached(current_pos, self.goal_pos):
                # v2: ??????????? Land/Disarm/DisableApiControl?
                # ?????? UE actor ???????????????????????
                try:
                    self.client.send_velocity(0, 0)
                    self.client.hover()
                except Exception:
                    pass
                elapsed = time.time() - start_time
                return {
                    "success": True,
                    "steps": self.step_count,
                    "time": elapsed,
                    "path_length": self._compute_path_length()
                }

            # ---- 3. ?????DRL? ----
            if lidar_points.shape[0] > 0:
                sector_distances = self.sensor_processor.lidar_to_polar(lidar_points)
                nearest_dist, nearest_angle =                     self.sensor_processor.find_nearest_obstacle(lidar_points)
            else:
                sector_distances = np.ones(16) * 35.0
                nearest_dist, nearest_angle = 35.0, 0.0

            # DRL state 必须相对真实目标点构造（与训练一致），
            # 不能用 A* 路点（训练时 state 相对 goal 归一化）
            state = self.local_planner.build_state(
                current_pos, self.goal_pos, velocity,
                sector_distances, nearest_dist, nearest_angle
            )
            drl_action = self.local_planner.get_action(state)

            # ---- 4. ???? ----
            obstacle_positions = self.client.get_obstacles()[:, :2]                 if lidar_points.shape[0] > 0 else np.array([]).reshape(0, 2)
            safety_result = self.safety_monitor.check(
                current_pos, velocity, obstacle_positions
            )

            # ---- 5. ?????? ----
            if not safety_result["safe"]:
                final_action = safety_result["action"]
                mode = "SAFETY"
            elif self.local_planner.has_model():
                final_action = drl_action
                mode = "DRL"
            else:
                final_action = self.global_planner.get_velocity_command(
                    current_pos, yaw, next_waypoint
                )
                mode = "GLOBAL"

            # ??????
            final_action = self._clamp_to_corridor(final_action)

            # ---- 6. ???? ----
            self.client.send_velocity(final_action[0], final_action[1],
                                      duration=0.3)

            # ---- 7. ???? ----
            self.flight_log.append({
                "step": self.step_count,
                "x": current_pos[0], "y": current_pos[1], "z": current_pos[2],
                "vx": velocity[0], "vy": velocity[1],
                "mode": mode,
                "nearest_obs": nearest_dist,
                "action_x": float(final_action[0]),
                "action_y": float(final_action[1]),
            })

            time.sleep(0.05)

        # ??????
        try:
            self.client.send_velocity(0, 0)
        except Exception:
            pass
        elapsed = time.time() - start_time
        return {
            "success": False,
            "reason": "?????? %d" % max_steps,
            "steps": self.step_count,
            "time": elapsed
        }

    def stop(self) -> None:
        self.is_running = False
        try:
            self.client.send_velocity(0, 0)
        except Exception:
            pass

    def _compute_path_length(self) -> float:
        if len(self.flight_log) < 2:
            return 0.0
        total = 0.0
        for i in range(1, len(self.flight_log)):
            dx = self.flight_log[i]["x"] - self.flight_log[i - 1]["x"]
            dy = self.flight_log[i]["y"] - self.flight_log[i - 1]["y"]
            total += np.sqrt(dx ** 2 + dy ** 2)
        return total

    def get_log(self) -> list:
        return self.flight_log

    def save_log(self, filepath: str = "logs/flights/flight_log.csv") -> None:
        import csv
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        if not self.flight_log:
            print("[Supervisor] ?????")
            return
        keys = list(self.flight_log[0].keys())
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(self.flight_log)
        print("[Supervisor] ?????: %s" % filepath)
