"""Task-conditioned agent queries over the task-blind dynamics transformer."""
import torch
from torch import nn
from torch.nn import functional as F

from .actions import ACTION_CODEC, forbidden_buttons
from .contract import require


AGENT_CONFIG = dict(tasks=17, distances=9, reward_bins=255, reward_support='symexp(-20:20)',
                    query_tokens=1, attention='one-way cross-attention over final world tokens')


def incoming_actions(actions):
    """Observation z_t sees a_(t-1); a_t is exclusively a supervision target."""
    return {k: torch.cat((torch.tensor(ACTION_CODEC['noop'][k], device=v.device)
                         .expand(v.shape[0], 1, *v.shape[2:]), v[:, :-1]), 1) for k, v in actions.items()}


class Agent(nn.Module):
    def __init__(self, dynamics):
        super().__init__()
        self.dynamics = dynamics
        d = dynamics.config.width
        self.task = nn.Linear(17, d, bias=False)
        self.query = nn.Parameter(torch.randn(1, 1, d) * .02)
        self.cross = nn.MultiheadAttention(d, dynamics.config.heads, batch_first=True)
        self.norm = nn.LayerNorm(d)
        self.heads = nn.ModuleDict({k: nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 9 * n))
                                   for k, n in dict(binary=21, mouse=121, wheel=3, reward=255).items()})

    def forward(self, noisy, past_actions, task_condition, levels):
        require(tuple(task_condition.shape) == (*noisy.shape[:2], 17)
                and ((task_condition == 0) | (task_condition == 1)).all().item()
                and (task_condition.sum(-1) == 1).all().item(), '需要 17 維 one-hot 任務條件')
        # No task or agent representation is ever passed to the world transformer.
        hidden = self.dynamics.hidden(noisy, past_actions, levels, .25)
        query = self.query + self.task(task_condition).flatten(0, 1)[:, None]
        memory = hidden.flatten(0, 1)
        attended, _ = self.cross(query, memory, memory, need_weights=False)
        features = self.norm(query + attended).reshape(*noisy.shape[:2], -1)
        return {k: head(features).reshape(*features.shape[:2], 9, -1) for k, head in self.heads.items()}


def reward_support(device):
    positive = torch.expm1(torch.arange(1, 128, device=device, dtype=torch.float32) * (20 / 127))
    return torch.cat((-positive.flip(0), positive.new_zeros(1), positive))


def twohot(values):
    """Interpolate in reward units between exponentially spaced support values."""
    support = reward_support(values.device)
    require(torch.isfinite(values).all().item(), '非有限 reward target')
    values = values.float().clamp(support[0], support[-1])
    upper = torch.searchsorted(support, values.contiguous()).clamp(1, 254)
    lower = upper - 1
    weight = (values - support[lower]) / (support[upper] - support[lower])
    target = values.new_zeros(*values.shape, 255)
    target.scatter_add_(-1, lower[..., None], (1 - weight)[..., None])
    target.scatter_add_(-1, upper[..., None], weight[..., None])
    return target


def reward_expectation(logits):
    probabilities = logits.double().softmax(-1)
    support = reward_support(logits.device).double()
    # Pair symmetric bins to give exactly zero for a symmetric distribution.
    return ((probabilities[..., 128:] - probabilities[..., :127].flip(-1)) * support[128:]).sum(-1).float()


def mtp_loss(outputs, actions, rewards, task_condition, valid_mask, loss_mask):
    tasks = task_condition.argmax(-1)
    legal = ((actions['binary'] == 0) | (actions['binary'] == 1)).all(-1)
    for k, classes in (('mouse', 121), ('wheel', 3)):
        legal &= (actions[k] >= 0) & (actions[k] < classes)
    legal &= torch.tensor([not forbidden_buttons(row) for row in actions['binary'].flatten(0, 1).tolist()],
                          device=tasks.device).reshape_as(tasks)
    legal &= torch.isfinite(rewards) & ((rewards == 0) | (rewards == 1)) & ((tasks != 16) | (rewards == 0))
    valid = valid_mask & legal
    policy = outputs['binary'].float().reshape(-1)[:0].sum()
    reward = outputs['reward'].float().reshape(-1)[:0].sum()
    counts = []
    steps = tasks.shape[1]
    for distance in range(9):
        count = max(0, steps - distance)
        mask = valid[:, :count] & loss_mask[:, :count]
        for offset in range(1, distance + 1):
            mask = mask & valid[:, offset:offset+count] & (tasks[:, :count] == tasks[:, offset:offset+count])
        counts.append(int(mask.sum()))
        if not counts[-1]:
            continue
        target = {k: v[:, distance:distance+count][mask] for k, v in actions.items()}
        logits = {k: v[:, :count, distance][mask].float() for k, v in outputs.items()}
        policy = policy + F.binary_cross_entropy_with_logits(logits['binary'], target['binary'].float(), reduction='sum')
        for k in ('mouse', 'wheel'):
            policy = policy + F.cross_entropy(logits[k], target[k], reduction='sum')
        reward = reward - (twohot(rewards[:, distance:distance+count][mask]) * logits['reward'].log_softmax(-1)).sum()
    denominator = max(1, sum(counts))
    return dict(total=(policy + reward) / denominator, policy=policy / denominator,
                reward=reward / denominator, counts=counts)


def policy_action(logits, *, legal=True):
    """Raw threshold decisions for scoring; constrained decisions for control."""
    require(all(torch.isfinite(logits[k]).all().item() for k in ('binary', 'mouse', 'wheel')), '非有限 policy')
    bits = (logits['binary'] >= 0).long().tolist()
    if legal:
        # Reuse the codec's exclusions; prefer larger logits, ties by catalog index.
        active = sorted((i for i, bit in enumerate(bits) if bit), key=lambda i: (-float(logits['binary'][i]), i))
        bits = [0] * ACTION_CODEC['binary_width']
        for i in active:
            bits[i] = 1
            if forbidden_buttons(bits):
                bits[i] = 0
    return dict(binary=bits, mouse=int(logits['mouse'].argmax()), wheel=int(logits['wheel'].argmax()))
