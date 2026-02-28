# Python Package Infrastructure

<cite>
**Referenced Files in This Document**
- [pyproject.toml](file://pyproject.toml)
- [README.md](file://README.md)
- [motrix_envs/pyproject.toml](file://motrix_envs/pyproject.toml)
- [motrix_rl/pyproject.toml](file://motrix_rl/pyproject.toml)
- [motrix_envs/src/motrix_envs/__init__.py](file://motrix_envs/src/motrix_envs/__init__.py)
- [motrix_rl/src/motrix_rl/__init__.py](file://motrix_rl/src/motrix_rl/__init__.py)
- [motrix_envs/src/motrix_envs/base.py](file://motrix_envs/src/motrix_envs/base.py)
- [motrix_rl/src/motrix_rl/base.py](file://motrix_rl/src/motrix_rl/base.py)
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py)
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py)
- [motrix_rl/src/motrix_rl/cfgs.py](file://motrix_rl/src/motrix_rl/cfgs.py)
- [motrix_rl/src/motrix_rl/utils.py](file://motrix_rl/src/motrix_rl/utils.py)
- [motrix_rl/src/motrix_rl/skrl/cfg.py](file://motrix_rl/src/motrix_rl/skrl/cfg.py)
- [scripts/train.py](file://scripts/train.py)
- [scripts/view.py](file://scripts/view.py)
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
This document describes the Python package infrastructure of the MotrixLab project, a reinforcement learning framework built on top of the MotrixSim simulation engine. The project is structured as a multi-package workspace managed by UV, with two primary packages:
- motrix_envs: Simulation environments based on MotrixSim
- motrix_rl: Reinforcement learning training framework integrating SKRL with unified multi-backend interfaces

The infrastructure emphasizes modularity, extensibility, and reproducible installation via a workspace configuration and optional extras for different training backends.

## Project Structure
The repository follows a workspace layout with separate build configurations for each package and shared documentation and scripts at the root level.

```mermaid
graph TB
Root["Repository Root<br/>Workspace Configuration"] --> Workspace["UV Workspace<br/>Members: motrix_envs, motrix_rl"]
Workspace --> EnvPkg["Package: motrix_envs<br/>Build backend: uv_build"]
Workspace --> RLPkg["Package: motrix_rl<br/>Build backend: uv_build"]
Root --> Scripts["Scripts<br/>train.py, view.py, play.py"]
Root --> Docs["Documentation<br/>Sphinx config and assets"]
Root --> Config["Configuration<br/>pyproject.toml, ruff.toml, uv.lock"]
```

**Diagram sources**
- [pyproject.toml](file://pyproject.toml#L21-L29)
- [motrix_envs/pyproject.toml](file://motrix_envs/pyproject.toml#L1-L16)
- [motrix_rl/pyproject.toml](file://motrix_rl/pyproject.toml#L1-L32)

Key characteristics:
- Workspace-managed packages with independent build systems
- Shared Python version constraint (3.10.*) enforced across packages
- Optional extras for documentation and training backends
- Separate README and configuration files for each package

**Section sources**
- [pyproject.toml](file://pyproject.toml#L1-L29)
- [README.md](file://README.md#L1-L124)

## Core Components
The core infrastructure consists of three layers:
1. Environment abstraction and registry
2. RL configuration and registration system
3. Training and visualization utilities

### Environment Layer
The environment layer defines a unified interface for simulation environments and provides a registry for environment configurations and implementations.

```mermaid
classDiagram
class ABEnv {
<<abstract>>
+int num_envs
+EnvCfg cfg
+observation_space
+action_space
}
class EnvCfg {
+str model_file
+float sim_dt
+float max_episode_seconds
+float ctrl_dt
+float render_spacing
+max_episode_steps() int
+sim_substeps() int
+validate() void
}
class EnvMeta {
+Type[EnvCfg] env_cfg_cls
+Dict~str,Type[ABEnv]~ env_cls_dict
+available_sim_backend() str
+support_sim_backend(str) bool
}
class Registry {
+contains(str) bool
+register_env_config(str, Type[EnvCfg]) void
+register_env(str, Type[ABEnv], str) void
+make(str, str, Dict, int) ABEnv
+list_registered_envs() Dict
}
ABEnv <|-- EnvCfg
Registry --> EnvMeta : "manages"
Registry --> ABEnv : "instantiates"
```

**Diagram sources**
- [motrix_envs/src/motrix_envs/base.py](file://motrix_envs/src/motrix_envs/base.py#L61-L85)
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L24-L172)

### RL Configuration Layer
The RL configuration layer provides a framework-agnostic configuration system with environment-specific overrides and backend specialization.

```mermaid
classDiagram
class BaseRLCfg {
+Optional~int~ seed
+int num_envs
+int play_num_envs
+int max_env_steps
+int check_point_interval
+replace(**updates) BaseRLCfg
+max_batch_env_steps() int
}
class PPOCfg {
+tuple~int~ policy_hidden_layer_sizes
+tuple~int~ value_hidden_layer_sizes
+bool share_policy_value_features
+int rollouts
+int learning_epochs
+int mini_batches
+float discount_factor
+float lambda_param
+float learning_rate
+float learning_rate_scheduler_kl_threshold
+int random_timesteps
+int learning_starts
+float grad_norm_clip
+bool time_limit_bootstrap
+float ratio_clip
+float value_clip
+bool clip_predicted_values
+float entropy_loss_scale
+float value_loss_scale
+float kl_threshold
+float rewards_shaper_scale
}
class EnvRlCfgs {
+Dict~str,Dict~str,Type[BaseRLCfg]~~ cfgs
}
class RLRegistry {
+rlcfg(str, str) Callable
+default_rl_cfg(str, str, str) BaseRLCfg
}
BaseRLCfg <|-- PPOCfg
RLRegistry --> EnvRlCfgs : "stores"
```

**Diagram sources**
- [motrix_rl/src/motrix_rl/base.py](file://motrix_rl/src/motrix_rl/base.py#L20-L43)
- [motrix_rl/src/motrix_rl/skrl/cfg.py](file://motrix_rl/src/motrix_rl/skrl/cfg.py#L28-L74)
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py#L28-L115)

**Section sources**
- [motrix_envs/src/motrix_envs/base.py](file://motrix_envs/src/motrix_envs/base.py#L1-L85)
- [motrix_rl/src/motrix_rl/base.py](file://motrix_rl/src/motrix_rl/base.py#L1-L43)
- [motrix_rl/src/motrix_rl/skrl/cfg.py](file://motrix_rl/src/motrix_rl/skrl/cfg.py#L1-L74)

## Architecture Overview
The system architecture separates concerns across packages while maintaining a unified interface for environment creation and RL configuration.

```mermaid
graph TB
subgraph "User Scripts"
Train["scripts/train.py"]
View["scripts/view.py"]
Play["scripts/play.py"]
end
subgraph "RL Package"
Utils["motrix_rl/utils.py"]
Registry["motrix_rl/registry.py"]
Cfgs["motrix_rl/cfgs.py"]
SKRLCfg["motrix_rl/skrl/cfg.py"]
SKRLJAX["motrix_rl/skrl/jax/*"]
SKRLTorch["motrix_rl/skrl/torch/*"]
end
subgraph "Environment Package"
EnvInit["motrix_envs/__init__.py"]
EnvBase["motrix_envs/base.py"]
EnvRegistry["motrix_envs/registry.py"]
NpEnv["motrix_envs/np/env.py"]
NpRenderer["motrix_envs/np/renderer.py"]
end
Train --> Utils
Train --> Registry
Train --> SKRLJAX
Train --> SKRLTorch
View --> EnvRegistry
View --> NpEnv
View --> NpRenderer
Registry --> EnvRegistry
Cfgs --> SKRLCfg
EnvInit --> EnvBase
EnvInit --> EnvRegistry
```

**Diagram sources**
- [scripts/train.py](file://scripts/train.py#L1-L95)
- [scripts/view.py](file://scripts/view.py#L1-L83)
- [motrix_rl/src/motrix_rl/utils.py](file://motrix_rl/src/motrix_rl/utils.py#L1-L62)
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py#L1-L115)
- [motrix_rl/src/motrix_rl/cfgs.py](file://motrix_rl/src/motrix_rl/cfgs.py#L1-L498)
- [motrix_rl/src/motrix_rl/skrl/cfg.py](file://motrix_rl/src/motrix_rl/skrl/cfg.py#L1-L74)
- [motrix_envs/src/motrix_envs/__init__.py](file://motrix_envs/src/motrix_envs/__init__.py#L1-L17)
- [motrix_envs/src/motrix_envs/base.py](file://motrix_envs/src/motrix_envs/base.py#L1-L85)
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L1-L172)

## Detailed Component Analysis

### Environment Registry and Factory
The environment registry provides a centralized mechanism for registering and instantiating environments with configurable parameters and backend selection.

```mermaid
sequenceDiagram
participant User as "User Script"
participant Registry as "env_registry.make()"
participant Meta as "EnvMeta"
participant EnvCfg as "EnvCfg"
participant EnvCls as "Environment Class"
User->>Registry : make(name, sim_backend, env_cfg_override, num_envs)
Registry->>Meta : lookup env metadata
Meta-->>Registry : EnvMeta
Registry->>EnvCfg : instantiate config class
Registry->>EnvCfg : apply overrides
Registry->>EnvCfg : validate()
Registry->>Meta : select backend implementation
Meta-->>Registry : env class
Registry->>EnvCls : instantiate(env_cfg, num_envs)
EnvCls-->>Registry : environment instance
Registry-->>User : ABEnv instance
```

**Diagram sources**
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L114-L161)

Key features:
- Centralized environment registration with type safety
- Configurable environment parameters via dataclass overrides
- Automatic backend selection with explicit fallback
- Validation of simulation timing parameters

**Section sources**
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L1-L172)

### RL Configuration Management
The RL configuration system enables environment-specific tuning with framework-agnostic defaults and backend specialization.

```mermaid
flowchart TD
Start([Get RL Configuration]) --> CheckEnv{"Environment Registered?"}
CheckEnv --> |No| Error1["Raise ValueError"]
CheckEnv --> |Yes| GetMeta["Get EnvRlCfgs"]
GetMeta --> CheckFramework{"Framework Supported?"}
CheckFramework --> |No| Error2["Raise ValueError"]
CheckFramework --> |Yes| CheckBackend{"Backend Specific Config?"}
CheckBackend --> |Yes| UseBackend["Use Backend-Specific Config"]
CheckBackend --> |No| CheckUniversal{"Universal Config Available?"}
CheckUniversal --> |Yes| UseUniversal["Use Universal Config"]
CheckUniversal --> |No| Error3["Raise ValueError"]
UseBackend --> Instantiate["Instantiate Config Class"]
UseUniversal --> Instantiate
Error1 --> End([End])
Error2 --> End
Error3 --> End
Instantiate --> End([Return Config])
```

**Diagram sources**
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py#L81-L115)

Implementation highlights:
- Decorator-based registration for clean configuration definition
- Hierarchical fallback from backend-specific to universal configurations
- Integration with environment registry for validation
- Extensible framework support (currently SKRL)

**Section sources**
- [motrix_rl/src/motrix_rl/registry.py](file://motrix_rl/src/motrix_rl/registry.py#L1-L115)
- [motrix_rl/src/motrix_rl/cfgs.py](file://motrix_rl/src/motrix_rl/cfgs.py#L1-L498)

### Training Backend Selection
The training infrastructure automatically selects appropriate backends based on device capabilities and user preferences.

```mermaid
flowchart TD
Start([Select Training Backend]) --> CheckDevice["Check DeviceSupports"]
CheckDevice --> CheckJAXGPU{"JAX GPU Available?"}
CheckJAXGPU --> |Yes| UseJAXGPU["Use JAX (GPU)"]
CheckJAXGPU --> |No| CheckTorchGPU{"PyTorch GPU Available?"}
CheckTorchGPU --> |Yes| UseTorchGPU["Use PyTorch (GPU)"]
CheckTorchGPU --> |No| CheckJAXCPU{"JAX CPU Available?"}
CheckJAXCPU --> |Yes| UseJAXCPU["Use JAX (CPU)"]
CheckJAXCPU --> |No| CheckTorchCPU{"PyTorch CPU Available?"}
CheckTorchCPU --> |Yes| UseTorchCPU["Use PyTorch (CPU)"]
CheckTorchCPU --> |No| Error["Raise Exception"]
UseJAXGPU --> End([Return Backend])
UseTorchGPU --> End
UseJAXCPU --> End
UseTorchCPU --> End
Error --> End
```

**Diagram sources**
- [scripts/train.py](file://scripts/train.py#L39-L50)
- [motrix_rl/src/motrix_rl/utils.py](file://motrix_rl/src/motrix_rl/utils.py#L39-L62)

**Section sources**
- [scripts/train.py](file://scripts/train.py#L1-L95)
- [motrix_rl/src/motrix_rl/utils.py](file://motrix_rl/src/motrix_rl/utils.py#L1-L62)

## Dependency Analysis
The package dependencies form a clear hierarchy with explicit optional extras for different training backends.

```mermaid
graph TB
subgraph "Workspace Packages"
EnvPkg["motrix_envs"]
RLPkg["motrix_rl"]
end
subgraph "External Dependencies"
Gymnasium["gymnasium==1.1.1"]
SKRL["skrl==1.4.3"]
Torch["torch==2.7.0+cu128"]
TorchVision["torchvision==v0.22.0+cu128"]
TorchAudio["torchaudio==2.7.0+cu128"]
JAX["jax[cuda12]==0.4.34"]
Flax["flax==0.10.4"]
TF["tensorflow==2.20.0"]
MotrixSim["motrixsim>=0.5.0b2"]
end
RLPkg --> Gymnasium
RLPkg --> SKRL
RLPkg --> EnvPkg
EnvPkg --> MotrixSim
RLPkg -.-> Torch
RLPkg -.-> TorchVision
RLPkg -.-> TorchAudio
RLPkg -.-> JAX
RLPkg -.-> Flax
RLPkg -.-> TF
```

**Diagram sources**
- [motrix_rl/pyproject.toml](file://motrix_rl/pyproject.toml#L13-L27)
- [motrix_envs/pyproject.toml](file://motrix_envs/pyproject.toml#L13-L15)

Dependency characteristics:
- Workspace-relative source resolution for local development
- Optional extras for platform-specific GPU support
- Strict version pinning for reproducible builds
- Clear separation between core dependencies and optional backends

**Section sources**
- [pyproject.toml](file://pyproject.toml#L21-L29)
- [motrix_rl/pyproject.toml](file://motrix_rl/pyproject.toml#L1-L32)
- [motrix_envs/pyproject.toml](file://motrix_envs/pyproject.toml#L1-L16)

## Performance Considerations
The infrastructure includes several mechanisms for performance optimization and resource management:

1. **Vectorized Environments**: The environment abstraction supports multiple simultaneous environments for efficient training
2. **Backend Selection**: Automatic detection of GPU availability optimizes computational resources
3. **Configuration Overrides**: Environment-specific tuning allows performance optimization per task
4. **Checkpoint Management**: Configurable checkpoint intervals balance progress preservation and storage overhead

Best practices:
- Use appropriate num_envs settings based on available memory
- Leverage backend-specific optimizations (e.g., shared features in PyTorch)
- Monitor training progress through configurable intervals
- Utilize environment-specific configurations for optimal hyperparameters

## Troubleshooting Guide

### Common Installation Issues
- **Missing Dependencies**: Ensure all optional extras are installed based on target backend
- **Version Conflicts**: The workspace enforces Python 3.10.*; verify environment compatibility
- **Platform-Specific Packages**: Some extras require Linux with CUDA support

### Runtime Issues
- **Backend Detection**: If automatic backend selection fails, specify backend manually via command-line flags
- **Environment Registration**: Verify environment names match registered configurations
- **Configuration Validation**: Check that environment timing parameters satisfy simulation constraints

### Debugging Tools
The system provides structured logging and configuration validation to aid in troubleshooting:
- Device capability detection with detailed reporting
- Environment configuration validation with clear error messages
- Backend-specific error handling for missing dependencies

**Section sources**
- [scripts/train.py](file://scripts/train.py#L39-L50)
- [motrix_envs/src/motrix_envs/registry.py](file://motrix_envs/src/motrix_envs/registry.py#L53-L59)

## Conclusion
The MotrixLab Python package infrastructure demonstrates a well-architected multi-package workspace that balances modularity with usability. The design enables:

- Clean separation of concerns between environment simulation and RL training
- Flexible backend selection with automatic capability detection
- Extensible configuration system supporting multiple environments and frameworks
- Reproducible installation and development workflows through workspace management

The infrastructure provides a solid foundation for extending with new environments, algorithms, and training backends while maintaining backward compatibility and clear upgrade paths.