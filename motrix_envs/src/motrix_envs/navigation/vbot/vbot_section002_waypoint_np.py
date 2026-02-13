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

from .cfg import VBotSection002WaypointEnvCfg


@registry.env("vbot_navigation_section002_waypoint", "np")
class VBotSection002WaypointEnv(NpEnv):
    """
    VBot在Section002地形上的导航任务
    继承自NpEnv，使用VBotSection002WaypointEnvCfg配置
    """
    _cfg: VBotSection002WaypointEnvCfg
    
    def __init__(self, cfg: VBotSection002WaypointEnvCfg, num_envs: int = 1):
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
                
        # 初始化路径点相关变量
        self._init_waypoint_system()
        
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
        self.action_filter_alpha = 0.35  # 平衡滤波强度，既减少抖动又保持响应性
    
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
    
    def _init_waypoint_system(self):
        """初始化路径点系统"""
        # 从配置读取路径点信息
        self.way_points = self._cfg.asset.way_point_names if hasattr(self._cfg.asset, 'way_point_names') else []
        self.current_waypoint_index = np.zeros(self._num_envs, dtype=np.int32)  # per-env当前目标路径点索引
        self.visited_waypoints = [set() for _ in range(self._num_envs)]  # per-env已访问的路径点集合
        
        # 按index字段排序路径点
        self.way_points.sort(key=lambda wp: wp.get('index', 999))
        
        # 初始化路径点接触检测
        self._init_waypoint_contact_detection()
        
        # --- Brief visible celebration action state (per-env) ---
        num_actuators = self._model.num_actuators
        self._celebration_active = np.zeros(self._num_envs, dtype=bool)
        self._celebration_step = np.zeros(self._num_envs, dtype=np.int32)
        self._celebration_duration = 60  # About 1 second at 60Hz
        self._celebration_target_pos = np.zeros((self._num_envs, num_actuators), dtype=np.float32)
        self._celebration_start_pos = np.zeros((self._num_envs, num_actuators), dtype=np.float32)

        print(f"[Waypoint] Initialized {len(self.way_points)} waypoints (sorted by index)")
        for i, wp in enumerate(self.way_points):
            print(f"  [index={wp.get('index', 'N/A')}] {wp['name']} (action: {wp['action']})")
    
    def _init_waypoint_contact_detection(self):
        """初始化路径点接触检测传感器"""
        self.waypoint_contact_sensors = []
        
        for wp_info in self.way_points:
            wp_name = wp_info['name']
            # 传感器名称格式: waypoint_X-Y_body_contact (与XML中定义一致)
            sensor_name = f"{wp_name}_contact"
            print(f"[Waypoint] Checking sensor: {sensor_name}")
            try:
                # 检查传感器是否存在
                # 创建临时数据对象用于传感器检查
                temp_data = mtx.SceneData(self._model)
                sensor_value = self._model.get_sensor_value(sensor_name, temp_data)
                self.waypoint_contact_sensors.append({
                    'name': wp_name,
                    'sensor_name': sensor_name,
                    'requires_action': wp_info['action'],
                    'visited': np.zeros(self._num_envs, dtype=bool)
                })
                print(f"[Waypoint] Registered contact sensor for {wp_name}")
            except Exception as e:
                print(f"[Warning] Failed to register contact sensor for {wp_name}: {e}")
                # 创建虚拟检测逻辑
                self.waypoint_contact_sensors.append({
                    'name': wp_name,
                    'sensor_name': None,  # 标记为使用位置检测
                    'requires_action': wp_info['action'],
                    'visited': np.zeros(self._num_envs, dtype=bool)
                })
    
    def _check_waypoint_reached(self, data: mtx.SceneData, root_pos: np.ndarray) -> list:
        """检查是否到达路径点，返回已到达的路径点列表（每个包含per-env mask）"""
        reached_waypoints = []
        num_envs = root_pos.shape[0]
        
        for i, wp_sensor in enumerate(self.waypoint_contact_sensors):
            wp_name = wp_sensor['name']
            already_visited = wp_sensor['visited']  # np.ndarray(bool, num_envs)
            
            # 如果所有env都已经访问过，跳过
            if np.all(already_visited):
                continue
            
            reached = np.zeros(num_envs, dtype=bool)
            
            # 方法1：使用接触传感器检测
            if wp_sensor['sensor_name'] is not None:
                try:
                    contact_value = self._model.get_sensor_value(wp_sensor['sensor_name'], data)
                    if isinstance(contact_value, np.ndarray):
                        if contact_value.ndim == 1:
                            reached = contact_value > 0.1
                        else:
                            reached = np.any(contact_value > 0.1, axis=1)
                        reached = reached.flatten()[:num_envs]
                    else:
                        reached[:] = contact_value > 0.1
                except Exception:
                    pass
            
            # 方法2：位置距离检测（备用方案，仅对尚未通过传感器检测到的env）
            need_position_check = ~reached & ~already_visited
            if np.any(need_position_check):
                try:
                    wp_body = self._model.get_body(wp_name)
                    if wp_body is not None:
                        wp_pos = wp_body.get_pose(data)[:, :3]  # [num_envs, 3]
                        distance = np.linalg.norm(root_pos - wp_pos, axis=1)
                        reached = reached | (distance < 0.5)
                except Exception as e:
                    print(f"[Warning] Cannot get position for waypoint {wp_name}: {e}")
                    continue
            
            # 只保留新到达的env（排除已访问的）
            newly_reached = reached & ~already_visited
            
            if np.any(newly_reached):
                # 检查是否按顺序到达（只有连续的路径点才登记为已访问）
                ordered_reached = np.zeros(num_envs, dtype=bool)
                for env_idx in range(num_envs):
                    if newly_reached[env_idx]:
                        # 获取当前环境已访问的路径点index
                        visited_indices = set()
                        for visited_wp_name in self.visited_waypoints[env_idx]:
                            for wp in self.way_points:
                                if wp['name'] == visited_wp_name:
                                    visited_indices.add(wp['index'])
                                    break
                        
                        # 获取当前路径点的index
                        current_index = None
                        for wp in self.way_points:
                            if wp['name'] == wp_name:
                                current_index = wp['index']
                                break
                        
                        # 检查是否是下一个预期的路径点（按顺序）
                        if current_index is not None:
                            expected_next_index = len(visited_indices)  # 应该是下一个连续的index
                            if current_index == expected_next_index:
                                ordered_reached[env_idx] = True
                                self.visited_waypoints[env_idx].add(wp_name)
                                wp_sensor['visited'][env_idx] = True
                                # print(f"[Waypoint] Env {env_idx}: Registered waypoint {wp_name} (index={current_index}) as visited (in order)")
                            else:
                                # print(f"[Waypoint] Env {env_idx}: Ignored waypoint {wp_name} (index={current_index}), expected index={expected_next_index}")
                                pass
                
                # 只处理按顺序到达的路径点
                if np.any(ordered_reached):
                    reached_waypoints.append({
                    'index': i,
                    'name': wp_name,
                    'requires_action': wp_sensor['requires_action'],
                    'env_mask': ordered_reached.copy(),
                })
        
        return reached_waypoints
    
    # ===== Waypoints that trigger brief celebration =====
    _CELEBRATION_WAYPOINTS = {"wp_1-4_body", "wp_2-1_body", "wp_3-1_body"}
    
    # Celebration pose: front legs raised, rear legs crouched for stability
    _CELEBRATION_POSE = {
        # Front legs: raise up with bent knees
        "FR_hip_joint": -0.1, "FR_thigh_joint": 0.3, "FR_calf_joint": -0.8,
        "FL_hip_joint": 0.1,  "FL_thigh_joint": 0.3, "FL_calf_joint": -0.8,
        # Rear legs: crouch for stability
        "RR_hip_joint": -0.1, "RR_thigh_joint": 1.2, "RR_calf_joint": -2.0,
        "RL_hip_joint": 0.1,  "RL_thigh_joint": 1.2, "RL_calf_joint": -2.0,
    }

    def _trigger_celebration(self, waypoint_name: str, env_mask: np.ndarray):
        """Trigger a brief visible celebration with front leg raise."""
        if not np.any(env_mask):
            return
        
        # Only trigger celebration for designated waypoints
        if waypoint_name not in self._CELEBRATION_WAYPOINTS:
            return
        
        # Get current joint positions as start
        current_pos = self.get_dof_pos(self._state.data)
        self._celebration_start_pos[env_mask] = current_pos[env_mask]
        
        # Build target pose
        target_pos = current_pos.copy()
        for i in range(self._model.num_actuators):
            for joint_name, angle in self._CELEBRATION_POSE.items():
                if joint_name in self._model.actuator_names[i]:
                    target_pos[env_mask, i] = angle
                    break
        self._celebration_target_pos[env_mask] = target_pos[env_mask]
        
        self._celebration_active[env_mask] = True
        self._celebration_step[env_mask] = 0
        print(f"[Celebration] Front leg raise at {waypoint_name} for {int(env_mask.sum())} envs")

    def _get_celebration_override(self) -> tuple[np.ndarray | None, np.ndarray]:
        """Return (override_actions, active_mask) for celebration animation.
        
        Uses smooth interpolation: raise up in first half, return in second half.
        """
        if not np.any(self._celebration_active):
            return None, self._celebration_active
        
        active = self._celebration_active.copy()
        num_envs = len(active)
        override_actions = np.zeros((num_envs, self._model.num_actuators), dtype=np.float32)
        action_scale = self._cfg.control_config.action_scale
        
        # Advance step counter
        self._celebration_step[active] += 1
        
        # Calculate interpolation: 0->1 in first half (raise), 1->0 in second half (return)
        half_duration = self._celebration_duration // 2
        step = self._celebration_step[active]
        
        # Alpha goes 0->1->0 (raise then lower)
        alpha = np.where(
            step <= half_duration,
            step / half_duration,  # Rising phase
            2.0 - step / half_duration  # Falling phase
        )
        alpha = np.clip(alpha, 0.0, 1.0)
        
        # Interpolate between start and target pose
        interp_pos = (
            self._celebration_start_pos[active] +
            alpha[:, np.newaxis] * (self._celebration_target_pos[active] - self._celebration_start_pos[active])
        )
        
        # Convert to normalized RL actions
        celebration_actions = (interp_pos - self.default_angles) / action_scale
        override_actions[active] = np.clip(celebration_actions, -1.0, 1.0)
        
        # Check completion
        done = self._celebration_step >= self._celebration_duration
        if np.any(done):
            self._celebration_active[done] = False
            self._celebration_step[done] = 0
        
        return override_actions[active], active
    
    def _get_first_waypoint_pos(self, data: mtx.SceneData) -> np.ndarray:
        """获取第一个路径点的坐标位置"""
        # 从配置中查找index为0的路径点
        first_waypoint = None
        for wp in self.way_points:
            if wp.get('index', -1) == 0:
                first_waypoint = wp
                break
        
        if first_waypoint is None:
            print("[Warning] No waypoint with index 0 found, falling back to get_goal_pos")
            return self.get_goal_pos(data)
        
        # 获取路径点body名称
        waypoint_body_name = first_waypoint['name']
        
        try:
            # 获取路径点body的坐标
            waypoint_body = self._model.get_body(waypoint_body_name)
            if waypoint_body is not None:
                # 获取body的位置坐标 [x, y, z]
                waypoint_pos = waypoint_body.get_pose(data)[:, :3]  # 只取位置部分
                # print(f"[Waypoint] First waypoint '{waypoint_body_name}' position: {waypoint_pos[0]} (first 10)={waypoint_pos[:10] if len(waypoint_pos) > 10 else waypoint_pos}")
                return waypoint_pos
            else:
                # print(f"[Warning] Waypoint body '{waypoint_body_name}' not found, falling back to get_goal_pos")
                return self.get_goal_pos(data)
        except Exception as e:
            # print(f"[Warning] Failed to get position for waypoint '{waypoint_body_name}': {e}, falling back to get_goal_pos")
            return self.get_goal_pos(data)
    
    def _update_goal_to_next_waypoint(self, current_goal: np.ndarray, data: mtx.SceneData, env_idx: int = 0) -> np.ndarray:
        """更新目标位置到下一个未访问的路径点或最终目标（按index字段顺序, per-env）"""
        # 按照index字段对路径点进行排序
        sorted_waypoints = sorted(self.way_points, key=lambda wp: wp.get('index', 999))
        
        # 寻找下一个未访问的路径点（按index顺序）
        for wp_info in sorted_waypoints:
            # 跳过该env已访问的路径点
            if wp_info['name'] in self.visited_waypoints[env_idx]:
                # print(f"[DEBUG] Skipping already visited waypoint: {wp_info['name']} (index={wp_info.get('index', 'N/A')})")
                continue
            # print(f"[DEBUG] Found next unvisited waypoint: {wp_info['name']} (index={wp_info.get('index', 'N/A')})")
                
            # 获取该路径点的位置
            try:
                waypoint_body_name = wp_info['name']
                waypoint_body = self._model.get_body(waypoint_body_name)
                if waypoint_body is not None:
                    # 通过body名称推导对应的geom名称来获取位置
                    # body名称: waypoint_X-Y_body -> geom名称: waypoint_X-Y_trigger
                    geom_suffix = waypoint_body_name.replace('_body', '_trigger')
                    geom = self._model.get_geom(geom_suffix)
                    if geom is not None:
                        waypoint_pos = geom.get_pose(data)[:, :3]
                    else:
                        # 如果找不到geom，使用body的位置
                        waypoint_pos = waypoint_body.get_pose(data)[:, :3]
                    new_goal = waypoint_pos[env_idx].copy()  # 取对应环境的数据
                    # print(f"[Waypoint] Updated goal to waypoint {wp_info['name']} (index={wp_info.get('index', 'N/A')}) at {new_goal[:2]}")
                    return new_goal
                else:
                    print(f"[Warning] Waypoint body '{waypoint_body_name}' not found")
                    continue
            except Exception as e:
                print(f"[Warning] Cannot get position for waypoint {wp_info['name']}: {e}")
                continue
        
        # 如果没有更多路径点，返回最终目标
        # print("[Waypoint] All waypoints visited, returning to final goal")
        return current_goal
    
    def _init_contact_geometry(self):
        """初始化接触检测所需的几何体索引"""
        self._init_termination_contact()
        self._init_foot_contact()
    
    def _init_termination_contact(self):
        """初始化终止接触检测：基座geom与地面geom的碰撞"""
        termination_contact_names = self._cfg.asset.terminate_after_contacts_on
        
        # 获取所有地面geom（遍历所有geom，找到包含地面子树前缀的）
        # 从配置文件读取地面子树前缀列表
        ground_geoms = []
        ground_prefixes = self._cfg.asset.ground_subtree_prefixes  # 从配置读取地面前缀列表
        
        for geom_name in self._model.geom_names:
            if geom_name is not None:
                # 检查是否匹配任何一个地面前缀
                for prefix in ground_prefixes:
                    if (prefix in geom_name) and (self._cfg.asset.ground_name in geom_name.lower()):
                        try:
                            geom_idx = self._model.get_geom_index(geom_name)
                            ground_geoms.append(geom_idx)
                            break  # 找到匹配就跳出内层循环
                        except Exception:
                            continue
        print(f"[Info] 地面前缀匹配结果: {ground_geoms}")

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
            print(f"[Info] 检测的地面前缀: {ground_prefixes}")
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
        
        # Override RL actions during celebration animation
        override_actions, active_mask = self._get_celebration_override()
        if override_actions is not None and np.any(active_mask):
            state.info["filtered_actions"][active_mask] = override_actions
        
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
        
        # 下坡地形自适应PD控制器
        # 检测是否处于下坡状态
        try:
            gravity_projection = self._model.get_sensor_value("gravity_projection", data)
            slope_angle = np.arctan2(
                np.linalg.norm(gravity_projection[:, :2], axis=1),
                np.abs(gravity_projection[:, 2])
            )
            # 下坡检测：更早识别下坡状态（降低阈值）
            is_downhill = np.logical_and(slope_angle < -np.deg2rad(5), slope_angle > -np.deg2rad(45))
        except:
            is_downhill = np.zeros(data.shape[0], dtype=bool)
        
        # 根据地形调整控制器参数
        # 平地/上坡：较强参数以支持翻越
        kp_fl_fr_normal = 85.0     # 提高前腿增益支持攀爬
        kp_rl_rr_normal = 100.0    # 提高后腿增益增强推进力
        kv_normal = 6.0            # 降低阻尼允许更积极的动作
        
        # 下坡：大幅降低增益提高稳定性，防止滑倒
        kp_fl_fr_downhill = 65.0   # 下坡时前腿增益显著降低（从75→65）
        kp_rl_rr_downhill = 80.0   # 下坡时后腿增益显著降低（从90→80）
        kv_downhill = 8.5          # 下坡时增大阻尼（从7→8.5）提供更多阻尼力
        
        # 混合参数
        kp_fl_fr = np.where(is_downhill, kp_fl_fr_downhill, kp_fl_fr_normal)
        kp_rl_rr = np.where(is_downhill, kp_rl_rr_downhill, kp_rl_rr_normal)
        kv = np.where(is_downhill, kv_downhill, kv_normal)
        
        pos_error = target_pos - current_pos
        
        # 分别计算前腿和后腿的力矩
        torques = np.zeros_like(pos_error)
        # 前腿 (FR, FL): 索引 0-2, 3-5
        torques[:, 0:3] = kp_fl_fr[:, np.newaxis] * pos_error[:, 0:3] - kv[:, np.newaxis] * current_vel[:, 0:3]  # FR
        torques[:, 3:6] = kp_fl_fr[:, np.newaxis] * pos_error[:, 3:6] - kv[:, np.newaxis] * current_vel[:, 3:6]  # FL
        # 后腿 (RR, RL): 索引 6-8, 9-11
        torques[:, 6:9] = kp_rl_rr[:, np.newaxis] * pos_error[:, 6:9] - kv[:, np.newaxis] * current_vel[:, 6:9]   # RR
        torques[:, 9:12] = kp_rl_rr[:, np.newaxis] * pos_error[:, 9:12] - kv[:, np.newaxis] * current_vel[:, 9:12] # RL
        
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
        
        # ===== 路径点系统核心逻辑 =====
        num_envs = root_pos.shape[0]
        # 检查是否到达路径点
        reached_waypoints = self._check_waypoint_reached(data, root_pos)
        
        # 如果到达了需要特殊动作的路径点，触发庆祝（仅作标记，不影响RL控制）
        for wp in reached_waypoints:
            env_mask = wp['env_mask']
            if wp['requires_action']:
                # 触发简化的庆祝（不影响RL控制）
                self._trigger_celebration(wp['name'], wp['env_mask'])
                
        # 如果到达了路径点，per-env更新目标位置
        if len(reached_waypoints) > 0:
            for env_idx in range(num_envs):
                any_reached = any(wp['env_mask'][env_idx] for wp in reached_waypoints)
                if any_reached:
                    new_goal_pos = self._update_goal_to_next_waypoint(
                        np.array([target_position[env_idx, 0], target_position[env_idx, 1], 0.0]),
                        data,
                        env_idx,
                    )
                    pose_commands[env_idx, 0] = new_goal_pos[0]  # x
                    pose_commands[env_idx, 1] = new_goal_pos[1]  # y
            # 更新state.info中的目标命令
            state.info["pose_commands"] = pose_commands
            
            # 更新目标位置变量
            target_position = pose_commands[:, :2]
        
        
        # 计算位置误差
        position_error = target_position - robot_position  # 位置误差
        distance_to_target = np.linalg.norm(position_error, axis=1)
        
        # 计算朝向误差
        heading_diff = target_heading - robot_heading
        heading_diff = np.where(heading_diff > np.pi, heading_diff - 2*np.pi, heading_diff)
        heading_diff = np.where(heading_diff < -np.pi, heading_diff + 2*np.pi, heading_diff)
        
        # 达到判定（只看位置，不看朝向，与奖励计算保持一致）
        position_threshold = 0.3
        reached_position = distance_to_target < position_threshold  # 楼梯任务：只要到达位置即可
        # reached_all只在到达最后一个路径点时才置位
        if len(self.way_points) > 0:
            all_waypoints_visited = np.array([
                len(self.visited_waypoints[i]) >= len(self.way_points)
                for i in range(num_envs)
            ], dtype=bool)
            reached_all = reached_position & all_waypoints_visited
        else:
            reached_all = reached_position
        
        # 计算期望速度命令（与平地navigation一致，简单P控制器）
        desired_vel_xy = np.clip(position_error * 1.0, -1.0, 1.0)
        desired_vel_xy = np.where(reached_all[:, np.newaxis], 0.0, desired_vel_xy)
        
        # 角速度命令：改进的转向策略
        # 计算到目标点的方向
        desired_heading = np.arctan2(position_error[:, 1], position_error[:, 0])
        heading_to_movement = desired_heading - robot_heading
        heading_to_movement = np.where(heading_to_movement > np.pi, heading_to_movement - 2*np.pi, heading_to_movement)
        heading_to_movement = np.where(heading_to_movement < -np.pi, heading_to_movement + 2*np.pi, heading_to_movement)
        
        # ===== 改进：智能转向控制 =====
        # 当需要大转向时，优先转向而不是前进
        large_turn_required = np.abs(heading_to_movement) > np.deg2rad(60)  # 需要大于60度转向
        
        # 对于大转向情况，降低前进速度，提高转向速度
        turn_priority_factor = np.where(large_turn_required, 0.3, 1.0)  # 大转向时前进速度降为30%
        turn_amplification = np.where(large_turn_required, 1.5, 1.0)    # 大转向时转向增益提高50%
        
        # 计算期望速度命令
        desired_vel_xy = np.clip(position_error * 1.0 * turn_priority_factor[:, np.newaxis], -1.0, 1.0)
        desired_vel_xy = np.where(reached_all[:, np.newaxis], 0.0, desired_vel_xy)
        
        # 转向命令（增强版）
        desired_yaw_rate = np.clip(heading_to_movement * 1.0 * turn_amplification, -1.5, 1.5)  # 提高转向上限到1.5
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
            contact_threshold = 0.3  # base接触阈值(原始值为0.01,即一接触就结束)
            if base_contact_value.ndim == 0:
                base_contact = np.array([base_contact_value > contact_threshold], dtype=bool)
            elif base_contact_value.shape[0] != self._num_envs:
                base_contact = np.full(self._num_envs, base_contact_value.flatten()[0] > contact_threshold, dtype=bool)
            else:
                # base_contact = (base_contact_value > 0.01).flatten()[:self._num_envs]  # 数值大于0.01代表base已接触地面，可以触发终止条件了?
                # 对每个环境检查是否有任何接触点超过阈值
                base_contact = np.any(base_contact_value > contact_threshold, axis=1)[:self._num_envs]
        except Exception as e:
            print(f"[Warning] 无法读取base_contact传感器: {e}")
            base_contact = np.zeros(self._num_envs, dtype=bool)  
        # terminated = base_contact.copy()
        # 只打印前10条数据，如果条数小于10，打印全部
        # if hasattr(base_contact, '__len__'):
        #     display_data = base_contact[:10] if len(base_contact) > 10 else base_contact
        #     print(f"[base_contact] base_contact (first 10): {display_data}")
        # else:
        #     print(f"[base_contact] base_contact: {base_contact}")
        terminated = np.logical_or(terminated, base_contact)

        # 陀螺仪三轴加速度传感器数据异常终止
        gyro = self._model.get_sensor_value(self._cfg.sensor.base_gyro, data)
        abs_gyro_z = np.abs(gyro[:, 2])
        large_values = abs_gyro_z[abs_gyro_z > 20]  # 找出绝对值大于20的值
        if len(large_values) > 0:
            print(f"[Warning] abs_gyro_z contains large values: {large_values}")
            terminated = np.logical_or(terminated, abs_gyro_z > 20)

        # 调试：统计终止原因
        if terminated.any():
            timeout_count = int(timeout.sum())
            contact_count = int(base_contact.sum())
            gyro_abnormal_count = int(large_values.sum())
            total = int(terminated.sum())
            if total > 0 and state.info["steps"][0] % 100 == 0:  # 每100步打印一次
                print(f"[termination] total={total} timeout={timeout_count} contact={contact_count} gyro={gyro_abnormal_count}")
                pass
        
        return state.replace(terminated=terminated)
    
    def _compute_slope_features(self, data: mtx.SceneData) -> dict:
        """
        计算坡度特征用于自适应步态调整
        返回坡度相关信息：倾斜角度、方向等
        """
        # 方法1：使用新增的重力投影传感器（优先）
        try:
            # 获取重力在机器人坐标系中的投影
            gravity_projection = self._model.get_sensor_value("gravity_projection", data)  # [num_envs, 3]
            # 重力向量在机器人坐标系中应该指向下，即[0, 0, -1]
            # 偏离程度反映坡度
            gravity_xy_norm = np.linalg.norm(gravity_projection[:, :2], axis=1)
            slope_angle = np.arctan2(gravity_xy_norm, np.abs(gravity_projection[:, 2]))
            slope_direction = np.arctan2(gravity_projection[:, 1], gravity_projection[:, 0])
        except Exception:
            # 方法2：回退到基于四元数的计算
            pose = self._body.get_pose(data)
            root_quat = pose[:, 3:7]
            projected_gravity = self._compute_projected_gravity(root_quat)
            gravity_xy_norm = np.linalg.norm(projected_gravity[:, :2], axis=1)
            slope_angle = np.arctan2(gravity_xy_norm, np.abs(projected_gravity[:, 2]))
            slope_direction = np.arctan2(projected_gravity[:, 1], projected_gravity[:, 0])
        
        # 计算垂直速度变化率（用于判断上升/下降趋势）
        base_lin_vel = self._model.get_sensor_value(self._cfg.sensor.base_linvel, data)
        vertical_velocity = base_lin_vel[:, 2]  # Z轴速度
        
        return {
            'slope_angle': slope_angle,             # 坡度角度
            'slope_direction': slope_direction,     # 坡度方向
            'vertical_velocity': vertical_velocity, # 垂直速度
            'gravity_xy_norm': gravity_xy_norm,     # XY重力分量大小
        }
    
    def _compute_foot_edge_distance(self, data: mtx.SceneData) -> np.ndarray:
        """
        计算足端到台阶边缘的距离，鼓励足端落在中心区域
        返回平均足端边缘距离
        """
        # 获取足端位置（使用新增的传感器）
        foot_positions = []
        foot_sensor_names = ['FR_foot_pos', 'FL_foot_pos', 'RR_foot_pos', 'RL_foot_pos']
        
        for sensor_name in foot_sensor_names:
            try:
                foot_pos = self._model.get_sensor_value(sensor_name, data)  # [num_envs, 3]
                foot_positions.append(foot_pos)
            except Exception:
                # 如果获取不到传感器数据，使用body位置作为备选
                try:
                    foot_body = self._model.get_body(sensor_name.split('_')[0] + '_foot')
                    foot_pos = foot_body.get_pose(data)[:, :3]  # [num_envs, 3]
                    foot_positions.append(foot_pos)
                except Exception:
                    # 如果都获取不到，返回默认值
                    foot_positions.append(np.zeros((data.shape[0], 3), dtype=np.float32))
        
        if len(foot_positions) == 0:
            return np.zeros(data.shape[0], dtype=np.float32)
        
        # 计算足端到最近台阶边缘的距离
        # 简化模型：假设台阶宽度为0.3m，足端应落在中心±0.1m范围内
        min_distances = []
        for foot_pos in foot_positions:
            # 计算到台阶中心线的距离（简化为X-Y平面距离）
            # 假设台阶沿Y轴延伸，中心线为X=0
            distance_to_center = np.abs(foot_pos[:, 0])  # 到中心线的横向距离
            
            # 限制在合理范围内（台阶半宽0.15m）
            edge_distance = np.maximum(0.15 - distance_to_center, 0)  # 距离边缘的距离
            min_distances.append(edge_distance)
        
        # 返回所有足端的平均边缘距离
        avg_edge_distance = np.mean(np.stack(min_distances, axis=1), axis=1)
        return avg_edge_distance
    
    def _compute_dynamic_stability_reward(self, data: mtx.SceneData, slope_features: dict) -> np.ndarray:
        """
        计算动力学稳定性奖励，考虑楼梯地形的垂直运动特性
        """
        # 获取基础传感器数据
        base_lin_vel = self._model.get_sensor_value(self._cfg.sensor.base_linvel, data)
        gyro = self._model.get_sensor_value(self._cfg.sensor.base_gyro, data)
        
        # 1. 垂直速度稳定性（楼梯升降运动）
        vertical_vel = base_lin_vel[:, 2]
        # 允许一定的垂直速度，但不能过大
        vert_stability = np.exp(-np.square(vertical_vel) / (0.5**2))  # σ=0.5 m/s
        
        # 2. 角速度稳定性（特别是绕X/Y轴的倾斜）
        ang_vel_magnitude = np.linalg.norm(gyro[:, :2], axis=1)  # X,Y轴角速度
        ang_stability = np.exp(-np.square(ang_vel_magnitude) / (1.0**2))  # σ=1.0 rad/s
        
        # 3. 坡度适应性奖励
        slope_angle = slope_features['slope_angle']
        # 小坡度时给予奖励，大坡度时适度惩罚
        slope_adaptation = np.exp(-np.square(slope_angle) / (np.pi/6)**2)  # σ=30°
        
        # 综合稳定性奖励
        stability_reward = 0.4 * vert_stability + 0.3 * ang_stability + 0.3 * slope_adaptation
        return stability_reward
    
    def _compute_reward(self, data: mtx.SceneData, info: dict, velocity_commands: np.ndarray) -> np.ndarray:
        """
        速度跟踪奖励机制（增强版：适配楼梯地形）
        velocity_commands: [num_envs, 3] - (vx, vy, vyaw)
        """
        # 计算坡度特征
        slope_features = self._compute_slope_features(data)
        
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
        # print(f"[termination_penalty] side_flip_count={side_flip_mask.sum()}")
        
        # 线速度跟踪奖励（适配楼梯地形）
        base_lin_vel = self._model.get_sensor_value(self._cfg.sensor.base_linvel, data)
        lin_vel_error = np.sum(np.square(velocity_commands[:, :2] - base_lin_vel[:, :2]), axis=1)
        tracking_lin_vel = np.exp(-lin_vel_error / 0.25)  # tracking_sigma = 0.25
        
        # 角速度跟踪奖励 / 朝向偏差惩罚（混合策略）
        gyro = self._model.get_sensor_value(self._cfg.sensor.base_gyro, data)
        ang_vel_error = np.square(velocity_commands[:, 2] - gyro[:, 2])
        tracking_ang_vel = np.exp(-ang_vel_error / 0.25)
        
        # 1. 坡度自适应奖励
        slope_angle = slope_features['slope_angle']  # 1 radians=57.2958 degrees
        # 打印前10条数据，如果条数小于10，打印全部
        if hasattr(slope_angle, '__len__'):
            display_data = slope_angle[:10] if len(slope_angle) > 10 else slope_angle
            print(f"[slope_angle(in radians)] (first 10): {[f'{x:.2f}' for x in display_data]}")
        else:
            print(f"[slope_angle(in radians)]: {slope_angle:.2f}")
        # 坡度适中时给予奖励（鼓励稳定的爬坡姿态）
        slope_adaptation_reward = np.exp(-np.square(slope_angle) / (np.pi/8)**2)  # σ=22.5°
        
        # 2. 足端边缘距离奖励
        foot_edge_distance = self._compute_foot_edge_distance(data)  # [num_envs]
        edge_distance_reward = np.clip(foot_edge_distance / 0.15, 0, 1)  # 归一化到[0,1]
        
        # 3. 动力学稳定性奖励（考虑Z轴运动）
        dyn_stability_reward = self._compute_dynamic_stability_reward(data, slope_features)
        
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
        
        position_threshold = self._cfg.waypoint_reach_distance  # 与目标位置的误差阈值(要小于途径点标识物的尺寸)
        reached_position = distance_to_target < position_threshold
        # 只打印前10条数据，如果条数小于10，打印全部
        if hasattr(reached_position, '__len__') and hasattr(distance_to_target, '__len__'):
            display_reached = reached_position[:10] if len(reached_position) > 10 else reached_position
            display_distance = distance_to_target[:10] if len(distance_to_target) > 10 else distance_to_target
            display_target = target_position[:10] if len(target_position) > 10 else target_position
            display_robot = robot_position[:10] if len(robot_position) > 10 else robot_position
            # print(f"[reached_position] reached_position (first 10)={display_reached}")
            print(f"[reached_position] distance_to_target (first 10)={[f'{x:.4f}' for x in display_distance]}")
            target_formatted = [f'[{float(row[0]):.2f}, {float(row[1]):.2f}]' for row in display_target]
            print(f"[reached_position] target_position (first 10)={', '.join(target_formatted)}")
            robot_formatted = [f'[{float(row[0]):.2f}, {float(row[1]):.2f}]' for row in display_robot]
            print(f"[reached_position] robot_position  (first 10)={', '.join(robot_formatted)}")
        else:
            # print(f"[reached_position] reached_position={reached_position}")
            print(f"[reached_position] distance_to_target={[f'{x:.4f}' for x in display_distance]}")
            target_formatted = [f'[{float(row[0]):.2f}, {float(row[1]):.2f}]' for row in display_target]
            print(f"[reached_position] target_position={', '.join(target_formatted)}")
            robot_formatted = [f'[{float(row[0]):.2f}, {float(row[1]):.2f}]' for row in display_robot]
            print(f"[reached_position]  robot_position={', '.join(robot_formatted)}")
            pass
        
        heading_threshold = np.deg2rad(15)
        reached_heading = np.abs(heading_diff) < heading_threshold
        reached_all = np.logical_and(reached_position, reached_heading)
        # reached_all只在到达最后一个路径点时才置位
        if len(self.way_points) > 0:
            all_waypoints_visited = np.array([
                len(self.visited_waypoints[i]) >= len(self.way_points)
                for i in range(self._num_envs)
            ], dtype=bool)
            reached_all = reached_all & all_waypoints_visited
        
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
        # print("speed_xy 统计信息:")
        # print(f"  最小值: {np.min(speed_xy)}")
        # print(f"  最大值: {np.max(speed_xy)}")
        gyro_z_calc = np.clip((np.abs(gyro_z_clipped) / 0.1)**4, 0, 100)  # 限制最小值为0，最大值为100
        # print("gyro[:, 2] 统计信息:")
        # print(f"  最小值: {np.min(gyro[:, 2])}")
        # print(f"  最大值: {np.max(gyro[:, 2])}")
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
        
        # ===== 新增：前进方向奖励机制 =====
        # 鼓励机器人正面朝向运动方向，防止侧身或倒着走
        movement_direction = np.arctan2(base_lin_vel[:, 1], base_lin_vel[:, 0] + 1e-6)  # 运动方向
        forward_alignment = np.cos(movement_direction - robot_heading)  # 与朝向的对齐程度
        forward_alignment_reward = np.clip(forward_alignment, 0, 1)  # 只奖励正面运动
        
        # ===== 新增：转向准备奖励机制 =====
        # 鼓励机器人在移动前先调整朝向
        # 计算到下一目标点的理想朝向
        next_waypoint_direction = np.arctan2(position_error[:, 1], position_error[:, 0] + 1e-6)
        heading_to_target = next_waypoint_direction - robot_heading
        heading_to_target = np.where(heading_to_target > np.pi, heading_to_target - 2*np.pi, heading_to_target)
        heading_to_target = np.where(heading_to_target < -np.pi, heading_to_target + 2*np.pi, heading_to_target)
        
        # 转向准备奖励：当角速度与所需转向方向一致时给予奖励
        required_turn_direction = np.sign(heading_to_target)  # 所需转向方向 (+1 或 -1)
        gyro_z_sign = np.sign(gyro[:, 2] + 1e-6)  # 实际转向方向
        turn_preparation_reward = np.where(
            np.logical_and(
                np.abs(heading_to_target) > np.deg2rad(30),  # 需要较大转向时
                required_turn_direction * gyro_z_sign > 0.5   # 转向方向正确
            ),
            np.clip(np.abs(gyro[:, 2]) * 2.0, 0, 1.0),  # 根据角速度大小奖励
            0.0
        )
        
        # 转向完成奖励：当朝向接近目标方向时给予奖励
        heading_alignment_reward = np.exp(-np.square(heading_to_target) / (np.pi/6)**2)  # σ=30°
        
        # ===== 新增：步态节奏奖励 =====
        # 鼓励交替迈步的自然步态
        foot_contact_pattern = np.zeros(self._num_envs, dtype=np.float32)
        gait_symmetry_penalty = np.zeros(self._num_envs, dtype=np.float32)  # 步态对称性惩罚
        try:
            # 简化的步态节奏检测：基于足端Z坐标变化
            foot_heights = {}  # 存储各足端高度用于对称性检测
            for i, foot_name in enumerate(['FR', 'FL', 'RR', 'RL']):
                foot_pos_sensor = f'{foot_name}_foot_pos'
                foot_pos = self._model.get_sensor_value(foot_pos_sensor, data)
                # 检测足端离地高度
                foot_height = foot_pos[:, 2]
                foot_heights[foot_name] = foot_height
                # 简单的步态节奏奖励：鼓励足端有一定抬升
                foot_contact_pattern += np.clip((foot_height - 0.05) * 2.0, 0, 1)
            
            # ===== 新增：步态对称性惩罚 =====
            # 四足动物自然步态中，对角腿成对运动（trot gait）
            # 对角线对1：FL + RR 同步
            diagonal1_asymmetry = np.abs(foot_heights['FL'] - foot_heights['RR'])
            # 对角线对2：FR + RL 同步
            diagonal2_asymmetry = np.abs(foot_heights['FR'] - foot_heights['RL'])
            # 总对称性惩罚：当对角腿高度差>0.03m时开始惩罚
            gait_symmetry_penalty = (
                np.clip((diagonal1_asymmetry - 0.03) * 5.0, 0, 1) + 
                np.clip((diagonal2_asymmetry - 0.03) * 5.0, 0, 1)
            )
        except:
            foot_contact_pattern = np.zeros(self._num_envs, dtype=np.float32)
            gait_symmetry_penalty = np.zeros(self._num_envs, dtype=np.float32)
        
        # ===== 改进：楼梯攀登专用奖励 =====
        # 垂直运动奖励：鼓励合理的上升下降
        vertical_vel = slope_features['vertical_velocity']  # 从坡度特征中获取垂直速度
        vertical_motion_reward = np.exp(-np.square(vertical_vel) / (1.0**2))  # σ=1.0 m/s
        
        # 楼梯台阶检测奖励
        stair_step_reward = np.zeros(self._num_envs, dtype=np.float32)
        # 简化检测：当有垂直速度且姿态稳定时给予奖励
        stair_condition = np.logical_and(
            np.abs(vertical_vel) > 0.1,  # 有明显的垂直运动
            np.abs(slope_features['slope_angle']) < np.deg2rad(45)  # 坡度不太陡峭
        )
        stair_step_reward = np.where(stair_condition, 0.5, 0.0)
        
        # ===== 新增：地形状态检测 =====
        # 1. 楼梯攀登状态检测
        stair_climbing_state = np.zeros(self._num_envs, dtype=np.float32)
        try:
            # 简化检测：当前腿足端较高且有向上速度时认为在攀爬
            for foot_name in ['FL', 'FR']:  # 前腿足端传感器
                foot_pos_sensor = f'{foot_name}_foot_pos'
                foot_pos = self._model.get_sensor_value(foot_pos_sensor, data)
                foot_height = foot_pos[:, 2]
                # 当前腿足端离地且有向上速度时判定为攀爬状态
                climbing_condition = np.logical_and(
                    foot_height > 0.1,  # 足端离地一定高度
                    vertical_vel > 0.05  # 有向上的垂直速度
                )
                stair_climbing_state = np.maximum(stair_climbing_state, climbing_condition.astype(np.float32))
        except:
            stair_climbing_state = np.zeros(self._num_envs, dtype=np.float32)
        
        # ===== 新增： waypoint proximity turning guidance =====
        # 当接近waypoint时，更强地鼓励转向行为
        waypoint_proximity_turning = np.zeros(self._num_envs, dtype=np.float32)
        try:
            # 检查是否接近waypoint（距离小于1.0米）
            close_to_waypoint = distance_to_target < 1.0
            if np.any(close_to_waypoint):
                # 在接近waypoint时，如果需要大转向，则强烈鼓励原地转向
                large_turn_required = np.abs(heading_to_target) > np.deg2rad(45)  # 需要大于45度转向
                should_turn_in_place = np.logical_and(close_to_waypoint, large_turn_required)
                
                # 原地转向奖励：低线速度 + 高角速度
                low_forward_speed = np.linalg.norm(base_lin_vel[:, :2], axis=1) < 0.3  # 前进速度低于0.3m/s
                high_turning_speed = np.abs(gyro[:, 2]) > 0.8  # 转向角速度高于0.8 rad/s
                
                turning_in_place_condition = np.logical_and(
                    should_turn_in_place,
                    np.logical_and(low_forward_speed, high_turning_speed)
                )
                
                waypoint_proximity_turning = np.where(turning_in_place_condition, 1.5, 0.0)
        except:
            waypoint_proximity_turning = np.zeros(self._num_envs, dtype=np.float32)
        
        # 2. 下坡状态检测（更敏感）
        slope_angle = slope_features['slope_angle']
        is_downhill = np.logical_and(slope_angle < -np.deg2rad(5), slope_angle > -np.deg2rad(45))
        downhill_state = is_downhill.astype(np.float32)
        
        # 3. 下坡稳定性奖励（强化）
        # 下坡时强烈鼓励稳定下降，严格限制动作幅度
        downhill_stability = np.zeros(self._num_envs, dtype=np.float32)
        if np.any(is_downhill):
            # 下坡时奖励极小的角速度和缓慢的前进速度
            ang_vel_magnitude = np.linalg.norm(gyro[:, :2], axis=1)
            forward_speed = np.linalg.norm(base_lin_vel[:, :2], axis=1)
            # 下坡稳定性：极严格的角速度限制 + 缓慢前进速度
            downhill_stability = np.where(
                is_downhill,
                np.exp(-np.square(ang_vel_magnitude) / (0.3**2)) * np.clip(forward_speed / 0.8, 0, 1),  # 更严格的角速度阈值(0.5→0.3)和更低速限制(1.0→0.8)
                0.0
            )
        
        # 楼梯攀登激励奖励
        stair_climb_incentive = stair_climbing_state * 0.8  # 攀爬状态下给予额外奖励
        # 下坡激励奖励（增强）
        downhill_incentive = downhill_state * 0.8  # 下坡状态下给予更高奖励（0.6→0.8）
        
        # 综合奖励（楼梯地形优化版 + 步态引导 + 攀爬激励 + 转向奖励）
        # 到达后：停止所有正向奖励，只保留停止奖励和惩罚项
        reward = np.where(
            reached_all,
            # 到达后：只有停止奖励和惩罚
            (
                stop_bonus
                + arrival_bonus
                - 0.1 * lin_vel_z_penalty    # 极度减少Z轴惩罚，完全允许上下楼梯
                - 0.01 * ang_vel_xy_penalty  # 进一步减少XY角速度惩罚
                - 0.0 * orientation_penalty
                - 0.00001 * torque_penalty
                - 0.0 * dof_vel_penalty
                - 0.0002 * action_rate_penalty  # 进一步减少动作变化惩罚
                - 0.3 * gait_symmetry_penalty   # 到达后也维持步态对称性
                + termination_penalty
            ),
            # 未到达：正常奖励（平衡激进性与稳定性）
            (
                0.7 * tracking_lin_vel      # 线速度跟踪（略微降低权重给转向让路）
                + 0.3 * tracking_ang_vel    # 角速度跟踪（提高权重）
                + 1.2 * forward_alignment_reward  # 前进方向奖励（提高）
                + 0.8 * turn_preparation_reward   # 转向准备奖励（新增）
                + 1.0 * heading_alignment_reward  # 转向完成奖励（新增）
                + 1.2 * waypoint_proximity_turning # waypoint接近时转向奖励（新增）
                + 0.4 * foot_contact_pattern      # 步态节奏奖励
                + approach_reward            # 接近奖励
                + 0.35 * slope_adaptation_reward # 坡度适应奖励（恢复）
                + 0.55 * edge_distance_reward    # 足端边缘距离奖励（提高）
                + 0.35 * dyn_stability_reward    # 动力学稳定性奖励（提高）
                + 0.6 * vertical_motion_reward   # 垂直运动奖励（提高）
                + 0.7 * stair_step_reward        # 楼梯台阶奖励（提高）
                + stair_climb_incentive          # 楼梯攀登激励奖励
                + downhill_incentive             # 下坡激励奖励
                + downhill_stability             # 下坡稳定性奖励
                - 0.1 * lin_vel_z_penalty    # 进一步减少Z轴惩罚
                - 0.01 * ang_vel_xy_penalty  # 进一步减少XY角速度惩罚
                - 0.0 * orientation_penalty
                - 0.00001 * torque_penalty
                - 0.0 * dof_vel_penalty
                - 0.00008 * action_rate_penalty  # 适度减少动作变化惩罚
                - 0.5 * gait_symmetry_penalty    # 步态对称性惩罚，防止单腿持续抬起
                + termination_penalty
            )
        )
        
        # 调试打印：扩展的楼梯地形调试信息
        try:
            arrival_count = int((arrival_bonus > 0).sum())
            stop_count = int((stop_bonus > 0).sum())
            zero_ang_count = int((zero_ang_bonus > 0).sum())
            gyro_z_mean = float(np.mean(abs(gyro_z_clipped)))
            total_envs = self._num_envs
            
            # 额外统计：环境状态分布
            reached_pos_count = int(reached_position.sum())
            reached_head_count = int(reached_heading.sum())
            
            # 楼梯地形特有统计
            slope_angle_deg = float(np.rad2deg(np.mean(slope_features['slope_angle'])))
            vert_vel_mean = float(np.mean(np.abs(slope_features['vertical_velocity'])))
            edge_dist_mean = float(np.mean(foot_edge_distance))
            dyn_stab_mean = float(np.mean(dyn_stability_reward))
            
            # 添加NaN检查和处理
            if np.any(np.isnan(distance_to_target)):
                print(f"[Warning] distance_to_target contains NaN values, replacing with large values")
                distance_to_target = np.where(np.isnan(distance_to_target), 1000.0, distance_to_target)
            
            if np.any(np.isnan(heading_diff)):
                print(f"[Warning] heading_diff contains NaN values, replacing with zero")
                heading_diff = np.where(np.isnan(heading_diff), 0.0, heading_diff)
            
            if np.any(np.isnan(gyro_z_clipped)):
                print(f"[Warning] gyro[:, 2] contains NaN values, replacing with zero")
                gyro_z_clipped = np.where(np.isnan(gyro_z_clipped), 0.0, gyro_z_clipped)
            
            if np.any(np.isnan(reward)):
                print(f"[Warning] reward contains NaN values, replacing with zero")
                reward = np.where(np.isnan(reward), 0.0, reward)
            
            dist_mean = float(np.mean(distance_to_target))
            heading_err_mean = float(np.rad2deg(np.mean(np.abs(heading_diff))))
            reward_mean = float(np.mean(reward))
            
            print(f"[reward_debug] arrival={arrival_count}/{total_envs} stop={stop_count}/{total_envs} zero_ang={zero_ang_count}/{total_envs}")
            print(f"[position] reached_pos={reached_pos_count}/{total_envs} dist_mean={dist_mean:.2f} m")
            print(f"[heading] reached_head={reached_head_count}/{total_envs} heading_err_mean={heading_err_mean:.1f}°")
            print(f"[reachAll] reached_all={int(reached_all.sum())}/{total_envs}")
            print(f"[velocity] gyro_z_mean={gyro_z_mean:.4f} rad/s vert_vel={vert_vel_mean:.3f} m/s")
            print(f"[stairs] slope_angle={slope_angle_deg:.1f}° edge_dist={edge_dist_mean:.3f}m dyn_stab={dyn_stab_mean:.3f}")
            print(f"[reward] reward={reward_mean}")
            visited_list = [list(s) for s in self.visited_waypoints[:10]]
            visited_list_count = [len(s) for s in self.visited_waypoints[:10]]
            print(f"[waypoint] Visited_waypoints(first 10 envs): {visited_list}")
            print(f"[waypoint] Visited_waypoints_count(first 10 envs): {visited_list_count}")
            
            # 转向行为调试信息
            turn_prep_mean = float(np.mean(turn_preparation_reward))  # 转向准备奖励的平均值
            heading_align_mean = float(np.mean(heading_alignment_reward))  # 转向完成奖励的平均值
            waypoint_turn_mean = float(np.mean(waypoint_proximity_turning))  # waypoint接近时转向奖励的平均值
            large_turn_count = int(large_turn_required.sum())
            print(f"[turning] turn_prep={turn_prep_mean:.3f} heading_align={heading_align_mean:.3f} wp_turn={waypoint_turn_mean:.3f} large_turn={large_turn_count}/{total_envs}")
        except Exception:
            pass
        return reward

    def _reset_done_envs(self):
        """Override to properly reset per-env waypoint state for only the terminated envs."""
        state = self._state
        done = state.done
        if not np.any(done):
            return

        # Get the actual env indices that are done
        done_indices = np.where(done)[0]

        # Reset waypoint system state for done envs only
        self.current_waypoint_index[done_indices] = 0
        for env_idx in done_indices:
            self.visited_waypoints[env_idx].clear()
        # Reset contact sensor visited state for done envs only
        for wp_sensor in self.waypoint_contact_sensors:
            wp_sensor['visited'][done_indices] = False
        # Reset celebration state for done envs only
        self._celebration_active[done_indices] = False
        self._celebration_step[done_indices] = 0

        # Call parent to handle standard reset (obs, info, physics)
        super()._reset_done_envs()

    def reset(self, data: mtx.SceneData, done: np.ndarray = None) -> tuple[np.ndarray, dict]:
        cfg: VBotSection001EnvCfg = self._cfg
        num_envs = data.shape[0]
        
        # 在高台中央小范围内随机生成位置
        # 方法1(用于训练):X, Y: 在spawn_center周围 ±spawn_range 范围内随机
        random_xy = np.random.uniform(
            low=-self.spawn_range,
            high=self.spawn_range,
            size=(num_envs, 2)
        )
        # 方法2(用于测试):X: -2.5~2.5, Y: -0.5~0.5
        # random_x = np.random.uniform(low=-2.5, high=2.5, size=(num_envs, 1))
        # random_y = np.random.uniform(low=-0.5, high=0.5, size=(num_envs, 1))
        # random_xy = np.hstack([random_x, random_y])
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
        # 目标位置为第一个路径点：从way_point_names中index为0的元素获取
        goal_pos = self._get_first_waypoint_pos(data)
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
                # target_positions = np.random.uniform(
                #     low=np.abs(goal_xy) - 0.0,
                #     high=np.abs(goal_xy) + 0.0,
                #     size=(num_envs, 2)
                # )
                target_positions = np.random.uniform(
                    low=goal_xy - self._cfg.init_state.pos_range,
                    high=goal_xy + self._cfg.init_state.pos_range,
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
        reached_position = distance_to_target < position_threshold  # 楼梯任务：只看位置
        # reached_all只在到达最后一个路径点时才置位
        if len(self.way_points) > 0:
            all_waypoints_visited = np.array([
                len(self.visited_waypoints[i]) >= len(self.way_points)
                for i in range(num_envs)
            ], dtype=bool)
            reached_all = reached_position & all_waypoints_visited
        else:
            reached_all = reached_position
        
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
            # 路径点系统相关
            "current_waypoint_index": np.zeros(num_envs, dtype=np.int32),  # per-env当前路径点索引
        }
        
        return obs, info
