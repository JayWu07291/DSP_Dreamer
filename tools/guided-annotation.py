"""Prepare source-bound questions or check human answers into a partial draft."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import runpy
import shutil

lesson = runpy.run_path(str(Path(__file__).with_name('export-annotation-lesson.py')))
atomic_save, file_info, load, require, sha = (lesson[k] for k in ('atomic_save', 'file_info', 'load', 'require', 'sha'))

# Manually located on the original validation PNGs. No proposed answers are included.
QUESTIONS = [
    ('Q01', 'R031', [0, 224, 79, 245], '左側物品提示，上面一行'),
    ('Q02', 'R031', [0, 245, 77, 267], '左側物品提示，下面一行'),
    ('Q03', 'R041', [27, 46, 53, 69], '左上角背包，第一格'),
    ('Q04', 'R051', [0, 245, 79, 267], '左側物品提示，最下面一行'),
    ('Q05', 'R071', [0, 245, 79, 267], '左側物品提示，最下面一行'),
]
ITEMS = ['鐵礦', '銅礦', '石礦', '煤礦', '鐵塊', '銅塊', '石材', '磁鐵', '磁線圈', '電路板', '齒輪', '採礦機', '電磁矩陣']


def seal(value):
    return dict(value, artifact_id=sha(json.dumps(value, sort_keys=True, allow_nan=False).encode()))


def export_batch(workbench, out):
    workbench, out = workbench.resolve(), out.resolve()
    require(out != workbench and out not in workbench.parents and workbench not in out.parents,
            'Output must not overlap source workbench')
    require(not out.exists(), 'Refusing batch overwrite')
    receipt, work = lesson['verified_workbench'](workbench)
    rows = {r['id']: r for r in work['reconstruction']}
    questions = [dict(id=q, source=rows[r], box=b, target=t) for q, r, b, t in QUESTIONS]
    for q in questions:
        relative = q['source']['image']
        require(file_info(workbench / relative) == receipt['files'][relative], 'Question image changed')
        q['image_sha256'] = receipt['files'][relative]['sha256']
    batch = seal(dict(schema='dsp-guided-annotation-batch/1', workbench_id=receipt['artifact_id'],
        protocol_id=work['protocol_id'], index_id=work['index_id'], evaluation_inputs_id=work['evaluation_inputs_id'],
        questions=questions, item_options=ITEMS, status='pending', training_authorized=False))
    out.mkdir(parents=True)
    for q in questions:
        relative = q['source']['image']
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(workbench / relative, target)
        require(file_info(target) == receipt['files'][relative], 'Copied image differs')
    atomic_save(out / 'batch.json', batch)
    (out / 'batch.js').write_text('const BATCH = ' + json.dumps(batch, ensure_ascii=False).replace('<', '\\u003c') + ';\n', encoding='utf-8')
    shutil.copyfile(Path(__file__).with_name('guided-annotation.html'), out / 'index.html')
    atomic_save(out / 'export.json', seal(dict(schema='dsp-guided-annotation-export/1', batch_id=batch['artifact_id'],
        files={p.relative_to(out).as_posix(): file_info(p) for p in out.rglob('*') if p.is_file()},
        status='pending', training_authorized=False)))
    return batch


def checked_answers(batch, submission):
    """Recompute labels from human answers. A local item never approves a whole frame."""
    require(batch.get('artifact_id') == seal({k: v for k, v in batch.items() if k != 'artifact_id'})['artifact_id'],
            'Batch seal mismatch')
    require(batch.get('schema') in (None, 'dsp-guided-annotation-batch/1', 'dsp-guided-annotation-batch/2'), 'Unknown batch schema')
    is_state_batch = batch.get('schema') == 'dsp-guided-annotation-batch/2'
    schema = 'dsp-guided-annotation-answers/2' if is_state_batch else 'dsp-guided-annotation-answers/1'
    if is_state_batch:
        require(all(q.get('type') in ('cursor', 'recipe', 'connection') and isinstance(q.get('prompt'), str)
                    and q['prompt'].strip() for q in batch['questions']), 'Invalid state question')
    require(set(submission) == {'schema', 'batch_id', 'status', 'training_authorized', 'answers'}, 'Unexpected answer fields')
    require(submission['schema'] == schema and submission['batch_id'] == batch['artifact_id']
            and submission['status'] == 'pending' and submission['training_authorized'] is False
            and isinstance(submission['answers'], dict), 'Answer provenance mismatch')
    questions = {q['id']: q for q in batch['questions']}
    records: dict = {}
    pending = []
    for key, a in submission['answers'].items():
        require(key in questions and isinstance(a, dict) and set(a) ==
                ({'status', 'expected', 'reviewer', 'answered_at'} if is_state_batch else
                 {'status', 'item', 'count', 'reviewer', 'answered_at'}), 'Unknown question or answer fields')
        require(isinstance(a['reviewer'], str) and 0 < len(a['reviewer'].strip()) <= 80, 'Missing reviewer')
        require(isinstance(a['answered_at'], str) and datetime.fromisoformat(a['answered_at'].replace('Z', '+00:00')).tzinfo is not None,
                'Answer timestamp must have timezone')
        require(a['status'] in ('readable', 'unreadable', 'wrong_target'), 'Invalid answer status')
        if is_state_batch:
            require(isinstance(a['expected'], str) and 0 < len(a['expected'].strip()) <= 800
                    if a['status'] == 'readable' else a['expected'] is None, 'Invalid state description or uncertain answer')
        elif a['status'] == 'readable':
            require(isinstance(a['item'], str) and 0 < len(a['item'].strip()) <= 80 and isinstance(a['count'], str)
                    and 0 < len(a['count']) <= 6 and a['count'].isascii() and a['count'].isdigit(), 'Invalid item or complete number')
        else:
            require(a['item'] is None and a['count'] is None, 'Uncertain answers cannot contain guessed labels')
        q = questions[key]
        if a['status'] == 'wrong_target':
            pending.append(dict(question_id=key, reason='需要重新框選或修改題目'))
            continue
        source = q['source']
        r = records.setdefault('reconstruction:' + source['id'], dict(mode='reconstruction', source=source, items=[],
            category='', region=None, ui_regions=[], reviewed=False, reviewer=a['reviewer'], reviewed_at=a['answered_at'],
            note='引導題的局部項目已填答；整張圖的其他關鍵項目與 UI 區域仍待確認。'))
        expected = a['expected'] if is_state_batch else f"{q['target']}：{a['item']}；完整數字={a['count']}"
        r['items'].append(dict(type=q['type'] if is_state_batch else 'item_number', box=q['box'],
            expected=expected if a['status'] == 'readable' else '',
            eligible=a['status'] == 'readable', exclusion_reason=None if a['status'] == 'readable' else
                ('原圖指定位置的狀態無法可靠辨識' if is_state_batch else '原圖指定位置的物品或完整數字無法可靠辨識'),
            question_id=key, reviewer=a['reviewer'], reviewed_at=a['answered_at']))
    pending.extend(dict(question_id=k, reason='尚未填答') for k in questions if k not in submission['answers'])
    return dict(schema='dsp-annotation-draft/1', protocol_id=batch['protocol_id'], index_id=batch['index_id'],
        evaluation_inputs_id=batch['evaluation_inputs_id'], reviewer='逐項保存', records=records,
        status='pending', training_authorized=False, guided_batch_id=batch['artifact_id'],
        pending_questions=pending, whole_frames_reviewed=0)


def check_submission(folder, answers, out):
    folder, out = folder.resolve(), out.resolve()
    require(out != folder and folder not in out.parents and out != answers.resolve(), 'Draft must not overwrite its inputs')
    require(not out.exists(), 'Refusing draft overwrite')
    receipt = load(folder / 'export.json')
    require(receipt.get('artifact_id') == seal({k: v for k, v in receipt.items() if k != 'artifact_id'})['artifact_id'], 'Export seal mismatch')
    for relative, info in receipt['files'].items():
        target = (folder / relative).resolve()
        require(folder in target.parents and file_info(target) == info, 'Export file changed or outside folder')
    batch = load(folder / 'batch.json')
    require(batch['artifact_id'] == receipt['batch_id'], 'Export batch mismatch')
    draft = checked_answers(batch, load(answers))
    atomic_save(out, draft)
    return draft


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='準備引導題，或核對人工回答並產生局部草稿；不凍結標籤')
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    for name in ('workbench', 'out'):
        export.add_argument('--' + name, type=Path, required=True)
    check = sub.add_parser('check')
    for name in ('batch', 'answers', 'out'):
        check.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'export':
        result = export_batch(args.workbench, args.out)
    else:
        result = check_submission(args.batch, args.answers, args.out)
    print(json.dumps(dict(out=str(args.out), status=result['status'], training_authorized=False)))
