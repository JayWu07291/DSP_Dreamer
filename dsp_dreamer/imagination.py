"""Fixed-task imagination from a frozen stage-two agent, with policy/value updates only."""
import copy
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import platform
import random
import shutil
import time

import numpy as np
import torch
from torch import nn
from torch.distributions import Bernoulli, Categorical, Independent, kl_divergence

from .actions import ACTION_CODEC, EXCLUSIVE_CONTROLS
from .agent import Agent, incoming_actions, reward_expectation, twohot
from .agent_training import AgentTrainingConfig, read_agent_checkpoint, save_agent_checkpoint, sequence_pools
from .contract import atomic_save, file_info, require
from .dynamics import Dynamics, DynamicsConfig
from .dynamics_training import load_tokenizer, verify_implementation
from .evaluation_protocol import seal


IMAGINATION_CONFIG = dict(horizon=15, gamma=.997, lambda_=.95, alpha=.5, beta=.3,
    policy_lr=3e-5, value_lr=1e-4, value_bins=255, value_support='symexp(-20:20)',
    action_distribution='independent controls conditioned on codec exclusions',
    continuation='fixed horizon, bootstrap final value', task='fixed at final context observation')
POLICY_PREFIXES = ('heads.binary.', 'heads.mouse.', 'heads.wheel.')
GROUPS = [[ACTION_CODEC['controls'].index(k) for k in group] for group in EXCLUSIVE_CONTROLS]
INDEPENDENT = [i for i in range(ACTION_CODEC['binary_width']) if all(i not in group for group in GROUPS)]
TOOL_VERSIONS = dict(python=platform.python_version(), torch=str(torch.__version__), numpy=np.__version__)


@dataclass(frozen=True)
class ImaginationConfig(AgentTrainingConfig):
    max_seconds: float = 14400

    def __post_init__(self):
        super().__post_init__()
        require(self.max_seconds <= 14400, '第三階段最多 4 小時')


def policy_distributions(logits):
    """Exact factorization of Bernoulli controls conditioned on legal combinations."""
    require(all(torch.isfinite(v).all().item() for v in logits.values()), '非有限 policy')
    bits = logits['binary'].float()
    result = dict(binary=Independent(Bernoulli(logits=bits[..., INDEPENDENT]), 1),
                  mouse=Categorical(logits=logits['mouse'].float()), wheel=Categorical(logits=logits['wheel'].float()))
    for i, group in enumerate(GROUPS):
        # Legal outcomes are all off or exactly one on; common Bernoulli factors cancel.
        result[str(i)] = Categorical(logits=torch.cat((torch.zeros_like(bits[..., :1]), bits[..., group]), -1))
    return result


def sample_action(logits):
    distributions = policy_distributions(logits)
    bits = torch.zeros_like(logits['binary'], dtype=torch.long)
    bits[..., INDEPENDENT] = distributions['binary'].sample().long()
    for i, group in enumerate(GROUPS):
        selected = distributions[str(i)].sample()
        for j, position in enumerate(group, 1):
            bits[..., position] = (selected == j).long()
    return dict(binary=bits, mouse=distributions['mouse'].sample(), wheel=distributions['wheel'].sample())


def action_log_prob(distributions, actions):
    bits = actions['binary']
    result = distributions['binary'].log_prob(bits[..., INDEPENDENT].float())
    for k in ('mouse', 'wheel'):
        result = result + distributions[k].log_prob(actions[k])
    for i, group in enumerate(GROUPS):
        selected = (bits[..., group] * torch.arange(1, len(group) + 1, device=bits.device)).sum(-1)
        result = result + distributions[str(i)].log_prob(selected)
    return result


def lambda_returns(rewards, values, *, gamma=.997, lambda_=.95):
    require(values.shape == (*rewards.shape[:-1], rewards.shape[-1] + 1), 'Return 需末端 bootstrap value')
    result = []
    future = values[..., -1]
    for t in reversed(range(rewards.shape[-1])):
        future = rewards[..., t] + gamma * ((1 - lambda_) * values[..., t + 1] + lambda_ * future)
        result.append(future)
    return torch.stack(result[::-1], -1).detach()


