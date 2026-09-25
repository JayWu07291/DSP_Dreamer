import copy
import json
import subprocess
import sys

import numpy as np

from dsp_dreamer import Recording, compile_recording, open_dataset
from dsp_dreamer.actions import ACTION_CODEC
from dsp_dreamer.contract import CATALOG, sha
from dsp_dreamer.runner import episode_result
from test_control import FFMPEG


def test_runner_deadline_denominators_and_consecutive_misses():
    from dsp_dreamer.runner import timing_report
    steps = [dict(step=i, capture_ticks=i * 100, requested_ticks=i * 100 + 20,
                  missed=False) for i in range(100)]
    steps[50].update(missed=True, requested_ticks=5101)
    report = timing_report(steps, 1000)
    assert report['passed'] and report['miss_fraction'] == .01
    assert abs(report['p99_ms'] - 20.81) < 1e-9
    for i in range(5):
        steps[i]['missed'] = True
    report = timing_report(steps, 1000)
    assert not report['passed'] and report['max_consecutive_misses'] == 5
    assert timing_report([], 1000)['p95_ms'] is None


def test_checkpoint_policy_rgb_history_and_episode_reset(tmp_path):
    import torch
    from dsp_dreamer.runner import CheckpointPolicy
    from dsp_dreamer.contract import InvalidRecording
    import pytest

    # Reuse a real, chained engineering checkpoint created by the public training integration test.
    from test_agent import test_stage_one_loader_finetuning_resume_and_gate_rejection
    test_stage_one_loader_finetuning_resume_and_gate_rejection(tmp_path)
    policy = CheckpointPolicy(tmp_path / 'agent.pt', engineering_only=True, device='cpu')
    rgb = np.zeros((360, 640, 3), dtype=np.uint8)
    tasks = np.eye(17, dtype=np.float32)
    noop = copy.deepcopy(ACTION_CODEC['noop'])
    policy.reset(29)
    assert policy.act(rgb, noop, tasks[0]) == noop
    expected = policy.act(rgb, noop, tasks[1])
    assert policy.history_steps == 2  # Prompt changes keep the preceding observation.
    policy.reset(29)
    assert policy.act(rgb, noop, tasks[0]) == noop
    assert policy.act(rgb, noop, tasks[1]) == expected
    with pytest.raises(InvalidRecording, match='工程'):
        CheckpointPolicy(tmp_path / 'agent.pt', engineering_only=False, device='cpu')
    with pytest.raises(InvalidRecording, match='RGB'):
        policy.act(rgb[..., 0], noop, tasks[0])
    with pytest.raises(InvalidRecording, match='17'):
        policy.act(rgb, noop, np.ones(17))
    messages = bytearray()
    sample = dict(ticks=1, sequence_number=1, held=[], down=[], up=[], delta=[0, 0], wheel=0)
    for i, episode in enumerate(('one', 'one', 'two')):
        header = dict(episode_id=episode, capture_id=i, capture_ticks=100 + i * 100,
                      task_id=i, policy_seed=29, inputs=[sample])
        messages.extend(json.dumps(header).encode() + b'\n' + bytes(640 * 360 * 4))
    import ctypes
    counter = ctypes.c_longlong()
    ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(counter))
    offset, before = counter.value - 1_000_000, counter.value
    child = subprocess.run([sys.executable, '-m', 'dsp_dreamer.runner', '--checkpoint', str(tmp_path / 'agent.pt'),
                            '--engineering-only', '--device', 'cpu', '--delay-ms', '120',
                            '--clock-offset-ticks', str(offset)],
                           input=messages, capture_output=True, timeout=60, check=True)
    ready, first, second, reset = [json.loads(line) for line in child.stdout.splitlines()]
    assert ready['ready'] and not ready['qualified']
    assert {k: first[k] for k in noop} == {k: reset[k] for k in noop} == noop
    assert {k: second[k] for k in noop} == expected
    ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(counter))
    assert before - offset <= first['inference_started_ticks'] <= reset['inference_ticks'] <= counter.value - offset
    assert (second['inference_ticks'] - second['inference_started_ticks']) / ready['frequency'] >= .12


def test_runner_result_uses_observed_inputs_and_keeps_failure_separate(tmp_path):
    with Recording.synthetic(tmp_path / 'source', FFMPEG) as recording:
        recording.begin_attempt(dict(manifest_id='trial', split_group_id='trial',
                                     mecha_seed=1, camera_seed=2, policy_seed=3))
        recording.metadata.update(control_mode='policy', runner=dict(status='engineering_only',
            qualified=False, checkpoint_sha256='a' * 64,
            action_codec_sha256=sha(json.dumps(ACTION_CODEC, sort_keys=True).encode())))
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for i, capture in enumerate((50, 150, 250)):
            action = copy.deepcopy(ACTION_CODEC['noop'])
            if i:
                action['binary'][1] = 1  # Requested Digit1, but the actual input remains no-op.
            recording.events.append(dict(recording.identity(capture + 20), type='control_request',
                operation='model_action', request_id=i + 1, catalog=CATALOG, **action,
                capture_ticks=capture, inference_ticks=capture + 10, requested_ticks=capture + 20,
                sent_count=1, requested_count=1, succeeded=True))
            recording.events.append(dict(recording.identity(capture + 20), type='control_request',
                operation='runner_step', step=i, capture_ticks=capture, inference_started_ticks=capture + 2,
                inference_ticks=capture + 10, requested_ticks=capture + 20, request_id=i + 1, missed=False))
            recording.input(capture + 30, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(355), type='control_request', operation='release_all',
            requested_ticks=355, sent_count=21, requested_count=21, succeeded=True))
        recording.input(365, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for ticks in range(50, 401, 50):
            if ticks == 400:
                recording.end_episode(380, outcome='death')
            recording.complete(recording.request(ticks, 1, 1), np.zeros((360, 640, 4), dtype=np.uint8))
    evidence = recording.publish(tmp_path / 'evidence')
    dataset = open_dataset(compile_recording(evidence, tmp_path / 'dataset', FFMPEG))
    result = episode_result(dataset)
    assert result['status'] == 'engineering_only' and result['qualified'] is False
    assert result['episode_outcome'] == 'death'
    assert result['validity_status'] == 'invalid' and 'injection_failure' in result['validity_reasons']
    assert result['timing']['p95_ms'] == result['timing']['p99_ms'] == 20
    assert result['timing']['miss_fraction'] == 0
    assert result['control']['requests'][0]['observed_ticks'] == 80
    assert result['control']['requests'][1]['observed_ticks'] is None
    assert dataset[0]['action']['binary'] == [0] * 21
