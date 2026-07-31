"""
人工势场法
用于安全切换器，当DRL输出可能碰撞时提供备份指令
"""

import numpy as np


class PotentialField:
    """
    人工势场法：目标产生引力，障碍物产生斥力
    输出安全逃逸方向作为备份控制指令
    """

    def __init__(self, repulsive_gain: float = 50.0,
                 attractive_gain: float = 1.0,
                 repulsive_range: float = 3.0):
        """
        Args:
            repulsive_gain: 斥力增益
            attractive_gain: 引力增益
            repulsive_range: 斥力作用范围 (m)
        """
        self.repulsive_gain = repulsive_gain
        self.attractive_gain = attractive_gain
        self.repulsive_range = repulsive_range

    def compute_force(self, current_pos: np.ndarray,
                      goal_pos: np.ndarray,
                      obstacles: np.ndarray) -> np.ndarray:
        """
        计算合力和方向

        Args:
            current_pos: 当前位置 (x, y)
            goal_pos: 目标位置 (x, y)
            obstacles: (N, 2) 障碍物位置数组

        Returns:
            (2,) 合力方向向量 (vx, vy)
        """
        attractive_force = self._attractive_force(current_pos, goal_pos)
        repulsive_force = self._repulsive_force(current_pos, obstacles)

        total_force = attractive_force + repulsive_force
        return total_force

    def compute_escape_direction(self, current_pos: np.ndarray,
                                  obstacles: np.ndarray) -> np.ndarray:
        """
        计算紧急逃逸方向（仅考虑斥力）

        Args:
            current_pos: 当前位置 (x, y)
            obstacles: (N, 2) 障碍物位置数组

        Returns:
            (2,) 逃逸方向单位向量
        """
        repulsive_force = self._repulsive_force(current_pos, obstacles)
        norm = np.linalg.norm(repulsive_force)
        if norm > 0.01:
            return repulsive_force / norm
        return np.array([1.0, 0.0])  # 默认前向

    def _attractive_force(self, current: np.ndarray,
                          goal: np.ndarray) -> np.ndarray:
        """计算引力"""
        direction = goal - current
        dist = np.linalg.norm(direction)
        if dist < 0.01:
            return np.zeros(2)
        return self.attractive_gain * direction / dist

    def _repulsive_force(self, current: np.ndarray,
                         obstacles: np.ndarray) -> np.ndarray:
        """计算所有障碍物的总斥力"""
        total_repulsive = np.zeros(2)

        if obstacles.shape[0] == 0:
            return total_repulsive

        for obs in obstacles:
            diff = current[:2] - obs[:2]
            dist = np.linalg.norm(diff)
            if dist > self.repulsive_range or dist < 0.01:
                continue

            # 斥力大小与距离成反比
            magnitude = self.repulsive_gain * \
                (1.0 / dist - 1.0 / self.repulsive_range) / (dist ** 2)
            total_repulsive += magnitude * diff / dist

        return total_repulsive

    def is_danger(self, current_pos: np.ndarray,
                  obstacles: np.ndarray,
                  safety_distance: float = 1.5) -> bool:
        """
        判断当前是否处于危险状态（需要安全切换）

        Args:
            current_pos: 当前位置 (x, y)
            obstacles: (N, 2) 障碍物位置
            safety_distance: 安全距离阈值 (m)

        Returns:
            True 表示需要安全介入
        """
        if obstacles.shape[0] == 0:
            return False

        for obs in obstacles:
            dist = np.linalg.norm(current_pos[:2] - obs[:2])
            if dist < safety_distance:
                return True
        return False