def imagination_loss(logits, prior, actions, value_logits, returns, values):
    policy = policy_distributions(logits)
    reference = policy_distributions({k: v.detach() for k, v in prior.items()})
    log_prob = action_log_prob(policy, actions)
    positive = (returns - values).detach() >= 0
    negative = ~positive
    # Empty sets contribute zero; counts are over the whole effective batch and horizon.
    pmpo = .5 * (log_prob[negative].sum() / negative.sum().clamp_min(1)
                 - log_prob[positive].sum() / positive.sum().clamp_min(1))
    kl = torch.stack([kl_divergence(policy[k], reference[k]) for k in policy]).sum(0).mean()
    value = -(twohot(returns.detach()) * value_logits.float().log_softmax(-1)).sum(-1).mean()
    return dict(total=pmpo + .3 * kl + value, policy=pmpo, kl=kl, value=value,
                positive=int(positive.sum()), negative=int(negative.sum()))


def state_hash(state):
    digest = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        digest.update(f'{name}:{tensor.dtype}:{tuple(tensor.shape)}'.encode())
        digest.update(tensor.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


def require_stage_two(path, index, inputs, proof, provenance):
    from .agent_evaluation import combine_gates
    value = read_agent_checkpoint(path)
    require(value['schema'] == 'dsp-agent-checkpoint/1' and value['formal'] and value['step'] > 0
            and all(s['source_kind'] == 'live' for s in value['sources']), '需要合格第二階段，工程 checkpoint 不可升級')
    require(all(value['provenance'].get(k) == provenance.get(k) and provenance.get(k) for k in
                ('protocol_id', 'data_freeze_id', 'evaluation_inputs_id', 'annotations_id')), '第二階段凍結來源不同')
    require(isinstance(proof, dict) and set(proof) == {'metrics', 'recipe', 'prediction', 'gate'},
            '正式第三階段需要第二階段三項 gate 證據')
    gate = combine_gates(proof['metrics'], index, inputs, checkpoint_path=path,
                         recipe=proof['recipe'], prediction=proof['prediction'])
    require(gate == proof['gate'] and gate['qualified'] and gate['status'] == 'passed', '第二階段 gate 未通過')
    return value


def validate_imagination_checkpoint(value):
    require(value['imagination_config'] == IMAGINATION_CONFIG, '不相容想像訓練配方')
    require(value['tool_versions'] == TOOL_VERSIONS, '不相容訓練工具版本')
    source = value['stage_two_source']
    require(file_info(source['path']) == source['checkpoint'], '第二階段 checkpoint 已改變')
    original = read_agent_checkpoint(source['path'])
    require(original['schema'] == 'dsp-agent-checkpoint/1' and original['step'] > 0
            and original['formal'] == value['formal'], '需要相同類型的第二階段 checkpoint')
    require(all(value[k] == original[k] for k in ('index_id', 'sources', 'model_config', 'tokenizer_source',
                                                 'agent_config', 'stage_one_source', 'metric')), '第二階段 checkpoint 來源不符')
    require(state_hash(value['model']) == state_hash(original['model']) == value['frozen']['dynamics']
            and state_hash({k: v for k, v in value['agent'].items() if not k.startswith(POLICY_PREFIXES)})
                == state_hash({k: v for k, v in original['agent'].items() if not k.startswith(POLICY_PREFIXES)})
                == value['frozen']['representation_reward']
            and state_hash(value['prior']) == state_hash({k.removeprefix('heads.'): v for k, v in original['agent'].items()
                                                        if k.startswith(POLICY_PREFIXES)}) == value['frozen']['prior'],
            '凍結權重與第二階段不同')
    require(file_info(value['tokenizer_source']['path']) == value['tokenizer_source']['checkpoint'], 'Tokenizer checkpoint 已改變')
    token = torch.load(value['tokenizer_source']['path'], map_location='cpu', weights_only=True)
    require(state_hash(token['model']) == value['frozen']['tokenizer'], '凍結 tokenizer 不符')


class ImaginationTrainer:
    def __init__(self, stage_two_path, index, config, *, device='cuda', formal=False,
                 inputs=None, proof=None, provenance=None):
        value = read_agent_checkpoint(stage_two_path)
        require(value['schema'] == 'dsp-agent-checkpoint/1' and value['step'] > 0, '需載入已更新的第二階段 checkpoint')
        self.provenance = provenance or {}
        if formal:
            require_stage_two(stage_two_path, index, inputs, proof, self.provenance)
            verify_implementation(self.provenance)
            config.validate_formal()
            require(value['model_config'] == asdict(DynamicsConfig()) and index.report['coverage_gate_passed']
                    and torch.device(device).type == 'cuda', '正式架構、資料覆蓋或 CUDA 不符')
        else:
            require(not value['formal'] and all(s['source_kind'] == 'synthetic' for s in index.report['sources']),
                    '工程驗證只接受合成 fixtures')
        require(value['index_id'] == index.report['artifact_id'] and value['sources'] == index.report['sources'],
                '第二階段資料身分不同')
        if value['provenance'].get('implementation'):
            verify_implementation(value['provenance'])
        self.stage_two_source = dict(path=str(Path(stage_two_path).resolve()), checkpoint=file_info(stage_two_path))
        self.source = value
        self.tokenizer_source = value['tokenizer_source']
        require(file_info(self.tokenizer_source['path']) == self.tokenizer_source['checkpoint'], 'Tokenizer checkpoint 已改變')
        self.device = torch.device(device)
        require(self.device.type in ('cpu', 'cuda'), '不支援的 device')
        if self.device.type == 'cuda':
            require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), '需要 BF16 CUDA')
        self.index, self.config, self.formal, self.inputs, self.proof = index, config, formal, inputs, proof
        random.seed(config.seed)
        np.random.seed(config.seed)
        torch.manual_seed(config.seed)
        self.tokenizer, token = load_tokenizer(self.tokenizer_source['path'], device=self.device)
        require(token['index_id'] == value['index_id'] and token['sources'] == value['sources'], 'Tokenizer 資料不符')
        self.model = Agent(Dynamics(DynamicsConfig(**value['model_config']))).to(self.device).eval()
        self.model.load_state_dict({**{f'dynamics.{k}': v for k, v in value['model'].items()}, **value['agent']})
        self.model.requires_grad_(False)
        self.prior = nn.ModuleDict({k: copy.deepcopy(self.model.heads[k]) for k in ('binary', 'mouse', 'wheel')}).eval()
        d = self.model.dynamics.config.width
        self.value = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 255)).to(self.device)
        for key in self.prior:
            self.model.heads[key].requires_grad_(True)
        groups = []
        for module, lr in ((self.model, 3e-5), (self.value, 1e-4)):
            for decay in (True, False):
                parameters = [p for n, p in module.named_parameters() if p.requires_grad
                              and (p.ndim >= 2 and not n.endswith('bias')) == decay]
                groups.append(dict(params=parameters, lr=lr, peak_lr=lr, weight_decay=.01 if decay else 0.))
        self.optimizer = torch.optim.AdamW(groups, betas=(.9, .999), eps=1e-8)
        self.pools = {length: sequence_pools(index, length)['uniform'] for length in {config.short_length, config.long_length}}
        require(all(self.pools.values()), 'Train 缺少合法 context')
        self.step, self.elapsed_seconds = 0, 0.
        self.history = []
        self.frozen = self.frozen_hashes()

    def frozen_hashes(self):
        return dict(tokenizer=state_hash(self.tokenizer.state_dict()), dynamics=state_hash(self.model.dynamics.state_dict()),
            representation_reward=state_hash({k: v for k, v in self.model.state_dict().items()
                                             if not k.startswith(('dynamics.', *POLICY_PREFIXES))}),
            prior=state_hash(self.prior.state_dict()))

    @torch.no_grad()
    def imagine(self, batches, *, deadline=None):
        require(all(b['valid_mask'].all() and b['loss_mask'].all() for b in batches), '想像起點含非法區間')
        rgb = torch.from_numpy(np.stack([b['inputs']['observation'] for b in batches])).to(self.device)
        history = self.tokenizer.encode(rgb).float()[:, -64:]
        past = incoming_actions({k: torch.from_numpy(np.stack([b['inputs'][k] for b in batches])).to(self.device)
                                 for k in ('binary', 'mouse', 'wheel')})
        past = {k: v[:, -64:] for k, v in past.items()}
        task = torch.from_numpy(np.stack([b['inputs']['task_condition'][-1] for b in batches])).to(self.device)
        features, sampled = [], []
        for t in range(16):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('已達預算，想像 rollout 未完成')
            noisy = .1 * history + .9 * torch.randn_like(history)
            h = self.model.features(noisy, past, task[:, None].expand(-1, history.shape[1], -1),
                                    torch.full(history.shape[:2], .1, device=self.device))[:, -1]
            features.append(h.float())
            if t == 15:
                break
            action = sample_action(self.policy_logits(h.float()))
            sampled.append(action)
            following = self.model.dynamics.rollout(history, past, {k: v[:, None] for k, v in action.items()},
                                                    seed=int(torch.randint(2**31, (), device=self.device)))
            history = torch.cat((history, following), 1)[:, -64:]
            past = {k: torch.cat((v, action[k][:, None]), 1)[:, -64:] for k, v in past.items()}
        return dict(features=torch.stack(features, 1), actions={k: torch.stack([a[k] for a in sampled], 1) for k in past},
                    tasks=task.argmax(-1)[:, None].expand(-1, 16))

    def policy_logits(self, features, *, prior=False):
        heads = self.prior if prior else self.model.heads
        return {k: heads[k](features).reshape(*features.shape[:-1], 9, -1)[..., 0, :].float()
                for k in ('binary', 'mouse', 'wheel')}

    def update(self, *, deadline=None):
        cfg = self.config
        require(self.step < cfg.updates and self.elapsed_seconds < cfg.max_seconds, '已達訓練預算')
        require(self.frozen_hashes() == self.frozen, '凍結參數已改變')
        started = time.monotonic()
        deadline = min(deadline or float('inf'), started + cfg.max_seconds - self.elapsed_seconds)
        length = cfg.long_length if self.step % 4 == 3 else cfg.short_length
        rng = random.Random(cfg.seed + self.step)
        samples = [rng.choice(self.pools[length]) for _ in range(cfg.microbatch * cfg.accumulation)]
        trajectories = []
        self.optimizer.zero_grad(set_to_none=True)
        for offset in range(0, len(samples), cfg.microbatch):
            batches = [self.index.views[a].sequence(s, length) for a, s in samples[offset:offset + cfg.microbatch]]
            with torch.autocast(self.device.type, dtype=torch.bfloat16, enabled=self.device.type == 'cuda'):
                trajectories.append(self.imagine(batches, deadline=deadline))
        features = torch.cat([t['features'] for t in trajectories])
        actions = {k: torch.cat([t['actions'][k] for t in trajectories]) for k in ('binary', 'mouse', 'wheel')}
        tasks = torch.cat([t['tasks'] for t in trajectories])
        with torch.no_grad():
            rewards = reward_expectation(self.model.heads['reward'](features[:, :-1]).reshape(len(samples), 15, 9, 255)[:, :, 0])
            rewards = torch.where(tasks[:, :-1] == 16, 0., rewards)
            values = reward_expectation(self.value(features))
            returns = lambda_returns(rewards, values)
            prior = self.policy_logits(features[:, :-1], prior=True)
        losses = imagination_loss(self.policy_logits(features[:, :-1]), prior, actions,
                                  self.value(features[:, :-1]), returns, values[:, :-1])
        require(torch.isfinite(losses['total']).item(), '非有限 loss，停止訓練')
        losses['total'].backward()
        parameters = [p for group in self.optimizer.param_groups for p in group['params']]
        norm = torch.nn.utils.clip_grad_norm_(parameters, 1., error_if_nonfinite=True)
        warmup = max(1, math.ceil(cfg.updates * .05))
        factor = ((self.step + 1) / warmup if self.step < warmup else
                  .1 + .9 * (1 + math.cos(math.pi * (self.step - warmup + 1) / max(1, cfg.updates - warmup))) / 2)
        for group in self.optimizer.param_groups:
            group['lr'] = group['peak_lr'] * factor
        if time.monotonic() >= deadline:
            raise TimeoutError('已達預算，未完成的 update 不更新權重')
        self.optimizer.step()
        require(self.frozen_hashes() == self.frozen, '凍結參數已改變')
        self.step += 1
        self.elapsed_seconds += time.monotonic() - started
        result = dict(step=self.step, length=length, samples=samples, horizon=15, task_ids=tasks[:, 0].tolist(),
            **{k: v.item() if torch.is_tensor(v) else v for k, v in losses.items()}, grad_norm=norm.item(),
            learning_rates=[g['lr'] for g in self.optimizer.param_groups], frozen=self.frozen)
        self.history.append(result)
        return result

    def save(self, path):
        require(self.frozen_hashes() == self.frozen, '凍結參數已改變')
        state = np.random.get_state(legacy=True)
        assert isinstance(state, tuple)
        payload = dict(self.source)
        payload.update(schema='dsp-imagination-checkpoint/1', imagination_config=IMAGINATION_CONFIG,
            tool_versions=TOOL_VERSIONS,
            stage_two_source=self.stage_two_source, stage_two_proof=self.proof, evaluation_inputs=self.inputs,
            prior=self.prior.state_dict(), value=self.value.state_dict(), frozen=self.frozen,
            model=self.model.dynamics.state_dict(), agent={k: v for k, v in self.model.state_dict().items() if not k.startswith('dynamics.')},
            optimizer=self.optimizer.state_dict(), training_config=asdict(self.config), provenance=self.provenance,
            step=self.step, elapsed_seconds=self.elapsed_seconds, history=self.history,
            python_rng=random.getstate(), numpy_rng=(state[0], state[1].tolist(), *state[2:]),
            torch_rng=torch.get_rng_state(), cuda_rng=torch.cuda.get_rng_state_all() if self.device.type == 'cuda' else [],
            device_type=self.device.type)
        save_agent_checkpoint(path, payload)

    @classmethod
    def restore(cls, path, index, *, device='cuda', provenance=None):
        value = read_agent_checkpoint(path)
        require(value['schema'] == 'dsp-imagination-checkpoint/1', '需要第三階段 checkpoint')
        require(value['device_type'] == torch.device(device).type, 'Checkpoint device 不同')
        require(provenance is None or provenance == value['provenance'], 'Checkpoint 凍結資料或實作不同')
        trainer = cls(value['stage_two_source']['path'], index, ImaginationConfig(**value['training_config']), device=device,
            formal=value['formal'], inputs=value['evaluation_inputs'], proof=value['stage_two_proof'], provenance=value['provenance'])
        trainer.model.load_state_dict({**{f'dynamics.{k}': v for k, v in value['model'].items()}, **value['agent']})
        trainer.value.load_state_dict(value['value'])
        trainer.optimizer.load_state_dict(value['optimizer'])
        trainer.step, trainer.elapsed_seconds, trainer.history = value['step'], value['elapsed_seconds'], value['history']
        random.setstate(value['python_rng'])
        state = value['numpy_rng']
        np.random.set_state((state[0], np.array(state[1], dtype=np.uint32), *state[2:]))
        torch.set_rng_state(value['torch_rng'])
        if value['cuda_rng']:
            torch.cuda.set_rng_state_all(value['cuda_rng'])
        return trainer


