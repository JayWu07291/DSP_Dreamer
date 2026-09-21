"""Prepare the remaining three UI types using the prior static page's styling."""
import html
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import read_protocol, seal, verify_seal

integration_root = Path('runs/catalog-v4/corpus-integration-20260921')
workbench = integration_root / 'workbench'
export = load(workbench / 'export.json')
verify_seal(export)
require(export['artifact_id'] == 'f88618ed686130fa4a21501ec24c6439077dbedc60682782072171ef9fb2366e', 'Different workbench needs new proposals')
require(file_info(workbench / 'data.js') == export['files']['data.js'], 'Workbench changed')
workbench_data = json.loads((workbench / 'data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
require(read_protocol('protocols/evaluation-v2.json')['artifact_id'] == workbench_data['protocol_id'], 'Protocol changed')
rows = {row['id']:row for row in workbench_data['reconstruction']}
proposals = []
for identity, source_id, panel, ui_type, box in [
    ('3A','R016','科技樹（整個畫面）','technology',[0,0,640,360]),
    ('4A','R081','電弧熔爐視窗露出的上半部','building',[15,26,244,75]),
    ('4B','R081','配方選取視窗','building',[7,74,287,284]),
    ('5A','R157','矩陣研究站視窗','lab',[277,84,523,245]),
]:
    source = rows[source_id]
    require(file_info(workbench / source['image']) == export['files'][source['image']], 'Source image changed')
    require(0 <= box[0] < box[2] <= 640 and 0 <= box[1] < box[3] <= 360, 'Invalid region')
    proposals.append(dict(id=identity,source=source,panel=panel,ui_type=ui_type,box=box,
        image_sha256=export['files'][source['image']]['sha256'],reviewed=False))
batch = seal(dict(schema='dsp-ui-region-review-batch/1',workbench_id=export['artifact_id'],
    protocol_id=workbench_data['protocol_id'],index_id=workbench_data['index_id'],
    evaluation_inputs_id=workbench_data['evaluation_inputs_id'],proposals=proposals,
    status='pending',training_authorized=False,whole_frames_reviewed=0))
prior_folder = integration_root / 'ui-regions-01'
prior_export = load(prior_folder / 'export.json')
verify_seal(prior_export)
require(prior_export['batch_id'] == '124b6a8e18b625c1b977c5b4c37fc4c4f55df58e225625c5516c40ce7607cd84', 'Different prior page')
require(file_info(prior_folder / 'index.html') == prior_export['files']['index.html'], 'Prior template changed')
prior_page = (prior_folder / 'index.html').read_text(encoding='utf-8')
require(prior_page.count('<h1>') == 1, 'Unknown page structure')
head = prior_page.split('<h1>',1)[0]
out = integration_root / 'ui-regions-02'
out.mkdir(exist_ok=False)
cards = []
for number, source_id in ((3,'R016'),(4,'R081'),(5,'R157')):
    group = [p for p in proposals if p['source']['id'] == source_id]
    relative = group[0]['source']['image']
    target = out / relative
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(workbench / relative,target)
    require(file_info(target) == export['files'][relative], 'Copied image differs')
    marks = []
    for p in group:
        x0,y0,x1,y1 = p['box']
        marks.append(f'<div class="mark" style="left:{x0/6.4}%;top:{y0/3.6}%;width:{(x1-x0)/6.4}%;height:{(y1-y0)/3.6}%"><span>{html.escape(p["id"])}</span></div>')
    legend = '；'.join(html.escape(p['id']+'：'+p['panel']) for p in group)
    cards.append(f'<section><h2>第 {number} 張</h2><p>{legend}</p><div class="picture"><img src="{html.escape(relative,quote=True)}" alt="第 {number} 張原始遊戲畫面，框的位置見上方說明">{"".join(marks)}</div></section>')
page = head + '''<style>.mark span{top:auto;left:auto;bottom:0;right:0}</style><h1>確認另外四個 UI 框</h1>
<p>上一組四個框已保存。這次確認科技樹、熔爐操作視窗與矩陣研究站的範圍，供之後比較 UI 畫面的重建誤差。</p>
<p>確認青框的名稱與畫面相符，而且完整圈住指定的可見範圍。3A 是全畫面的科技樹；4A 只圈熔爐視窗露出的上半部，下方被 4B 配方選取視窗擋住；5A 圈研究站視窗。</p>
<p class="notice">看完回到對話回答。都符合可回「3A、4A、4B、5A 都正確」。有問題就指出編號、名稱或哪條邊需要修正；看不清楚也可以直接說。這些框尚待人工確認，不用填座標或匯出 JSON。</p>
''' + ''.join(cards) + '<p>這次只確認上述 UI 範圍；其餘區域與整圖仍待後續確認。</p></html>'
require(page.count('class="mark"') == len(proposals) == 4 and len(cards) == 3
        and all(p['reviewed'] is False for p in proposals), 'Invalid review page')
(out / 'index.html').write_text(page,encoding='utf-8')
atomic_save(out / 'batch.json',batch)
receipt = seal(dict(schema='dsp-ui-region-review-export/1',batch_id=batch['artifact_id'],path=out.as_posix(),
    files={p.relative_to(out).as_posix():file_info(p) for p in out.rglob('*') if p.is_file()},
    preparer=dict(path=Path(__file__).as_posix(),file=file_info(__file__)),
    reused_template=dict(export_id=prior_export['artifact_id'],file=prior_export['files']['index.html']),
    status='pending',training_authorized=False,historical_datasets_opened=0,corpus_rebuilt=False))
atomic_save(out / 'export.json',receipt)
atomic_save('docs/validation/ui-regions-02-prepared-20260921.json',receipt)
print(batch['artifact_id'])
