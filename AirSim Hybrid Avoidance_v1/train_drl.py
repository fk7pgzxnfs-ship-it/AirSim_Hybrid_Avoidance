"""
DRL 训练入口脚本
启动 DDPG 训练循环
"""

import sys
import os
import yaml
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hybrid_controller.supervisor import Supervisor
from drl.env import DroneEnv
from drl.trainer import DDPGTrainer
from drl.utils_drl import set_seed


def main():
    """主训练入口"""
    print("=" * 50)
    print("AirSim DRL 训练启动")
    print("=" * 50)

    # 加载配置
    config_path = "config/default.yaml"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # 设置随机种子
    seed = config['drl'].get('seed', 42)
    set_seed(seed)

    # 初始化 Supervisor（仅用于环境接口）
    supervisor = Supervisor(config_path)

    # 初始化 DRL 环境
    env_config = {
        **config['drl']['env'],
        'reward': config['drl']['reward'],
    }
    env = DroneEnv(supervisor, env_config)

    # 训练
    trainer = DDPGTrainer(env, config['drl'])
    stats = trainer.train()

    # 保存训练曲线
    save_dir = "logs/train"
    os.makedirs(save_dir, exist_ok=True)
    np.save(os.path.join(save_dir, "rewards.npy"),
            np.array(trainer.episode_rewards))

    print("\n训练完成！")
    print(f"模型保存目录: models/drl_agent/")
    print(f"训练日志保存: {save_dir}/")

    return stats


if __name__ == "__main__":
    main()