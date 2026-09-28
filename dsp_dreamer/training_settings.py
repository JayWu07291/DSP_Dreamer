"""Resolve one human-editable training recipe before touching data or CUDA."""
from dataclasses import asdict
import math
from pathlib import Path
import runpy

from .agent_training import AgentTrainingConfig
from .contract import require
from .dynamics import DynamicsConfig
from .dynamics_training import DynamicsTrainingConfig
from .imagination import ImaginationConfig
from .tokenizer import TokenizerConfig
from .tokenizer_training import TrainingConfig
from .training_control import STAGE_SECONDS


CONFIG_TYPES = dict(A=TrainingConfig, B=DynamicsTrainingConfig, second=AgentTrainingConfig, third=ImaginationConfig)
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / 'training_config.py'


def read_settings(path=DEFAULT_CONFIG, *, exploratory_b=False):
    value = runpy.run_path(str(path))
    runtime = dict(value['RUNTIME'])
    runtime.setdefault('cuda_memory_fraction', .75)
    require(set(runtime) == {'verify_rgb', 'preflight_seconds', 'validation_seconds', 'validation_updates',
                            'update_fraction', 'num_threads', 'cuda_memory_fraction'}, 'Unknown runtime setting')
    require(type(runtime['verify_rgb']) is bool and
            all(math.isfinite(runtime[k]) and runtime[k] > 0 for k in ('preflight_seconds', 'validation_seconds'))
            and math.isfinite(runtime['update_fraction']) and 0 < runtime['update_fraction'] < 1
            and type(runtime['validation_updates']) is int and runtime['validation_updates'] >= 0
            and type(runtime['num_threads']) is int and runtime['num_threads'] > 0, 'Invalid runtime setting')
    require(math.isfinite(runtime['cuda_memory_fraction']) and 0 < runtime['cuda_memory_fraction'] <= 1,
            'Invalid CUDA memory fraction')
    require(runtime['preflight_seconds'] <= STAGE_SECONDS['preflight'], '前置預算最多 2 小時')
    require(set(value['STAGES']) == set(CONFIG_TYPES), 'Missing/unknown training stage')
    stages = {}
    for stage, config_type in CONFIG_TYPES.items():
        settings = dict(value['STAGES'][stage])
        limit = settings.pop('updates')
        require(limit is None or type(limit) is int and limit > 0, 'Invalid update limit')
        config = config_type(updates=limit or 4, **settings)
        config.validate_formal()
        require(stage == 'A' or stage == 'B' and exploratory_b or
                config.max_seconds is not None and config.max_seconds <= STAGE_SECONDS[stage],
                f'{stage} 超過正式階段預算上限')
        require(config.max_seconds is not None or limit is not None, '取消時間上限時必須指定更新次數')
        stages[stage] = dict(asdict(config), updates=limit)
    tokenizer, dynamics = TokenizerConfig(**value['TOKENIZER']), DynamicsConfig(**value['DYNAMICS'])
    require(tokenizer.latent_tokens == dynamics.latent_tokens == 64
            and tokenizer.bottleneck == dynamics.bottleneck == 32, '正式表徵固定為 64×32')
    require(stages['A']['long_length'] > tokenizer.context
            and stages['B']['long_length'] > dynamics.context
            and stages['second']['long_length'] > dynamics.context, '長片段需超過模型 context')
    return dict(runtime=dict(runtime), stages=stages, tokenizer=asdict(tokenizer), dynamics=asdict(dynamics))
