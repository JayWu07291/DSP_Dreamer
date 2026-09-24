"""One-off handoff of visually inspected movement proposals; never approve labels."""
from collections import Counter
import html
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import read_protocol, seal, verify_seal

ROOT = Path('runs/catalog-v4/corpus-integration-20260921')
LATEST = '026c17afd46fe5c92b97eaac4603e03b50ef63ec496dba5670287581f16c6cff'
# Agent observations from the original start, step 5 and step 15 PNGs.
# These are proposals, not additional answers attributed to Jay.
PROPOSALS = {
    'P231': ('機甲朝銅礦脈移動，地面與採礦機的畫面位置跟著改變。', '游標在銅礦脈右下方的地面上。'),
    'P244': ('機甲繼續靠近銅礦脈，鏡頭跟隨；後段才開始採礦。', '游標在正在採礦的機甲右下方地面上。'),
    'P276': ('機甲朝銅礦脈走，礦脈相對機甲逐漸靠近。', '游標在銅礦脈與機甲右下方的地面上。'),
    'P299': ('機甲在熔爐前移動，熔爐、採礦機與岸線的畫面位置一起改變。', '游標在機甲右下方的地面上，沒有停在面板按鈕上。'),
    'P311': ('機甲從銅礦採礦機旁移開，兩座採礦機與岸線一起位移。', '游標在機甲右側、風力渦輪機左側的地面上。'),
    'P336': ('機甲在兩座採礦機之間移動，鏡頭跟隨，地面與建築一起位移。', '游標在機甲右上方的地面上。'),
    'P347': ('鏡頭角度與建築投影位置改變，兩條產線仍在畫面中。', '游標在機甲右側的地面上。'),
    'P372': ('鏡頭從較平的視角轉向俯視，機甲繼續靠近銅礦脈。', '游標指向銅礦脈，旁邊顯示銅礦脈提示。'),
    'P388': ('機甲朝銅礦脈走，鏡頭跟隨；後段才開始採礦。', '游標在銅礦脈與機甲右下方的地面上。'),
    'P392': ('前 0.5 秒機甲與鏡頭移動；後段才打開熔爐介面。', '游標停在已開啟介面的熔爐上，建築有綠色外框。'),
}


