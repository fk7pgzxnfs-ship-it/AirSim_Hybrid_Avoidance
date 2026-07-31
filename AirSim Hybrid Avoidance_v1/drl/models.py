"""
神经网络模型定义
Actor 和 Critic 网络（用于 DDPG / SAC）
"""

import torch
import torch.nn as nn
import numpy as np


def init_weights(m):
    """权重初始化"""
    if isinstance(m, nn.Linear):
        nn.init.xavier_uniform_(m.weight)
        nn.init.constant_(m.bias, 0.0)


class Actor(nn.Module):
    """
    Actor 网络：状态 → 动作
    输出连续速度指令 [vx, vy]
    """

    def __init__(self, state_dim: int, action_dim: int,
                 hidden_layers: list = None, action_low: list = None,
                 action_high: list = None):
        """
        Args:
            state_dim: 状态维度
            action_dim: 动作维度
            hidden_layers: 隐藏层神经元数
            action_low: 动作下界
            action_high: 动作上界
        """
        super().__init__()
        hidden_layers = hidden_layers or [256, 256]

        layers = []
        prev_dim = state_dim
        for h in hidden_layers:
            layers.extend([
                nn.Linear(prev_dim, h),
                nn.ReLU(),
                nn.LayerNorm(h)
            ])
            prev_dim = h

        layers.append(nn.Linear(prev_dim, action_dim))
        self.net = nn.Sequential(*layers)
        self.net.apply(init_weights)

        # 动作范围
        self.register_buffer('action_low',
                             torch.tensor(action_low or [-2.0, -2.0]))
        self.register_buffer('action_high',
                             torch.tensor(action_high or [2.0, 2.0]))

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """前向传播，输出 (-1, 1) 范围的动作"""
        x = self.net(state)
        return torch.tanh(x)

    def get_action(self, state: torch.Tensor) -> torch.Tensor:
        """
        获取实际尺度动作

        Args:
            state: (batch, state_dim)

        Returns:
            (batch, action_dim) 缩放到 action_low ~ action_high
        """
        raw_action = self.forward(state)
        # 缩放到实际动作范围
        action = self.action_low + (raw_action + 1.0) * 0.5 * \
                (self.action_high - self.action_low)
        return action


class Critic(nn.Module):
    """
    Critic 网络：(状态, 动作) → Q值
    用于评估动作价值
    """

    def __init__(self, state_dim: int, action_dim: int,
                 hidden_layers: list = None):
        """
        Args:
            state_dim: 状态维度
            action_dim: 动作维度
            hidden_layers: 隐藏层神经元数
        """
        super().__init__()
        hidden_layers = hidden_layers or [256, 256]

        layers = []
        prev_dim = state_dim + action_dim
        for h in hidden_layers:
            layers.extend([
                nn.Linear(prev_dim, h),
                nn.ReLU(),
                nn.LayerNorm(h)
            ])
            prev_dim = h

        layers.append(nn.Linear(prev_dim, 1))
        self.net = nn.Sequential(*layers)
        self.net.apply(init_weights)

    def forward(self, state: torch.Tensor,
                action: torch.Tensor) -> torch.Tensor:
        """前向传播，输出 Q 值"""
        x = torch.cat([state, action], dim=-1)
        return self.net(x)


class CriticTwin(nn.Module):
    """
    双 Critic 网络（用于减少 Q 值过估计）
    包含两个独立的 Critic
    """

    def __init__(self, state_dim: int, action_dim: int,
                 hidden_layers: list = None):
        super().__init__()
        self.q1 = Critic(state_dim, action_dim, hidden_layers)
        self.q2 = Critic(state_dim, action_dim, hidden_layers)

    def forward(self, state: torch.Tensor,
                action: torch.Tensor) -> tuple:
        """
        Returns:
            (q1, q2) 两个 Q 值
        """
        return self.q1(state, action), self.q2(state, action)