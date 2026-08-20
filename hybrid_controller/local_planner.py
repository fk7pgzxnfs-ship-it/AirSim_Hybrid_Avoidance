"""
局部规划器（DRL 推理）
加载训练好的模型，根据实时状态输出避障指令
"""

import numpy as np


class LocalPlanner:
    """
    局部规划器：加载 DRL Agent 模型，
    根据当前状态输出速度指令
    """

    def __init__(self, agent=None, action_dim: int = 2,
                 action_low: list = None, action_high: list = None):
        """
        Args:
            agent: DRL Agent 实例（推理模式）
            action_dim: 动作维度
            action_low: 动作下界
            action_high: 动作上界
        """
        self.agent = agent
        self.action_dim = action_dim
        self.action_low = np.array(action_low or [-2.0, -2.0])
        self.action_high = np.array(action_high or [2.0, 2.0])

    def get_action(self, state: np.ndarray) -> np.ndarray:
        """
        根据状态输出动作

        Args:
            state: (state_dim,) 状态向量

        Returns:
            (2,) 速度指令 (vx, vy)
        """
        if self.agent is not None:
            action = self.agent.predict(state)
        else:
            # 无模型时默认输出零速度
            action = np.zeros(self.action_dim)

        # 裁剪到合法范围
        action = np.clip(action, self.action_low, self.action_high)
        return action

    def build_state(self, current_pos: np.ndarray, goal_pos: np.ndarray,
                    velocity: np.ndarray, obstacle_distances: np.ndarray,
                    nearest_obstacle_dist: float,
                    nearest_obstacle_angle: float) -> np.ndarray:
        """
        构建 DRL 状态向量

        状态设计（8维）：
        [dx, dy, vx, vy, obs_min_dist, obs_min_angle, goal_dist, goal_angle]

        Args:
            current_pos: 当前位置 (x, y)
            goal_pos: 目标位置 (x, y)
            velocity: 当前速度 (vx, vy)
            obstacle_distances: (N,) 各方向障碍物距离
            nearest_obstacle_dist: 最近障碍物距离
            nearest_obstacle_angle: 最近障碍物方向角

        Returns:
            (8,) 状态向量
        """
        dx = goal_pos[0] - current_pos[0]
        dy = goal_pos[1] - current_pos[1]
        goal_dist = np.sqrt(dx ** 2 + dy ** 2)
        goal_angle = np.arctan2(dy, dx)

        state = np.array([
            dx, dy,
            velocity[0], velocity[1],
            nearest_obstacle_dist,
            nearest_obstacle_angle,
            goal_dist,
            goal_angle
        ], dtype=np.float32)

        return state

    def has_model(self) -> bool:
        """检查是否已加载模型"""
        return self.agent is not None

    def set_agent(self, agent) -> None:
        """设置/更新 DRL Agent"""
        self.agent = agent