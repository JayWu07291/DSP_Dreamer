"""Prepare four UI boundary proposals from two already-exported validation PNGs."""
import html
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import read_protocol, seal, verify_seal

root = Path('runs/catalog-v4/corpus-integration-20260921')
workbench = root / 'workbench'
export = load(workbench / 'export.json')
verify_seal(export)
require(export['artifact_id'] == 'f88618ed686130fa4a21501ec24c6439077dbedc60682782072171ef9fb2366e', 'Different workbench needs new proposals')
require(file_info(workbench / 'data.js') == export['files']['data.js'], 'Workbench changed')
work = json.loads((workbench / 'data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
require(read_protocol('protocols/evaluation-v2.json')['artifact_id'] == work['protocol_id'], 'Protocol changed')
rows = {row['id']:row for row in work['reconstruction']}
proposals = []
for number, source_id, right_bottom in ((1, 'R021', 348), (2, 'R091', 267)):
    source = rows[source_id]
    require(file_info(workbench / source['image']) == export['files'][source['image']], 'Source image changed')
    for letter, panel, ui_type, box in [('A', '物品清單', 'backpack', [17,29,244,151]),
                                       ('B', '合成器', 'crafting', [322,14,617,right_bottom])]:
        require(0 <= box[0] < box[2] <= 640 and 0 <= box[1] < box[3] <= 360, 'Invalid region')
        proposals.append(dict(id=f'{number}{letter}', source=source, panel=panel, ui_type=ui_type,
            box=box, image_sha256=export['files'][source['image']]['sha256'], reviewed=False))
batch = seal(dict(schema='dsp-ui-region-review-batch/1', workbench_id=export['artifact_id'],
    protocol_id=work['protocol_id'], index_id=work['index_id'], evaluation_inputs_id=work['evaluation_inputs_id'],
    proposals=proposals, status='pending', training_authorized=False, whole_frames_reviewed=0))
out = root / 'ui-regions-01'
out.mkdir(exist_ok=False)
cards = []
for offset in (0,2):
    pair = proposals[offset:offset+2]
    relative = pair[0]['source']['image']
    target = out / relative
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(workbench / relative, target)
    require(file_info(target) == export['files'][relative], 'Copied image differs')
    marks = []
    for proposal in pair:
        x0,y0,x1,y1 = proposal['box']
        label = html.escape(f"{proposal['id']} {proposal['panel']}")
        marks.append(f'<div class="mark" style="left:{x0/6.4}%;top:{y0/3.6}%;width:{(x1-x0)/6.4}%;height:{(y1-y0)/3.6}%"><span>{label}</span></div>')
    cards.append(f'<section><h2>第 {offset//2+1} 張</h2><div class="picture"><img src="{html.escape(relative, quote=True)}" alt="第 {offset//2+1} 張原始遊戲畫面；青框 A 為物品清單，B 為合成器">{"".join(marks)}</div></section>')
page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>確認四個 UI 面板框</title><style>
body{font:18px/1.7 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;background:#f2f5f6;color:#20313f}section{background:white;padding:20px;margin:24px 0;border:1px solid #ccd5dd;border-radius:10px}h1,h2{line-height:1.4}.picture{position:relative;line-height:0}img{width:100%;display:block}.mark{position:absolute;box-sizing:border-box;border:2px solid #00dcef;outline:1px solid #102c37;pointer-events:none}.mark span{position:absolute;top:0;left:0;background:#073c48;color:white;font:14px/1.4 system-ui;padding:1px 4px}.notice{padding:16px;background:#fff3cc}
</style><h1>確認四個 UI 面板框</h1>
<p>這次確認左側「物品清單」和右側「合成器」的範圍。之後會在這些範圍比較原圖與模型重建圖。</p>
<p>看每個青色框：是否圈住整個面板，包含標題、內容及面板底部，沒有漏掉一截或明顯多圈到外面的場景？框上的名稱也要符合畫面。</p>
<p class="notice">看完直接回到對話回答，不用在這頁輸入。四個都符合就回「1A、1B、2A、2B 都正確」。有問題請指出編號及哪一邊，例如「1A 左邊漏了一截」；無法判斷也可直接說。這些框目前只是待確認提案。</p>
''' + ''.join(cards) + '<p>這四個回答只確認指定 UI 面板。整圖與其他 UI 區域仍待後續確認。</p></html>'
(out / 'index.html').write_text(page, encoding='utf-8')
atomic_save(out / 'batch.json', batch)
receipt = seal(dict(schema='dsp-ui-region-review-export/1', batch_id=batch['artifact_id'],
    path=out.as_posix(), files={p.relative_to(out).as_posix():file_info(p) for p in out.rglob('*') if p.is_file()},
    preparer=dict(path=Path(__file__).as_posix(), file=file_info(__file__)),
    status='pending', training_authorized=False, historical_datasets_opened=0, corpus_rebuilt=False))
atomic_save(out / 'export.json', receipt)
atomic_save('docs/validation/ui-regions-prepared-20260921.json', receipt)
require(len(proposals) == 4 and len({p['source']['image'] for p in proposals}) == 2
        and all(p['reviewed'] is False for p in proposals) and page.count('class="mark"') == 4, 'Invalid review page')
print(batch['artifact_id'])
