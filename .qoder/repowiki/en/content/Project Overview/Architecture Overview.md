# Architecture Overview

<cite>
**Referenced Files in This Document**
- [pyproject.toml](file://pyproject.toml)
- [motrix_envs/src/motrix_envs/__init__.py](file://motrix_envs/src/motrix_envs/__init__.py)
- [motrix_envs/src/motrix_envs/base.py](file://motrix_envs/src/motrix_envs/base.py)
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py)
- [motrix_envs/src/motrix_envs/np/env.py](file://motrix_envs/src/motrix_envs/np/env.py)
- [motrix_envs/src/motrix_envs/basic/cartpole/cartpole_np.py](file://motrix_envs/src/motrix_envs/basic/cartpole/cartpole_np.py)
- [motrix_envs/src/motrix_envs/basic/cartpole/cfg.py](file://motrix_envs/src/motrix_envs/basic/cartpole/cfg.py)
- [motrix_envs/src/motrix_envs/locomotion/go1/walk_np.py](file://motrix_envs/src/motrix_envs/locomotion/go1/walk_np.py)
- [motrix_envs/src/motrix_envs/locomotion/go1/cfg.py](file://motrix_envs/src/motrix_envs/locomotion/go1/cfg.py)
- [motrix_rl/src/motrix_rl/__init__.py](file://motrix_rl/src/motrix_rl/__init__.py)
- [motrix_rl/src/motrix_rl/base.py](file://motrix_rl/src/motrix_rl/base.py)
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py)
- [motrix_rl/src/motrix_rl/skrl/cfg.py](file://motrix_rl/src/motrix_rl/skrl/cfg.py)
- [motrix_rl/src/motrix_rl/utils.py](file://motrix_rl/src/motrix_rl/utils.py)
- [motrix_rl/src/motrix_rl/skrl/torch/train/ppo.py](file://motrix_rl/src/motrix_rl/skrl/torch/train/ppo.py)
- [motrix_rl/src/motrix_rl/skrl/jax/train/ppo.py](file://motrix_rl/src/motrix_rl/skrl/jax/train/ppo.py)
- [scripts/train.py](file://scripts/train.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)

## Introduction
This document describes the overall system design of MotrixLab-S1, a modular monorepo that separates environment systems from training frameworks. It focuses on:
- Clear separation of concerns between physics environments and reinforcement learning training backends
- Centralized environment and configuration management via a registry pattern
- Dynamic environment instantiation through a factory-like interface
- Pluggable training backends orchestrated by a strategy-like selection mechanism
- End-to-end data flow from user input to environment creation, physics simulation, state updates, and observation generation
- Integration boundaries among MotrixSim physics engine, Gymnasium-compatible interfaces, and SKRL training framework

## Project Structure
MotrixLab-S1 is organized as a Python monorepo with two primary packages:
- motrix_envs: Physics environments and Gymnasium-compatible wrappers backed by MotrixSim
- motrix_rl: Training framework integrations (SKRL) with pluggable backends (JAX/Torch)

The workspace uses a shared toolchain configuration and defines both packages as members of the workspace.

```mermaid
graph TB
subgraph "Workspace Root"
PY["pyproject.toml"]
end
subgraph "motrix_envs Package"
ENV_INIT["motrix_envs/__init__.py"]
BASE["base.py"]
REG_ENV["registry.py"]
NP_ENV["np/env.py"]
CARTPOLE["basic/cartpole/*"]
GO1["locomotion/go1/*"]
end
subgraph "motrix_rl Package"
RL_INIT["motrix_rl/__init__.py"]
RL_BASE["base.py"]
RL_REG["registry.py"]
RL_CFG["skrl/cfg.py"]
UTILS["utils.py"]
SK_TORCH["skrl/torch/train/ppo.py"]
SK_JAX["skrl/jax/train/ppo.py"]
end
subgraph "Scripts"
TRAIN["scripts/train.py"]
end
PY --> ENV_INIT
PY --> RL_INIT
TRAIN --> SK_TORCH
TRAIN --> SK_JAX
SK_TORCH --> REG_ENV
SK_JAX --> REG_ENV
RL_REG --> REG_ENV
```

**Diagram sources**
- [pyproject.toml](file://pyproject.toml#L21-L22)
- [motrix_envs/src/motrix_envs/__init__.py](file://motrix_envs/src/motrix_envs/__init__.py#L16-L17)
- [motrix_rl/src/motrix_rl/__init__.py](file://motrix_rl/src/motrix_rl/__init__.py#L16-L17)
- [scripts/train.py](file://scripts/train.py#L76-L87)

**Section sources**
- [pyproject.toml](file://pyproject.toml#L21-L22)

## Core Components
- Environment Registry Pattern: Centralized registration and lookup of environment configurations and implementations, enabling decoupled discovery and instantiation.
- Factory Pattern: The environment factory constructs instances by name and backend, applying configuration overrides safely.
- Strategy Pattern: Training backends (JAX/Torch) are selected dynamically at runtime based on device availability and user preferences, while keeping the training orchestration consistent.

Key building blocks:
- Environment base classes and configuration model
- Numpy-backed environment implementation using MotrixSim
- Gymnasium-compatible wrappers for SKRL
- RL configuration classes and registry for SKRL backends
- Training entrypoints and device-aware backend selection

**Section sources**
- [motrix_envs/src/motrix_envs/base.py](file://motrix_envs/src/motrix_envs/base.py#L23-L85)
- [motrix_envs/src/motrix_envs/np/env.py](file://motrix_envs/src/motrix_envs/np/env.py#L52-L209)
- [motrix_rl/src/motrix_rl/base.py](file://motrix_rl/src/motrix_rl/base.py#L20-L43)
- [motrix_rl/src/motrix_rl/skrl/cfg.py](file://motrix_rl/src/motrix_rl/skrl/cfg.py#L28-L74)
- [motrix_rl/src/motrix_rl/utils.py](file://motrix_rl/src/motrix_rl/utils.py#L19-L62)

## Architecture Overview
The system follows a layered architecture:
- User input drives training scripts
- Training scripts select a backend (JAX/Torch) and construct a Trainer
- Trainer resolves RL configuration via the RL registry
- Trainer requests an environment from the environment registry
- The environment registry constructs a Gymnasium-compatible wrapper around a MotrixSim-backed Numpy environment
- The environment performs physics steps and generates observations and rewards
- The Trainer orchestrates agent training using SKRL

```mermaid
graph TB
U["User CLI<br/>scripts/train.py"] --> T["Trainer<br/>SKRL/JAX or SKRL/Torch"]
T --> R["RL Registry<br/>default_rl_cfg()"]
T --> E["Env Registry<br/>make()"]
E --> W["Gymnasium Wrapper<br/>SKRL Wrapper"]
W --> N["NpEnv (MotrixSim)<br/>physics_step(), step()"]
N --> S["SceneData<br/>state transitions"]
N --> O["Observations & Rewards"]
T --> A["Agent (PPO)<br/>Models & Memory"]
A --> M["Training Loop<br/>SequentialTrainer"]
```

**Diagram sources**
- [scripts/train.py](file://scripts/train.py#L52-L91)
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py#L81-L115)
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L114-L161)
- [motrix_envs/src/motrix_envs/np/env.py](file://motrix_envs/src/motrix_envs/np/env.py#L186-L209)
- [motrix_rl/src/motrix_rl/skrl/torch/train/ppo.py](file://motrix_rl/src/motrix_rl/skrl/torch/train/ppo.py#L145-L184)
- [motrix_rl/src/motrix_rl/skrl/jax/train/ppo.py](file://motrix_rl/src/motrix_rl/skrl/jax/train/ppo.py#L145-L184)

## Detailed Component Analysis

### Environment Registry and Factory
The environment registry centralizes:
- Registration of environment configurations and implementations
- Backend-aware selection and instantiation
- Validation of configuration overrides and backend compatibility

```mermaid
classDiagram
class EnvMeta {
+env_cfg_cls
+env_cls_dict
+available_sim_backend()
+support_sim_backend(sim_backend) bool
}
class EnvRegistry {
+contains(name) bool
+envcfg(name)
+register_env_config(name, env_cfg_cls)
+env(name, sim_backend)
+register_env(name, env_cls, sim_backend)
+find_available_sim_backend(env_name) str
+make(name, sim_backend, env_cfg_override, num_envs) ABEnv
+list_registered_envs() Dict
}
EnvRegistry --> EnvMeta : "manages"
```

**Diagram sources**
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L24-L172)

**Section sources**
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L41-L172)

### Gymnasium-Compatible Environment Base
The environment base defines:
- Configuration model with validation and derived properties
- Abstract base environment contract for Gymnasium spaces and vectorization

```mermaid
classDiagram
class EnvCfg {
+model_file : str
+sim_dt : float
+max_episode_seconds : float
+ctrl_dt : float
+render_spacing : float
+max_episode_steps()
+sim_substeps()
+validate()
}
class ABEnv {
<<abstract>>
+num_envs : int
+cfg : EnvCfg
+observation_space
+action_space
}
ABEnv --> EnvCfg : "has"
```

**Diagram sources**
- [motrix_envs/src/motrix_envs/base.py](file://motrix_envs/src/motrix_envs/base.py#L23-L85)

**Section sources**
- [motrix_envs/src/motrix_envs/base.py](file://motrix_envs/src/motrix_envs/base.py#L23-L85)

### Numpy Environment Implementation (MotrixSim)
The Numpy-backed environment integrates MotrixSim:
- Scene model loading and timestep configuration
- Physics stepping loop aligned with control frequency
- State lifecycle: initialization, action application, physics step, state update, truncation, and reset handling
- Observation and reward computation per environment

```mermaid
flowchart TD
Start(["step(actions)"]) --> CheckState["Ensure state initialized"]
CheckState --> PrevStep["_prev_physics_step()<br/>reset reward/truncation"]
PrevStep --> Apply["apply_action(actions, state)"]
Apply --> Physics["physics_step()<br/>repeat sim_substeps"]
Physics --> Update["update_state(state)"]
Update --> Inc["Increment step counter"]
Inc --> Truncate["_update_truncate()"]
Truncate --> ResetDone["_reset_done_envs()"]
ResetDone --> Done(["return NpEnvState"])
```

**Diagram sources**
- [motrix_envs/src/motrix_envs/np/env.py](file://motrix_envs/src/motrix_envs/np/env.py#L196-L209)

**Section sources**
- [motrix_envs/src/motrix_envs/np/env.py](file://motrix_envs/src/motrix_envs/np/env.py#L52-L209)

### Environment Implementations (Examples)
- CartPole environment demonstrates minimal Gymnasium spaces, action application, observation concatenation, reward shaping, and termination conditions.
- Go1 walking environment showcases complex observation composition, PD control, contact queries, reward composition, and terrain-specific configurations.

```mermaid
classDiagram
class CartPoleEnv {
+apply_action(actions, state) NpEnvState
+update_state(state) NpEnvState
+reset(data) -> (obs, info)
+observation_space
+action_space
}
class Go1WalkTask {
+apply_action(actions, state) NpEnvState
+update_state(state) NpEnvState
+update_observation(state) NpEnvState
+update_reward(state) NpEnvState
+reset(data) -> (obs, info)
+observation_space
+action_space
}
CartPoleEnv --|> NpEnv
Go1WalkTask --|> NpEnv
```

**Diagram sources**
- [motrix_envs/src/motrix_envs/basic/cartpole/cartpole_np.py](file://motrix_envs/src/motrix_envs/basic/cartpole/cartpole_np.py#L26-L98)
- [motrix_envs/src/motrix_envs/locomotion/go1/walk_np.py](file://motrix_envs/src/motrix_envs/locomotion/go1/walk_np.py#L26-L387)

**Section sources**
- [motrix_envs/src/motrix_envs/basic/cartpole/cartpole_np.py](file://motrix_envs/src/motrix_envs/basic/cartpole/cartpole_np.py#L26-L98)
- [motrix_envs/src/motrix_envs/locomotion/go1/walk_np.py](file://motrix_envs/src/motrix_envs/locomotion/go1/walk_np.py#L26-L387)

### RL Registry and Strategy Selection
The RL registry maps environment names to framework/backend-specific configuration classes. The Trainer selects a backend (JAX/Torch) and constructs the agent accordingly.

```mermaid
sequenceDiagram
participant User as "User"
participant Train as "scripts/train.py"
participant Utils as "motrix_rl/utils.py"
participant Trainer as "SKRL Trainer"
participant RLReg as "motrix_rl/registry.py"
participant EnvReg as "motrix_envs/registry.py"
User->>Train : Run with flags
Train->>Utils : get_device_supports()
Utils-->>Train : DeviceSupports
Train->>Train : choose backend (jax/torch)
Train->>Trainer : initialize Trainer(env_name, sim_backend, ...)
Trainer->>RLReg : default_rl_cfg(env_name, "skrl", backend)
RLReg-->>Trainer : BaseRLCfg subclass instance
Trainer->>EnvReg : make(env_name, sim_backend, num_envs)
EnvReg-->>Trainer : ABEnv instance (wrapped for Gymnasium)
Trainer->>Trainer : build models, agent, memory
Trainer->>Trainer : train()
```

**Diagram sources**
- [scripts/train.py](file://scripts/train.py#L52-L91)
- [motrix_rl/src/motrix_rl/utils.py](file://motrix_rl/src/motrix_rl/utils.py#L39-L62)
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py#L81-L115)
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L114-L161)
- [motrix_rl/src/motrix_rl/skrl/torch/train/ppo.py](file://motrix_rl/src/motrix_rl/skrl/torch/train/ppo.py#L145-L184)
- [motrix_rl/src/motrix_rl/skrl/jax/train/ppo.py](file://motrix_rl/src/motrix_rl/skrl/jax/train/ppo.py#L145-L184)

**Section sources**
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py#L42-L115)
- [motrix_rl/src/motrix_rl/skrl/torch/train/ppo.py](file://motrix_rl/src/motrix_rl/skrl/torch/train/ppo.py#L145-L184)
- [motrix_rl/src/motrix_rl/skrl/jax/train/ppo.py](file://motrix_rl/src/motrix_rl/skrl/jax/train/ppo.py#L145-L184)

### Configuration Classes and Overrides
- Base RL configuration defines training hyperparameters and derived metrics
- SKRL PPO configuration extends the base with agent-specific parameters
- Environment configurations encapsulate model paths, episode durations, and rendering spacing

```mermaid
classDiagram
class BaseRLCfg {
+seed : int?
+num_envs : int
+play_num_envs : int
+max_env_steps : int
+check_point_interval : int
+replace(**updates) BaseRLCfg
+max_batch_env_steps() int
}
class PPOCfg {
+policy_hidden_layer_sizes : tuple
+value_hidden_layer_sizes : tuple
+share_policy_value_features : bool
+rollouts : int
+learning_epochs : int
+mini_batches : int
+discount_factor : float
+lambda_param : float
+learning_rate : float
+learning_rate_scheduler_kl_threshold : float
+random_timesteps : int
+learning_starts : int
+grad_norm_clip : float
+time_limit_bootstrap : bool
+ratio_clip : float
+value_clip : float
+clip_predicted_values : bool
+entropy_loss_scale : float
+value_loss_scale : float
+kl_threshold : float
+rewards_shaper_scale : float
}
PPOCfg --|> BaseRLCfg
```

**Diagram sources**
- [motrix_rl/src/motrix_rl/base.py](file://motrix_rl/src/motrix_rl/base.py#L20-L43)
- [motrix_rl/src/motrix_rl/skrl/cfg.py](file://motrix_rl/src/motrix_rl/skrl/cfg.py#L28-L74)

**Section sources**
- [motrix_rl/src/motrix_rl/base.py](file://motrix_rl/src/motrix_rl/base.py#L20-L43)
- [motrix_rl/src/motrix_rl/skrl/cfg.py](file://motrix_rl/src/motrix_rl/skrl/cfg.py#L28-L74)

### Environment Configuration Examples
- CartPole configuration sets model file, reset noise, episode duration, and rendering spacing
- Go1 configurations define noise, control, reward, initialization, commands, normalization, assets, sensors, and simulation timesteps

**Section sources**
- [motrix_envs/src/motrix_envs/basic/cartpole/cfg.py](file://motrix_envs/src/motrix_envs/basic/cartpole/cfg.py#L25-L32)
- [motrix_envs/src/motrix_envs/locomotion/go1/cfg.py](file://motrix_envs/src/motrix_envs/locomotion/go1/cfg.py#L122-L137)

## Dependency Analysis
- Workspace membership ties both packages together and enables shared tooling
- Training scripts depend on device detection utilities and backend-specific trainers
- RL registry depends on environment registry for existence checks
- SKRL trainers depend on environment registry for instantiation and on Gymnasium wrappers for compatibility

```mermaid
graph TB
PY["pyproject.toml"] --> ENV_PKG["motrix_envs package"]
PY --> RL_PKG["motrix_rl package"]
TRAIN["scripts/train.py"] --> UTILS["motrix_rl/utils.py"]
TRAIN --> SK_TORCH["skrl/torch/train/ppo.py"]
TRAIN --> SK_JAX["skrl/jax/train/ppo.py"]
SK_TORCH --> RLREG["motrix_rl/registry.py"]
SK_JAX --> RLREG
RLREG --> ENVREG["motrix_envs/registry.py"]
SK_TORCH --> WRAP["SKRL Gymnasium Wrapper"]
SK_JAX --> WRAP
WRAP --> NPE["motrix_envs/np/env.py"]
```

**Diagram sources**
- [pyproject.toml](file://pyproject.toml#L21-L22)
- [scripts/train.py](file://scripts/train.py#L76-L87)
- [motrix_rl/src/motrix_rl/utils.py](file://motrix_rl/src/motrix_rl/utils.py#L39-L62)
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py#L52-L53)
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L41-L43)
- [motrix_rl/src/motrix_rl/skrl/torch/train/ppo.py](file://motrix_rl/src/motrix_rl/skrl/torch/train/ppo.py#L145-L184)
- [motrix_rl/src/motrix_rl/skrl/jax/train/ppo.py](file://motrix_rl/src/motrix_rl/skrl/jax/train/ppo.py#L145-L184)

**Section sources**
- [pyproject.toml](file://pyproject.toml#L21-L22)
- [scripts/train.py](file://scripts/train.py#L52-L91)
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py#L42-L115)
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L41-L172)

## Performance Considerations
- Vectorized environments: The environment base and Numpy implementation support multiple environments in batch, controlled by configuration and factory parameters
- Simulation fidelity vs speed: Simulation substeps and control timestep influence accuracy and throughput; tune sim_dt and ctrl_dt appropriately
- Backend selection: Automatic detection of GPU availability for JAX/Torch can improve training throughput; fallback to CPU is handled gracefully
- Logging and checkpointing: RL configuration exposes intervals for experiment writes and checkpoints to balance performance and observability

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Environment not registered: Ensure environment configuration and implementation are decorated and imported so they register during package initialization
- Unsupported simulation backend: Only the "np" backend is supported in the current registry; verify environment registration and backend selection
- Missing RL configuration: Verify that RL configuration classes are registered for the chosen environment and backend
- Device backend mismatch: If neither JAX nor Torch is available, the training script raises an explicit error; install compatible libraries and drivers

**Section sources**
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L71-L83)
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py#L52-L53)
- [scripts/train.py](file://scripts/train.py#L39-L50)

## Conclusion
MotrixLab-S1 employs a clean separation of concerns:
- Environment registry and factory provide centralized, validated instantiation of Gymnasium-compatible environments backed by MotrixSim
- RL registry and Trainer orchestrate SKRL training with pluggable JAX/Torch backends
- The design supports extensibility: new environments and training configurations can be added without changing core orchestration logic
- The modular monorepo structure simplifies development, testing, and deployment across related domains (classic control, locomotion, manipulation)