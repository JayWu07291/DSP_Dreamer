"""Revise states-01 into states-02; the prior version is retained in commit 1dc97c8."""
import json
from pathlib import Path
import runpy
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import seal, verify_seal, read_protocol

integration_root = Path('runs/catalog-v4/corpus-integration-20260921')
workbench = integration_root / 'workbench'
receipt = load(workbench / 'export.json')
verify_seal(receipt)
require(receipt['artifact_id'] == 'f88618ed686130fa4a21501ec24c6439077dbedc60682782072171ef9fb2366e', 'Different workbench needs new questions')
require(file_info(workbench / 'data.js') == receipt['files']['data.js'], 'Workbench data changed')
workbench_data = json.loads((workbench / 'data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
rows = {r['id']:r for r in workbench_data['reconstruction']}
require(read_protocol('protocols/evaluation-v2.json')['artifact_id'] == workbench_data['protocol_id'], 'Protocol mismatch')
cursor_prompt = '黃色框有沒有圈對這張圖的游標？游標是否清楚、完整，沒有被框切掉？若都符合，填「框選正確，游標清楚完整」。沒圈對或沒圈完整，請選「框的位置不對」；看不清楚，請選「無法可靠判斷」。這題記錄游標位置，供日後檢查模型有沒有把它畫錯位置；不用再描述顏色、形狀或朝向，也不用填座標。'
locations = [
    ('Q01', 'R031', 'cursor', [452,253,469,273], '畫面右下側的游標',
     cursor_prompt),
    ('Q02', 'R091', 'cursor', [364,150,383,171], '合成器配方列表旁的游標',
     cursor_prompt),
    ('Q03', 'R021', 'recipe', [413,261,466,340], '合成器下方的配方詳情',
     '合成器目前選中的配方叫什麼？請只寫配方名稱，不寫製造佇列。'),
    ('Q04', 'R111', 'connection', [373,211,456,256], '下方採礦機與旁邊熔爐的連接',
     '這條連接把物品從哪個建築送到哪個建築？目前是否已接通？請寫「起點 → 終點；已接通／未接通」。若無法從原圖確認方向或接通狀態，請選無法可靠判斷。'),
    ('Q05', 'R111', 'connection', [246,126,335,184], '上方採礦機與左邊熔爐的連接',
     '只看框內採礦機與左邊那座熔爐之間的連接。物品從哪裡送到哪裡，目前是否已接通？請寫「起點 → 終點；已接通／未接通」。若看不清楚，請選無法可靠判斷。'),
]
questions = []
for qid, sample, kind, box, target, prompt in locations:
    source = rows[sample]
    require(file_info(workbench / source['image']) == receipt['files'][source['image']], 'Question image changed')
    require(0 <= box[0] < box[2] <= 640 and 0 <= box[1] < box[3] <= 360, 'Invalid question box')
    questions.append(dict(id=qid, source=source, type=kind, box=box, target=target, prompt=prompt,
        image_sha256=receipt['files'][source['image']]['sha256']))
batch = seal(dict(schema='dsp-guided-annotation-batch/2', workbench_id=receipt['artifact_id'],
    protocol_id=workbench_data['protocol_id'], index_id=workbench_data['index_id'], evaluation_inputs_id=workbench_data['evaluation_inputs_id'],
    questions=questions, status='pending', training_authorized=False))
guided = runpy.run_path('tools/guided-annotation.py')
empty = dict(schema='dsp-guided-annotation-answers/2', batch_id=batch['artifact_id'], status='pending', training_authorized=False, answers={})
draft = guided['checked_answers'](batch, empty)
require(len(draft['pending_questions']) == 5 and draft['whole_frames_reviewed'] == 0, 'Empty answers must remain pending')
out = integration_root / 'guided-states-02'
out.mkdir(exist_ok=False)
for relative in {q['source']['image'] for q in questions}:
    target = out / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(workbench / relative, target)
    require(file_info(target) == receipt['files'][relative], 'Copied image differs')
atomic_save(out / 'batch.json', batch)
(out / 'batch.js').write_text('const BATCH = ' + json.dumps(batch, ensure_ascii=False).replace('<','\\u003c') + ';\n', encoding='utf-8')
shutil.copyfile('tools/guided-annotation.html', out / 'index.html')
atomic_save(out / 'export.json', seal(dict(schema='dsp-guided-annotation-export/1', batch_id=batch['artifact_id'],
    files={p.relative_to(out).as_posix():file_info(p) for p in out.rglob('*') if p.is_file()}, status='pending', training_authorized=False)))
print(batch['artifact_id'])
