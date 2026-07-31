"""
AirSim 接口辅助函数
坐标变换、数据格式转换等
"""

import numpy as np
import airsim


def world_to_body(position: np.ndarray, yaw: float) -> np.ndarray:
    """
    将世界坐标系下的向量转换到机体坐标系

    Args:
        position: 世界坐标系下的位置/向量 (x, y)
        yaw: 机体偏航角 (弧度)

    Returns:
        机体坐标系下的向量 (x_body, y_body)
    """
    cos_yaw = np.cos(yaw)
    sin_yaw = np.sin(yaw)
    rotation_matrix = np.array([
        [cos_yaw, sin_yaw],
        [-sin_yaw, cos_yaw]
    ])
    return rotation_matrix @ position[:2]


def body_to_world(velocity: np.ndarray, yaw: float) -> np.ndarray:
    """
    将机体坐标系下的速度转换到世界坐标系

    Args:
        velocity: 机体速度 (vx, vy)
        yaw: 机体偏航角 (弧度)

    Returns:
        世界坐标系下的速度 (vx_world, vy_world)
    """
    cos_yaw = np.cos(yaw)
    sin_yaw = np.sin(yaw)
    rotation_matrix = np.array([
        [cos_yaw, -sin_yaw],
        [sin_yaw, cos_yaw]
    ])
    return rotation_matrix @ velocity[:2]


def get_yaw_from_quaternion(quaternion: airsim.Quaternionr) -> float:
    """
    从四元数提取偏航角 (yaw)

    Args:
        quaternion: AirSim四元数

    Returns:
        偏航角 (弧度)
    """
    w, x, y, z = quaternion.w_val, quaternion.x_val, quaternion.y_val, quaternion.z_val
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return np.arctan2(siny_cosp, cosy_cosp)


def normalize_angle(angle: float) -> float:
    """
    将角度归一化到 [-pi, pi]

    Args:
        angle: 输入角度 (弧度)

    Returns:
        归一化后的角度
    """
    return np.arctan2(np.sin(angle), np.cos(angle))


def compute_distance(p1: np.ndarray, p2: np.ndarray) -> float:
    """计算二维欧氏距离"""
    return float(np.linalg.norm(p1[:2] - p2[:2]))


def compute_angle_to_target(current_pos: np.ndarray,
                             target_pos: np.ndarray,
                             current_yaw: float) -> float:
    """
    计算机体到目标点的水平偏角

    Args:
        current_pos: 当前位置 (x, y)
        target_pos: 目标位置 (x, y)
        current_yaw: 当前偏航角 (弧度)

    Returns:
        目标相对于机体的偏角 (弧度)，正值表示偏右
    """
    dx = target_pos[0] - current_pos[0]
    dy = target_pos[1] - current_pos[1]
    target_angle = np.arctan2(dy, dx)
    relative_angle = normalize_angle(target_angle - current_yaw)
    return relative_angle


def depth_to_distance(depth_img: np.ndarray) -> float:
    """
    从深度图中提取前方最近障碍物距离

    Args:
        depth_img: (H, W) 深度图

    Returns:
        最近障碍物距离 (m)
    """
    if depth_img.size == 0:
        return float('inf')
    valid = (depth_img > 0.1) & (depth_img < 100.0)
    if np.any(valid):
        return float(np.min(depth_img[valid]))
    return float('inf')


def vector3r_to_numpy(vec: airsim.Vector3r) -> np.ndarray:
    """将 AirSim Vector3r 转为 numpy 数组"""
    return np.array([vec.x_val, vec.y_val, vec.z_val])