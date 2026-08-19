"""
二维占据栅格地图构建
根据预设障碍物位置生成栅格地图
"""

import numpy as np


class GridMap:
    """构建和管理二维占据栅格地图"""

    def __init__(self, x_min: float, x_max: float,
                 y_min: float, y_max: float, resolution: float):
        """
        Args:
            x_min, x_max: X轴范围 (m)
            y_min, y_max: Y轴范围 (m)
            resolution: 栅格分辨率 (m/格)
        """
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max
        self.resolution = resolution

        self.width = int((x_max - x_min) / resolution)
        self.height = int((y_max - y_min) / resolution)
        # 0: 自由, 1: 占用
        self.grid = np.zeros((self.height, self.width), dtype=np.uint8)

    def add_obstacle(self, x: float, y: float, radius: float) -> None:
        """
        添加圆形障碍物

        Args:
            x, y: 障碍物中心世界坐标 (m)
            radius: 障碍物半径 (m)
        """
        # 计算障碍物覆盖的栅格范围
        cx, cy = self.world_to_grid(x, y)
        radius_cells = int(radius / self.resolution) + 1

        for i in range(max(0, cy - radius_cells),
                       min(self.height, cy + radius_cells + 1)):
            for j in range(max(0, cx - radius_cells),
                           min(self.width, cx + radius_cells + 1)):
                # 检查是否在圆形范围内
                gx, gy = self.grid_to_world(j, i)
                dist = np.sqrt((gx - x) ** 2 + (gy - y) ** 2)
                if dist <= radius:
                    self.grid[i, j] = 1

    def add_obstacle_list(self, obstacles: list) -> None:
        """批量添加障碍物 [[x, y, radius], ...]"""
        for obs in obstacles:
            self.add_obstacle(obs[0], obs[1], obs[2])

    def world_to_grid(self, x: float, y: float) -> tuple:
        """???? -> ???????????????"""
        j = int((x - self.x_min) / self.resolution)
        i = int((y - self.y_min) / self.resolution)
        j = min(max(j, 0), self.width - 1)
        i = min(max(i, 0), self.height - 1)
        return (j, i)

    def grid_to_world(self, j: int, i: int) -> tuple:
        """栅格坐标 -> 世界坐标（栅格中心）"""
        x = self.x_min + (j + 0.5) * self.resolution
        y = self.y_min + (i + 0.5) * self.resolution
        return (x, y)

    def is_occupied(self, j: int, i: int) -> bool:
        """检查栅格是否被占用"""
        if 0 <= i < self.height and 0 <= j < self.width:
            return self.grid[i, j] == 1
        return True  # 超出地图边界视为占用

    def is_collision(self, x: float, y: float) -> bool:
        """检查世界坐标点是否与障碍物碰撞"""
        j, i = self.world_to_grid(x, y)
        return self.is_occupied(j, i)

    def get_obstacle_map(self) -> np.ndarray:
        """获取栅格地图副本"""
        return self.grid.copy()

    def inflate_obstacles(self, inflation_radius: float) -> None:
        """
        膨胀障碍物（用于安全裕量）

        Args:
            inflation_radius: 膨胀半径 (m)
        """
        iters = int(inflation_radius / self.resolution)
        if iters < 1:
            # scipy iterations=0 ????????????????
            return
        from scipy.ndimage import binary_dilation
        struct = np.ones((3, 3), dtype=bool)
        inflated = binary_dilation(self.grid == 1, structure=struct,
                                   iterations=iters)
        self.grid[inflated] = 1

    def get_free_space(self) -> np.ndarray:
        """获取自由空间坐标列表 (N, 2)"""
        free_indices = np.where(self.grid == 0)
        free_coords = []
        for i, j in zip(free_indices[0], free_indices[1]):
            x, y = self.grid_to_world(j, i)
            free_coords.append([x, y])
        return np.array(free_coords)