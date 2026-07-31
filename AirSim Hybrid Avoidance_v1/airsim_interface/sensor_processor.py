"""
传感器数据处理模块
将原始LiDAR/深度数据转为规划与DRL可用的格式
"""

import numpy as np


class SensorProcessor:
    """处理LiDAR和深度相机数据，提取障碍物信息"""

    def __init__(self, max_range: float = 30.0, num_sectors: int = 16):
        """
        Args:
            max_range: LiDAR最大探测距离 (m)
            num_sectors: 极坐标扇区数，将360°分为N个扇区
        """
        self.max_range = max_range
        self.num_sectors = num_sectors
        self.sector_angle = 2 * np.pi / num_sectors

    def lidar_to_polar(self, points: np.ndarray) -> np.ndarray:
        """
        将LiDAR点云转为极坐标距离向量

        Args:
            points: (N, 3) LiDAR点云（世界坐标系）

        Returns:
            (num_sectors,) 每个扇区的最小障碍物距离，
            无障碍物则填充 max_range
        """
        if points.shape[0] == 0:
            return np.ones(self.num_sectors) * self.max_range

        # 计算水平角度和水平距离
        angles = np.arctan2(points[:, 1], points[:, 0])
        distances = np.linalg.norm(points[:, :2], axis=1)

        # 分配到扇区
        sector_distances = np.ones(self.num_sectors) * self.max_range
        for i in range(self.num_sectors):
            angle_min = i * self.sector_angle - np.pi
            angle_max = (i + 1) * self.sector_angle - np.pi
            mask = (angles >= angle_min) & (angles < angle_max)
            if np.any(mask):
                sector_distances[i] = np.min(distances[mask])

        return sector_distances

    def depth_to_obstacle_grid(self, depth_img: np.ndarray,
                                fov: float = 90.0) -> np.ndarray:
        """
        将深度图转为障碍物距离向量

        Args:
            depth_img: (H, W) 深度图
            fov: 相机视场角 (度)

        Returns:
            (num_sectors,) 每个方向的最小障碍物距离
        """
        if depth_img.size == 0:
            return np.ones(self.num_sectors) * self.max_range

        H, W = depth_img.shape
        # 将深度图按水平方向分成N个扇区
        sector_width = W // self.num_sectors
        sector_distances = np.ones(self.num_sectors) * self.max_range

        for i in range(self.num_sectors):
            col_start = i * sector_width
            col_end = min((i + 1) * sector_width, W)
            sector = depth_img[:, col_start:col_end]
            # 取该扇区的最小有效深度值
            valid = (sector > 0.1) & (sector < self.max_range)
            if np.any(valid):
                sector_distances[i] = np.min(sector[valid])

        return sector_distances

    def find_nearest_obstacle(self, points: np.ndarray) -> tuple:
        """
        找到最近的障碍物距离和方向

        Args:
            points: (N, 3) LiDAR点云

        Returns:
            (min_distance, min_angle): 最近障碍物距离和水平方向角
        """
        if points.shape[0] == 0:
            return self.max_range, 0.0

        distances = np.linalg.norm(points[:, :2], axis=1)
        min_idx = np.argmin(distances)

        min_distance = distances[min_idx]
        min_angle = np.arctan2(points[min_idx, 1], points[min_idx, 0])

        return min_distance, min_angle

    def compute_obstacle_density(self, points: np.ndarray,
                                  radius: float = 2.0) -> float:
        """
        计算机体周围指定半径内的障碍物密度

        Args:
            points: (N, 3) LiDAR点云
            radius: 统计半径 (m)

        Returns:
            密度值 [0, 1]，越大越危险
        """
        if points.shape[0] == 0:
            return 0.0

        distances = np.linalg.norm(points[:, :2], axis=1)
        near_count = np.sum(distances < radius)
        return min(near_count / 20.0, 1.0)