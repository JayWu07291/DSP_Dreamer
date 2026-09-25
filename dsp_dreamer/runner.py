"""Single-episode policy inference and evidence-bound engineering results."""
import copy
import json
from pathlib import Path
import sys
import time

import numpy as np

from .actions import ACTION_CODEC, decode_action, encode_action
from .contract import file_info, require, sha
from .control import inspect_control
from .dataset import aggregate


def timing_report(steps, frequency):
    require(frequency > 0, '無效控制時鐘')
    elapsed, misses, consecutive, longest = [], 0, 0, 0
    for index, row in enumerate(steps):
        require(row['step'] == index, '控制步缺失或重複')
        start, end = row['capture_ticks'], row['requested_ticks']
        require(0 <= start <= end, '無效 capture/request 時間')
        latency = (end - start) * 1000 / frequency
        elapsed.append(latency)
        miss = row['missed'] or latency > 100
        misses += int(miss)
        consecutive = consecutive + 1 if miss else 0
        longest = max(longest, consecutive)
    p95, p99 = np.percentile(elapsed, [95, 99]).tolist() if elapsed else (None, None)
    fraction = misses / len(steps) if steps else None
    return dict(steps=len(steps), misses=misses, miss_fraction=fraction, max_consecutive_misses=longest,
                p95_ms=p95, p99_ms=p99, passed=bool(p95 is not None and p99 is not None
                and fraction is not None and p95 <= 80 and p99 <= 100 and fraction <= .01 and longest < 5))


def episode_result(dataset):
    episodes = dataset.metadata['episodes']
    require(len(episodes) == 1, '單回合 runner 需要一個回合')
    episode = episodes[0]
    identity = dataset.metadata['runner']
    require(identity['action_codec_sha256'] == sha(json.dumps(ACTION_CODEC, sort_keys=True).encode())
            and identity['status'] == 'engineering_only'
            and identity['qualified'] is False, '未支援或未核准的 runner 身分')
    steps = [e for e in dataset.events if e['type'] == 'control_request' and e.get('operation') == 'runner_step']
    steps.sort(key=lambda e: (e['ticks'], e['sequence_number']))
    timing = timing_report(steps, dataset.metadata['ticks_frequency'])
    control = inspect_control(dataset)
    reasons = list(episode['validity_reasons'])
    if not timing['passed']:
        reasons.append('system_latency')
    if (not control['requests'] or not control['releases']
            or any(not r['observed'] for r in control['requests'])
            or any(not r['submitted'] or r['required'] and not r['released'] for r in control['releases'])):
        reasons.append('injection_failure')
    requests = {r['request_id']: r for r in control['requests']}
    for row in steps:
        row['observed_ticks'] = requests.get(row['request_id'], {}).get('observed_ticks')
    return dict(schema='dsp-runner-result/1', status='engineering_only', qualified=False,
        checkpoint_sha256=identity['checkpoint_sha256'], dataset_id=dataset.metadata['artifact_id'],
        dataset_completed=file_info(dataset.path / 'COMPLETED'), source_manifest=dataset.metadata['source_manifest'],
        trial_manifest=dataset.metadata['trial_manifest'], episode_id=episode['episode_id'], attempt_id=episode['attempt_id'],
        episode_outcome=episode['episode_outcome'], final_capture_id=episode['final_capture_id'],
        validity_status='incomplete' if episode['final_capture_id'] is None else 'invalid' if reasons else 'valid',
        validity_reasons=sorted(set(reasons)), timing=timing, steps=steps, control=control)


class CheckpointPolicy:
    def __init__(self, checkpoint, *, engineering_only=False, device='cuda'):
        import torch
        from .agent import Agent
        from .agent_training import read_agent_checkpoint
        from .dynamics import Dynamics, DynamicsConfig
        from .dynamics_training import load_tokenizer

        value = read_agent_checkpoint(checkpoint)
        # Formal candidate admission belongs to #34/#35 and must recheck all source-bound gates.
        require(engineering_only and not value['formal'] and value['status'] == 'engineering_only',
                '此入口只允許明確指定的工程 checkpoint，不能啟動正式試驗')
        source = value['tokenizer_source']
        require(file_info(source['path']) == source['checkpoint'], 'Tokenizer checkpoint 已改變')
        self.tokenizer, _ = load_tokenizer(source['path'], device=device)
        self.model = Agent(Dynamics(DynamicsConfig(**value['model_config']))).to(device).eval()
        self.model.load_state_dict({**{f'dynamics.{k}': v for k, v in value['model'].items()}, **value['agent']})
        self.device = torch.device(device)
        self.identity = dict(status='engineering_only', qualified=False, checkpoint_sha256=file_info(checkpoint)['sha256'],
                             action_codec_sha256=sha(json.dumps(ACTION_CODEC, sort_keys=True).encode()),
                             history_steps=64, signal=.1)
        self.reset(0)

    def reset(self, seed):
        self.seed, self.step = seed, 0
        self.frames: list = []
        self.actions: list = []
        self.tasks: list = []

    @property
    def history_steps(self):
        return len(self.frames)

    def act(self, rgb, observed_action, task_condition):
        import torch
        from .agent import policy_action

        require(isinstance(rgb, np.ndarray) and rgb.dtype == np.uint8 and rgb.shape == (360, 640, 3),
                '需要完整 640×360 uint8 RGB')
        require(np.shape(task_condition) == (17,) and np.isin(task_condition, [0, 1]).all()
                and np.sum(task_condition) == 1, '需要 17 維 one-hot 任務條件')
        decode_action(observed_action)
        self.frames = [*self.frames[-63:], rgb.copy()]
        self.actions = [*self.actions[-63:], copy.deepcopy(observed_action)]
        self.tasks = [*self.tasks[-63:], np.array(task_condition, dtype=np.float32)]
        self.step += 1
        if self.step == 1:
            return copy.deepcopy(ACTION_CODEC['noop'])
        # Changing history shapes otherwise retain >10 GiB of unused CUDA blocks on Windows.
        if self.device.type == 'cuda':
            torch.cuda.empty_cache()
        with torch.inference_mode(), torch.autocast(self.device.type, dtype=torch.bfloat16,
                                                    enabled=self.device.type == 'cuda'):
            frames = torch.from_numpy(np.stack(self.frames)).permute(0, 3, 1, 2).unsqueeze(0).to(self.device).float() / 255
            past = {k: torch.tensor([[a[k] for a in self.actions]], device=self.device) for k in ACTION_CODEC['noop']}
            tasks = torch.from_numpy(np.stack(self.tasks)).unsqueeze(0).to(self.device)
            clean = self.tokenizer.encode(frames).float()
            generator = torch.Generator(device=self.device).manual_seed(self.seed + self.step)
            noisy = .1 * clean + .9 * torch.randn(clean.shape, device=self.device, generator=generator)
            outputs = self.model(noisy, past, tasks, torch.full(clean.shape[:2], .1, device=self.device))
            return policy_action({k: v[0, -1, 0].float() for k, v in outputs.items()})


