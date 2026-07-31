"""
安全监视器（安全切换器）
实时监测障碍物距离，决定是否接管控制权
"""

import numpy as np
from planning.potential_field import PotentialField


class SafetyMonitor:
    """
    安全切换器：三层安全逻辑
    1. 距离检测：最近障碍物距离 < 阈值
    2. 趋势检测：朝着障碍物运动
    3. 势场逃逸：生成替代指令
    """

    def __init__(self, safety_distance: float = 1.5,
                 warning_distance: float = 3.0,
                 potential_field: PotentialField = None):
        """
        Args:
            safety_distance: 安全距离阈值 (m)，小于此值触发切换
            warning_distance: 预警距离 (m)，开始关注
            potential_field: 人工势场法实例
        """
        self.safety_distance = safety_distance
        self.warning_distance = warning_distance
        self.potential_field = potential_field or PotentialField()

        # 状态追踪
        self.is_switched = False
        self.switch_counter = 0
        self.last_obstacle_distance = float('inf')

    def check(self, current_pos: np.ndarray,
              velocity: np.ndarray,
              obstacle_positions: np.ndarray) -> dict:
        """
        安全检测主函数

        Args:
            current_pos: 当前位置 (x, y)
            velocity: 当前速度 (vx, vy)
            obstacle_positions: (N, 2) 障碍物位置

        Returns:
            {
                "safe": bool,          # 是否安全
                "action": ndarray,     # 建议控制指令
                "reason": str,         # 切换原因
                "severity": str        # 严重程度: "normal" / "warning" / "critical"
            }
        """
        result = {
            "safe": True,
            "action": np.zeros(2),
            "reason": "",
            "severity": "normal"
        }

        if obstacle_positions.shape[0] == 0:
            self.is_switched = False
            return result

        # 计算最近障碍物
        nearest_dist, nearest_angle = self._get_nearest_obstacle(
            current_pos, obstacle_positions
        )

        # 趋势检测：是否朝障碍物运动
        approaching = self._is_approaching_obstacle(
            current_pos, velocity, obstacle_positions
        )

        # ---- 三级安全逻辑 ----
        if nearest_dist < self.safety_distance:
            # 1级：临界危险，立即切换
            escape_dir = self.potential_field.compute_escape_direction(
                current_pos, obstacle_positions
            )
            result["safe"] = False
            result["action"] = escape_dir * 2.0  # 紧急速度
            result["reason"] = f"碰撞危险！最近障碍物: {nearest_dist:.2f}m"
            result["severity"] = "critical"
            self.is_switched = True
            self.switch_counter += 1

        elif nearest_dist < self.warning_distance and approaching:
            # 2级：预警+朝障碍物运动，触发预防性切换
            escape_dir = self.potential_field.compute_escape_direction(
                current_pos, obstacle_positions
            )
            result["safe"] = False
            result["action"] = escape_dir * 1.5
            result["reason"] = f"正在靠近障碍物，距离: {nearest_dist:.2f}m"
            result["severity"] = "warning"
            self.is_switched = True
            self.switch_counter += 1

        else:
            # 3级：安全状态
            self.is_switched = False

        self.last_obstacle_distance = nearest_dist
        return result

    def _get_nearest_obstacle(self, pos: np.ndarray,
                               obstacles: np.ndarray) -> tuple:
        """获取最近障碍物的距离和角度"""
        diffs = obstacles - pos[:2]
        dists = np.linalg.norm(diffs, axis=1)
        min_idx = np.argmin(dists)
        min_dist = dists[min_idx]
        min_angle = np.arctan2(diffs[min_idx, 1], diffs[min_idx, 0])
        return min_dist, min_angle

    def _is_approaching_obstacle(self, pos: np.ndarray,
                                  vel: np.ndarray,
                                  obstacles: np.ndarray) -> bool:
        """检测是否正在靠近障碍物"""
        if np.linalg.norm(vel) < 0.1:
            return False

        for obs in obstacles:
            to_obs = obs - pos[:2]
            to_obs_dist = np.linalg.norm(to_obs)
            if to_obs_dist > self.warning_distance * 1.5:
                continue

            # 速度方向指向障碍物？
            vel_dir = vel[:2] / (np.linalg.norm(vel[:2]) + 1e-6)
            obs_dir = to_obs / (to_obs_dist + 1e-6)
            dot = np.dot(vel_dir, obs_dir)

            if dot > 0.5:  # 夹角小于60度
                return True

        return False

    def reset(self) -> None:
        """重置安全监视器状态"""
        self.is_switched = False
        self.switch_counter = 0
        self.last_obstacle_distance = float('inf')