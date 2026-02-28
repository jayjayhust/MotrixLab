# 技术说明文档

## 第一章 总体思路

### 1.1 训练简述

本项目针对MotrixArena S1比赛的两个赛段（Section001和Section01）分别进行了强化学习训练，采用PPO（Proximal Policy Optimization）算法训练VBot四足机器人在复杂地形上的导航能力。

#### 1.1.1 训练方式

- **硬件环境**: RTX 5070Ti(自己的主机，没有在地瓜平台上训练)
- **操作系统**: Ubuntu 22.04
- **算法**: PPO (Proximal Policy Optimization)
- **训练框架**: SKRL (基于JAX后端)
- **仿真环境**: MotrixSim物理引擎
- **并行环境数**: 2048个
- **训练步长**: 100Hz (sim_dt = 0.01s)
- **训练总步数**: 100,000,000步

#### 1.1.2 模型结构

采用三层全连接神经网络结构：

| 网络类型 | 隐藏层结构 | 激活函数 |
|---------|-----------|---------|
| Policy Network | (256, 128, 64) | ReLU |
| Value Network | (256, 128, 64) | ReLU |

- **观测空间维度**: 54维
- **动作空间维度**: 12维（对应12个关节执行器）

#### 1.1.3 关键超参

| 参数名称 | 数值 | 说明 |
|---------|------|------|
| learning_rate | 3e-4 | 学习率 |
| rollouts | 48 | 经验回滚次数 |
| learning_epochs | 6 | 每次更新的训练轮数 |
| mini_batches | 32 | 小批量数量 |
| discount_factor | 0.99 | 折扣因子 |
| lambda_param | 0.95 | GAE参数 |
| ratio_clip | 0.2 | PPO裁剪比率 |
| grad_norm_clip | 1.0 | 梯度裁剪 |
| entropy_loss_scale | 0.001 | 熵损失权重 |

#### 1.1.4 奖励简述

**第一赛段 (Section001) 奖励设计:**

| 奖励项 | 权重 | 说明 |
|-------|------|------|
| tracking_lin_vel | 0.7 | 线速度跟踪奖励 |
| tracking_ang_vel | 0.3 | 角速度跟踪奖励 |
| forward_alignment_reward | 1.2 | 前进方向对齐奖励 |
| turn_preparation_reward | 0.8 | 转向准备奖励 |
| heading_alignment_reward | 1.0 | 朝向对齐奖励 |
| waypoint_proximity_turning | 1.2 | 路径点附近转向奖励 |
| foot_contact_pattern | 0.4 | 步态节奏奖励 |
| approach_reward | 1.0 | 接近目标奖励 |
| slope_adaptation_reward | 0.35 | 坡度适应奖励 |
| edge_distance_reward | 0.55 | 足端边缘距离奖励 |
| dyn_stability_reward | 0.35 | 动力学稳定性奖励 |
| vertical_motion_reward | 0.6 | 垂直运动奖励 |
| stair_step_reward | 0.7 | 楼梯台阶奖励 |
| stair_climb_incentive | 0.8 | 楼梯攀登激励 |
| downhill_incentive | 0.8 | 下坡激励 |
| downhill_stability | 1.0 | 下坡稳定性奖励 |
| large_action_bonus | 动态 | 陡峭楼梯大动作奖励 |
| height_gain_bonus | 动态 | 高度增益奖励 |
| stop_bonus | 动态 | 到达停止奖励 |
| arrival_bonus | 10.0 | 首次到达奖励 |
| termination_penalty | -20.0 | 终止惩罚 |

**第二赛段 (Section01) 奖励设计:**

在Section001基础上增加了保守模式调整：
- 提高动作变化惩罚权重（0.002→0.005）
- 新增动作幅度惩罚（0.001）
- 增加接地奖励（0.15）
- 降低步态对称性惩罚（0.8→0.4）
- 新增极端滞空惩罚（0.2）
- 移除陡峭楼梯区域的大动作奖励

#### 1.1.5 文件说明

| 文件名 | 作用 |
|-------|------|
| vbot_section001_np.py | 第一赛段环境实现（平地地形） |
| vbot_section002_waypoint_np.py | 第二赛段环境实现（全地形+路径点） |
| cfg_opendoge.py | 环境配置文件（地形、奖励、初始状态等） |
| cfgs_opendoge.py | PPO训练配置文件（超参数、网络结构等） |
| train.py | 训练启动脚本 |
| play.py | 模型推理演示脚本 |

