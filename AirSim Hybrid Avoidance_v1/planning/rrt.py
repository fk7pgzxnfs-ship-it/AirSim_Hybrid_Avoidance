"""
RRT (Rapidly-exploring Random Tree) 路径规划算法
可选模块，用于对比实验
"""

import numpy as np


class RRT:
    """RRT 路径规划算法"""

    def __init__(self, grid_map, max_iterations: int = 5000,
                 step_size: float = 1.0, goal_sample_rate: float = 0.1):
        """
        Args:
            grid_map: GridMap 实例
            max_iterations: 最大迭代次数
            step_size: 扩展步长 (m)
            goal_sample_rate: 目标偏置采样概率
        """
        self.grid_map = grid_map
        self.max_iterations = max_iterations
        self.step_size = step_size
        self.goal_sample_rate = goal_sample_rate

    def plan(self, start_world: tuple, goal_world: tuple) -> np.ndarray:
        """
        RRT 路径规划

        Args:
            start_world: 起点 (x, y)
            goal_world: 终点 (x, y)

        Returns:
            (N, 2) 路径点数组
        """
        nodes = [np.array(start_world)]
        parent = [0]

        for _ in range(self.max_iterations):
            # 采样
            if np.random.random() < self.goal_sample_rate:
                sample = np.array(goal_world)
            else:
                sample = np.array([
                    np.random.uniform(self.grid_map.x_min, self.grid_map.x_max),
                    np.random.uniform(self.grid_map.y_min, self.grid_map.y_max)
                ])

            # 找最近节点
            nearest_idx = np.argmin([np.linalg.norm(n - sample) for n in nodes])
            nearest = nodes[nearest_idx]

            # 扩展
            direction = sample - nearest
            dist = np.linalg.norm(direction)
            if dist < 0.01:
                continue

            new_node = nearest + (direction / dist) * min(self.step_size, dist)

            # 碰撞检测
            if self.grid_map.is_collision(new_node[0], new_node[1]):
                continue

            nodes.append(new_node)
            parent.append(nearest_idx)

            # 检查是否到达终点
            if np.linalg.norm(new_node - np.array(goal_world)) < self.step_size:
                return self._reconstruct_path(nodes, parent, goal_world)

        print("[RRT] 未找到路径")
        return np.array([])

    def _reconstruct_path(self, nodes: list, parent: list,
                          goal_world: tuple) -> np.ndarray:
        """回溯路径"""
        path = [np.array(goal_world)]
        idx = len(nodes) - 1
        while idx > 0:
            path.append(nodes[idx])
            idx = parent[idx]
        path.append(nodes[0])
        path.reverse()
        return np.array(path)