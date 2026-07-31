"""
混合控制器总控
整合全局规划 + 局部避障 + 安全切换的三层决策循环
"""

import sys
import os

# 自动将项目根目录加入 sys.path，支持直接运行此文件
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import time
import numpy as np
import yaml

from airsim_interface.client import AirSimClientWrapper
from airsim_interface.sensor_processor import SensorProcessor
from airsim_interface.utils import get_yaw_from_quaternion
from hybrid_controller.global_planner import GlobalPlanner
from hybrid_controller.local_planner import LocalPlanner
from hybrid_controller.safety_monitor import SafetyMonitor
from planning.grid_map import GridMap
from planning.potential_field import PotentialField


class Supervisor:
    """
    总控器：三层混合架构主循环

    每帧决策流程：
    1. 全局规划器 → 获取当前目标点
    2. 局部规划器（DRL）→ 输出避障动作
    3. 安全监视器 → 校验/修正动作
    4. 发送最终指令
    """

    def __init__(self, config_path: str = "config/default.yaml"):
        """
        Args:
            config_path: 配置文件路径
        """
        # 加载配置
        with open(config_path, 'r', encoding='utf-8') as f:
            self.cfg = yaml.safe_load(f)

        # 初始化各模块
        self._init_modules()

        # 状态跟踪
        self.flight_log = []
        self.step_count = 0
        self.is_running = False

    def _init_modules(self) -> None:
        """初始化所有子模块"""
        cfg = self.cfg

        # AirSim 客户端
        self.client = AirSimClientWrapper(
            ip=cfg['airsim']['ip'],
            port=cfg['airsim']['port'],
            vehicle_name=cfg['airsim']['vehicle_name']
        )

        # 栅格地图
        self.grid_map = GridMap(
            x_min=cfg['map']['x_min'],
            x_max=cfg['map']['x_max'],
            y_min=cfg['map']['y_min'],
            y_max=cfg['map']['y_max'],
            resolution=cfg['map']['resolution']
        )
        self.grid_map.add_obstacle_list(cfg['map']['obstacles'])

        # 传感器处理
        self.sensor_processor = SensorProcessor(
            max_range=30.0, num_sectors=16
        )

        # 全局规划器
        gp_cfg = cfg['global_planner']
        self.global_planner = GlobalPlanner(
            grid_map=self.grid_map,
            lookahead_distance=gp_cfg['lookahead_distance'],
            waypoint_reach_threshold=gp_cfg['waypoint_reach_threshold'],
            max_speed=gp_cfg['max_speed']
        )

        # 局部规划器（无DRL模型时为占位）
        drl_cfg = cfg['drl']
        self.local_planner = LocalPlanner(
            agent=None,
            action_dim=drl_cfg['env']['action_dim'],
            action_low=drl_cfg['env']['action_low'],
            action_high=drl_cfg['env']['action_high']
        )

        # 安全监视器
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

        # 目标位置
        self.start_pos = np.array(cfg['map']['origin'][:2])
        self.goal_pos = np.array([10.0, 10.0])  # 默认终点

    def set_goal(self, goal_x: float, goal_y: float) -> None:
        """设置目标位置"""
        self.goal_pos = np.array([goal_x, goal_y])

    def run(self, max_steps: int = 1000) -> dict:
        """
        执行主控制循环

        Args:
            max_steps: 最大步数

        Returns:
            飞行结果统计
        """
        # 起飞
        self.client.takeoff(height=self.cfg['airsim']['takeoff_height'])
        time.sleep(0.5)

        # 规划全局路径
        current_pos = self.client.get_position()
        if not self.global_planner.plan_path(current_pos, self.goal_pos):
            return {"success": False, "reason": "路径规划失败"}

        self.is_running = True
        self.step_count = 0
        start_time = time.time()

        while self.is_running and self.step_count < max_steps:
            self.step_count += 1

            # ---- 1. 获取状态 ----
            current_pos = self.client.get_position()
            velocity = self.client.get_velocity()
            lidar_points = self.client.get_lidar_data()

            # 获取四元数并提取偏航角
            state = self.client.client.getMultirotorState(
                vehicle_name=self.client.vehicle_name
            )
            yaw = get_yaw_from_quaternion(
                state.kinematics_estimated.orientation
            )

            # ---- 2. 全局规划：获取目标点 ----
            next_waypoint = self.global_planner.get_next_waypoint(current_pos)

            # 检查是否到达终点
            if self.global_planner.is_goal_reached(current_pos, self.goal_pos):
                self.client.send_velocity(0, 0)
                elapsed = time.time() - start_time
                self.client.land()
                return {
                    "success": True,
                    "steps": self.step_count,
                    "time": elapsed,
                    "path_length": self._compute_path_length()
                }

            # ---- 3. 局部规划（DRL） ----
            if lidar_points.shape[0] > 0:
                sector_distances = self.sensor_processor.lidar_to_polar(
                    lidar_points
                )
                nearest_dist, nearest_angle = \
                    self.sensor_processor.find_nearest_obstacle(lidar_points)
            else:
                sector_distances = np.ones(16) * 30.0
                nearest_dist, nearest_angle = 30.0, 0.0

            # 构建DRL状态
            state = self.local_planner.build_state(
                current_pos, next_waypoint, velocity,
                sector_distances, nearest_dist, nearest_angle
            )

            # DRL输出动作
            drl_action = self.local_planner.get_action(state)

            # ---- 4. 安全检测 ----
            obstacle_positions = lidar_points[:, :2] if lidar_points.shape[0] > 0 \
                else np.array([]).reshape(0, 2)

            safety_result = self.safety_monitor.check(
                current_pos, velocity, obstacle_positions
            )

            # ---- 5. 最终指令选择 ----
            if not safety_result["safe"]:
                # 安全切换器接管
                final_action = safety_result["action"]
                mode = "SAFETY"
            elif self.local_planner.has_model():
                # DRL 控制
                final_action = drl_action
                mode = "DRL"
            else:
                # 纯全局路径跟踪
                final_action = self.global_planner.get_velocity_command(
                    current_pos, yaw, next_waypoint
                )
                mode = "GLOBAL"

            # ---- 6. 发送指令 ----
            self.client.send_velocity(
                final_action[0], final_action[1], duration=0.3
            )

            # ---- 7. 记录日志 ----
            self.flight_log.append({
                "step": self.step_count,
                "x": current_pos[0],
                "y": current_pos[1],
                "z": current_pos[2],
                "vx": velocity[0],
                "vy": velocity[1],
                "mode": mode,
                "nearest_obs": nearest_dist
            })

            time.sleep(0.05)

        # 到达最大步数
        self.client.send_velocity(0, 0)
        elapsed = time.time() - start_time
        return {
            "success": False,
            "reason": f"达到最大步数 {max_steps}",
            "steps": self.step_count,
            "time": elapsed
        }

    def stop(self) -> None:
        """停止飞行"""
        self.is_running = False
        self.client.send_velocity(0, 0)

    def _compute_path_length(self) -> float:
        """计算飞行路径总长度"""
        if len(self.flight_log) < 2:
            return 0.0
        total = 0.0
        for i in range(1, len(self.flight_log)):
            dx = self.flight_log[i]["x"] - self.flight_log[i - 1]["x"]
            dy = self.flight_log[i]["y"] - self.flight_log[i - 1]["y"]
            total += np.sqrt(dx ** 2 + dy ** 2)
        return total

    def get_log(self) -> list:
        """获取飞行日志"""
        return self.flight_log

    def save_log(self, filepath: str = "logs/flights/flight_log.csv") -> None:
        """保存飞行日志到CSV"""
        import pandas as pd
        df = pd.DataFrame(self.flight_log)
        df.to_csv(filepath, index=False)
        print(f"[Supervisor] 日志保存至: {filepath}")