---

### 1.2 第一赛段训练策略 (Section001)

#### 1.2.1 整体训练思路

第一赛段针对平地地形进行训练，主要目标是让机器人学会在平坦地面上稳定行走并到达目标点。

**训练流程图:**

```
初始化环境
    ↓
固定终点为地图中心点，生成随机目标位置 (以地图中心点为圆心，有效起始距离为环形内半径的区域内)
    ↓
观测获取 (54维) → Policy网络 → 动作输出 (12维)
    ↓
PD控制器转换为力矩 → 物理仿真步进
    ↓
奖励计算 → 终止条件检查
    ↓
达到终止条件? → 是: 重置环境 / 否: 继续训练
    ↓
PPO更新
```

**核心策略:**
1. **固定目标训练**: 目标位置固定在地图中心点，让机器人专注于学习直线行走
2. **小范围随机初始化**: 起始位置在以地图中心点为圆心，有效起始距离为环形内半径的区域内随机，增加泛化能力
3. **渐进式难度**: 从简单地形开始，逐步增加难度

#### 1.2.2 终止条件

| 终止条件 | 阈值 | 惩罚 |
|---------|------|------|
| 基座接触地面 | base_contact > 0.3 | -20.0 |
| 关节速度超限 | max_dof_vel > 100 | -20.0 |
| 侧翻 | tilt_angle > 75° | -20.0 |
| X轴越界 | abs(robot_x) >= 5.0m | -20.0 |
| 步数超时 | steps >= 4000 | 无惩罚 |
| 陀螺仪异常 | abs(gyro_z) > 20 | -20.0 |

#### 1.2.3 数据处理与观测量

**观测空间 (54维):**

| 观测项 | 维度 | 归一化系数 | 说明 |
|-------|------|-----------|------|
| base_lin_vel | 3 | 2.0 | 基座线速度 |
| base_gyro | 3 | 0.25 | 基座角速度 |
| projected_gravity | 3 | - | 投影重力向量 |
| joint_pos_rel | 12 | 1.0 | 相对关节位置 |
| joint_vel | 12 | 0.05 | 关节速度 |
| last_actions | 12 | - | 上一步动作 |
| command_normalized | 3 | - | 归一化速度命令 |
| position_error_normalized | 2 | - | 归一化位置误差 |
| heading_error_normalized | 1 | - | 归一化朝向误差 |
| distance_normalized | 1 | - | 归一化距离 |
| reached_flag | 1 | - | 到达标志 |
| stop_ready_flag | 1 | - | 停止就绪标志 |

**动作空间 (12维):**

对应12个关节执行器（FR/FL/RR/RL各3个关节），输出范围[-1, 1]，通过action_scale=0.2缩放后作为PD控制器的目标位置偏移。

#### 1.2.4 其他处理

**PD控制器参数:**
- kp = 80.0 (位置增益)
- kv = 6.0 (速度增益)
- 力矩限制: hip/thigh ±17 N·m, calf ±34 N·m

**动作滤波:**
- action_filter_alpha = 0.25
- 使用指数移动平均平滑动作输出

---

### 1.3 第二赛段训练策略 (Section01)

#### 1.3.1 整体训练思路

第二赛段针对全地形（平地+楼梯+波浪地形+吊桥）进行训练，引入路径点系统引导机器人通过复杂地形。

**训练流程图:**

```
初始化环境
    ↓
加载路径点配置 (hard-4模式: 14个路径点)
    ↓
按顺序访问路径点 (wp_1-1 → wp_1-2 → ... → wp_3-1)
    ↓
接触检测 → 到达路径点? → 更新目标到下一路径点
    ↓
观测获取 (54维) → Policy网络 → 动作输出 (12维)
    ↓
自适应PD控制器 (下坡参数调整) → 物理仿真
    ↓
奖励计算 (保守模式) → 终止条件检查
    ↓
达到终止条件? → 是: 重置环境 / 否: 继续训练
    ↓
PPO更新
```

**核心策略:**
1. **路径点引导**: 使用14个路径点引导机器人通过复杂地形
2. **难度渐进**: 支持多种难度模式(simple/easy/normal/hard-1~6)
3. **保守训练**: 采用更保守的参数防止机器人在复杂地形摔倒
4. **庆祝动作**: 到达关键路径点时触发庆祝动作（驻留点）

#### 1.3.2 终止条件

与Section001基本相同，但增加了：
- 更严格的动作幅度限制
- 更敏感的下坡检测（阈值从10°降低到5°）

