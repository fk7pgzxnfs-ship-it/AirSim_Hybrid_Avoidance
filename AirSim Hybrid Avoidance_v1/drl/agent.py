"""
DRL Agent 推理类
加载训练好的模型，在部署时输出动作
"""

import torch
import numpy as np
from drl.models import Actor


class DRLAgent:
    """
    DRL 推理 Agent
    加载训练好的 Actor 网络，输出速度指令
    """

    def __init__(self, state_dim: int, action_dim: int,
                 hidden_layers: list = None,
                 action_low: list = None, action_high: list = None,
                 device: str = None):
        """
        Args:
            state_dim: 状态维度
            action_dim: 动作维度
            hidden_layers: 隐藏层结构
            action_low: 动作下界
            action_high: 动作上界
            device: 运行设备
        """
        self.device = device or (
            "cuda" if torch.cuda.is_available() else "cpu"
        )

        self.actor = Actor(
            state_dim, action_dim,
            hidden_layers or [256, 256],
            action_low or [-2.0, -2.0],
            action_high or [2.0, 2.0]
        ).to(self.device)
        self.actor.eval()

        self.model_loaded = False

    def load(self, path: str) -> bool:
        """
        加载训练好的模型权重

        Args:
            path: 模型文件路径

        Returns:
            是否加载成功
        """
        try:
            checkpoint = torch.load(path, map_location=self.device)
            if 'actor_state_dict' in checkpoint:
                self.actor.load_state_dict(checkpoint['actor_state_dict'])
            else:
                self.actor.load_state_dict(checkpoint)
            self.model_loaded = True
            print(f"[Agent] 模型加载成功: {path}")
            return True
        except Exception as e:
            print(f"[Agent] 模型加载失败: {e}")
            return False

    def predict(self, state: np.ndarray) -> np.ndarray:
        """
        根据状态预测动作

        Args:
            state: (state_dim,) 状态向量

        Returns:
            (action_dim,) 动作向量
        """
        if not self.model_loaded:
            return np.zeros(2)

        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)

        with torch.no_grad():
            action = self.actor.get_action(state_tensor)

        return action.cpu().numpy()[0]

    def predict_batch(self, states: np.ndarray) -> np.ndarray:
        """批量预测"""
        if not self.model_loaded:
            return np.zeros((states.shape[0], 2))

        states_tensor = torch.FloatTensor(states).to(self.device)

        with torch.no_grad():
            actions = self.actor.get_action(states_tensor)

        return actions.cpu().numpy()

    def is_ready(self) -> bool:
        """检查是否已加载模型"""
        return self.model_loaded