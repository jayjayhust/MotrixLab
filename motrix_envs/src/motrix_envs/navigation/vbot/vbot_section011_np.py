# Copyright (C) 2020-2025 Motphys Technology Co., Ltd. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

import numpy as np
import motrixsim as mtx
import gymnasium as gym

from motrix_envs import registry
from motrix_envs.np.env import NpEnv, NpEnvState
from motrix_envs.math.quaternion import Quaternion

from .cfg import VBotSection011EnvCfg


def generate_repeating_array(num_period, num_reset, period_counter):
    """
    生成重复数组，用于在固定位置中循环选择
    num_period: 位置总数
    num_reset: 需要重置的环境数
    period_counter: 当前计数器
    """
    idx = []
    for i in range(num_reset):
        idx.append((period_counter + i) % num_period)
    return np.array(idx)


@registry.env("vbot_navigation_section011", "np")
class VBotSection011Env(NpEnv):
    """
    VBot在Section011地形上的导航任务
    继承自NpEnv，使用VBotSection011EnvCfg配置
    """
    _cfg: VBotSection011EnvCfg
    
    def __init__(self, cfg: VBotSection011EnvCfg, num_envs: int = 1):
        # 调用父类NpEnv初始化
        super().__init__(cfg, num_envs=num_envs)
        
        # 初始化机器人body和接触
        self._body = self._model.get_body(cfg.asset.body_name)
        self._init_contact_geometry()

        # 获取目标标记的body
        self._target_marker_body = self._model.get_body("target_marker")
        
        # 获取箭头body（用于可视化，不影响物理）
        try:
            self._robot_arrow_body = self._model.get_body("robot_heading_arrow")
            self._desired_arrow_body = self._model.get_body("desired_heading_arrow")
        except Exception:
            self._robot_arrow_body = None
            self._desired_arrow_body = None
        
        # 动作和观测空间
        self._action_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(12,), dtype=np.float32)  # 12维动作空间
        # 观测空间：67维（55 + 12维接触力）
        self._observation_space = gym.spaces.Box(low=-np.inf, high=np.inf, shape=(54,), dtype=np.float32)
        
        self._num_dof_pos = self._model.num_dof_pos
        self._num_dof_vel = self._model.num_dof_vel
        self._num_action = self._model.num_actuators
        
        # 初始化DOF位置和速度
        # DOF pos 维度：36
        # 分别是：?
        self._init_dof_pos = self._model.compute_init_dof_pos()
        print(f"Init DOF Pos array len : {len(self._init_dof_pos)}")
        # DOF vel 维度：33
        # 分别是：?
        self._init_dof_vel = np.zeros((self._model.num_dof_vel,), dtype=np.float32)
        print(f"Init DOF Vel array len : {len(self._init_dof_vel)}")
        # debug
        print(f"self._model.joint_names: {self._model.joint_names}")  # 'target_x', 'target_y', 'target_yaw' + 12 joint
        print(f"self._model.actuator_names: {self._model.actuator_names}")  # 12 actuator
        print(f"self._model.joint_dof_pos_nums: {self._model.joint_dof_pos_nums}")
        print(f"self._model.joint_dof_vel_nums: {self._model.joint_dof_vel_nums}")
        
        # 查找target_marker的DOF索引
        self._find_target_marker_dof_indices()
        
        # 查找箭头的DOF索引
        if self._robot_arrow_body is not None and self._desired_arrow_body is not None:
            self._find_arrow_dof_indices()
        
        # 初始化缓存
        self._init_buffer()
        
        # 初始位置生成参数：从配置文件读取
        self.spawn_center = np.array(cfg.init_state.pos, dtype=np.float32)  # 从配置读取
        self.spawn_range = cfg.init_state.pos_range  # 随机生成范围：±0.1m（0.2m×0.2m区域）
    
        # 导航统计计数器
        self.navigation_stats_step = 0
    
    def _init_buffer(self):
        """初始化缓存和参数"""
        cfg = self._cfg
        self.default_angles = np.zeros(self._num_action, dtype=np.float32)
        
        # 归一化系数
        self.commands_scale = np.array(
            [cfg.normalization.lin_vel, cfg.normalization.lin_vel, cfg.normalization.ang_vel],
            dtype=np.float32
        )
        
        # 设置默认关节角度
        for i in range(self._model.num_actuators):
            for name, angle in cfg.init_state.default_joint_angles.items():
                if name in self._model.actuator_names[i]:
                    self.default_angles[i] = angle
        
        self._init_dof_pos[-self._num_action:] = self.default_angles
        self.action_filter_alpha = 0.3  # 动作滤波参数
    
    def _find_target_marker_dof_indices(self):
        """查找target_marker在dof_pos中的索引位置"""
        self._target_marker_dof_start = 0
        self._target_marker_dof_end = 3
        self._init_dof_pos[0:3] = [0.0, 0.0, 0.0]
        self._base_quat_start = 6
        self._base_quat_end = 10
        
        # 确保base四元数初始化为单位四元数 [0, 0, 0, 1]
        self._init_dof_pos[self._base_quat_start:self._base_quat_end] = [0.0, 0.0, 0.0, 1.0]
    
    def _find_arrow_dof_indices(self):
        """查找箭头在dof_pos中的索引位置"""
        self._robot_arrow_dof_start = 22
        self._robot_arrow_dof_end = 29
        self._desired_arrow_dof_start = 29
        self._desired_arrow_dof_end = 36
        
        arrow_init_height = self._cfg.init_state.pos[2] + 0.5 
        if self._robot_arrow_dof_end <= len(self._init_dof_pos):
            self._init_dof_pos[self._robot_arrow_dof_start:self._robot_arrow_dof_end] = [0.0, 0.0, arrow_init_height, 0.0, 0.0, 0.0, 1.0]
        if self._desired_arrow_dof_end <= len(self._init_dof_pos):
            self._init_dof_pos[self._desired_arrow_dof_start:self._desired_arrow_dof_end] = [0.0, 0.0, arrow_init_height, 0.0, 0.0, 0.0, 1.0]
    
    def _init_contact_geometry(self):
        """初始化接触检测所需的几何体索引"""
        self._init_termination_contact()
        self._init_foot_contact()
    
    def _init_termination_contact(self):
        """初始化终止接触检测：基座geom与地面geom的碰撞"""
        termination_contact_names = self._cfg.asset.terminate_after_contacts_on
        
        # 获取所有地面geom（遍历所有geom，找到包含ground_subtree名称的）
        ground_geoms = []
        ground_prefix = self._cfg.asset.ground_subtree  # "0ground_root"
        for geom_name in self._model.geom_names:
            if geom_name is not None and ground_prefix in geom_name:
                ground_geoms.append(self._model.get_geom_index(geom_name))
        
        # if len(ground_geoms) == 0:
        #     print(f"[Warning] 未找到以 '{ground_prefix}' 开头的地面geom！")
        #     self.termination_contact = np.zeros((0, 2), dtype=np.uint32)
        #     self.num_termination_check = 0
        #     return
        
        # 构建碰撞对：每个基座geom × 每个地面geom
        termination_contact_list = []
        for base_geom_name in termination_contact_names:
            try:
                base_geom_idx = self._model.get_geom_index(base_geom_name)
                for ground_idx in ground_geoms:
                    termination_contact_list.append([base_geom_idx, ground_idx])
            except Exception as e:
                print(f"[Warning] 无法找到基座geom '{base_geom_name}': {e}")
        
        if len(termination_contact_list) > 0:
            self.termination_contact = np.array(termination_contact_list, dtype=np.uint32)
            self.num_termination_check = len(termination_contact_list)
            print(f"[Info] 初始化终止接触检测: {len(termination_contact_names)}个基座geom × {len(ground_geoms)}个地面geom = {self.num_termination_check}个检测对")
        else:
            self.termination_contact = np.zeros((0, 2), dtype=np.uint32)
            self.num_termination_check = 0
            print("[Warning] 未找到任何终止接触geom，基座接触检测将被禁用！")
    
    def _init_foot_contact(self):
        self.foot_contact_check = np.zeros((0, 2), dtype=np.uint32)
        self.num_foot_check = 4  
    
    def get_goal_pos(self, data: mtx.SceneData):
        """获取目标位置"""
        geom = self._model.get_geom(self._cfg.asset.goal_name)
        if geom is None:
            return None
        return geom.get_pose(data)

    def get_dof_pos(self, data: mtx.SceneData):
        return self._body.get_joint_dof_pos(data)
    
    def get_dof_vel(self, data: mtx.SceneData):
        return self._body.get_joint_dof_vel(data)
    
    def _extract_root_state(self, data):
        """从self._body中提取根节点状态"""
        pose = self._body.get_pose(data)
        root_pos = pose[:, :3]
        root_quat = pose[:, 3:7]
        root_linvel = self._model.get_sensor_value(self._cfg.sensor.base_linvel, data)
        return root_pos, root_quat, root_linvel
    
    @property
    def observation_space(self):
        return self._observation_space
    
    @property
    def action_space(self):
        return self._action_space
    
    def apply_action(self, actions: np.ndarray, state: NpEnvState):
        # 保存上一步的关节速度（用于计算加速度）
        state.info["last_dof_vel"] = self.get_dof_vel(state.data)
        state.info["last_actions"] = state.info["current_actions"]
        
        if "filtered_actions" not in state.info:
            print("[Info] 'filtered_actions' not in state.info")
        else:
            state.info["filtered_actions"] = (
                self.action_filter_alpha * actions + 
                (1.0 - self.action_filter_alpha) * state.info["filtered_actions"]
            )
        
        state.info["current_actions"] = state.info["filtered_actions"]

        state.data.actuator_ctrls = self._compute_torques(state.info["filtered_actions"], state.data)
        
        return state
    
    def _compute_torques(self, actions, data):
        """计算PD控制力矩（VBot使用motor执行器，需要力矩控制）"""
        action_scaled = actions * self._cfg.control_config.action_scale
        target_pos = self.default_angles + action_scaled
        
        # 获取当前关节状态
        current_pos = self.get_dof_pos(data)  # [num_envs, 12]
        current_vel = self.get_dof_vel(data)  # [num_envs, 12]
        
        # PD控制器：tau = kp * (target - current) - kv * vel
        kp = 80.0   # 位置增益
        kv = 6.0    # 速度增益
        
        pos_error = target_pos - current_pos
        torques = kp * pos_error - kv * current_vel
        
        # 限制力矩范围（与XML中的forcerange一致）
        # hip/thigh: ±17 N·m, calf: ±34 N·m
        torque_limits = np.array([17, 17, 34] * 4, dtype=np.float32)  # FR, FL, RR, RL
        torques = np.clip(torques, -torque_limits, torque_limits)
        
        return torques
    
    def _compute_projected_gravity(self, root_quat: np.ndarray) -> np.ndarray:
        """计算机器人坐标系中的重力向量"""
        gravity_vec = np.array([0.0, 0.0, -1.0], dtype=np.float32)
        gravity_vec = np.tile(gravity_vec, (root_quat.shape[0], 1))
        return Quaternion.rotate_inverse(root_quat, gravity_vec)
    
    def _get_heading_from_quat(self, quat: np.ndarray) -> np.ndarray:
        """从四元数计算yaw角（朝向）"""
        qx, qy, qz, qw = quat[:, 0], quat[:, 1], quat[:, 2], quat[:, 3]
        siny_cosp = 2 * (qw * qz + qx * qy)
        cosy_cosp = 1 - 2 * (qy * qy + qz * qz)
        heading = np.arctan2(siny_cosp, cosy_cosp)
        return heading
    
    def _update_target_marker(self, data: mtx.SceneData, pose_commands: np.ndarray):
        """
        更新目标位置标记的位置和朝向
        pose_commands: [num_envs, 3] - (target_x, target_y, target_heading)
        """
        num_envs = data.shape[0]
        all_dof_pos = data.dof_pos.copy()
        
        for env_idx in range(num_envs):
            target_x = float(pose_commands[env_idx, 0])
            target_y = float(pose_commands[env_idx, 1])
            target_yaw = float(pose_commands[env_idx, 2])  # 已经是角度，不需要转换
            # 只更新target_marker的DOF (0-2)，确保不修改其他DOF
            all_dof_pos[env_idx, self._target_marker_dof_start:self._target_marker_dof_end] = [
                target_x, target_y, target_yaw
            ]
        
        # 在设置DOF位置之前，显式确保所有四元数保持归一化
        # 这可以防止由于数值精度问题导致的四元数失效
        for env_idx in range(num_envs):
            # 确保base四元数归一化
            base_quat = all_dof_pos[env_idx, self._base_quat_start:self._base_quat_end]
            quat_norm = np.linalg.norm(base_quat)
            if quat_norm > 1e-6:
                all_dof_pos[env_idx, self._base_quat_start:self._base_quat_end] = base_quat / quat_norm
            else:
                all_dof_pos[env_idx, self._base_quat_start:self._base_quat_end] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
            
            # 如果箭头body存在，确保其四元数也归一化
            if self._robot_arrow_body is not None:
                # robot_arrow四元数
                robot_arrow_quat = all_dof_pos[env_idx, self._robot_arrow_dof_start+3:self._robot_arrow_dof_end]
                quat_norm = np.linalg.norm(robot_arrow_quat)
                if quat_norm > 1e-6:
                    all_dof_pos[env_idx, self._robot_arrow_dof_start+3:self._robot_arrow_dof_end] = robot_arrow_quat / quat_norm
                else:
                    all_dof_pos[env_idx, self._robot_arrow_dof_start+3:self._robot_arrow_dof_end] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
                
                # desired_arrow四元数
                desired_arrow_quat = all_dof_pos[env_idx, self._desired_arrow_dof_start+3:self._desired_arrow_dof_end]
                quat_norm = np.linalg.norm(desired_arrow_quat)
                if quat_norm > 1e-6:
                    all_dof_pos[env_idx, self._desired_arrow_dof_start+3:self._desired_arrow_dof_end] = desired_arrow_quat / quat_norm
                else:
                    all_dof_pos[env_idx, self._desired_arrow_dof_start+3:self._desired_arrow_dof_end] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        
        data.set_dof_pos(all_dof_pos, self._model)
        self._model.forward_kinematic(data)
    
    def _update_heading_arrows(self, data: mtx.SceneData, robot_pos: np.ndarray, desired_vel_xy: np.ndarray, base_lin_vel_xy: np.ndarray):
        """更新箭头位置（使用DOF控制freejoint，不影响物理）"""
        if self._robot_arrow_body is None or self._desired_arrow_body is None:
            return
        
        num_envs = data.shape[0]
        arrow_offset = 0.5  # 箭头相对于机器人的高度偏移
        all_dof_pos = data.dof_pos.copy()
        
        for env_idx in range(num_envs):
            # 算箭头高度 = 机器人当前高度 + 偏移
            arrow_height = robot_pos[env_idx, 2] + arrow_offset
            
            # 当前运动方向箭头(绿色）
            cur_v = base_lin_vel_xy[env_idx]
            if np.linalg.norm(cur_v) > 1e-3:
                cur_yaw = np.arctan2(cur_v[1], cur_v[0])
            else:
                cur_yaw = 0.0
            robot_arrow_pos = np.array([robot_pos[env_idx, 0], robot_pos[env_idx, 1], arrow_height], dtype=np.float32)
            robot_arrow_quat = self._euler_to_quat(0, 0, cur_yaw)
            quat_norm = np.linalg.norm(robot_arrow_quat)
            if quat_norm > 1e-6:
                robot_arrow_quat = robot_arrow_quat / quat_norm
            else:
                robot_arrow_quat = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
            all_dof_pos[env_idx, self._robot_arrow_dof_start:self._robot_arrow_dof_end] = np.concatenate([
                robot_arrow_pos, robot_arrow_quat
            ])
            
            # 期望运动方向箭头(蓝色）
            des_v = desired_vel_xy[env_idx]
            if np.linalg.norm(des_v) > 1e-3:
                des_yaw = np.arctan2(des_v[1], des_v[0])
            else:
                des_yaw = 0.0
            desired_arrow_pos = np.array([robot_pos[env_idx, 0], robot_pos[env_idx, 1], arrow_height], dtype=np.float32)
            desired_arrow_quat = self._euler_to_quat(0, 0, des_yaw)
            quat_norm = np.linalg.norm(desired_arrow_quat)
            if quat_norm > 1e-6:
                desired_arrow_quat = desired_arrow_quat / quat_norm
            else:
                desired_arrow_quat = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
            all_dof_pos[env_idx, self._desired_arrow_dof_start:self._desired_arrow_dof_end] = np.concatenate([
                desired_arrow_pos, desired_arrow_quat
            ])
        
        # 在设置DOF位置之前，显式确保所有四元数保持归一化
        # 这可以防止由于数值精度问题导致的四元数失效
        for env_idx in range(num_envs):
            # 确保base四元数归一化（虽然这里不直接修改，但copy操作可能影响）
            base_quat = all_dof_pos[env_idx, self._base_quat_start:self._base_quat_end]
            quat_norm = np.linalg.norm(base_quat)
            if quat_norm > 1e-6:
                all_dof_pos[env_idx, self._base_quat_start:self._base_quat_end] = base_quat / quat_norm
            else:
                all_dof_pos[env_idx, self._base_quat_start:self._base_quat_end] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
            
            # 确保箭头四元数归一化（虽然上面已经处理过，但再检查一次以防万一）
            robot_arrow_quat = all_dof_pos[env_idx, self._robot_arrow_dof_start+3:self._robot_arrow_dof_end]
            quat_norm = np.linalg.norm(robot_arrow_quat)
            if quat_norm > 1e-6:
                all_dof_pos[env_idx, self._robot_arrow_dof_start+3:self._robot_arrow_dof_end] = robot_arrow_quat / quat_norm
            else:
                all_dof_pos[env_idx, self._robot_arrow_dof_start+3:self._robot_arrow_dof_end] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
            
            desired_arrow_quat = all_dof_pos[env_idx, self._desired_arrow_dof_start+3:self._desired_arrow_dof_end]
            quat_norm = np.linalg.norm(desired_arrow_quat)
            if quat_norm > 1e-6:
                all_dof_pos[env_idx, self._desired_arrow_dof_start+3:self._desired_arrow_dof_end] = desired_arrow_quat / quat_norm
            else:
                all_dof_pos[env_idx, self._desired_arrow_dof_start+3:self._desired_arrow_dof_end] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        
        data.set_dof_pos(all_dof_pos, self._model)
        self._model.forward_kinematic(data)
    
    def _euler_to_quat(self, roll, pitch, yaw):
        """欧拉角转四元数 [qx, qy, qz, qw] - Motrix格式"""
        cy = np.cos(yaw * 0.5)
        sy = np.sin(yaw * 0.5)
        cp = np.cos(pitch * 0.5)
        sp = np.sin(pitch * 0.5)
        cr = np.cos(roll * 0.5)
        sr = np.sin(roll * 0.5)
        
        qw = cr * cp * cy + sr * sp * sy
        qx = sr * cp * cy - cr * sp * sy
        qy = cr * sp * cy + sr * cp * sy
        qz = cr * cp * sy - sr * sp * cy
        
        return np.array([qx, qy, qz, qw], dtype=np.float32)
    
    def update_state(self, state: NpEnvState) -> NpEnvState:
        """
        更新环境状态，计算观测、奖励和终止条件
        """
        data = state.data  # 单个环境数据
        cfg = self._cfg  # 环境配置
        
        # 获取基础状态
        root_pos, root_quat, root_vel = self._extract_root_state(data)
        joint_pos = self.get_dof_pos(data)
        joint_vel = self.get_dof_vel(data)
        joint_pos_rel = joint_pos - self.default_angles
        
        # 传感器数据
        base_lin_vel = root_vel[:, :3]  # 世界坐标系线速度
        gyro = self._model.get_sensor_value(cfg.sensor.base_gyro, data)
        projected_gravity = self._compute_projected_gravity(root_quat)
        
        # 导航目标
        pose_commands = state.info["pose_commands"]
        robot_position = root_pos[:, :2]
        robot_heading = self._get_heading_from_quat(root_quat)
        target_position = pose_commands[:, :2]  # 目标位置
        target_heading = pose_commands[:, 2]  # 目标朝向
        
        # 计算位置误差
        position_error = target_position - robot_position  # 位置误差
        distance_to_target = np.linalg.norm(position_error, axis=1)
        
        # 计算朝向误差
        heading_diff = target_heading - robot_heading
        heading_diff = np.where(heading_diff > np.pi, heading_diff - 2*np.pi, heading_diff)
        heading_diff = np.where(heading_diff < -np.pi, heading_diff + 2*np.pi, heading_diff)
        
        # 达到判定（只看位置，不看朝向，与奖励计算保持一致）
        position_threshold = 0.3
        reached_all = distance_to_target < position_threshold  # 楼梯任务：只要到达位置即可
        
        # 计算期望速度命令（与平地navigation一致，简单P控制器）
        desired_vel_xy = np.clip(position_error * 1.0, -1.0, 1.0)
        desired_vel_xy = np.where(reached_all[:, np.newaxis], 0.0, desired_vel_xy)
        
        # 角速度命令：跟踪运动方向（从当前位置指向目标）
        # 与vbot_np保持一致的增益和上限，确保转向足够快
        desired_heading = np.arctan2(position_error[:, 1], position_error[:, 0])
        heading_to_movement = desired_heading - robot_heading
        heading_to_movement = np.where(heading_to_movement > np.pi, heading_to_movement - 2*np.pi, heading_to_movement)
        heading_to_movement = np.where(heading_to_movement < -np.pi, heading_to_movement + 2*np.pi, heading_to_movement)
        desired_yaw_rate = np.clip(heading_to_movement * 1.0, -1.0, 1.0)  # 增益和上限与vbot_np一致
        deadband_yaw = np.deg2rad(8)
        desired_yaw_rate = np.where(np.abs(heading_to_movement) < deadband_yaw, 0.0, desired_yaw_rate)
        desired_yaw_rate = np.where(reached_all, 0.0, desired_yaw_rate)
        
        if desired_yaw_rate.ndim > 1:
            desired_yaw_rate = desired_yaw_rate.flatten()
        
        velocity_commands = np.concatenate(
            [desired_vel_xy, desired_yaw_rate[:, np.newaxis]], axis=-1
        )
        
        # 归一化观测
        noisy_linvel = base_lin_vel * cfg.normalization.lin_vel
        noisy_gyro = gyro * cfg.normalization.ang_vel
        noisy_joint_angle = joint_pos_rel * cfg.normalization.dof_pos
        noisy_joint_vel = joint_vel * cfg.normalization.dof_vel
        command_normalized = velocity_commands * self.commands_scale
        last_actions = state.info["current_actions"]
        
        # 任务相关观测
        position_error_normalized = position_error / 5.0
        heading_error_normalized = heading_diff / np.pi
        distance_normalized = np.clip(distance_to_target / 5.0, 0, 1)
        reached_flag = reached_all.astype(np.float32)
        
        stop_ready = np.logical_and(
            reached_all,
            np.abs(gyro[:, 2]) < 5e-2
        )
        stop_ready_flag = stop_ready.astype(np.float32)
        
        obs = np.concatenate(
            [
                noisy_linvel,       # 3
                noisy_gyro,         # 3
                projected_gravity,  # 3
                noisy_joint_angle,  # 12
                noisy_joint_vel,    # 12
                last_actions,       # 12
                command_normalized, # 3
                position_error_normalized,  # 2
                heading_error_normalized[:, np.newaxis],  # 1 - 最终朝向误差（保留）
                distance_normalized[:, np.newaxis],  # 1
                reached_flag[:, np.newaxis],  # 1
                stop_ready_flag[:, np.newaxis],  # 1
            ],
            axis=-1,
        )
        assert obs.shape == (data.shape[0], 54)  # 54 + 1 = 55维
        
        # 更新目标标记和箭头
        self._update_target_marker(data, pose_commands)
        base_lin_vel_xy = base_lin_vel[:, :2]
        self._update_heading_arrows(data, root_pos, desired_vel_xy, base_lin_vel_xy)
        
        # 计算奖励
        reward = self._compute_reward(data, state.info, velocity_commands)
        
        # 计算终止条件
        terminated_state = self._compute_terminated(state)
        terminated = terminated_state.terminated
        
        state.obs = obs
        state.reward = reward
        state.terminated = terminated
        
        return state
    
    def _compute_terminated(self, state: NpEnvState) -> NpEnvState:
        """
        终止条件
        """
        data = state.data
        terminated = np.zeros(self._num_envs, dtype = bool)

        # 超时终止
        timeout = np.zeros(self._num_envs, dtype=bool)
        if self._cfg.max_episode_steps:
            timeout = state.info["steps"] >= self._cfg.max_episode_steps
            terminated = np.logical_or(terminated, timeout)
            
        # 基座接触地面终止（使用传感器）
        try:
            base_contact_value = self._model.get_sensor_value("base_contact", data)  # 基座接触传感器值（全零代表未接触）
            # 只打印前10条数据，如果条数小于10，打印全部
            # if hasattr(base_contact_value, '__len__'):
            #     display_data = base_contact_value[:10] if len(base_contact_value) > 10 else base_contact_value
            #     print(f"[base_contact] base_contact_value (first 10): {display_data}")
            # else:
            #     print(f"[base_contact] base_contact_value: {base_contact_value}")
            if base_contact_value.ndim == 0:
                base_contact = np.array([base_contact_value > 0.01], dtype=bool)
            elif base_contact_value.shape[0] != self._num_envs:
                base_contact = np.full(self._num_envs, base_contact_value.flatten()[0] > 0.01, dtype=bool)
            else:
                # base_contact = (base_contact_value > 0.01).flatten()[:self._num_envs]  # 数值大于0.01代表base已接触地面，可以触发终止条件了?
                # 对每个环境检查是否有任何接触点超过阈值
                base_contact = np.any(base_contact_value > 0.01, axis=1)[:self._num_envs]
        except Exception as e:
            print(f"[Warning] 无法读取base_contact传感器: {e}")
            base_contact = np.zeros(self._num_envs, dtype=bool)  
        # terminated = base_contact.copy()
        # 只打印前10条数据，如果条数小于10，打印全部
        if hasattr(base_contact, '__len__'):
            display_data = base_contact[:10] if len(base_contact) > 10 else base_contact
            print(f"[base_contact] base_contact (first 10): {display_data}")
        else:
            print(f"[base_contact] base_contact: {base_contact}")
        terminated = np.logical_or(terminated, base_contact)

        # 陀螺仪三轴加速度传感器数据异常终止
        gyro = self._model.get_sensor_value(self._cfg.sensor.base_gyro, data)
        abs_gyro_z = np.abs(gyro[:, 2])
        large_values = abs_gyro_z[abs_gyro_z > 10]  # 找出绝对值大于10的值
        if len(large_values) > 0:
            print(f"[Warning] abs_gyro_z contains large values: {large_values}")
            terminated = np.logical_or(terminated, abs_gyro_z > 10)

        # 调试：统计终止原因
        if terminated.any():
            timeout_count = int(timeout.sum())
            contact_count = int(base_contact.sum())
            gyro_count = int(large_values.sum())
            total = int(terminated.sum())
            if total > 0 and state.info["steps"][0] % 100 == 0:  # 每100步打印一次
                print(f"[termination] total={total} timeout={timeout_count} contact={contact_count} gyro={gyro_count}")
                pass
        
        return state.replace(terminated=terminated)
    
    def _compute_reward(self, data: mtx.SceneData, info: dict, velocity_commands: np.ndarray) -> np.ndarray:
        """
        速度跟踪奖励机制
        velocity_commands: [num_envs, 3] - (vx, vy, vyaw)
        """
        # 计算终止条件惩罚
        termination_penalty = np.zeros(self._num_envs, dtype=np.float32)
        
        # 检查DOF速度是否超限
        dof_vel = self.get_dof_vel(data)
        vel_max = np.abs(dof_vel).max(axis=1)
        vel_overflow = vel_max > self._cfg.max_dof_vel
        vel_extreme = (np.isnan(dof_vel).any(axis=1)) | (np.isinf(dof_vel).any(axis=1)) | (vel_max > 1e6)
        termination_penalty = np.where(vel_overflow | vel_extreme, -20.0, termination_penalty)
        
        # 机器人基座接触地面惩罚
        cquerys = self._model.get_contact_query(data)
        termination_check = cquerys.is_colliding(self.termination_contact)
        termination_check = termination_check.reshape((self._num_envs, self.num_termination_check))
        base_contact = termination_check.any(axis=1)
        termination_penalty = np.where(base_contact, -20.0, termination_penalty)
        
        # 侧翻惩罚
        pose = self._body.get_pose(data)
        root_quat = pose[:, 3:7]
        proj_g = self._compute_projected_gravity(root_quat)
        gxy = np.linalg.norm(proj_g[:, :2], axis=1)
        gz = proj_g[:, 2]
        tilt_angle = np.arctan2(gxy, np.abs(gz))
        side_flip_mask = tilt_angle > np.deg2rad(75)
        termination_penalty = np.where(side_flip_mask, -20.0, termination_penalty)
        print(f"[termination_penalty] side_flip_count={side_flip_mask.sum()}")
        
        # 线速度跟踪奖励
        base_lin_vel = self._model.get_sensor_value(self._cfg.sensor.base_linvel, data)
        lin_vel_error = np.sum(np.square(velocity_commands[:, :2] - base_lin_vel[:, :2]), axis=1)
        tracking_lin_vel = np.exp(-lin_vel_error / 0.25)  # tracking_sigma = 0.25
        
        # 角速度跟踪奖励 / 朝向偏差惩罚（混合策略）
        gyro = self._model.get_sensor_value(self._cfg.sensor.base_gyro, data)
        ang_vel_error = np.square(velocity_commands[:, 2] - gyro[:, 2])
        tracking_ang_vel = np.exp(-ang_vel_error / 0.25)
        
        # 获取机器人位置和朝向用于到达判定
        robot_position = pose[:, :2]
        robot_heading = self._get_heading_from_quat(root_quat)
        target_position = info["pose_commands"][:, :2]
        target_heading = info["pose_commands"][:, 2]
        position_error = target_position - robot_position
        distance_to_target = np.linalg.norm(position_error, axis=1)
        heading_diff = target_heading - robot_heading
        heading_diff = np.where(heading_diff > np.pi, heading_diff - 2*np.pi, heading_diff)
        heading_diff = np.where(heading_diff < -np.pi, heading_diff + 2*np.pi, heading_diff)
        
        position_threshold = 0.3  # 与目标位置的误差阈值
        reached_position = distance_to_target < position_threshold
        # 只打印前10条数据，如果条数小于10，打印全部
        if hasattr(reached_position, '__len__') and hasattr(distance_to_target, '__len__'):
            display_reached = reached_position[:10] if len(reached_position) > 10 else reached_position
            display_distance = distance_to_target[:10] if len(distance_to_target) > 10 else distance_to_target
            display_target = target_position[:10] if len(target_position) > 10 else target_position
            display_robot = robot_position[:10] if len(robot_position) > 10 else robot_position
            # print(f"[reached_position] reached_position (first 10)={display_reached}")
            print(f"[reached_position] distance_to_target (first 10)={display_distance}")
            # print(f"[reached_position] target_position (first 10)={display_target}")
            # print(f"[reached_position] robot_position (first 10)={display_robot}")
        else:
            # print(f"[reached_position] reached_position={reached_position}")
            print(f"[reached_position] distance_to_target={distance_to_target}")
            # print(f"[reached_position] target_position={target_position}")
            # print(f"[reached_position] robot_position={robot_position}")
        
        heading_threshold = np.deg2rad(15)
        reached_heading = np.abs(heading_diff) < heading_threshold
        reached_all = np.logical_and(reached_position, reached_heading)
        
        # 首次到达位置的一次性奖励
        info["ever_reached"] = info.get("ever_reached", np.zeros(self._num_envs, dtype=bool))
        first_time_reach = np.logical_and(reached_all, ~info["ever_reached"])
        info["ever_reached"] = np.logical_or(info["ever_reached"], reached_all)
        arrival_bonus = np.where(first_time_reach, 10.0, 0.0)  # 初次到达位置的一次性奖励
        
        # 距离接近奖励：激励靠近目标
        # 使用历史最近距离来计算进步
        if "min_distance" not in info:
            info["min_distance"] = distance_to_target.copy()
        distance_improvement = info["min_distance"] - distance_to_target
        info["min_distance"] = np.minimum(info["min_distance"], distance_to_target)
        approach_reward = np.clip(distance_improvement * 4.0, -1.0, 1.0)  # 每接近1米奖励5分
        
        # 姿态稳定性奖励（惩罚偏离正常站立姿态）
        # 正常站立时 projected_gravity ≈ [0, 0, -1]
        projected_gravity = self._compute_projected_gravity(root_quat)
        orientation_penalty = np.square(projected_gravity[:, 0]) + np.square(projected_gravity[:, 1]) + np.square(projected_gravity[:, 2] + 1.0)

        # 到达与停止判定（奖励加成）
        speed_xy = np.linalg.norm(np.clip(base_lin_vel[:, :2], -100, 100), axis=1)  # 计算X/Y轴线速度
        gyro_z_clipped = np.clip(gyro[:, 2], -20, 20)  # 限制Z轴角速度在[-20, 20]范围内
        zero_ang_mask = np.abs(gyro_z_clipped) < 0.05  # 获取陀螺仪Z轴的角速度（所有行的第2列:z-axis），放宽到0.05 rad/s ≈ 2.86°/s
        zero_ang_bonus = np.where(np.logical_and(reached_all, zero_ang_mask), 6.0, 0.0)  # 到达后：零角速度 bonus
        # 防止指数溢出：限制指数参数的最大值
        speed_xy_calc = np.clip((speed_xy / 0.2)**2, 0, 100)  # 限制最小值为0，最大值为100
        print("speed_xy 统计信息:")
        print(f"  最小值: {np.min(speed_xy)}")
        print(f"  最大值: {np.max(speed_xy)}")
        # print(f"  绝对值最大值: {np.max(np.abs(speed_xy))}")
        gyro_z_calc = np.clip((np.abs(gyro_z_clipped) / 0.1)**4, 0, 100)  # 限制最小值为0，最大值为100
        print("gyro[:, 2] 统计信息:")
        print(f"  最小值: {np.min(gyro[:, 2])}")
        print(f"  最大值: {np.max(gyro[:, 2])}")
        # print(f"  绝对值最大值: {np.max(np.abs(gyro[:, 2]))}")
        stop_base = 2 * (0.8 * np.exp(-speed_xy_calc) + 1.2 * np.exp(-gyro_z_calc))  # 到达后：停止奖励基础
        stop_bonus = np.where(reached_all, stop_base + zero_ang_bonus, 0.0)  # 到达后：停止奖励（包含停止奖励基础+零角速度 bonus）
        
        # Z轴线速度惩罚（应用归一化避免溢出）
        lin_vel_z_penalty = np.square(np.clip(base_lin_vel[:, 2], -100, 100) * self._cfg.normalization.lin_vel)
        
        # XY轴角速度惩罚（应用归一化避免溢出）
        ang_vel_xy_penalty = np.sum(np.square(np.clip(gyro[:, :2], -20, 20) * self._cfg.normalization.ang_vel), axis=1)
        
        # 力矩惩罚
        torque_penalty = np.sum(np.square(data.actuator_ctrls), axis=1)
        
        # 关节速度惩罚（应用归一化避免溢出）
        joint_vel = self.get_dof_vel(data)
        dof_vel_penalty = np.sum(np.square(np.clip(joint_vel, -self._cfg.max_dof_vel, self._cfg.max_dof_vel) * self._cfg.normalization.dof_vel), axis=1)
        
        # 动作变化惩罚
        action_diff = info["current_actions"] - info["last_actions"]
        action_rate_penalty = np.sum(np.square(action_diff), axis=1)
        
        # 综合奖励
        # 到达后：停止所有正向奖励，只保留停止奖励和惩罚项
        reward = np.where(
            reached_all,
            # 到达后：只有停止奖励和惩罚
            (
                stop_bonus
                + arrival_bonus
                - 2.0 * lin_vel_z_penalty
                - 0.05 * ang_vel_xy_penalty
                - 0.0 * orientation_penalty
                # - 0.00001 * orientation_penalty
                - 0.00001 * torque_penalty
                - 0.0 * dof_vel_penalty
                - 0.001 * action_rate_penalty
                + termination_penalty  # 终止条件惩罚
            ),
            # 未到达：正常奖励
            (
                1.5 * tracking_lin_vel    # 提高X/Y轴线速度跟踪权重
                + 0.3 * tracking_ang_vel  # 降低角速度权重
                + approach_reward         # 接近奖励
                - 2.0 * lin_vel_z_penalty  # Z轴线速度惩罚
                - 0.05 * ang_vel_xy_penalty  # XY轴角速度惩罚
                - 0.0 * orientation_penalty  # 姿态稳定性惩罚
                - 0.00001 * torque_penalty  # 力矩惩罚（惩罚大力矩）
                - 0.0 * dof_vel_penalty  # 关节速度惩罚
                # - 0.001 * action_rate_penalty  # 动作变化惩罚（惩罚动作突变）
                - 0.0001 * action_rate_penalty  # 动作变化惩罚（惩罚动作突变）
                + termination_penalty  # 终止条件惩罚
            )
        )
        
        # 调试打印：到达一次性奖励、停止奖励、零角奖励、角速度
        try:
            arrival_count = int((arrival_bonus > 0).sum())
            stop_count = int((stop_bonus > 0).sum())
            zero_ang_count = int((zero_ang_bonus > 0).sum())
            gyro_z_mean = float(np.mean(abs(gyro_z_clipped)))
            total_envs = self._num_envs
            
            # 额外统计：环境状态分布
            reached_pos_count = int(reached_position.sum())
            reached_head_count = int(reached_heading.sum())
            
            # 添加NaN检查和处理
            if np.any(np.isnan(distance_to_target)):
                print(f"[Warning] distance_to_target contains NaN values, replacing with large values")
                distance_to_target = np.where(np.isnan(distance_to_target), 1000.0, distance_to_target)  # 用大值替换NaN
            
            if np.any(np.isnan(heading_diff)):
                print(f"[Warning] heading_diff contains NaN values, replacing with zero")
                heading_diff = np.where(np.isnan(heading_diff), 0.0, heading_diff)  # 用0替换NaN
            
            if np.any(np.isnan(gyro_z_clipped)):
                print(f"[Warning] gyro[:, 2] contains NaN values, replacing with zero")
                gyro_z_clipped = np.where(np.isnan(gyro_z_clipped), 0.0, gyro_z_clipped)  # 用0替换NaN
            
            if np.any(np.isnan(reward)):
                print(f"[Warning] reward contains NaN values, replacing with zero")
                reward = np.where(np.isnan(reward), 0.0, reward)  # 用0替换NaN
            
            dist_mean = float(np.mean(distance_to_target))
            heading_err_mean = float(np.rad2deg(np.mean(np.abs(heading_diff))))
            reward_mean = float(np.mean(reward))
            
            print(f"[reward_debug] arrival={arrival_count}/{total_envs} stop={stop_count}/{total_envs} zero_ang={zero_ang_count}/{total_envs}")
            print(f"[position] reached_pos={reached_pos_count}/{total_envs} dist_mean={dist_mean:.2f} m")
            print(f"[heading] reached_head={reached_head_count}/{total_envs} heading_err_mean={heading_err_mean:.1f}°")
            print(f"[velocity] gyro_z_mean={gyro_z_mean:.4f} rad/s")
            print(f"[orientation] orientation_penalty_mean={float(np.mean(orientation_penalty))}")
            print(f"[reward] reward={reward_mean}")
        except Exception:
            pass
        return reward

    def reset(self, data: mtx.SceneData, done: np.ndarray = None) -> tuple[np.ndarray, dict]:
        cfg: VBotSection001EnvCfg = self._cfg
        num_envs = data.shape[0]
        
        # 在高台中央小范围内随机生成位置
        # X, Y: 在spawn_center周围 ±spawn_range 范围内随机
        random_xy = np.random.uniform(
            low=-self.spawn_range,
            high=self.spawn_range,
            size=(num_envs, 2)
        )
        robot_init_xy = self.spawn_center[:2] + random_xy  # [num_envs, 2]
        terrain_heights = np.full(num_envs, self.spawn_center[2], dtype=np.float32)  # 使用配置的高度
        
        # 组合XYZ坐标
        robot_init_pos = robot_init_xy  # [num_envs, 2]
        robot_init_xyz = np.column_stack([robot_init_xy, terrain_heights])  # [num_envs, 3]
        
        # 初始化DOF位置和速度
        dof_pos = np.tile(self._init_dof_pos, (num_envs, 1))
        dof_vel = np.tile(self._init_dof_vel, (num_envs, 1))
        
        # 设置 base 的 XYZ位置（DOF 3-5）
        dof_pos[:, 3:6] = robot_init_xyz  # [x, y, z] 随机生成的位置
        
        # 设置目标位置和朝向
        # target_offset = np.random.uniform(
        #     low=cfg.commands.pose_command_range[:2],
        #     high=cfg.commands.pose_command_range[3:5],
        #     size=(num_envs, 2)
        # )
        # # 计算目标位置
        # target_positions = robot_init_pos + target_offset
        # 目标位置为中心灯笼所在位置：获取goal参数
        goal_pos = self.get_goal_pos(data)
        # 检查goal_pos是否有效，如果无效则使用默认目标位置
        if goal_pos is None or np.any(np.isnan(goal_pos)) or np.any(np.isinf(goal_pos)):
            # 使用默认目标位置（场景中心附近）
            default_target_range = 0.2  # 默认目标范围半径
            target_positions = np.random.uniform(
                low=-default_target_range,
                high=default_target_range,
                size=(num_envs, 2)
            )
            print(f"[Warning] Goal position invalid, using default targets around origin")
        else:
            # 确保goal_pos的XY坐标有效
            goal_xy = goal_pos[:, :2]
            default_target_range = 2.0
            # print(f"[Info] Goal position is valid, XY coordinates: {goal_xy}")
            if np.any(np.isnan(goal_xy)) or np.any(np.isinf(goal_xy)):
                # 如果goal_xy包含无效值，使用默认值
                target_positions = np.random.uniform(
                    low=-default_target_range,
                    high=default_target_range,
                    size=(num_envs, 2)
                )
                print(f"[Warning] Goal XY coordinates contain invalid values, using default targets")
            else:
                # 使用goal位置作为目标范围中心
                target_positions = np.random.uniform(
                    low=np.abs(goal_xy) - 0.0,
                    high=np.abs(goal_xy) + 0.0,
                    size=(num_envs, 2)
                )
        # print("Target Positions:", target_positions)

        # 计算目标朝向
        target_headings = np.random.uniform(
            low=cfg.commands.pose_command_range[2],
            high=cfg.commands.pose_command_range[5],
            size=(num_envs, 1)
        )
        # print("Target Headings:", target_headings)
        
        pose_commands = np.concatenate([target_positions, target_headings], axis=1)
        
        # 归一化base的四元数（DOF 6-9）
        for env_idx in range(num_envs):
            quat = dof_pos[env_idx, self._base_quat_start:self._base_quat_end]
            quat_norm = np.linalg.norm(quat)
            if quat_norm > 1e-6:
                dof_pos[env_idx, self._base_quat_start:self._base_quat_end] = quat / quat_norm
            else:
                dof_pos[env_idx, self._base_quat_start:self._base_quat_end] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
            
            # 归一化箭头的四元数（如果箭头body存在）
            if self._robot_arrow_body is not None:
                robot_arrow_quat = dof_pos[env_idx, self._robot_arrow_dof_start+3:self._robot_arrow_dof_end]
                quat_norm = np.linalg.norm(robot_arrow_quat)
                if quat_norm > 1e-6:
                    dof_pos[env_idx, self._robot_arrow_dof_start+3:self._robot_arrow_dof_end] = robot_arrow_quat / quat_norm
                else:
                    dof_pos[env_idx, self._robot_arrow_dof_start+3:self._robot_arrow_dof_end] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
                
                desired_arrow_quat = dof_pos[env_idx, self._desired_arrow_dof_start+3:self._desired_arrow_dof_end]
                quat_norm = np.linalg.norm(desired_arrow_quat)
                if quat_norm > 1e-6:
                    dof_pos[env_idx, self._desired_arrow_dof_start+3:self._desired_arrow_dof_end] = desired_arrow_quat / quat_norm
                else:
                    dof_pos[env_idx, self._desired_arrow_dof_start+3:self._desired_arrow_dof_end] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        
        data.reset(self._model)
        data.set_dof_vel(dof_vel)
        data.set_dof_pos(dof_pos, self._model)
        self._model.forward_kinematic(data)
        
        # 更新目标位置标记
        self._update_target_marker(data, pose_commands)
        
        # 获取根节点状态
        # 根节点位置、四元数和线速度
        root_pos, root_quat, root_vel = self._extract_root_state(data)
        
        # 关节状态
        joint_pos = self.get_dof_pos(data)
        joint_vel = self.get_dof_vel(data)
        joint_pos_rel = joint_pos - self.default_angles
        
        # 传感器数据
        base_lin_vel = root_vel[:, :3]
        gyro = self._model.get_sensor_value(self._cfg.sensor.base_gyro, data)
        projected_gravity = self._compute_projected_gravity(root_quat)
        
        # 计算速度命令
        robot_position = root_pos[:, :2]
        robot_heading = self._get_heading_from_quat(root_quat)
        target_position = pose_commands[:, :2]
        target_heading = pose_commands[:, 2]
        
        position_error = target_position - robot_position
        distance_to_target = np.linalg.norm(position_error, axis=1)
        
        position_threshold = 0.3
        reached_all = distance_to_target < position_threshold  # 楼梯任务：只看位置
        
        # 计算期望速度
        desired_vel_xy = np.clip(position_error * 1.0, -1.0, 1.0)
        desired_vel_xy = np.where(reached_all[:, np.newaxis], 0.0, desired_vel_xy)
        
        base_lin_vel_xy = base_lin_vel[:, :2]
        self._update_heading_arrows(data, root_pos, desired_vel_xy, base_lin_vel_xy)
        
        heading_diff = target_heading - robot_heading
        heading_diff = np.where(heading_diff > np.pi, heading_diff - 2*np.pi, heading_diff)
        heading_diff = np.where(heading_diff < -np.pi, heading_diff + 2*np.pi, heading_diff)
        
        # ===== 与reset一致：角速度跟踪运动方向 =====
        # 计算期望的运动方向（从update_state中复制）
        desired_heading = np.arctan2(position_error[:, 1], position_error[:, 0])
        heading_to_movement = desired_heading - robot_heading
        heading_to_movement = np.where(heading_to_movement > np.pi, heading_to_movement - 2*np.pi, heading_to_movement)
        heading_to_movement = np.where(heading_to_movement < -np.pi, heading_to_movement + 2*np.pi, heading_to_movement)
        desired_yaw_rate = np.clip(heading_to_movement * 1.0, -1.0, 1.0)
        
        # 添加死区，与update_state保持一致
        deadband_yaw = np.deg2rad(8)
        desired_yaw_rate = np.where(np.abs(heading_to_movement) < deadband_yaw, 0.0, desired_yaw_rate)
        
        desired_yaw_rate = np.where(reached_all, 0.0, desired_yaw_rate)
        desired_vel_xy = np.where(reached_all[:, np.newaxis], 0.0, desired_vel_xy)
        
        if desired_yaw_rate.ndim > 1:
            desired_yaw_rate = desired_yaw_rate.flatten()
        
        velocity_commands = np.concatenate(
            [desired_vel_xy, desired_yaw_rate[:, np.newaxis]], axis=-1
        )
        
        # 归一化观测
        noisy_linvel = base_lin_vel * self._cfg.normalization.lin_vel
        noisy_gyro = gyro * self._cfg.normalization.ang_vel
        noisy_joint_angle = joint_pos_rel * self._cfg.normalization.dof_pos
        noisy_joint_vel = joint_vel * self._cfg.normalization.dof_vel
        command_normalized = velocity_commands * self.commands_scale
        last_actions = np.zeros((num_envs, self._num_action), dtype=np.float32)
        
        # 任务相关观测
        position_error_normalized = position_error / 5.0
        heading_error_normalized = heading_diff / np.pi
        distance_normalized = np.clip(distance_to_target / 5.0, 0, 1)
        reached_flag = reached_all.astype(np.float32)
        
        stop_ready = np.logical_and(
            reached_all,
            np.abs(gyro[:, 2]) < 5e-2
        )
        stop_ready_flag = stop_ready.astype(np.float32)

        obs = np.concatenate(
            [
                noisy_linvel,       # 3
                noisy_gyro,         # 3
                projected_gravity,  # 3
                noisy_joint_angle,  # 12
                noisy_joint_vel,    # 12
                last_actions,       # 12
                command_normalized, # 3
                position_error_normalized,  # 2
                heading_error_normalized[:, np.newaxis],  # 1 - 最终朝向误差（保留）
                distance_normalized[:, np.newaxis],  # 1
                reached_flag[:, np.newaxis],  # 1
                stop_ready_flag[:, np.newaxis],  # 1
            ],
            axis=-1,
        )
        # print(f"obs.shape:{obs.shape}")
        assert obs.shape == (num_envs, 54)  # 54 + 1 = 55维
        
        # Info信息（包含目标位置命令、最后动作、步数、当前动作、过滤后动作、是否首次到达、最小距离）
        info = {
            "pose_commands": pose_commands,
            "last_actions": np.zeros((num_envs, self._num_action), dtype=np.float32),
            "steps": np.zeros(num_envs, dtype=np.int32),
            "current_actions": np.zeros((num_envs, self._num_action), dtype=np.float32),
            "filtered_actions": np.zeros((num_envs, self._num_action), dtype=np.float32),  # 过滤后的动作（申明此字段也说明开启了动作滤波）
            "ever_reached": np.zeros(num_envs, dtype=bool),
            "min_distance": distance_to_target.copy(),  # 统一使用min_distance机制
            # 新增：与locomotion一致的字段
            "last_dof_vel": np.zeros((num_envs, self._num_action), dtype=np.float32),  # 上一步关节速度
            "contacts": np.zeros((num_envs, self.num_foot_check), dtype=np.bool_),  # 足部接触状态
        }
        
        return obs, info
