"""
经验回放缓冲区
支持优先经验回放（可选）
"""

import numpy as np
from collections import deque
import random


class ReplayBuffer:
    """标准经验回放缓冲区"""

    def __init__(self, capacity: int = 100000):
        """
        Args:
            capacity: 缓冲区最大容量
        """
        self.buffer = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        """存储一条经验"""
        self.buffer.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int) -> tuple:
        """随机采样一个批次"""
        batch = random.sample(self.buffer, min(batch_size, len(self.buffer)))
        states, actions, rewards, next_states, dones = zip(*batch)
        return (np.array(states), np.array(actions), np.array(rewards),
                np.array(next_states), np.array(dones))

    def __len__(self) -> int:
        return len(self.buffer)

    def clear(self):
        """清空缓冲区"""
        self.buffer.clear()


class PrioritizedReplayBuffer:
    """优先经验回放缓冲区（可选）"""

    def __init__(self, capacity: int = 100000, alpha: float = 0.6,
                 beta: float = 0.4, beta_increment: float = 0.001):
        """
        Args:
            capacity: 最大容量
            alpha: 优先级指数（0=均匀采样，1=完全按优先级）
            beta: 重要性采样权重
            beta_increment: beta 每步增量
        """
        self.capacity = capacity
        self.alpha = alpha
        self.beta = beta
        self.beta_increment = beta_increment
        self.buffer = []
        self.priorities = np.zeros(capacity, dtype=np.float32)
        self.position = 0
        self.size = 0

    def push(self, state, action, reward, next_state, done,
             td_error: float = 1.0):
        """存储经验，td_error 用于计算优先级"""
        priority = (abs(td_error) + 1e-6) ** self.alpha

        if len(self.buffer) < self.capacity:
            self.buffer.append((state, action, reward, next_state, done))
        else:
            self.buffer[self.position] = (state, action, reward,
                                          next_state, done)

        self.priorities[self.position] = priority
        self.position = (self.position + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch_size: int) -> tuple:
        """按优先级采样"""
        if self.size < batch_size:
            batch_size = self.size

        # 计算采样概率
        priorities = self.priorities[:self.size]
        probs = priorities / priorities.sum()

        # 采样索引
        indices = np.random.choice(self.size, batch_size, p=probs)

        # 计算重要性采样权重
        total = self.size
        weights = (total * probs[indices]) ** (-self.beta)
        weights /= weights.max()

        self.beta = min(1.0, self.beta + self.beta_increment)

        batch = [self.buffer[i] for i in indices]
        states, actions, rewards, next_states, dones = zip(*batch)

        return (np.array(states), np.array(actions), np.array(rewards),
                np.array(next_states), np.array(dones), indices, weights)

    def update_priorities(self, indices: np.ndarray, td_errors: np.ndarray):
        """更新优先级"""
        for idx, error in zip(indices, td_errors):
            self.priorities[idx] = (abs(error) + 1e-6) ** self.alpha

    def __len__(self) -> int:
        return self.size