def serve(checkpoint, *, engineering_only=False, device='cuda', delay_ms=0, clock_offset_ticks=0):
    """Private child-process pipe: JSON line, then exactly one RGBA frame. No network listener."""
    import ctypes
    import os
    import torch

    require(os.name == 'nt', 'Live runner 需要 Windows QPC 時鐘')
    require(type(delay_ms) is int and 0 <= delay_ms <= 1000, '無效工程延遲')
    torch.set_num_threads(2)
    frequency = ctypes.c_longlong()
    require(ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(frequency)), '無法取得 QPC frequency')

    def ticks():
        value = ctypes.c_longlong()
        require(ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(value)), '無法取得 QPC')
        return value.value - clock_offset_ticks

    def reply(value):
        print(json.dumps(value, allow_nan=False), flush=True)

    policy = CheckpointPolicy(checkpoint, engineering_only=engineering_only, device=device)
    # Warm the real model before the capture clock. It does not update any weights.
    blank = np.zeros((360, 640, 3), dtype=np.uint8)
    task = np.eye(17, dtype=np.float32)[0]
    policy.act(blank, ACTION_CODEC['noop'], task)
    policy.act(blank, ACTION_CODEC['noop'], task)
    if policy.device.type == 'cuda':
        torch.cuda.synchronize()
    reply(dict(ready=True, frequency=frequency.value, **policy.identity))
    episode, previous_ticks = None, 0
    stream = sys.stdin.buffer
    while line := stream.readline(2_000_000):
        require(line.endswith(b'\n'), '過長或不完整的控制訊息')
        header = json.loads(line)
        require(set(header) == {'episode_id', 'capture_id', 'capture_ticks', 'task_id', 'policy_seed', 'inputs'},
                '不允許的 policy 封包欄位')
        data = stream.read(640 * 360 * 4)
        require(len(data) == 640 * 360 * 4, '不完整 RGB 封包')
        require(type(header['task_id']) is int and 0 <= header['task_id'] < 17, '未知 task ID')
        start = ticks()
        if episode != header['episode_id']:
            episode, previous_ticks = header['episode_id'], 0
            policy.reset(header['policy_seed'])
        current = header['capture_ticks']
        require(type(current) is int and previous_ticks < current <= start, '無效 capture 時間')
        observed = copy.deepcopy(ACTION_CODEC['noop'])
        if previous_ticks:
            samples = sorted(header['inputs'], key=lambda e: (e['ticks'], e['sequence_number']))
            before = [s for s in samples if s['ticks'] < previous_ticks]
            require(bool(before), '實際動作歷史已超過有界緩衝區')
            selected = [s for s in samples if previous_ticks <= s['ticks'] < current]
            observed = encode_action(aggregate(selected, previous_ticks, current, before[-1]['held']))
        rgb = np.frombuffer(data, np.uint8).reshape(360, 640, 4)[..., :3]
        action = policy.act(rgb, observed, np.eye(17, dtype=np.float32)[header['task_id']])
        if delay_ms and policy.step > 1:
            time.sleep(delay_ms / 1000)
        end = ticks()
        reply(dict(episode_id=episode, capture_id=header['capture_id'], capture_ticks=current,
                   inference_started_ticks=start, inference_ticks=end, **action))
        previous_ticks = current


def main():
    import argparse
    parser = argparse.ArgumentParser(description='單回合工程 policy 工作程序')
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--engineering-only', action='store_true')
    parser.add_argument('--device', choices=['cuda', 'cpu'], default='cuda')
    parser.add_argument('--delay-ms', type=int, default=0, help='工程故障測試延遲；不適用正式試驗')
    parser.add_argument('--clock-offset-ticks', type=int, default=0, help='Windows QPC 與錄製器時鐘原點差')
    args = parser.parse_args()
    serve(args.checkpoint, engineering_only=args.engineering_only, device=args.device, delay_ms=args.delay_ms,
          clock_offset_ticks=args.clock_offset_ticks)


if __name__ == '__main__':
    main()
