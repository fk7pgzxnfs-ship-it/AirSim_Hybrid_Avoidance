"""
A* 路径规划算法实现
在二维栅格地图上搜索最短路径
"""

import heapq
import numpy as np


class AStar:
    """A* 路径规划算法"""

    def __init__(self, grid_map, heuristic_weight: float = 1.2,
                 diagonal_movement: bool = True, max_iterations: int = 50000):
        """
        Args:
            grid_map: GridMap 实例
            heuristic_weight: 启发式权重，>1 使搜索更贪婪
            diagonal_movement: 是否允许对角线移动
            max_iterations: 最大搜索迭代次数
        """
        self.grid_map = grid_map
        self.heuristic_weight = heuristic_weight
        self.diagonal_movement = diagonal_movement
        self.max_iterations = max_iterations

        # 8个移动方向及其代价
        if diagonal_movement:
            self.directions = [
                (0, 1, 1.0), (0, -1, 1.0), (1, 0, 1.0), (-1, 0, 1.0),
                (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)
            ]
        else:
            self.directions = [
                (0, 1, 1.0), (0, -1, 1.0), (1, 0, 1.0), (-1, 0, 1.0)
            ]

    def plan(self, start_world: tuple, goal_world: tuple) -> np.ndarray:
        """
        规划从起点到终点的路径

        Args:
            start_world: 起点世界坐标 (x, y)
            goal_world: 终点世界坐标 (x, y)

        Returns:
            (N, 2) 路径点世界坐标数组，不可达返回空数组
        """
        start_grid = self.grid_map.world_to_grid(start_world[0], start_world[1])
        goal_grid = self.grid_map.world_to_grid(goal_world[0], goal_world[1])

        # 检查起点和终点是否有效
        if self.grid_map.is_occupied(start_grid[0], start_grid[1]):
            print("[A*] 起点被占用！")
            return np.array([])
        if self.grid_map.is_occupied(goal_grid[0], goal_grid[1]):
            print("[A*] 终点被占用！")
            return np.array([])

        # A* 主循环
        open_list = []
        start_node = _Node(start_grid, None, 0.0,
                           self._heuristic(start_grid, goal_grid))
        heapq.heappush(open_list, start_node)

        closed_set = set()
        g_costs = {start_grid: 0.0}

        iterations = 0
        while open_list and iterations < self.max_iterations:
            iterations += 1
            current = heapq.heappop(open_list)

            if current.grid == goal_grid:
                return self._reconstruct_path(current)

            closed_set.add(current.grid)

            for dx, dy, cost in self.directions:
                neighbor = (current.grid[0] + dx, current.grid[1] + dy)

                # 检查栅格是否可通行
                if not (0 <= neighbor[0] < self.grid_map.width and
                        0 <= neighbor[1] < self.grid_map.height):
                    continue
                if self.grid_map.is_occupied(neighbor[0], neighbor[1]):
                    continue
                if neighbor in closed_set:
                    continue

                tent_g = g_costs[current.grid] + cost
                if neighbor not in g_costs or tent_g < g_costs[neighbor]:
                    g_costs[neighbor] = tent_g
                    f_cost = tent_g + self.heuristic_weight * \
                             self._heuristic(neighbor, goal_grid)
                    heapq.heappush(open_list, _Node(neighbor, current,
                                                     tent_g, f_cost))

        print(f"[A*] 未找到路径，迭代次数: {iterations}")
        return np.array([])

    def _heuristic(self, grid_a: tuple, grid_b: tuple) -> float:
        """启发式函数（欧氏距离）"""
        return np.sqrt((grid_a[0] - grid_b[0]) ** 2 +
                       (grid_a[1] - grid_b[1]) ** 2)

    def _reconstruct_path(self, node) -> np.ndarray:
        """回溯路径"""
        path = []
        current = node
        while current is not None:
            world_xy = self.grid_map.grid_to_world(current.grid[0],
                                                    current.grid[1])
            path.append(world_xy)
            current = current.parent
        path.reverse()
        return np.array(path)


class _Node:
    """A* 搜索节点（内部使用）"""

    def __init__(self, grid, parent, g_cost, f_cost):
        self.grid = grid
        self.parent = parent
        self.g_cost = g_cost
        self.f_cost = f_cost

    def __lt__(self, other):
        return self.f_cost < other.f_cost

    def __eq__(self, other):
        return self.grid == other.grid

    def __hash__(self):
        return hash(self.grid)