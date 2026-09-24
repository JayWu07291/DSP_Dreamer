"""Finish proposals for classified movement/waiting rows; never confirm for Jay.

Run with --check to verify the saved handoff without reopening datasets.
"""
from collections import Counter
import html
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import seal, verify_seal

ROOT = Path('runs/catalog-v4/corpus-integration-20260921')
OUT = ROOT / 'sequence-state-completion-01'
# Each description was read from its own native step15 original.
CURSORS = {
    'P021': '游標停在銅礦採礦機上，旁邊顯示採礦機提示。',
    'P080': '游標在機甲左側、兩座採礦機之間的地面上。',
    'P087': '游標在銅礦脈右下方的地面上。',
    'P091': '游標在機甲右側、兩條產線之間的地面上。',
    'P100': '游標在銅礦脈右側的地面上。',
    'P130': '游標在合成介面的磁線圈配方圖示旁，圖示有外框。',
    'P135': '游標在機甲下方的建造格線上。',
    'P151': '游標停在底部建造選單的採礦機圖示上，顯示採礦機說明。',
    'P167': '游標在機甲右下方、銅礦脈右側的地面上。',
    'P181': '游標在機甲右上方、風力渦輪機左上側的地面上。',
    'P186': '游標在機甲下方、銅礦熔爐左側的地面上。',
    'P189': '放置游標在兩條產線之間的空地上，旁邊顯示選擇起點物體。',
    'P202': '游標在合成介面的空白配方格內、齒輪圖示右下方。',
    'P001': '游標在登陸艙右上方的地面上。',
    'P006': '游標在電磁學研究完成提示的確定按鈕上。',
    'P007': '游標在機甲左下方的地面上。',
    'P013': '游標停在上排右邊的熔爐上，熔爐有綠色外框。',
    'P014': '游標停在左邊製造台上，顯示製造台提示。',
    'P016': '游標在機甲下方的地面上。',
    'P017': '游標在登陸艙右上方的地面上。',
    'P023': '游標在銅礦採礦機右下方的地面上。',
    'P026': '游標在銅礦採礦機旁的熔爐上方。',
    'P028': '放置游標在上排熔爐右側的建造格線上。',
    'P030': '游標停在底部建造選單的研究站圖示旁。',
    'P033': '游標在登陸艙右上方的地面上。',
    'P042': '游標在銅礦採礦機左下方、傳送帶下方的地面上。',
    'P043': '放置游標在銅礦熔爐上，旁邊顯示選擇起點物體。',
    'P046': '游標停在左邊製造台上，顯示製造台提示。',
    'P048': '游標在機甲右上方、風力渦輪機上方的地面上。',
    'P049': '游標在登陸艙右上方的地面上。',
    'P053': '游標在機甲右上方、風力渦輪機左上側的地面上。',
    'P058': '游標在銅礦採礦機左下方、傳送帶下方的地面上。',
    'P063': '游標在研究站右側、銅礦熔爐左側的地面上。',
    'P064': '游標在銅礦採礦機左側、熔爐右下方的地面上。',
    'P065': '游標在登陸艙右上方的地面上。',
    'P073': '游標在機甲上方的水面上。',
    'P075': '游標在底部建造選單的採集分類圖示旁。',
    'P081': '游標停在登陸艙右下邊緣，靠近黃色圓環。',
    'P086': '游標在鐵礦採礦機右側的地面上。',
    'P090': '游標在機甲下方、銅礦熔爐左側的建造格線上。',
    'P097': '游標停在登陸艙右下邊緣，靠近黃色圓環。',
    'P105': '游標在合成介面的空白配方格內、電力感應塔圖示下方。',
    'P107': '放置游標在上排右邊熔爐上，旁邊顯示選擇起點物體。',
    'P110': '游標在兩座製造台右下方的地面上。',
    'P112': '游標在機甲上方的地面上。',
    'P113': '游標在登陸艙右上方的地面上。',
    'P119': '游標在銅礦採礦機左側、機甲下方的地面上。',
    'P122': '游標在銅礦採礦機左下邊緣旁的地面上。',
    'P124': '游標在銅礦熔爐下方的地面上。',
    'P125': '游標停在右邊製造台上，顯示製造台提示。',
    'P126': '游標停在左邊製造台上，顯示製造台提示。',
    'P128': '游標停在銅礦熔爐上。',
    'P129': '游標在登陸艙右上方的地面上。',
    'P137': '游標在合成介面頂部製造佇列內、齒輪圖示右側。',
    'P142': '游標停在右邊製造台上，顯示製造台提示。',
    'P154': '游標在銅礦採礦機左側、傳送帶下方的地面上。',
    'P158': '游標停在左邊製造台上，顯示製造台提示。',
    'P161': '游標在登陸艙右上方的地面上。',
    'P172': '放置游標在上排熔爐右側的建造格線上。',
    'P173': '游標在基礎製造研究完成提示的確定按鈕上。',
    'P176': '游標在銅礦採礦機左下邊緣旁的地面上。',
    'P177': '游標停在登陸艙右下邊緣，靠近黃色圓環。',
    'P182': '游標在鐵礦採礦機右側的地面上。',
    'P183': '游標在機甲右上方的地面上。',
    'P185': '游標在風力渦輪機正上方的地面上。',
    'P190': '游標在底部建造選單上方空白區，靠近分揀器圖示右側。',
    'P193': '游標在登陸艙右上方的地面上。',
    'P197': '游標在畫面上方、岸邊附近的建造格線上。',
    'P201': '游標在機甲右上方的水面上。',
    'P203': '游標在機甲右側、兩條產線之間的地面上。',
    'P204': '放置游標在銅礦熔爐上，旁邊顯示選擇起點物體。',
}
STATES = {key: dict(type='cursor', expected=value) for key, value in CURSORS.items()}
STATES.update({
    'P025': dict(type='recipe', expected='熔爐介面選用銅塊配方。'),
    'P037': dict(type='recipe', expected='合成介面選中電路板配方。'),
    'P057': dict(type='recipe', expected='熔爐介面選用磁鐵配方。'),
    'P074': dict(type='recipe', expected='合成介面選中電路板配方。'),
    'P150': dict(type='item_number', expected='左側取得物品提示顯示齒輪，數量 22。'),
    'P169': dict(type='recipe', expected='熔爐介面選用銅塊配方。'),
})


