"""Prepare the remaining classified rows for human review; --check uses no datasets."""
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
OUT = ROOT / 'sequence-state-completion-02'
DATA = Path('docs/validation/ui-interaction-state-proposals-20260924.json')
RECEIPT = 'docs/validation/sequence-state-completion-01-confirmed-20260924.json'
PREPARED = 'docs/validation/sequence-state-completion-02-prepared-20260924.json'


def region(bounds):
    if bounds is None:
        return [0, 0, 640, 360]
    require(len(bounds) == 4 and all(type(v) is int for v in bounds), 'Invalid bounds')
    x0, y0, x1, y1 = bounds
    require(0 <= x0 < x1 <= 640 and 0 <= y0 < y1 <= 360, 'Bounds outside image')
    result = []
    for lo, hi, limit in ((x0, x1, 640), (y0, y1, 360)):
        lo, hi = max(0, lo-8), min(limit, hi+8)
        if hi-lo < 64:
            lo = max(0, min(limit-64, (lo+hi-64)//2))
            hi = lo+64
        result.append((lo, hi))
    return [result[0][0], result[1][0], result[0][1], result[1][1]]


def inputs():
    receipt = load(RECEIPT); verify_seal(receipt)
    aggregate = load(receipt['draft']['path']); verify_seal(aggregate)
    require(file_info(receipt['draft']['path']) == receipt['draft']['file'], 'Changed aggregate')
    raw = load(DATA)
    require(len(raw) == len({p[0] for p in raw}) == 127, 'Duplicate or missing proposal')
    require(all(p[2] in ('cursor', 'recipe', 'item_number', 'connection') and p[3].strip() for p in raw), 'Invalid state')
    rows = {r['source']['id']: r for r in aggregate['rows'] if r['classification_reviewed'] and not r['reviewed']}
    require(set(rows) == {p[0] for p in raw}, 'Wrong remaining rows')
    return receipt, aggregate, raw, rows


def frame(path, key, caption, box):
    x0, y0, x1, y1 = box
    style = f'left:{x0/6.4:.5f}%;top:{y0/3.6:.5f}%;width:{(x1-x0)/6.4:.5f}%;height:{(y1-y0)/3.6:.5f}%'
    return f'''<figure><a class="original" href="{path}" target="_blank" rel="noopener"><img src="{path}" alt="{key} {caption}，青框為建議評估範圍" loading="lazy" width="640" height="360"><span class="region" style="{style}" aria-hidden="true"></span></a><figcaption>{caption} · 點圖開啟無框原圖</figcaption></figure>'''


def prepare():
    receipt, aggregate, raw, rows = inputs()
    work = ROOT / 'workbench'
    source_export = load(work / 'export.json'); verify_seal(source_export)
    require(source_export['artifact_id'] == aggregate['workbench_id'], 'Wrong workbench')
    require(file_info(work / 'data.js') == source_export['files']['data.js'], 'Changed source mapping')
    data = json.loads((work / 'data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
    sources = {r['id']: r for r in data['prediction']}
    proposals = []
    cards = []
    for key, bounds, state_type, expected in raw:
        row = rows[key]; source = row['source']; box = region(bounds)
        require(source == sources[key] and row['category'] in ('ui', 'interaction'), 'Changed source/category')
        proposals.append(dict(source=source, category=row['category'], classification_reviewed=True,
            classification_aggregate_id=aggregate['artifact_id'], suggested_regions=[box],
            proposed_affected_bounds=bounds, region_basis='camera_or_scene_overlay_changes' if bounds is None else 'affected_bounds_plus8_min64',
            suggested_key_states=[dict(type=state_type, expected=expected)], key_state_step=15, reviewed=False, proposer='assistant'))
        label = 'UI' if row['category'] == 'ui' else '建造／物品'
        scope = '整張畫面' if bounds is None else '青框內的範圍'
        originals = ''.join(frame(path, key, caption, box) for path, caption in zip(source['images'][:2], ('起點原圖', '第 5 步原圖')))
        cards.append(f'''<section id="{key}"><h2>{key} <small>已確認分類：{label}</small></h2>
<p><strong>① 評估範圍：{scope}。</strong>請看是否涵蓋這段操作改變的游標、面板或建築，也有沒有框得過大。</p>
<p><strong>② 末幀狀態：</strong>{html.escape(expected)}</p>
{frame(source['images'][2], key, '第 15 步原圖', box)}
<details><summary>展開前後原圖與影片，核對範圍</summary>{originals}
<video controls preload="none" aria-label="{key} 原始片段" data-begin="{source['begin']}" data-boundary="{source['boundary']}" data-end="{source['end']}" src="{source['video']}#t={source['boundary']},{source['end']}"></video>
<div class="buttons"><button data-mode="boundary">播放這 1.5 秒</button><button data-mode="begin">連同前情播放</button></div><p class="message" role="status"></p></details>
<a href="#top">回到題目索引</a></section>''')
    common = {k: aggregate[k] for k in ('protocol_id','index_id','workbench_id','evaluation_inputs_id')}
    batch = seal(dict(schema='dsp-sequence-state-proposals/1', **common, proposals=proposals,
        human_aggregate_id=aggregate['artifact_id'], scope='regions_and_step15_key_states_only',
        proposed_counts=dict(Counter(p['category'] for p in proposals)), reviewed_count=0,
        status='pending', training_authorized=False))
    template_dir = ROOT / 'movement-priority-review-01'
    template_export = load(template_dir / 'export.json'); verify_seal(template_export)
    require(file_info(template_dir / 'index.html') == template_export['files']['index.html'], 'Changed player template')
    template = (template_dir / 'index.html').read_text(encoding='utf-8')
    head = template.split('<h1>',1)[0].replace('移動候選：確認已整理的標註', 'UI 與建造／物品：核對範圍與末幀')
    head = head.replace('</style>', '.original{display:block;position:relative;max-width:640px}.original img{width:100%;height:auto}.region{position:absolute;box-sizing:border-box;border:2px solid #00ffff;box-shadow:0 0 0 1px #002b36;pointer-events:none}details{margin:16px 0}summary{cursor:pointer}nav a{display:inline-block;margin:3px 6px}small{font-size:16px}figure{max-width:640px}</style>')
    page = head + '''<h1 id="top">最後兩類：核對範圍與末幀狀態</h1>
<p>上一頁 77 題已保存。移動 50 段、等待 64 段都有完整標註，足夠各抽樣 50 段。這頁合併剩下 UI 63 題、建造／物品 64 題，共 127 題。</p>
<p>每題只核對兩項：<strong>① 青框範圍；② 最後一張圖的描述。</strong>分類已確認，不用重答。這些範圍與描述是我依原圖整理的建議，仍需你核對；有疑問可展開前情。</p>
<p>青框代表要評估的位置。局部操作已加上邊界，不需要貼緊游標或建築；鏡頭或整片建造格線改變時可能涵蓋全畫面。若漏框或太大，只說「應包含／不應包含哪裡」，不用填座標。描述看第 15 步原圖，不用再寫完整操作。</p>
<p class="notice">全部符合就回覆「127 題的兩項都正確」。有誤只列題號、項次與修正；不確定就保留不確定。也可分次回覆，例如「UI 63 題的兩項都正確」。不用補錄或匯出 JSON。</p>
<p>本頁全數通過後，我會按既定規則抽樣四類各 50 段並檢查資料凍結條件。P085 仍保留待判定，不影響目前各類候選數量。這次確認不代表授權訓練。</p>'''
    for category, label in (('ui','UI：63 題'), ('interaction','建造／物品：64 題')):
        page += f'<nav aria-label="{label}"><strong>{label}</strong><br>' + ' · '.join(f'<a href="#{p["source"]["id"]}">{p["source"]["id"]}</a>' for p in proposals if p['category'] == category) + '</nav>'
    page += ''.join(cards) + '<script>' + template.split('<script>',1)[1]
    require(not OUT.exists(), 'Refusing to overwrite handoff')
    OUT.mkdir()
    assets = sorted({path for p in proposals for path in [p['source']['video'], *p['source']['images']]})
    for relative in assets:
        require((work / relative).resolve().is_relative_to(work.resolve()), 'Asset escapes source')
        require(file_info(work / relative) == source_export['files'][relative], 'Changed source asset')
        target = OUT / relative; target.parent.mkdir(exist_ok=True)
        os.link(work / relative, target)
    atomic_save(OUT / 'batch.json', batch)
    (OUT / 'index.html').write_text(page, encoding='utf-8')
    files = {name: source_export['files'][name] for name in assets}
    files.update({name: file_info(OUT / name) for name in ('batch.json','index.html')})
    output = seal(dict(schema='dsp-sequence-state-export/1', **common, path=OUT.as_posix(),
        batch_id=batch['artifact_id'], human_receipt_id=receipt['artifact_id'], proposed_counts=batch['proposed_counts'],
        confirmation_fields=['regions','step15_key_states'], files=files,
        proposal_data=dict(path=DATA.as_posix(), file=file_info(DATA)),
        preparer=dict(path=Path(__file__).as_posix(), file=file_info(__file__)),
        historical_datasets_opened=0, corpus_rebuilt=False, media_bytes_copied=0, media_reencoded=False,
        classification_changed=False, final_sampling_frozen=False, status='pending', training_authorized=False))
    atomic_save(OUT / 'export.json', output); atomic_save(PREPARED, output)
    print(f'Prepared 127 pending proposals: {batch["artifact_id"]}')


def check():
    receipt, aggregate, raw, rows = inputs()
    prior_receipt = load('docs/validation/movement-supplement-01-confirmed-20260924.json')
    prior = load(prior_receipt['draft']['path']); old_fragment = load(prior_receipt['formal_candidates']['path'])
    confirmed_batch = load(ROOT / 'sequence-state-completion-01/batch.json')
    confirmed_export = load(ROOT / 'sequence-state-completion-01/export.json')
    fragment = load(receipt['formal_candidates']['path'])
    output = load(OUT / 'export.json'); batch = load(OUT / 'batch.json')
    tasks = load(ROOT / 'movement-supplement-source-01/sources.json')
    task_export = load(ROOT / 'movement-supplement-source-01/export.json')
    for value in (prior_receipt,prior,old_fragment,confirmed_batch,confirmed_export,fragment,output,batch,tasks,task_export):
        verify_seal(value)
    for field in ('protocol_id','index_id','workbench_id','evaluation_inputs_id'):
        assert all(v[field] == aggregate[field] for v in (prior,confirmed_batch,confirmed_export,output,batch,tasks))
    assert fragment['protocol_id'] == aggregate['protocol_id'] and fragment['index_id'] == aggregate['index_id']
    assert aggregate['prior_aggregate_id'] == prior['artifact_id']
    assert receipt['proposal_export_id'] == confirmed_export['artifact_id']
    assert batch['human_aggregate_id'] == aggregate['artifact_id']
    assert output['human_receipt_id'] == receipt['artifact_id']
    assert file_info(ROOT / 'movement-supplement-source-01/sources.json') == task_export['files']['sources.json']
    assert file_info(prior_receipt['draft']['path']) == prior_receipt['draft']['file']
    assert file_info(prior_receipt['formal_candidates']['path']) == prior_receipt['formal_candidates']['file']
    assert file_info(receipt['formal_candidates']['path']) == receipt['formal_candidates']['file']
    assert file_info(receipt['raw_submission']['path']) == receipt['raw_submission']['file']
    assert load(receipt['raw_submission']['path']) == receipt['submission']
    assert receipt['submission']['raw_answer'] == '77 題的兩項都正確'
    assert receipt['submission']['confirmed_fields'] == ['regions','step15_key_states']
    assert receipt['submission']['batch_id'] == confirmed_batch['artifact_id'] == confirmed_export['batch_id']
    for name in ('batch.json','index.html'):
        assert file_info(ROOT / 'sequence-state-completion-01' / name) == confirmed_export['files'][name]
    confirmed = {p['source']['id']: p for p in confirmed_batch['proposals']}
    assert set(receipt['submission']['confirmed_ids']) == set(confirmed) and len(confirmed) == 77
    assert len(aggregate['rows']) == len(prior['rows']) == 242
    fields = {'regions','key_states','key_state_step','reviewed','state_confirmation'}
    for old,new in zip(prior['rows'], aggregate['rows']):
        if new['source']['id'] not in confirmed:
            assert old == new
            continue
        p = confirmed[new['source']['id']]
        assert {k:v for k,v in old.items() if k not in fields} == {k:v for k,v in new.items() if k not in fields}
        assert new['source'] == p['source'] and new['category'] == p['category']
        assert new['reviewed'] and new['key_state_step'] == 15
        assert new['regions'] == p['suggested_regions'] and new['key_states'] == p['suggested_key_states']
        assert new['state_confirmation']['confirmation_id'] == receipt['submission']['artifact_id']
    assert fragment['samples'][:37] == old_fragment['samples'] and len(fragment['samples']) == 114
    for p,formal in zip(confirmed_batch['proposals'], fragment['samples'][37:]):
        s = p['source']
        assert formal == dict(artifact_id=s['artifact_id'], start=s['start'], task_id=tasks['original_task_ids'][s['id']], category=p['category'], reviewed=True, evidence=s['evidence'], regions=p['suggested_regions'], key_states=p['suggested_key_states'])
    assert aggregate['classification_counts'] == dict(movement=50,ui=63,interaction=64,waiting=64)
    assert aggregate['complete_counts'] == dict(movement=50,waiting=64)
    assert aggregate['pending_classifications'] == ['P085']
    assert output == load(PREPARED) and output['batch_id'] == batch['artifact_id']
    assert file_info(__file__) == output['preparer']['file'] and file_info(DATA) == output['proposal_data']['file']
    for name,info in output['files'].items():
        assert file_info(OUT / name) == info, name
    assert len(batch['proposals']) == 127 and batch['proposed_counts'] == dict(ui=63,interaction=64)
    for (key,bounds,kind,expected),p in zip(raw,batch['proposals']):
        assert p['source'] == rows[key]['source'] and p['category'] == rows[key]['category']
        assert p['classification_reviewed'] and not p['reviewed'] and p['key_state_step'] == 15
        assert p['suggested_regions'] == [region(bounds)] and p['suggested_key_states'] == [dict(type=kind,expected=expected)]
        for path in [p['source']['video'],*p['source']['images']]:
            assert os.path.samefile(ROOT / 'workbench' / path, OUT / path)
    assert region([100,100,200,200]) == [92,92,208,208]
    assert region([0,0,1,1]) == [0,0,64,64]
    assert region([639,359,640,360]) == [576,296,640,360]
    assert region(None) == [0,0,640,360]
    page = (OUT / 'index.html').read_text(encoding='utf-8')
    assert page.count('<section ') == page.count('<details>') == page.count('<video ') == 127
    assert page.count('<img ') == page.count('class="region"') == 381
    assert '127 題的兩項都正確' in page
    assert not any(v['training_authorized'] for v in (receipt,aggregate,batch,output))
    assert not output['final_sampling_frozen']
    print('PASS: exact 77 confirmations; 114 complete; 127 pending; padding/clipping; hashes and hard links; no dataset reads')


if __name__ == '__main__':
    require(sys.argv[1:] in ([], ['--check']), 'Expected no arguments or --check')
    check() if sys.argv[1:] == ['--check'] else prepare()
