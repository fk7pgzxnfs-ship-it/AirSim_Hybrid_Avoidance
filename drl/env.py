# -*- coding: utf-8 -*-
"""
自定义 Gym 环境
封装 AirSim 无人机避障任务的强化学习环境
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import time


class DroneEnv(gym.Env):
    """
    无人机避障 Gym 环境

    状态空间 (8维): [dx, dy, vx, vy, obs_min_dist, obs_min_angle, goal_dist, goal_angle]
    动作空间 (2维): [vx, vy] 连续速度指令
    奖励: 到达终点+100, 碰撞-50, 每步惩罚-0.1, 靠近目标奖励
    """

    def __init__(self, supervisor, config: dict, scene=None):
        """
        Args:
            supervisor: Supervisor 实例（提供 client 接口）
            config: DRL 环境配置字典
        """
        super().__init__()
        self.supervisor = supervisor
        self.client = supervisor.client
        self.cfg = config
        self.max_steps = config['max_steps']

        # 状态和动作空间
        self.state_dim = config['state_dim']
        self.action_dim = config['action_dim']
        self.action_low = np.array(config['action_low'])
        self.action_high = np.array(config['action_high'])

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(self.state_dim,), dtype=np.float32
        )
        self.action_space = spaces.Box(
            low=self.action_low, high=self.action_high, dtype=np.float32
        )

        # 奖励系数
        self.reward_cfg = config.get('reward', {})
        self.step_count = 0
        self._prev_action = None
        # v3: 场景配置（可选），用于走廊/边界惩罚与横向偏差计算
        self.scene = scene

    def reset(self, seed=None, options=None):
        """重置环境"""
        super().reset(seed=seed)

        # 重置无人机到起点
        start = self.supervisor.start_pos
        self.client.reset_position(start[0], start[1],
                                   self.supervisor.cfg['airsim']['takeoff_height'])

        self.step_count = 0
        self._prev_goal_dist = None
        self._prev_action = None
        info = {}

        # 获取初始状态
        state = self._get_state()
        return state, info

    def step(self, action: np.ndarray):
        """
        执行动作

        Args:
            action: (2,) 速度指令 [vx, vy]

        Returns:
            (state, reward, terminated, truncated, info)
        """
        self.step_count += 1

        # 裁剪动作
        action = np.clip(action, self.action_low, self.action_high)

        # 动作变化量（用于平滑惩罚，v2.1）
        if self._prev_action is not None:
            action_change = float(np.linalg.norm(action - self._prev_action))
        else:
            action_change = 0.0
        self._prev_action = action.copy()

        # 发送速度指令
        self.client.send_velocity(action[0], action[1], duration=0.3)
        sleep_step = self.cfg.get('sleep_step', 0.1)
        if sleep_step:
            time.sleep(sleep_step)

        # 获取新状态
        next_state = self._get_state()

        # 检查碰撞
        collided = self.client.get_collision_info()

        # 检查是否到达终点
        current_pos = self.client.get_position()
        goal_pos = self.supervisor.goal_pos
        goal_reached = np.linalg.norm(current_pos[:2] - goal_pos) < 1.0

        # 计算奖励
        reward = self._compute_reward(
            next_state, collided, goal_reached, action_change
        )

        # 判断终止
        terminated = collided or goal_reached
        truncated = self.step_count >= self.max_steps

        info = {
            "collided": collided,
            "goal_reached": goal_reached,
            "step": self.step_count
        }

        return next_state, reward, terminated, truncated, info

    def _get_state(self) -> np.ndarray:
        """获取当前状态向量"""
        current_pos = self.client.get_position()
        velocity = self.client.get_velocity()
        lidar = self.client.get_lidar_data()

        # 障碍物处理
        if lidar.shape[0] > 0:
            angles = np.arctan2(lidar[:, 1], lidar[:, 0])
            dists = np.linalg.norm(lidar[:, :2], axis=1)
            nearest_idx = np.argmin(dists)
            nearest_dist = dists[nearest_idx]
            nearest_angle = angles[nearest_idx]
        else:
            nearest_dist, nearest_angle = 30.0, 0.0

        # 目标偏移
        dx = self.supervisor.goal_pos[0] - current_pos[0]
        dy = self.supervisor.goal_pos[1] - current_pos[1]
        goal_dist = np.sqrt(dx ** 2 + dy ** 2)
        goal_angle = np.arctan2(dy, dx)

        state = np.array([
            dx, dy,
            velocity[0], velocity[1],
            nearest_dist, nearest_angle,
            goal_dist, goal_angle
        ], dtype=np.float32)

        return state

    def _compute_reward(self, state: np.ndarray,
                        collided: bool, goal_reached: bool,
                        action_change: float = 0.0) -> float:
        """计算奖励"""
        if collided:
            return self.reward_cfg.get('collision_penalty', -50.0)

        if goal_reached:
            return self.reward_cfg.get('goal_reward', 100.0)

        dx, dy = state[0], state[1]
        prev_dist = getattr(self, '_prev_goal_dist', None)
        current_dist = np.sqrt(dx ** 2 + dy ** 2)

        reward = 0.0

        # 距离变化奖励
        if prev_dist is not None:
            dist_change = prev_dist - current_dist
            reward += self.reward_cfg.get('distance_gain', 1.0) * dist_change

        # 步数惩罚
        reward += self.reward_cfg.get('step_penalty', -0.1)

        # 靠近障碍物惩罚
        nearest_dist = state[4]
        if nearest_dist < 3.0:
            reward += self.reward_cfg.get('obstacle_penalty', -5.0) * \
                      (1.0 - nearest_dist / 3.0)

        # 走廊边界惩罚 + 横向偏移惩罚
        corr_limit = self.reward_cfg.get('corridor_limit', 4.5)
        corr_pen = self.reward_cfg.get('corridor_penalty', 3.0)
        lateral_pen = self.reward_cfg.get('lateral_penalty', 0.0)
        if self.scene is not None:
            # v3: 横向偏差 = 到起点-终点直线的距离（自定义起点终点时仍有效）
            pos = self.client.get_position()
            lat = self.scene.lateral_distance(pos)
            if lat > corr_limit:
                reward += -corr_pen * (lat - corr_limit)
            if lateral_pen > 0.0:
                reward += -lateral_pen * lat
            # v3: 地图矩形边界惩罚（飞出边界额外惩罚）
            if not self.scene.in_bounds(pos[0], pos[1]):
                over = max(self.scene.x_min - pos[0], pos[0] - self.scene.x_max,
                           self.scene.y_min - pos[1], pos[1] - self.scene.y_max, 0.0)
                reward += -self.reward_cfg.get('boundary_penalty', 5.0) * (1.0 + over)
        else:
            # 旧行为（无场景配置时兼容 v2：|y| = |state[1]|，goal_y=0）
            if abs(state[1]) > corr_limit:
                reward += -corr_pen * (abs(state[1]) - corr_limit)
            if lateral_pen > 0.0:
                reward += -lateral_pen * abs(state[1])

        # v2.1: 动作平滑惩罚（惩罚相邻动作突变，迫使策略输出平滑指令）
        smooth_pen = self.reward_cfg.get('action_smooth_penalty', 0.0)
        if smooth_pen > 0.0:
            reward += -smooth_pen * action_change

        self._prev_goal_dist = current_dist
        return reward

    def render(self, mode='human'):
        pass

    def close(self):
        pass
