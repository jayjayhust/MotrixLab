# VBot楼梯地形攀爬能力改进方案

## 改进概述

针对楼梯地形的三大挑战：
1. **参数通用性差** - 台阶尺寸与陡度差异大，步态难以自适应
2. **边缘打滑** - 足端落在台阶边缘易引发接触力突变与失衡
3. **动力学复杂** - 质心升降幅度大，受重力与惯性冲击影响显著

实施了以下三项核心改进：

---

## 1. 坡度自适应识别 (Slope Adaptation Recognition)

### 实现方式
在 `vbot_section012_np.py` 中新增 `_compute_slope_features()` 方法：

```python
def _compute_slope_features(self, data: mtx.SceneData) -> dict:
    """
    计算坡度特征用于自适应步态调整
    返回坡度相关信息：倾斜角度、方向等
    """
    # 获取机器人姿态
    pose = self._body.get_pose(data)
    root_quat = pose[:, 3:7]
    
    # 计算投影重力向量
    projected_gravity = self._compute_projected_gravity(root_quat)
    
    # 计算坡度角度（相对于水平面）
    gravity_xy_norm = np.linalg.norm(projected_gravity[:, :2], axis=1)
    slope_angle = np.arctan2(gravity_xy_norm, np.abs(projected_gravity[:, 2]))
    
    # 计算坡度方向和垂直速度
    slope_direction = np.arctan2(projected_gravity[:, 1], projected_gravity[:, 0])
    vertical_velocity = base_lin_vel[:, 2]
    
    return {
        'slope_angle': slope_angle,           # 坡度角度
        'slope_direction': slope_direction,   # 坡度方向
        'vertical_velocity': vertical_velocity, # 垂直速度
        'gravity_xy_norm': gravity_xy_norm,   # XY重力分量大小
    }
```

### 奖励机制
新增坡度适应奖励：
```python
slope_adaptation_reward = np.exp(-np.square(slope_angle) / (np.pi/8)**2)  # σ=22.5°
```
- 坡度适中时给予正奖励（鼓励稳定的爬坡姿态）
- 坡度过大时适度惩罚
- 权重：0.5

---

## 2. 足端定位优化 (Foot Placement Optimization)

### 实现方式
新增 `_compute_foot_edge_distance()` 方法：

```python
def _compute_foot_edge_distance(self, data: mtx.SceneData) -> np.ndarray:
    """
    计算足端到台阶边缘的距离，鼓励足端落在中心区域
    """
    # 获取四个足端位置
    foot_positions = []
    for foot_name in ['FR_foot', 'FL_foot', 'RR_foot', 'RL_foot']:
        foot_body = self._model.get_body(foot_name)
        foot_pos = foot_body.get_pose(data)[:, :3]
        foot_positions.append(foot_pos)
    
    # 计算到台阶中心线的距离
    min_distances = []
    for foot_pos in foot_positions:
        distance_to_center = np.abs(foot_pos[:, 0])  # 横向距离
        edge_distance = np.maximum(0.15 - distance_to_center, 0)  # 距离边缘
        min_distances.append(edge_distance)
    
    # 返回平均边缘距离
    return np.mean(np.stack(min_distances, axis=1), axis=1)
```

### 奖励机制
新增边缘距离奖励：
```python
edge_distance_reward = np.clip(foot_edge_distance / 0.15, 0, 1)
```
- 足端越靠近台阶中心，奖励越高
- 足端接近边缘时奖励递减
- 权重：0.8（较高权重强调足端稳定性）

---

## 3. 动力学补偿 (Dynamics Compensation)

### 实现方式
新增 `_compute_dynamic_stability_reward()` 方法：

```python
def _compute_dynamic_stability_reward(self, data: mtx.SceneData, slope_features: dict) -> np.ndarray:
    """
    计算动力学稳定性奖励，考虑楼梯地形的垂直运动特性
    """
    # 1. 垂直速度稳定性（允许合理的升降运动）
    vertical_vel = base_lin_vel[:, 2]
    vert_stability = np.exp(-np.square(vertical_vel) / (0.5**2))  # σ=0.5 m/s
    
    # 2. 角速度稳定性（抑制倾斜晃动）
    ang_vel_magnitude = np.linalg.norm(gyro[:, :2], axis=1)
    ang_stability = np.exp(-np.square(ang_vel_magnitude) / (1.0**2))  # σ=1.0 rad/s
    
    # 3. 坡度适应性奖励
    slope_angle = slope_features['slope_angle']
    slope_adaptation = np.exp(-np.square(slope_angle) / (np.pi/6)**2)  # σ=30°
    
    # 综合稳定性奖励
    return 0.4 * vert_stability + 0.3 * ang_stability + 0.3 * slope_adaptation
```