def prepare():
    workbench = ROOT / 'workbench'
    export = load(workbench / 'export.json')
    verify_seal(export)
    require(export['artifact_id'] == 'f88618ed686130fa4a21501ec24c6439077dbedc60682782072171ef9fb2366e', 'Different workbench')
    require(file_info(workbench / 'data.js') == export['files']['data.js'], 'Changed workbench data')
    work = json.loads((workbench / 'data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
    require(read_protocol('protocols/evaluation-v2.json')['artifact_id'] == work['protocol_id'], 'Changed protocol')
    sources = {s['id']: s for s in work['prediction']}
    require(list(sources) == [f'P{n:03}' for n in range(1, 401)], 'Changed queue')
    # Recheck the 390 small exported PNGs, never the recording datasets or RGB archive.
    inspected = [relative for s in work['prediction'][205:] for relative in s['images'][:2]]
    assets = sorted({relative for key in PROPOSALS for relative in [sources[key]['video'], *sources[key]['images']]})
    for relative in set(inspected + assets):
        require((workbench / relative).resolve().is_relative_to(workbench.resolve()), 'Asset escapes root')
        require(file_info(workbench / relative) == export['files'][relative], 'Changed source asset')

    # Follow receipts newest first, so a later human clarification wins without
    # rewriting its original answer. All predecessor identities remain recorded.
    receipts = {}
    for path in Path('docs/validation').glob('sequence*.json'):
        receipt = load(path)
        if receipt.get('schema', '').startswith(('dsp-sequence-classification-receipt/',
                'dsp-sequence-classification-confirmation-receipt/', 'dsp-sequence-classification-clarification-receipt/')):
            receipts[receipt['artifact_id']] = (path, receipt)
    current, chain, rows = LATEST, [], {}
    while current:
        require(current not in [r['artifact_id'] for r in chain], 'Receipt cycle')
        path, receipt = receipts[current]
        verify_seal(receipt)
        info = receipt['draft']
        require(file_info(info['path']) == info['file'], 'Changed human draft')
        draft = load(info['path'])
        verify_seal(draft)
        require(draft['artifact_id'] == info['artifact_id'], 'Wrong human draft')
        chain.append(dict(path=path.as_posix(), artifact_id=current, file=file_info(path), draft=info))
        for row in draft['rows']:
            require(row['source'] == sources[row['source']['id']], 'Human source mismatch')
            rows.setdefault(row['source']['id'], row)
        current = receipt.get('prior_receipt_id')
    counts = dict(Counter(r['category'] for r in rows.values() if r['classification_reviewed']))
    pending = sorted(k for k, r in rows.items() if not r['classification_reviewed'])
    require(len(rows) == 205 and counts == dict(movement=13, ui=63, interaction=64, waiting=64)
            and pending == ['P085'] and not any(r['reviewed'] for r in rows.values()), 'Unexpected human progress')

    out = ROOT / 'movement-priority-review-01'
    require(not out.exists(), 'Refusing to overwrite handoff')
    common = dict(protocol_id=work['protocol_id'], index_id=work['index_id'],
        evaluation_inputs_id=work['evaluation_inputs_id'], workbench_id=export['artifact_id'],
        status='pending', training_authorized=False)
    aggregate = seal(dict(schema='dsp-sequence-human-aggregate/1', **common, prior_receipt_id=LATEST,
        receipt_chain=chain, rows=[rows[k] for k in sorted(rows)], classification_counts=counts,
        pending_classifications=pending, candidates_reviewed=0,
        agent_region_proposals=[dict(id=k, suggested_regions=[[0, 0, 640, 360]],
            basis='protocol_waiting_full_frame', reviewed=False) for k, r in sorted(rows.items()) if r['category'] == 'waiting']))
    proposals = [dict(source=sources[k], suggested_category='movement', category_basis=basis,
        suggested_regions=[[0, 0, 640, 360]], region_basis='camera_changes_scene',
        suggested_key_states=[dict(type='cursor', expected=expected)], key_state_step=15,
        classification_reviewed=False, reviewed=False, proposer='assistant')
        for k, (basis, expected) in PROPOSALS.items()]
    batch = seal(dict(schema='dsp-sequence-priority-proposals/1', **common, proposals=proposals,
        human_aggregate_id=aggregate['artifact_id'], prescreened_ids=list(sources)[205:],
        deferred_ids=[k for k in list(sources)[205:] if k not in PROPOSALS],
        scope='category_region_and_step15_key_state_proposals', candidates_reviewed=0,
        prescreen_method='Agent inspected all 195 start/step5 pairs; rechecked 15 triples at native resolution. Pixel differences ordered inspection only; no automatic classifications or exclusions.',
        rechecked_but_deferred=['P279', 'P295', 'P320', 'P352', 'P384'],
        exclusion_policy='Deferred candidates stay pending in the original pool; final sampling seed and row hash unchanged.'))
    require(len(proposals) == 10 and len(batch['deferred_ids']) == 185
            and len(aggregate['agent_region_proposals']) == 64, 'Invalid proposal counts')

    template_folder = ROOT / 'sequence-classification-01'
    template_export = load(template_folder / 'export.json')
    verify_seal(template_export)
    require(file_info(template_folder / 'index.html') == template_export['files']['index.html'], 'Changed player template')
    template = (template_folder / 'index.html').read_text(encoding='utf-8')
    head = template.split('<h1>', 1)[0].replace('五段影片的操作分類', '移動候選：確認已整理的標註')
    playback = '<script>' + template.split('<script>', 1)[1]
    cards = []
    for row in proposals:
        s = row['source']
        frames = ''.join(f'<figure><a href="{relative}" target="_blank" rel="noopener"><img src="{relative}" alt="{s["id"]} {label}" loading="lazy"></a><figcaption>{label}</figcaption></figure>'
            for relative, label in zip(s['images'], ('起點原圖', '第 5 步：分類依據', '第 15 步：游標狀態依據')))
        cards.append(f'''<section><h2>{s['id']}</h2>
<p><strong>① 分類建議：移動／視角。</strong>{html.escape(row['category_basis'])}</p>
<p><strong>② 評估範圍：整張畫面。</strong>鏡頭移動使場景整體改變，已替你填好。</p>
<p><strong>③ 最後一張原圖的狀態：</strong>{html.escape(row['suggested_key_states'][0]['expected'])}</p>
<video controls preload="none" aria-label="{s['id']} 原始片段" data-begin="{s['begin']}" data-boundary="{s['boundary']}" data-end="{s['end']}" src="{s['video']}#t={s['boundary']},{s['end']}"></video>
<div class="buttons"><button data-mode="boundary">播放這 1.5 秒</button><button data-mode="begin">連同前情播放</button></div>
<p class="message" role="status"></p><div class="frames">{frames}</div></section>''')
    page = head + '''<h1>只確認這 10 段已整理的標註</h1>
<p>我已預看剩餘 195 組原圖，先挑出這 10 段移動候選。每題的分類、範圍與最後畫面描述都已填好；請核對三項是否符合原圖，需要時再播放。</p>
<p class="notice">看完後回到對話即可：全部符合就回覆「10 題的三項都正確」。有不同，只寫題號與第幾項，例如「P231：第 3 項不對，游標在……」。不確定可直接寫不確定。不用重寫操作過程、填座標或匯出 JSON。</p>
<p>① 混合操作看第 5 步（0.5 秒後）的主要變化。② 本批鏡頭改變，評估整張畫面。③ 只核對第 15 步游標在哪裡、指著什麼，不問形狀、顏色或朝向。</p>
<p>目前移動類已確認 13／50；本頁 10 段仍待你確認，即使全數通過仍缺 27 段。其他三類分類數已足夠，不再要求你逐段重寫描述。範圍與關鍵狀態尚未全部完成。</p>
''' + ''.join(cards) + '<p>尚未確認的項目保留待處理；本頁不會自動批准標籤或啟動訓練。</p>' + playback
    require(page.count('<video ') == 10 and page.count('<figure>') == 30
            and 'P206：類別' not in page, 'Invalid review page')
    out.mkdir()
    for relative in assets:
        target = out / relative
        target.parent.mkdir(exist_ok=True)
        os.link(workbench / relative, target)
        require(os.path.samefile(workbench / relative, target), 'Media must share existing storage')
    atomic_save(out / 'human-aggregate.json', aggregate)
    atomic_save(out / 'batch.json', batch)
    (out / 'index.html').write_text(page, encoding='utf-8')
    files = {relative: export['files'][relative] for relative in assets}
    files.update({name: file_info(out / name) for name in ('index.html', 'batch.json', 'human-aggregate.json')})
    receipt = seal(dict(schema='dsp-sequence-priority-export/1', **common, path=out.as_posix(),
        batch_id=batch['artifact_id'], aggregate_id=aggregate['artifact_id'], prior_receipt_id=LATEST,
        proposed_ids=list(PROPOSALS), prescreened_count=195, deferred_count=185,
        human_classification_counts=counts, pending_classifications=pending,
        waiting_region_proposals=64, candidates_reviewed=0, files=files,
        preparer=dict(path=Path(__file__).as_posix(), file=file_info(__file__)),
        historical_datasets_opened=0, corpus_rebuilt=False, media_bytes_copied=0, media_reencoded=False,
        original_pool_changed=False, final_sampling_changed=False))
    atomic_save(out / 'export.json', receipt)
    atomic_save('docs/validation/movement-priority-01-prepared-20260924.json', receipt)
    print(json.dumps(dict(batch_id=batch['artifact_id'], aggregate_id=aggregate['artifact_id'], proposals=10, counts=counts)))


if __name__ == '__main__':
    prepare()