def prepare():
    receipt = load('docs/validation/movement-supplement-01-confirmed-20260924.json')
    verify_seal(receipt)
    aggregate = load(receipt['draft']['path'])
    verify_seal(aggregate)
    require(file_info(receipt['draft']['path']) == receipt['draft']['file'], 'Changed confirmed aggregate')
    work = ROOT / 'workbench'
    export = load(work / 'export.json')
    verify_seal(export)
    require(export['artifact_id'] == aggregate['workbench_id'], 'Wrong workbench')
    require(file_info(work / 'data.js') == export['files']['data.js'], 'Changed source mapping')
    data = json.loads((work / 'data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
    sources = {r['id']: r for r in data['prediction']}
    rows = [r for r in aggregate['rows'] if r['classification_reviewed'] and not r['reviewed'] and r['category'] in ('movement', 'waiting')]
    rows.sort(key=lambda r: (r['category'], r['source']['id']))
    require({r['source']['id'] for r in rows} == set(STATES) and len(rows) == 77, 'Incomplete state proposals')
    proposals = []
    for row in rows:
        s = row['source']
        require(s == sources[s['id']], 'Changed classified source')
        proposals.append(dict(source=s, category=row['category'], classification_reviewed=True,
            classification_aggregate_id=aggregate['artifact_id'], suggested_regions=[[0, 0, 640, 360]],
            region_basis='protocol_waiting_full_frame' if row['category'] == 'waiting' else 'camera_changes_scene',
            suggested_key_states=[STATES[s['id']]], key_state_step=15, reviewed=False, proposer='assistant'))
    common = {k: aggregate[k] for k in ('protocol_id','index_id','workbench_id','evaluation_inputs_id')}
    batch = seal(dict(schema='dsp-sequence-state-proposals/1', **common, proposals=proposals,
        human_aggregate_id=aggregate['artifact_id'], scope='regions_and_step15_key_states_only',
        proposed_counts=dict(Counter(r['category'] for r in rows)), reviewed_count=0,
        status='pending', training_authorized=False))
    template_dir = ROOT / 'movement-priority-review-01'
    template_export = load(template_dir / 'export.json'); verify_seal(template_export)
    require(file_info(template_dir / 'index.html') == template_export['files']['index.html'], 'Changed player template')
    template = (template_dir / 'index.html').read_text(encoding='utf-8')
    cards = []
    for p in proposals:
        s = p['source']; key = s['id']; label = '移動／視角' if p['category'] == 'movement' else '等待'
        images = ''.join(f'<figure><a href="{path}" target="_blank" rel="noopener"><img src="{path}" alt="{key} {caption}" loading="lazy"></a><figcaption>{caption}</figcaption></figure>'
            for path, caption in zip(s['images'][:2], ('起點原圖', '第 5 步原圖')))
        cards.append(f'''<section id="{key}"><h2>{key} <small>已確認分類：{label}</small></h2>
<p><strong>① 評估範圍：整張畫面。</strong></p>
<p><strong>② 末幀狀態：</strong>{html.escape(p['suggested_key_states'][0]['expected'])}</p>
<a href="{s['images'][2]}" target="_blank" rel="noopener"><img src="{s['images'][2]}" alt="{key} 第 15 步原圖" loading="lazy" style="display:block;width:100%;max-width:640px;height:auto"></a>
<details><summary>需要時展開前後原圖與影片</summary><div class="frames">{images}</div>
<video controls preload="none" aria-label="{key} 原始片段" data-begin="{s['begin']}" data-boundary="{s['boundary']}" data-end="{s['end']}" src="{s['video']}#t={s['boundary']},{s['end']}"></video>
<div class="buttons"><button data-mode="boundary">播放這 1.5 秒</button><button data-mode="begin">連同前情播放</button></div><p class="message" role="status"></p></details>
<a href="#top">回到題目索引</a></section>''')
    page = template.split('<h1>',1)[0].replace('移動候選：確認已整理的標註', '既有分類：核對範圍與末幀狀態') + '''<h1 id="top">補齊既有分類：只核對範圍與末幀狀態</h1>
<p>27 題確認已保存。四種分類都已足額，三項完整的候選目前有 37 段。</p>
<p>這頁合併原先的 13 段移動與 64 段等待，共 77 題。分類已確認，不用重答；只看每題兩項新內容。移動片段因鏡頭改變、等待片段依既定規則，範圍均填整張畫面。</p>
<p class="notice">全數符合就回覆「77 題的兩項都正確」。有誤只列題號、項次與修正；不確定可直接寫不確定。不用重寫整段操作，也不需補錄。可以分次核對，回覆已看完的題號即可。</p>
<p>每題先顯示第 15 步原圖，點圖可放大；需要時才展開影片與前兩張圖。分類依第 5 步，末幀可能已開始下一個操作，兩者不同不代表要重改分類。</p>
<p>全數通過後，移動 50 段、等待 64 段會有完整標註，可滿足這兩類各取 50 的需求。UI 63 段與建造／物品 64 段的範圍及狀態仍待整理；P085 保留待判定。</p>
<nav aria-label="題目索引">''' + ' · '.join(f'<a href="#{p["source"]["id"]}">{p["source"]["id"]}</a>' for p in proposals) + '</nav>' + ''.join(cards) + '<script>' + template.split('<script>',1)[1]
    require(not OUT.exists(), 'Refusing to overwrite handoff')
    OUT.mkdir()
    assets = sorted({path for p in proposals for path in [p['source']['video'], *p['source']['images']]})
    for relative in assets:
        require((work / relative).resolve().is_relative_to(work.resolve()), 'Asset escapes source')
        require(file_info(work / relative) == export['files'][relative], 'Changed source asset')
        target=OUT / relative; target.parent.mkdir(exist_ok=True)
        os.link(work / relative, target)
    atomic_save(OUT / 'batch.json', batch)
    (OUT / 'index.html').write_text(page, encoding='utf-8')
    files = {p: export['files'][p] for p in assets}
    files.update({p: file_info(OUT / p) for p in ('batch.json','index.html')})
    output = seal(dict(schema='dsp-sequence-state-export/1', **common, path=OUT.as_posix(),
        batch_id=batch['artifact_id'], human_receipt_id=receipt['artifact_id'], proposed_counts=batch['proposed_counts'],
        confirmation_fields=['regions','step15_key_states'], files=files,
        preparer=dict(path=Path(__file__).as_posix(), file=file_info(__file__)),
        historical_datasets_opened=0, corpus_rebuilt=False, media_bytes_copied=0, media_reencoded=False,
        classification_changed=False, final_sampling_frozen=False, status='pending', training_authorized=False))
    atomic_save(OUT / 'export.json',output)
    atomic_save('docs/validation/sequence-state-completion-01-prepared-20260924.json',output)
    print(f'Prepared {len(proposals)} pending state proposals: {batch["artifact_id"]}')


def check():
    receipt=load('docs/validation/movement-supplement-01-confirmed-20260924.json')
    prior_receipt=load('docs/validation/movement-priority-01-confirmed-20260924.json')
    aggregate=load(receipt['draft']['path']); prior=load(prior_receipt['draft']['path'])
    confirmed_batch=load(ROOT / 'movement-supplement-review-01/batch.json')
    fragment=load(receipt['formal_candidates']['path'])
    output=load(OUT / 'export.json'); batch=load(OUT / 'batch.json')
    for value in (receipt,prior_receipt,aggregate,prior,confirmed_batch,fragment,output,batch):
        verify_seal(value)
    assert file_info(receipt['draft']['path']) == receipt['draft']['file']
    assert file_info(receipt['formal_candidates']['path']) == receipt['formal_candidates']['file']
    assert load(receipt['raw_submission']['path']) == receipt['submission']
    assert receipt['submission']['raw_answer'] == '27 題的三項都正'
    assert aggregate['rows'][:215] == prior['rows'] and len(aggregate['rows']) == 242
    assert sum(r['reviewed'] for r in aggregate['rows']) == len(fragment['samples']) == 37
    assert aggregate['classification_counts'] == dict(movement=50, ui=63, interaction=64, waiting=64)
    for row,p,formal in zip(aggregate['rows'][215:],confirmed_batch['proposals'],fragment['samples'][10:]):
        assert row['source'] == p['source'] and row['reviewed'] and row['reviewer'] == 'Jay'
        for field in ('category','regions','key_states'):
            assert row[field] == p['suggested_'+field] == formal[field]
        assert formal['task_id'] == row['source']['task_id']
    assert output == load('docs/validation/sequence-state-completion-01-prepared-20260924.json')
    assert output['batch_id'] == batch['artifact_id'] and file_info(__file__) == output['preparer']['file']
    for name,info in output['files'].items():
        assert file_info(OUT / name) == info, name
    expected={r['source']['id']:r for r in aggregate['rows'] if r['classification_reviewed'] and not r['reviewed'] and r['category'] in ('movement','waiting')}
    assert set(expected) == set(STATES) == {p['source']['id'] for p in batch['proposals']}
    assert batch['proposed_counts'] == dict(movement=13,waiting=64) and len(batch['proposals']) == 77
    for p in batch['proposals']:
        assert p['source'] == expected[p['source']['id']]['source']
        assert p['category'] == expected[p['source']['id']]['category'] and p['classification_reviewed'] and not p['reviewed']
        assert p['suggested_regions'] == [[0,0,640,360]] and p['key_state_step'] == 15
        assert p['suggested_key_states'] == [STATES[p['source']['id']]]
        for path in [p['source']['video'],*p['source']['images']]:
            assert os.path.samefile(ROOT / 'workbench' / path, OUT / path)
    page=(OUT / 'index.html').read_text(encoding='utf-8')
    assert page.count('<section ') == page.count('<details>') == page.count('<video ') == 77
    assert page.count('<img ') == 231 and '77 題的兩項都正確' in page
    assert not batch['training_authorized'] and not output['final_sampling_frozen']
    print('PASS: exact 27 confirmations; 37 complete; 77 pending state proposals; hashes and hard links; no dataset reads')


if __name__ == '__main__':
    require(sys.argv[1:] in ([], ['--check']), 'Expected no arguments or --check')
    check() if sys.argv[1:] == ['--check'] else prepare()
