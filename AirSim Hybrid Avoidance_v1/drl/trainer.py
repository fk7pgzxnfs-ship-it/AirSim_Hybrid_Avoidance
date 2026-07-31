"""
DRL 训练主逻辑
实现 DDPG 算法的训练循环
"""

import os
import time
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from tqdm import tqdm

from drl.models import Actor, Critic
from drl.replay_buffer import ReplayBuffer


class DDPGTrainer:
    """
    DDPG (Deep Deterministic Policy Gradient) 训练器
    适用于连续动作空间的无人机避障任务
    """

    def __init__(self, env, config: dict):
        """
        Args:
            env: Gym 环境实例
            config: DRL 训练配置字典
        """
        self.env = env
        self.cfg = config
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[Trainer] 使用设备: {self.device}")

        # 超参数
        tc = config['training']
        state_dim = config['env']['state_dim']
        action_dim = config['env']['action_dim']
        action_low = config['env']['action_low']
        action_high = config['env']['action_high']

        self.gamma = tc['gamma']
        self.tau = tc['tau']
        self.batch_size = tc['batch_size']
        self.episodes = tc['episodes']
        self.warmup_steps = tc['warmup_steps']
        self.update_every = tc.get('update_every', 2)
        self.save_every = tc.get('save_every', 100)

        # 探索噪声
        self.exploration_noise = tc.get('exploration_noise', 0.1)
        self.noise_decay = tc.get('noise_decay', 0.995)
        self.min_noise = tc.get('min_noise', 0.01)
        self.current_noise = self.exploration_noise

        # 网络
        hidden = config['network']['hidden_layers']
        self.actor = Actor(state_dim, action_dim, hidden,
                           action_low, action_high).to(self.device)
        self.actor_target = Actor(state_dim, action_dim, hidden,
                                  action_low, action_high).to(self.device)
        self.actor_target.load_state_dict(self.actor.state_dict())

        self.critic = Critic(state_dim, action_dim, hidden).to(self.device)
        self.critic_target = Critic(state_dim, action_dim, hidden).to(self.device)
        self.critic_target.load_state_dict(self.critic.state_dict())

        # 优化器
        lr = tc['learning_rate']
        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=lr)
        self.critic_optimizer = optim.Adam(self.critic.parameters(), lr=lr)

        # 经验回放
        self.replay_buffer = ReplayBuffer(tc['buffer_size'])

        # 训练记录
        self.episode_rewards = []
        self.episode_lengths = []
        self.loss_records = {'actor': [], 'critic': []}

    def train(self) -> dict:
        """
        执行完整训练流程

        Returns:
            训练统计信息
        """
        print(f"[Trainer] 开始训练，共 {self.episodes} 个 episode")

        total_steps = 0
        best_reward = -float('inf')

        for episode in range(1, self.episodes + 1):
            state, _ = self.env.reset()
            episode_reward = 0
            episode_steps = 0
            done = False

            while not done:
                # 选择动作（加探索噪声）
                action = self._select_action(state)

                # 执行动作
                next_state, reward, terminated, truncated, info = \
                    self.env.step(action)
                done = terminated or truncated

                # 存储经验
                self.replay_buffer.push(state, action, reward,
                                        next_state, done)
                state = next_state
                episode_reward += reward
                episode_steps += 1
                total_steps += 1

                # 更新网络
                if total_steps > self.warmup_steps and \
                   total_steps % self.update_every == 0:
                    self._update_network()

            # 记录
            self.episode_rewards.append(episode_reward)
            self.episode_lengths.append(episode_steps)

            # 衰减噪声
            self.current_noise = max(
                self.min_noise,
                self.current_noise * self.noise_decay
            )

            # 保存最佳模型
            if episode_reward > best_reward:
                best_reward = episode_reward
                self._save_model("best")

            # 定期保存
            if episode % self.save_every == 0:
                self._save_model(f"episode_{episode}")

            # 打印进度
            if episode % 10 == 0:
                avg_reward = np.mean(self.episode_rewards[-10:])
                avg_length = np.mean(self.episode_lengths[-10:])
                print(
                    f"[Episode {episode}/{self.episodes}] "
                    f"Reward: {episode_reward:.1f} (Avg: {avg_reward:.1f}) "
                    f"Steps: {episode_steps} (Avg: {avg_length:.1f}) "
                    f"Noise: {self.current_noise:.3f}"
                )

        # 保存最终模型
        self._save_model("final")

        stats = {
            "episodes": self.episodes,
            "total_steps": total_steps,
            "best_reward": best_reward,
            "final_reward": self.episode_rewards[-1],
            "avg_reward_last_100": np.mean(self.episode_rewards[-100:]),
            "success_rate": np.mean(
                [r > 0 for r in self.episode_rewards[-100:]]
            )
        }

        print(f"\n[Trainer] 训练完成！")
        print(f"  总步数: {total_steps}")
        print(f"  最佳奖励: {best_reward:.1f}")
        print(f"  最后100轮平均奖励: {stats['avg_reward_last_100']:.1f}")
        print(f"  成功率: {stats['success_rate']:.2%}")

        return stats

    def _select_action(self, state: np.ndarray) -> np.ndarray:
        """选择动作（带探索噪声）"""
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)

        with torch.no_grad():
            action = self.actor.get_action(state_tensor).cpu().numpy()[0]

        # 添加探索噪声
        noise = np.random.normal(0, self.current_noise, size=action.shape)
        action = action + noise

        # 裁剪到合法范围
        action = np.clip(
            action,
            self.cfg['env']['action_low'],
            self.cfg['env']['action_high']
        )
        return action

    def _update_network(self):
        """更新 Actor 和 Critic 网络"""
        if len(self.replay_buffer) < self.batch_size:
            return

        # 采样
        states, actions, rewards, next_states, dones = \
            self.replay_buffer.sample(self.batch_size)

        states = torch.FloatTensor(states).to(self.device)
        actions = torch.FloatTensor(actions).to(self.device)
        rewards = torch.FloatTensor(rewards).unsqueeze(1).to(self.device)
        next_states = torch.FloatTensor(next_states).to(self.device)
        dones = torch.FloatTensor(dones).unsqueeze(1).to(self.device)

        # ---- 更新 Critic ----
        with torch.no_grad():
            next_actions = self.actor_target.get_action(next_states)
            target_q = self.critic_target(next_states, next_actions)
            target_q = rewards + (1 - dones) * self.gamma * target_q

        current_q = self.critic(states, actions)
        critic_loss = nn.MSELoss()(current_q, target_q)

        self.critic_optimizer.zero_grad()
        critic_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.critic.parameters(), 1.0)
        self.critic_optimizer.step()

        # ---- 更新 Actor ----
        actor_loss = -self.critic(states,
                                  self.actor.get_action(states)).mean()

        self.actor_optimizer.zero_grad()
        actor_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.actor.parameters(), 1.0)
        self.actor_optimizer.step()

        # 记录损失
        self.loss_records['actor'].append(actor_loss.item())
        self.loss_records['critic'].append(critic_loss.item())

        # ---- 软更新目标网络 ----
        self._soft_update(self.actor, self.actor_target)
        self._soft_update(self.critic, self.critic_target)

    def _soft_update(self, source, target):
        """软更新目标网络参数"""
        for target_param, source_param in zip(target.parameters(),
                                              source.parameters()):
            target_param.data.copy_(
                self.tau * source_param.data +
                (1 - self.tau) * target_param.data
            )

    def _save_model(self, suffix: str):
        """保存模型"""
        save_dir = self.cfg.get('model', {}).get('save_dir',
                                                  "models/drl_agent")
        os.makedirs(save_dir, exist_ok=True)

        path = os.path.join(save_dir, f"ddpg_{suffix}.pth")
        torch.save({
            'actor_state_dict': self.actor.state_dict(),
            'critic_state_dict': self.critic.state_dict(),
            'actor_optimizer': self.actor_optimizer.state_dict(),
            'critic_optimizer': self.critic_optimizer.state_dict(),
            'episode_rewards': self.episode_rewards,
            'config': self.cfg
        }, path)
        print(f"[Trainer] 模型保存至: {path}")

    def load_model(self, path: str):
        """加载模型"""
        checkpoint = torch.load(path, map_location=self.device)
        self.actor.load_state_dict(checkpoint['actor_state_dict'])
        self.critic.load_state_dict(checkpoint['critic_state_dict'])
        self.actor_target.load_state_dict(self.actor.state_dict())
        self.critic_target.load_state_dict(self.critic.state_dict())
        print(f"[Trainer] 模型加载: {path}")