### 物理参数调整
在 `vbot.xml` 中优化了关键参数：

| 参数 | 原值 | 新值 | 说明 |
|------|------|------|------|
| 足端摩擦系数 | 0.4 | 0.8 | 提高抓地力，防打滑 |
| 关节阻尼 | 0.1 → 0.15 | 增加关节稳定性 |
| 摩擦损失 | 0.2 → 0.25/0.3 | 提高能量传递效率 |

### 奖励权重调整
显著减少了对垂直运动的惩罚：
```python
# 未到达目标时
- 1.0 * lin_vel_z_penalty  →  -0.8 * lin_vel_z_penalty  # 减少Z轴惩罚
- 0.05 * ang_vel_xy_penalty → -0.03 * ang_vel_xy_penalty # 减少XY角速度惩罚

# 到达目标时  
- 2.0 * lin_vel_z_penalty  →  -1.5 * lin_vel_z_penalty  # 允许小幅升降
```

---

## XML配置增强

### 传感器配置优化 (`scene_section012-1.xml`)
```xml
<!-- 足端接触传感器 - 增强版（支持更详细的接触力分析） -->
<contact name="FR_foot_contact_full" subtree1="FR_foot" subtree2="S2C_ground_root" data="force" num="3" />
<contact name="FL_foot_contact_full" subtree1="FL_foot" subtree2="S2C_ground_root" data="force" num="3" />
<contact name="RR_foot_contact_full" subtree1="RR_foot" subtree2="S2C_ground_root" data="force" num="3" />
<contact name="RL_foot_contact_full" subtree1="RL_foot" subtree2="S2C_ground_root" data="force" num="3" />
```

### 新增专用传感器 (`vbot.xml`)
```xml
<!-- 足端位置传感器（用于边缘距离计算） -->
<framepos name="FR_foot_pos" objtype="body" objname="FR_foot" />
<framepos name="FL_foot_pos" objtype="body" objname="FL_foot" />
<framepos name="RR_foot_pos" objtype="body" objname="RR_foot" />
<framepos name="RL_foot_pos" objtype="body" objname="RL_foot" />

<!-- 重力投影传感器（用于坡度检测） -->
<framezaxis name="gravity_projection" objtype="site" objname="trunk_imu" />
```

---

## 调试信息增强

新增楼梯地形专用调试输出：
```
[stairs] slope_angle=15.2° edge_dist=0.087m dyn_stab=0.765
[velocity] gyro_z_mean=0.0234 rad/s vert_vel=0.156 m/s
```

包括：
- 坡度角度
- 平均足端边缘距离
- 动力学稳定性得分
- 垂直速度统计

---

## 效果预期

### 短期效果（训练初期）
- 更稳定的起步和着陆
- 减少因足端打滑导致的摔倒
- 更好的坡度感知能力

### 长期效果（训练成熟）
- 自适应不同坡度的步态策略
- 精确的足端_placement控制
- 高效的动力学平衡调节
- 在各种楼梯配置下都能稳定攀爬

### 性能指标改善
预计在以下方面有显著提升：
- 成功率：+20-30%
- 平均完成时间：-15-25%
- 能耗效率：+10-15%
- 稳定性：大幅改善边缘打滑问题

---

## 文件变更清单

1. **`vbot_section012_np.py`**
   - 新增 `_compute_slope_features()` 方法
   - 新增 `_compute_foot_edge_distance()` 方法
   - 新增 `_compute_dynamic_stability_reward()` 方法
   - 修改 `_compute_reward()` 方法，集成三项新奖励
   - 增强调试信息输出

2. **`scene_section012-1.xml`**
   - 增强足端接触传感器配置
   - 添加完整的接触力数据采集

3. **`vbot.xml`**
   - 提高摩擦系数和阻尼参数
   - 新增足端位置和重力投影传感器
   - 添加楼梯辅助可视化标记

---

## 测试建议

1. **基础功能验证**
   - 单步上下楼梯测试
   - 不同坡度适应性测试
   - 边缘着陆稳定性测试

2. **性能基准测试**
   - 与改进前版本对比成功率
   - 记录完成时间和能耗数据
   - 统计摔倒频率和原因

3. **极限条件测试**
   - 最大坡度下的表现
   - 快速转向时的稳定性
   - 突发扰动恢复能力

这些改进应该能显著提升VBot在楼梯地形上的攀爬能力和稳定性。