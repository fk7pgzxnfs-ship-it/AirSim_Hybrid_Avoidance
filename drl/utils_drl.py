"""
DRL 工具函数
噪声生成、状态归一化、奖励统计等
"""

import numpy as np


class OUNoise:
    """
    Ornstein-Uhlenbeck 随机过程噪声
    用于 DDPG 探索，产生时间相关的噪声
    """

    def __init__(self, action_dim: int, mu: float = 0.0,
                 theta: float = 0.15, sigma: float = 0.2):
        """
        Args:
            action_dim: 动作维度
            mu: 均值
            theta: 回归速率
            sigma: 波动率
        """
        self.action_dim = action_dim
        self.mu = mu
        self.theta = theta
        self.sigma = sigma
        self.state = np.ones(action_dim) * mu

    def reset(self):
        """重置噪声状态"""
        self.state = np.ones(self.action_dim) * self.mu

    def sample(self) -> np.ndarray:
        """生成噪声样本"""
        dx = self.theta * (self.mu - self.state) + \
             self.sigma * np.random.randn(self.action_dim)
        self.state += dx
        return self.state


class GaussianNoise:
    """高斯探索噪声"""

    def __init__(self, action_dim: int, std: float = 0.1):
        self.action_dim = action_dim
        self.std = std

    def sample(self) -> np.ndarray:
        """生成噪声样本"""
        return np.random.normal(0, self.std, size=self.action_dim)


class RunningMeanStd:
    """
    在线计算均值和标准差
    用于状态归一化
    """

    def __init__(self, shape):
        self.mean = np.zeros(shape, dtype=np.float32)
        self.var = np.ones(shape, dtype=np.float32)
        self.count = 0

    def update(self, x: np.ndarray):
        """更新统计量"""
        batch_mean = np.mean(x, axis=0)
        batch_var = np.var(x, axis=0)
        batch_count = x.shape[0]

        self._update_from_moments(batch_mean, batch_var, batch_count)

    def _update_from_moments(self, batch_mean, batch_var, batch_count):
        """使用矩估计更新"""
        delta = batch_mean - self.mean
        tot_count = self.count + batch_count

        new_mean = self.mean + delta * batch_count / tot_count
        m_a = self.var * self.count
        m_b = batch_var * batch_count
        m_2 = m_a + m_b + delta ** 2 * self.count * batch_count / tot_count
        new_var = m_2 / tot_count

        self.mean = new_mean
        self.var = new_var
        self.count = tot_count

    def normalize(self, x: np.ndarray) -> np.ndarray:
        """归一化"""
        return (x - self.mean) / (np.sqrt(self.var) + 1e-8)


def compute_success_rate(episode_rewards: list, threshold: float = 0.0) -> float:
    """计算成功率（奖励大于阈值的episode比例）"""
    if len(episode_rewards) == 0:
        return 0.0
    return np.mean([r > threshold for r in episode_rewards])


def smooth_curve(values: list, window: int = 10) -> np.ndarray:
    """平滑曲线（移动平均）"""
    if len(values) < window:
        return np.array(values)
    return np.convolve(values, np.ones(window) / window, mode='valid')


def set_seed(seed: int):
    """设置全局随机种子"""
    import random
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)