"""三階段共用的累計預算、測速、恢復與驗證排程。"""
from contextlib import contextmanager
from dataclasses import asdict, replace
import copy
import json
import math
import os
from pathlib import Path
import random
import time
import uuid

import numpy as np
import torch

from .actions import ACTION_CODEC, validate_action_contract
from .contract import atomic_save, file_info, load, require
from .evaluation_protocol import seal, verify_seal


STAGE_SECONDS = dict(preflight=7200, A=14400, B=57600, second=21600, third=14400)


def plan_updates(seconds, durations):
    require(math.isfinite(seconds) and seconds > 0 and len(durations) >= 4 and len(durations) % 4 == 0
            and all(math.isfinite(v) and v > 0 for v in durations), '測速需完整四次更新及有限時間')
    return math.floor(.9 * seconds * len(durations) / sum(durations))


class TrainingBudget:
    def __init__(self, path, *, formal=True, clock=time.monotonic, wall_clock=time.time):
        self.path, self.formal = Path(path), formal
        self.clock, self.wall_clock = clock, wall_clock
        self.active = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.path.with_suffix('.lock').open('a+b')
        try:
            self.lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
            self.state = load(self.path) if self.path.exists() else dict(
                schema='dsp-training-budget/1', id=str(uuid.uuid4()), formal=self.formal,
                action_codec=ACTION_CODEC, attempts=[], stages={}, imports=[])
            require(self.state['schema'] == 'dsp-training-budget/1' and self.state['formal'] == self.formal,
                    '預算帳本版本或工程／正式用途不同')
            validate_action_contract(self.state['action_codec'])
            require(all(a['stage'] in STAGE_SECONDS and math.isfinite(a['seconds']) and a['seconds'] >= 0
                        for a in self.state['attempts']), '預算帳本含無效時數')
            for attempt in self.state['attempts']:
                if attempt['status'] == 'running':
                    # 無法得知強制終止時點，保守計入到重啟，最多扣完原先保留額度。
                    attempt.update(seconds=max(attempt['seconds'], min(attempt['reserved'],
                        max(0., self.wall_clock() - attempt['started']))), status='interrupted')
            self.save()
            return self
        except BaseException:
            self.lock.close()
            raise

    def __exit__(self, *args):
        self.lock.close()

    def save(self):
        temporary = self.path.with_suffix('.partial')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(self.state, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def import_history(self, path, stage, attempts, *, key=None):
        identity = dict(path=str(Path(path).resolve()), file=file_info(path), key=key or str(Path(path).resolve()))
        previous = [v for v in self.state['imports'] if v['key'] == identity['key']]
        if previous:
            require(previous == [identity], '已匯入的歷史用量被修改，需核對原始紀錄')
            return
        require(stage in STAGE_SECONDS, '未知預算階段')
        for row in attempts:
            seconds = row['seconds']
            if seconds is None:
                seconds = max(0., self.wall_clock() - row['started'])
            require(math.isfinite(seconds) and seconds >= 0, '歷史預算時間無效')
            self.state['attempts'].append(dict(row, stage=stage, seconds=seconds,
                status='interrupted' if row['seconds'] is None else row['status'], source=identity))
        self.state['imports'].append(identity)
        self.save()

    def remaining(self, stage):
        require(stage in STAGE_SECONDS, '未知預算階段')
        return max(0., min(STAGE_SECONDS[stage] - sum(a['seconds'] for a in self.state['attempts']
            if a['stage'] == stage), sum(STAGE_SECONDS.values()) - sum(a['seconds'] for a in self.state['attempts'])))

    def progress(self, stage):
        return self.state['stages'].setdefault(stage, dict(updates=0, validation_seconds=0.,
            latest=None, gate=dict(status='pending', qualified=False), plan=None))

    def invalidate(self, stage, status):
        progress = self.progress(stage)
        progress['gate'] = dict(status=status, qualified=False)
        progress.pop('evaluation', None)
        progress.pop('candidate', None)

    def require_upstream(self, stage, path):
        parent = dict(B='A', second='B', third='second').get(stage)
        if parent is None:
            return
        progress = self.progress(parent)
        require(self.formal and progress['gate'].get('qualified') and progress['gate']['status'] == 'passed'
                and progress.get('candidate') is not None,
                '前階段 gate 未通過或待驗證，停止依賴階段')
        require(path is not None and file_info(path) == progress['candidate']['file'], '前階段候選身分不同')

    def record_evaluation(self, stage, checkpoint, directory, gate):
        directory = Path(directory)
        self.progress(stage)['evaluation'] = dict(checkpoint=file_info(checkpoint),
            directory=str(directory.resolve()), artifacts={str(p.resolve()): file_info(p)
            for name in ('metrics.json', 'recipe.json') for p in directory.rglob(name)})
        self.progress(stage)['gate'] = dict(gate, qualified=self.formal and gate['status'] == 'passed',
                                           checkpoint_sha256=file_info(checkpoint)['sha256'])
        self.save()

    def require_evaluation(self, stage, checkpoint, control, metrics, *, prediction_metrics=None):
        evaluation = self.progress(stage).get('evaluation')
        require(control is not None and control['budget_id'] == self.state['id'] and control['stage'] == stage
                and evaluation is not None and file_info(checkpoint) == evaluation['checkpoint'],
                '評分需要本帳本已完成完整 gate 的候選')
        require(str(Path(metrics).resolve()) in evaluation['artifacts']
                and (prediction_metrics is None or str(Path(prediction_metrics).resolve()) in evaluation['artifacts'])
                and all(file_info(p) == v for p, v in evaluation['artifacts'].items()), '候選評估 metrics／recipe 已改變')

    @contextmanager
    def attempt(self, stage, command, *, microbatch=2, target=None):
        require(self.active is None and self.remaining(stage) > 0, '已達預算或已有執行中的工作')
        target = target or stage
        require(command != 'benchmark' or self.progress(target)['plan'] is None, '已有固定計畫，不可重新測速追加更新數')
        if self.formal and command in ('benchmark', 'train'):
            previous = [a for a in self.state['attempts'] if a.get('target', a['stage']) == target]
            require(microbatch in (1, 2), '正式 microbatch 只接受 2/8 或 1/16')
            oom = [a for a in previous if a['status'] == 'cuda_oom']
            require(not any(a['microbatch'] == 1 for a in oom), '1/16 仍顯存不足，停止')
            require((microbatch == 2 and not oom) or (microbatch == 1 and bool(oom)),
                    'OOM 後只可改 1/16 並重新測速')
        attempt = dict(stage=stage, target=target, command=command, microbatch=microbatch,
            started=self.wall_clock(), seconds=0., reserved=self.remaining(stage), status='running')
        self.state['attempts'].append(attempt)
        self.active, self.started = attempt, self.clock()
        self.deadline = self.started + attempt['reserved']
        if command in ('train', 'benchmark', 'evaluate'):
            self.invalidate(target, 'pending')
        self.save()
        try:
            yield self
            if attempt['status'] == 'running':
                attempt['status'] = 'completed'
        except torch.cuda.OutOfMemoryError:
            attempt['status'] = 'cuda_oom'
            if command in ('train', 'benchmark'):
                self.progress(target)['plan'] = None
            if command in ('train', 'benchmark', 'evaluate'):
                self.invalidate(target, 'failed')
            raise
        except TimeoutError:
            attempt['status'] = 'budget_exhausted'
            if command in ('train', 'benchmark', 'evaluate'):
                self.invalidate(target, 'pending')
            raise
        except BaseException:
            attempt['status'] = 'failed'
            if command in ('train', 'benchmark', 'evaluate'):
                self.invalidate(target, 'failed')
            raise
        finally:
            self.tick()
            self.active = None

    def tick(self):
        if self.active is not None:
            self.active['seconds'] = max(self.active['seconds'], self.clock() - self.started)
        self.save()


def import_existing_usage(budget, root):
    """既有 A 用量維持原歸屬；#25 兩次 GPU smoke 計入前置額度。"""
    root = Path(root)
    token = root / 'runs/tokenizer-budget.json'
    source = token if token.exists() else root / 'docs/issue-24-results.json'
    value = load(source)
    budget.import_history(source, 'A', (value if token.exists() else value['budget'])['attempts'], key='legacy-tokenizer')
    dynamics = root / 'runs/dynamics-budget.json'
    if dynamics.exists():
        budget.import_history(dynamics, 'B', load(dynamics)['attempts'], key='legacy-dynamics')
    history = root / 'docs/training-history.json'
    budget.import_history(history, 'preflight', load(history)['attempts'])


def trainer_identity(trainer):
    config = asdict(trainer.config)
    config.pop('updates')
    config.pop('max_seconds')
    model = trainer.model.dynamics if hasattr(trainer.model, 'dynamics') else trainer.model
    metric = trainer.loss.identity if hasattr(trainer, 'loss') else (
        trainer.source['metric'] if hasattr(trainer, 'source') else trainer.metric_identity)
    return dict(trainer=type(trainer).__name__, model=asdict(model.config), training=config,
        index_id=trainer.index.report['artifact_id'], sources=trainer.index.report['sources'],
        provenance=trainer.provenance, device_type=trainer.device.type,
        metric=metric,
        source=getattr(trainer, 'stage_two_source', getattr(trainer, 'stage_one_source', getattr(trainer, 'tokenizer_source', None))))


def synchronize(trainer):
    if trainer.device.type == 'cuda':
        torch.cuda.synchronize(trainer.device)


def benchmark(trainer, budget, stage, output, *, update_limit=None):
    require(budget.active is not None and budget.active['stage'] == 'preflight'
            and budget.active['target'] == stage, '測速必須計入前置預算')
    require(trainer.step == 0 and trainer.config.updates >= 4, '測速需要新的四步訓練器')
    if budget.formal:
        trainer.config.validate_formal()
        require(trainer.device.type == 'cuda' and all(s['source_kind'] == 'live' for s in trainer.index.report['sources'])
                and getattr(trainer, 'formal', True), '合成 smoke 不可估計正式 throughput')
        torch.cuda.reset_peak_memory_stats(trainer.device)
    durations = []
    for _ in range(4):
        synchronize(trainer)
        started = budget.clock()
        trainer.update(deadline=budget.deadline)
        synchronize(trainer)
        durations.append(budget.clock() - started)
        budget.tick()
    progress = budget.progress(stage)
    require(progress['plan'] is None, '已有固定計畫，不可重新測速追加更新數')
    ceiling = progress['updates'] + plan_updates(budget.remaining(stage), durations)
    if 'update_ceiling' in progress:
        ceiling = min(ceiling, progress['update_ceiling'])
    if update_limit is not None:
        require(type(update_limit) is int and update_limit > progress['updates'], '更新上限無效')
        ceiling = min(ceiling, update_limit)
    require(ceiling > progress['updates'], '剩餘預算不足一次更新')
    plan = seal(dict(schema='dsp-training-plan/1', stage=stage, formal=budget.formal,
        status='measured' if budget.formal else 'engineering_only', budget_id=budget.state['id'],
        identity=trainer_identity(trainer), durations=durations, lengths=[r['length'] for r in trainer.history],
        gpu=torch.cuda.get_device_name(trainer.device) if trainer.device.type == 'cuda' else None,
        peak_allocated_gib=torch.cuda.max_memory_allocated(trainer.device) / 2**30 if trainer.device.type == 'cuda' else None,
        peak_reserved_gib=torch.cuda.max_memory_reserved(trainer.device) / 2**30 if trainer.device.type == 'cuda' else None,
        updates=ceiling, update_fraction=.9, remaining_seconds=budget.remaining(stage)))
    atomic_save(output, plan)
    progress['plan'] = plan
    progress['update_ceiling'] = ceiling
    budget.save()
    return plan


@contextmanager
def preserve_rng(trainer):
    python, numpy = random.getstate(), np.random.get_state()
    devices = [trainer.device.index if trainer.device.index is not None else torch.cuda.current_device()] if trainer.device.type == 'cuda' else []
    try:
        with torch.random.fork_rng(devices=devices):
            yield
    finally:
        random.setstate(python)
        np.random.set_state(numpy)


def run_training(trainer, budget, stage, output, evaluate):
    """evaluate(checkpoint, directory, full, deadline) 回傳既有評分器的 gate。"""
    require(budget.active is not None and budget.active['stage'] == stage, '訓練需要本階段預算')
    progress = budget.progress(stage)
    plan = progress['plan']
    require(plan is not None, '需先執行完整 loader/loss 測速')
    verify_seal(plan)
    require(plan['budget_id'] == budget.state['id'] and plan['formal'] == budget.formal
            and plan['identity'] == trainer_identity(trainer), '測速計畫與訓練資料／配置不同')
    control = getattr(trainer, 'control', None)
    if progress['latest']:
        require(control is not None and control['budget_id'] == budget.state['id']
                and control['checkpoint_id'] == progress['latest']['id'], '必須從帳本最新 checkpoint 恢復')
        require(file_info(progress['latest']['path']) == progress['latest']['file'], '最新 checkpoint 已改變')
    else:
        require(trainer.step == 0 and control is None, '新流程需從第零步開始')
    require(control is None or control['stage'] == stage, 'Checkpoint 階段不同')
    trainer.config = replace(trainer.config, updates=plan['updates'])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    atomic_save(output / 'recipe.json', seal(dict(plan=plan, training=asdict(trainer.config),
        action_codec=ACTION_CODEC, provenance=trainer.provenance)))
    status = 'completed'
    checkpoint_path = None

    def save_checkpoint(label):
        nonlocal checkpoint_path
        budget.tick()
        trainer.elapsed_seconds = sum(a['seconds'] for a in budget.state['attempts'] if a['stage'] == stage)
        checkpoint_id = str(uuid.uuid4())
        trainer.control = dict(budget_id=budget.state['id'], stage=stage, checkpoint_id=checkpoint_id,
            plan=plan, progress=copy.deepcopy(progress), budget=copy.deepcopy(budget.state))
        checkpoint_path = output / f'{label}-{trainer.step}.pt'
        trainer.save(checkpoint_path)
        progress['latest'] = dict(path=str(checkpoint_path.resolve()), file=file_info(checkpoint_path), id=checkpoint_id)
        budget.tick()
        return checkpoint_path

    def validate(full):
        path = save_checkpoint('candidate' if full else f'validation-{progress["updates"]}')
        with preserve_rng(trainer):
            gate = evaluate(path, output / ('gate' if full else f'validation-{progress["updates"]}'), full, budget.deadline)
        budget.tick()
        if full:
            budget.record_evaluation(stage, path, output / 'gate', gate)
            if progress['gate']['qualified']:
                progress['candidate'] = copy.deepcopy(progress['latest'])
        else:
            progress['validation_seconds'] = sum(a['seconds'] for a in budget.state['attempts'] if a['stage'] == stage)
        budget.save()

    try:
        save_checkpoint('start')
        while progress['updates'] < plan['updates'] and trainer.step < trainer.config.updates:
            budget.tick()
            if budget.clock() >= budget.deadline or trainer.elapsed_seconds >= trainer.config.max_seconds:
                raise TimeoutError('已達階段時數預算')
            spent = sum(a['seconds'] for a in budget.state['attempts'] if a['stage'] == stage)
            if spent - progress['validation_seconds'] >= 1800:
                validate(False)
            # 先記帳。強制終止或失敗的更新也消耗一次上限，不因舊 checkpoint 退回。
            progress['updates'] += 1
            budget.save()
            trainer.elapsed_seconds = sum(a['seconds'] for a in budget.state['attempts'] if a['stage'] == stage)
            trainer.update(deadline=budget.deadline)
        if budget.clock() >= budget.deadline:
            raise TimeoutError('已達階段時數預算')
        validate(True)
    except TimeoutError:
        status = 'budget_exhausted'
        budget.active['status'] = status
        budget.invalidate(stage, 'pending')
    except BaseException:
        status = 'failed'
        budget.invalidate(stage, 'failed')
        raise
    finally:
        if status == 'completed':
            save_checkpoint('final')
        else:
            # 更新失敗可能已部分修改 AdamW；只恢復最近完整發布的權重與 RNG。
            checkpoint_path = Path(progress['latest']['path']) if progress['latest'] else None
            budget.tick()
        report = seal(dict(schema='dsp-training-run/1', status=status, formal=budget.formal,
            quality_status=progress['gate']['status'] if budget.formal else 'engineering_only',
            checkpoint=str(checkpoint_path) if checkpoint_path else None, updates=trainer.step, charged_updates=progress['updates'],
            planned_updates=plan['updates'], budget=copy.deepcopy(budget.state), gate=progress['gate']))
        atomic_save(output / 'run.json', report)
    return report


def select_candidate(budget, *, third_improved=False):
    """只有開發比較已確認改善才選第三階段；未執行或平手保留第二階段。"""
    for stage in (('third', 'second') if third_improved else ('second',)):
        progress = budget.progress(stage)
        candidate = progress.get('candidate')
        if budget.formal and progress['gate'].get('qualified') and candidate:
            require(file_info(candidate['path']) == candidate['file']
                    and progress['gate']['checkpoint_sha256'] == candidate['file']['sha256'], '候選或 gate 身分不符')
            return candidate
    return None
