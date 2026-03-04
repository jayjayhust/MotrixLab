# 运行说明文档

## 运行命令

**第一赛段训练:**
```bash
uv run scripts/train.py --env MotrixArena_S1_section001_opendoge
```

**第二赛段训练:**
```bash
uv run scripts/train.py --env MotrixArena_S1_section01_opendoge
```

**模型推理:**
```bash
uv run scripts/play.py --env MotrixArena_S1_section001_opendoge --checkpoint runs/MotrixArena_S1_section001_opendoge/xx-xx-xx_PPO/checkpoints/best_agent.pickle
uv run scripts/play.py --env MotrixArena_S1_section01_opendoge --num-envs 10
```

## 权重下载说明

训练好的模型权重保存在 `runs/` 目录下：
- Section001: `runs/MotrixArena_S1_section001_opendoge/`
- Section01: `runs/MotrixArena_S1_section01_opendoge/`
