"""
AirSim 客户端 - 支持真实 AirSim 和 2D 模拟器两种模式
"""

import time
import math
import numpy as np

# 切换此变量以选择模式
USE_REAL_AIRSIM = True


class AirSimClientWrapper:
    """
    无人机避障控制客户端
    USE_REAL_AIRSIM=True: 连接真实 AirSim
    USE_REAL_AIRSIM=False: 使用 Python 2D 模拟器
    """

    def __init__(self, ip: str = "127.0.0.1", port: int = 41451, vehicle_name: str = ""):
        self.vehicle_name = vehicle_name
        self.use_real = USE_REAL_AIRSIM

        if self.use_real:
            self._init_real(ip, port, vehicle_name)
        else:
            self._init_sim()

    def _init_real(self, ip, port, vehicle_name):
        """初始化真实 AirSim 连接"""
        import airsim
        self._client = airsim.MultirotorClient(ip=ip, port=port)
        self._client.confirmConnection()
        self.client = self._client  # 兼容接口
        print(f"[AirSim] 已连接到 {ip}:{port}")

    def _init_sim(self):
        """初始化 2D 模拟器"""
        self._pos = np.array([0.0, 0.0, -5.0])
        self._vel = np.array([0.0, 0.0, 0.0])
        self._yaw = 0.0
        self._collided = False
        self._started = False

        self._obstacles = np.array([
            [-3.0, -3.0, 1.0], [2.0, 4.0, 1.5], [5.0, -2.0, 1.0],
            [-5.0, 5.0, 1.2], [0.0, 8.0, 1.0], [8.0, 0.0, 1.3]
        ])
        self._lidar_range = 15.0
        self._noise_std = 0.05
        self.client = self

        try:
            import pygame
            pygame.init()
            self._viz = True
            self._screen = pygame.display.set_mode((800, 800))
            pygame.display.set_caption("AirSim 2D 避障模拟器")
            self._font = pygame.font.Font(None, 24)
            self._clock = pygame.time.Clock()
        except ImportError:
            self._viz = False
            print("[模拟器] pygame 未安装，用终端模式")

    # ========== 统一接口 ==========

    def takeoff(self, height=-5.0, timeout=10.0):
        if self.use_real:
            self._client.enableApiControl(True)
            self._client.armDisarm(True)
            self._client.takeoffAsync(timeout_sec=timeout).join()
            print(f"[AirSim] 起飞完成")
        else:
            print(f"[模拟器] 起飞到高度 {height}")
            self._pos[2] = height
            self._started = True
        return True

    def land(self):
        if self.use_real:
            self._client.landAsync().join()
            self._client.armDisarm(False)
            self._client.enableApiControl(False)
        else:
            print("[模拟器] 降落")
            self._started = False

    def get_position(self):
        if self.use_real:
            state = self._client.getMultirotorState()
            return np.array([state.kinematics_estimated.position.x_val,
                             state.kinematics_estimated.position.y_val,
                             state.kinematics_estimated.position.z_val])
        return self._pos.copy()

    def get_velocity(self):
        if self.use_real:
            state = self._client.getMultirotorState()
            return np.array([state.kinematics_estimated.linear_velocity.x_val,
                             state.kinematics_estimated.linear_velocity.y_val,
                             state.kinematics_estimated.linear_velocity.z_val])
        return self._vel.copy()

    def send_velocity(self, vx, vy, vz=0.0, duration=0.5):
        if self.use_real:
            self._client.moveByVelocityAsync(vx, vy, vz, duration).join()
        else:
            dt = duration
            self._pos[0] += vx * dt
            self._pos[1] += vy * dt
            self._pos[2] += vz * dt
            self._vel = np.array([vx, vy, vz])
            if abs(vx) > 0.01 or abs(vy) > 0.01:
                self._yaw = math.atan2(vy, vx)
            self._check_collision()
            self._render()

    def get_lidar_data(self):
        if self.use_real:
            lidar = self._client.getLidarData(vehicle_name=self.vehicle_name)
            if lidar and hasattr(lidar, 'point_cloud') and len(lidar.point_cloud) > 0:
                points = np.array(lidar.point_cloud, dtype=np.float32).reshape(-1, 3)
                return points
            return np.array([]).reshape(0, 3)
        points = []
        for obs in self._obstacles:
            ox, oy = obs[0], obs[1]
            dx = ox - self._pos[0]
            dy = oy - self._pos[1]
            dist = math.sqrt(dx*dx + dy*dy)
            if dist < self._lidar_range:
                noise = np.random.normal(0, self._noise_std, 2)
                points.append([ox + noise[0], oy + noise[1], 0.0])
        return np.array(points) if points else np.array([]).reshape(0, 3)

    def get_collision_info(self):
        if self.use_real:
            info = self._client.getCollisionInfo()
            return info.has_collided
        return self._collided

    def reset_position(self, x, y, z):
        if self.use_real:
            self._client.reset()
            time.sleep(0.5)
        else:
            self._pos = np.array([x, y, z])
            self._vel = np.array([0.0, 0.0, 0.0])
            self._collided = False

    def is_api_connected(self):
        if self.use_real:
            return self._client.isApiControlEnabled()
        return True

    # ========== 模拟器内部方法 ==========

    def get_pose(self):
        class Pose:
            pass
        p = Pose()
        p.x_val, p.y_val, p.z_val = self._pos
        return p

    def send_velocity_body(self, vx, vy, vz=0.0, duration=0.5):
        self.send_velocity(vx, vy, vz, duration)

    def get_depth_image(self):
        return np.array([])

    def _check_collision(self):
        for obs in self._obstacles:
            ox, oy, radius = obs
            dist = np.linalg.norm(self._pos[:2] - np.array([ox, oy]))
            if dist < radius:
                self._collided = True
                return
        self._collided = False

    def getMultirotorState(self, vehicle_name=""):
        class State:
            pass
        class Kinematics:
            pass
        kin = Kinematics()
        kin.position = self.get_pose()
        class Ori:
            def __init__(self, yaw):
                self.w_val = math.cos(yaw / 2)
                self.x_val = 0.0
                self.y_val = 0.0
                self.z_val = math.sin(yaw / 2)
        kin.orientation = Ori(self._yaw)
        class Vel:
            pass
        vel = Vel()
        vel.x_val, vel.y_val, vel.z_val = self._vel
        kin.linear_velocity = vel
        state = State()
        state.kinematics_estimated = kin
        return state

    def _render(self):
        if not self._viz:
            return
        import pygame
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._viz = False
                return
        self._screen.fill((255, 255, 255))
        scale = 20
        cx, cy = 400, 400

        def to_screen(x, y):
            return int(cx + x * scale), int(cy - y * scale)

        for i in range(-20, 21):
            c = (220, 220, 220)
            pygame.draw.line(self._screen, c, to_screen(i, -20), to_screen(i, 20), 1)
            pygame.draw.line(self._screen, c, to_screen(-20, i), to_screen(20, i), 1)
        for obs in self._obstacles:
            ox, oy, r = obs
            px, py = to_screen(ox, oy)
            pygame.draw.circle(self._screen, (100, 100, 100), (px, py), int(r * scale))
            pygame.draw.circle(self._screen, (50, 50, 50), (px, py), int(r * scale), 2)
        dx, dy = to_screen(self._pos[0], self._pos[1])
        color = (255, 0, 0) if self._collided else (0, 0, 255)
        pygame.draw.circle(self._screen, color, (dx, dy), 8)
        if np.linalg.norm(self._vel[:2]) > 0.1:
            ex = int(dx + 20 * math.cos(self._yaw))
            ey = int(dy - 20 * math.sin(self._yaw))
            pygame.draw.line(self._screen, (0, 0, 0), (dx, dy), (ex, ey), 3)
        sx, sy = to_screen(0, 0)
        pygame.draw.circle(self._screen, (0, 200, 0), (sx, sy), 6, 2)
        gx, gy = to_screen(10, 10)
        pygame.draw.circle(self._screen, (200, 0, 0), (gx, gy), 6, 2)
        infos = [
            f"位置: ({self._pos[0]:.1f}, {self._pos[1]:.1f})",
            f"速度: ({self._vel[0]:.1f}, {self._vel[1]:.1f})",
            f"碰撞: {'是' if self._collided else '否'}",
        ]
        for i, t in enumerate(infos):
            s = self._font.render(t, True, (0, 0, 0))
            self._screen.blit(s, (10, 10 + i * 25))
        pygame.display.flip()
        self._clock.tick(30)