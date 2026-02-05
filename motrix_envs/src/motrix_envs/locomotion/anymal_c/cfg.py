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

import os
from dataclasses import dataclass, field

from motrix_envs import registry
from motrix_envs.base import EnvCfg

model_file = os.path.dirname(__file__) + "/xmls/scene.xml"


@dataclass
class NoiseConfig:
    level: float = 1.0
    scale_joint_angle: float = 0.03
    scale_joint_vel: float = 1.5
    scale_gyro: float = 0.2
    scale_gravity: float = 0.05
    scale_linvel: float = 0.1


@dataclass
class ControlConfig:
    # stiffness[N*m/rad] uses kp parameter from XML, recorded for reference only
    # damping[N*m*s/rad] uses kv parameter from XML, recorded for reference only
    action_scale = 0.06  # action scale


@dataclass
class InitState:
    # the initial position of the robot in the world frame
    pos = [0.0, 0.0, 0.5]  # Z-axis height matches the initial height of base in XML

    # position randomization range [x_min, y_min, x_max, y_max]
    pos_randomization_range = [-10.0, -10.0, 10.0, 10.0]  # randomly distributed over 20m x 20m range on ground

    # the default angles for all joints. key = joint name, value = target angle [rad]
    default_joint_angles = {
        "LF_HAA": 0.0,  # [rad]
        "RF_HAA": 0.0,  # [rad]
        "LH_HAA": 0.0,  # [rad]
        "RH_HAA": 0.0,  # [rad]
        "LF_HFE": 0.4,  # [rad]
        "RF_HFE": 0.4,  # [rad]
        "LH_HFE": -0.4,  # [rad]
        "RH_HFE": -0.4,  # [rad]
        "LF_KFE": -0.8,  # [rad]
        "RF_KFE": -0.8,  # [rad]
        "LH_KFE": 0.8,  # [rad]
        "RH_KFE": 0.8,  # [rad]
    }


@dataclass
class Commands:
    # offset range of target position relative to robot initial position
    # [dx_min, dy_min, yaw_min, dx_max, dy_max, yaw_max]
    # dx/dy: offset relative to robot initial position (meters)
    # yaw: target absolute orientation (radians), random horizontal direction
    pose_command_range = [-5.0, -5.0, -3.14, 5.0, 5.0, 3.14]


@dataclass
class Normalization:
    lin_vel = 2.0
    ang_vel = 0.25
    dof_pos = 1.0
    dof_vel = 0.05


@dataclass
class Asset:
    body_name = "base"
    foot_names = ["LF_FOOT", "RF_FOOT", "LH_FOOT", "RH_FOOT"]
    terminate_after_contacts_on = ["base"]
    ground_name = "ground"


@dataclass
class Sensor:
    base_linvel = "base_linvel"
    base_gyro = "base_gyro"


@dataclass
class RewardConfig:
    scales: dict[str, float] = field(
        default_factory=lambda: {
            "termination": -400.0,
            "position_tracking": 0.5,
            "fine_position_tracking": 0.5,
            "orientation": -0.2,
        }
    )


@registry.envcfg("anymal_c_locomotion_flat")
@dataclass
class AnymalCEnvCfg(EnvCfg):
    model_file: str = model_file
    reset_noise_scale: float = 0.01
    max_episode_seconds: float = 7.0
    sim_dt: float = 0.01
    ctrl_dt: float = 0.01
    reset_yaw_scale: float = 0.1
    max_dof_vel: float = 100.0  # maximum joint velocity threshold, greater tolerance during early training

    noise_config: NoiseConfig = field(default_factory=NoiseConfig)
    control_config: ControlConfig = field(default_factory=ControlConfig)
    reward_config: RewardConfig = field(default_factory=RewardConfig)
    init_state: InitState = field(default_factory=InitState)
    commands: Commands = field(default_factory=Commands)
    normalization: Normalization = field(default_factory=Normalization)
    asset: Asset = field(default_factory=Asset)
    sensor: Sensor = field(default_factory=Sensor)
