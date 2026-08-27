"""
全局路径规划器
调用 A* 算法生成全局路径，并管理路径点跟踪
"""

import numpy as np
from planning.grid_map import GridMap
from planning.a_star import AStar


class GlobalPlanner:
    """全局路径规划器"""

    def __init__(self, grid_map: GridMap, lookahead_distance: float = 2.0,
                 waypoint_reach_threshold: float = 1.0, max_speed: float = 3.0,
                 route_mode: str = "line"):
        """
        Args:
            grid_map: 栅格地图
            lookahead_distance: 前视距离 (m)
            waypoint_reach_threshold: 到达路点阈值 (m)
            max_speed: 最大速度 (m/s)
        """
        self.grid_map = grid_map
        self.lookahead_distance = lookahead_distance
        self.waypoint_reach_threshold = waypoint_reach_threshold
        self.max_speed = max_speed
        # v3: line = 起点终点直线（默认）；astar = 传统 A* 路径
        self.route_mode = route_mode if route_mode in ("line", "astar") else "line"

        self.a_star = AStar(grid_map)
        self.path = np.array([])
        self.current_index = 0

    def plan_path(self, start_pos: np.ndarray, goal_pos: np.ndarray) -> bool:
        """
        规划全局路径

        Args:
            start_pos: 起点 (x, y)
            goal_pos: 终点 (x, y)

        Returns:
            是否成功找到路径
        """
        if self.route_mode == "line":
            # v3 直线路线：起点到终点的直线离散点
            start = np.array(start_pos[:2], dtype=float)
            goal = np.array(goal_pos[:2], dtype=float)
            dist = float(np.linalg.norm(goal - start))
            # 直线路线下仍用 A* 做可达性检查（障碍围死终点时提前报错）
            if len(self.a_star.plan((start[0], start[1]), (goal[0], goal[1]))) == 0:
                print("[GlobalPlanner] 未找到可达路径（直线路线被障碍物围死）！")
                self.path = np.array([])
                self.current_index = 0
                return False
            n = max(int(dist / 0.5), 1)
            ts = np.linspace(0.0, 1.0, n + 1)
            self.path = start[None, :] + ts[:, None] * (goal - start)[None, :]
            self.current_index = 0
            print(f"[GlobalPlanner] 直线路线规划成功，共 {len(self.path)} 个点")
            return True

        self.path = self.a_star.plan(
            (start_pos[0], start_pos[1]),
            (goal_pos[0], goal_pos[1])
        )
        self.current_index = 0

        if len(self.path) == 0:
            print("[GlobalPlanner] 未找到路径！")
            return False

        print(f"[GlobalPlanner] 路径规划成功，共 {len(self.path)} 个路点")
        return True

    def get_next_waypoint(self, current_pos: np.ndarray) -> np.ndarray:
        """
        获取当前应跟踪的下一个目标点（带前视）

        Args:
            current_pos: 当前位置 (x, y)

        Returns:
            (2,) 目标点坐标
        """
        if len(self.path) == 0:
            return np.array([0.0, 0.0])

        # 找到路径上距离当前位置最近的点
        min_dist = float('inf')
        nearest_idx = self.current_index
        for i in range(self.current_index, len(self.path)):
            dist = np.linalg.norm(current_pos[:2] - self.path[i])
            if dist < min_dist:
                min_dist = dist
                nearest_idx = i

        # 从前视距离选择目标点
        accumulated = 0.0
        target_idx = nearest_idx
        for i in range(nearest_idx, len(self.path) - 1):
            segment_dist = np.linalg.norm(self.path[i + 1] - self.path[i])
            accumulated += segment_dist
            if accumulated >= self.lookahead_distance:
                target_idx = i + 1
                break
            target_idx = i + 1

        self.current_index = nearest_idx
        return self.path[target_idx]

    def is_goal_reached(self, current_pos: np.ndarray,
                        goal_pos: np.ndarray) -> bool:
        """检查是否到达终点"""
        return np.linalg.norm(current_pos[:2] - goal_pos[:2]) < \
               self.waypoint_reach_threshold

    def get_velocity_command(self, current_pos: np.ndarray,
                              current_yaw: float,
                              target_pos: np.ndarray) -> np.ndarray:
        """
        生成跟踪目标点的速度指令

        Args:
            current_pos: 当前位置 (x, y)
            current_yaw: 当前偏航角 (弧度)
            target_pos: 目标位置 (x, y)

        Returns:
            (2,) 速度指令 (vx, vy) 世界坐标系
        """
        direction = target_pos - current_pos[:2]
        dist = np.linalg.norm(direction)

        if dist < 0.1:
            return np.zeros(2)

        # 距离越近速度越小，实现平滑减速
        speed = min(self.max_speed, dist * 1.5)
        velocity = direction / dist * speed
        return velocity

    def get_path(self) -> np.ndarray:
        """获取完整路径"""
        return self.path.copy()