#### 1.3.3 数据处理与观测量

观测空间与Section001相同（54维），但数据处理有以下差异：

**自适应PD控制器:**
- 下坡检测: slope_angle < -5°
- 下坡时降低前腿增益 (85→75)，提高后腿增益 (75→85)
- 增加阻尼系数 (kv: 6→8)

**路径点系统:**
- 当前目标路径点索引跟踪
- 已访问路径点集合记录
- 接触传感器检测路径点到达

#### 1.3.4 各个阶段处理细节

**地形难度模式 (difficulty_mode):**

| 模式 | 路径点数 | 驻留点动作 | 说明 |
|------|---------|-----------|------|
| simple | 1 | 无 | 最简单，直达终点 |
| easy | 3 | 有 | 简单路径，带庆祝 |
| normal | 6 | 无 | 标准路径 |
| hard-1 | 6 | 全部 | 标准路径带庆祝 |
| hard-2 | 9 | 无 | 复杂路径 |
| hard-3 | 9 | 全部 | 复杂路径带庆祝 |
| hard-4 | 14 | 驻留点 | 最复杂（当前使用） |
| hard-5 | 20 | 全部 | 超复杂路径 |
| hard-6 | 20 | 全部 | 包含吊桥和河床 |

**当前使用hard-4模式路径点序列:**
1. wp_1-1_body (index=0)
2. wp_1-2_body (index=1)
3. wp_1-3_body (index=2)
4. wp_1-7_body (index=3)
5. wp_1-6_body (index=4)
6. wp_1-5_body (index=5)
7. wp_1-4_body (index=6, action=True) - 驻留点
8. wp_2-8_body (index=7)
9. wp_2-12_body (index=8)
10. wp_2-10_body (index=9)
11. wp_2-5-1_body (index=10)
12. wp_2-5_body (index=11)
13. wp_2-1_body (index=12, action=True) - 驻留点
14. wp_3-1_body (index=13, action=True) - 终点

**驻留点庆祝动作:**
- 持续时间: 60步 (约1秒@60Hz)
- 动作: 预定义的关节位置序列（机器狗四足一起小幅弯曲，作出蹲下动作）
- 不影响RL控制，仅用于可视化

---

## 第二章 复现细节与结果

### 2.1 复现流程

#### 环境说明

**依赖包:**
- motrixsim: Motrix物理仿真引擎
- motrix_envs: 环境封装
- motrix_rl: RL训练框架
- skrl: 基于JAX/Torch的RL库
- jax/jaxlib: 加速计算后端

**修改内容:**
- 无修改原始例程，直接使用项目提供的配置

#### 运行命令

**第一赛段训练:**
```bash
python scripts/train.py --env MotrixArena_S1_section001_opendoge
```

**第二赛段训练:**
```bash
python scripts/train.py --env MotrixArena_S1_section01_opendoge
```

**模型推理:**
```bash
python scripts/play.py --env MotrixArena_S1_section001_opendoge --checkpoint runs/MotrixArena_S1_section001_opendoge/xx-xx-xx_PPO/checkpoints/best_agent.pickle
```

#### 权重下载说明

训练好的模型权重保存在 `runs/` 目录下：
- Section001: `runs/MotrixArena_S1_section001_opendoge/`
- Section01: `runs/MotrixArena_S1_section01_opendoge/`

### 2.2 运行结果与注意细节

#### 训练结果

**第一赛段 (Section001):**
- 训练步数: ~50M steps
- 成功率: >95%
- 平均奖励: ~15
- 到达时间: ~8-12秒

**第二赛段 (Section01):**
- 训练步数: ~80M steps
- 成功率: ~85%
- 平均奖励: ~12
- 完成时间: ~60-90秒

#### 注意细节

1. **训练稳定性**: 
   - 使用动作滤波(alpha=0.25)防止动作震荡
   - 梯度裁剪(grad_norm_clip=1.0)防止梯度爆炸

2. **地形适应**:
   - 下坡时自动调整PD控制器参数
   - 陡峭区域降低动作变化惩罚

3. **路径点跟踪**:
   - 使用接触传感器检测路径点到达
   - 路径点到达阈值: 0.1m

4. **朝向控制**:
   - 大转向时(>60°)降低前进速度
   - 转向增益提高50%

5. **调试信息**:
   - 训练时打印详细的奖励分解
   - 监控路径点访问状态
   - 记录坡度角度和足端距离