def export_candidate(path, index, inputs, output, *, metrics, recipe, prediction=None):
    from .agent_evaluation import combine_gates
    value = read_agent_checkpoint(path)
    require(value['schema'] == 'dsp-imagination-checkpoint/1' and value['step'] > 0, '需要已更新的第三階段 checkpoint')
    gate = combine_gates(metrics, index, inputs, checkpoint_path=path, recipe=recipe, prediction=prediction)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(path, output / 'model.pt')
    shutil.copyfile(str(path) + '.json', output / 'model.pt.json')
    require(file_info(path) == file_info(output / 'model.pt'), '候選 checkpoint 複製核對失敗')
    report = seal(dict(schema='dsp-imagination-candidate/1', status=gate['status'], qualified=gate['qualified'],
        checkpoint=file_info(output / 'model.pt'), source_checkpoint=dict(path=str(Path(path).resolve()), checkpoint=file_info(path)),
        stage_two_source=value['stage_two_source'], tokenizer_source=value['tokenizer_source'],
        index_id=value['index_id'], sources=value['sources'], action_codec=value['action_codec'],
        model_config=value['model_config'], agent_config=value['agent_config'], training_config=value['training_config'],
        imagination_config=value['imagination_config'], provenance=value['provenance'], frozen=value['frozen'], gate=gate,
        tool_versions=value['tool_versions'],
        evaluation=dict(metrics=metrics, recipe=recipe, prediction=prediction)))
    atomic_save(output / 'candidate.json', report)
    return report
