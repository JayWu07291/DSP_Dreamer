"""Prepare one review page from inspected originals; keep every suggestion pending."""
import html
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import seal, verify_seal

ROOT = Path('runs/catalog-v4/corpus-integration-20260921')
# Visually inspected start/step5/step15 originals, not labels inferred from inputs.
PROPOSALS = {
    'M001': ('機甲與鏡頭在兩座採礦機之間移動。', '游標在機甲右上方的地面上。'),
    'M002': ('機甲移動，岸線與建築一起位移；後段才出現科技提示。', '游標在風力渦輪機右側的地面上。'),
    'M003': ('機甲從銅礦採礦機旁移開，镜頭跟隨。', '游標在機甲左側的地面上。'),
    'M004': ('機甲在熔爐之間移動，岸線與建築一起位移。', '游標停在右下方的熔爐上，顯示熔爐提示。'),
    'M006': ('前 0.5 秒機甲與鏡頭移動，後段才打開合成介面。', '游標在合成介面配方格的空白處。'),
    'M007': ('機甲靠近銅礦脈，鏡頭跟隨。', '游標指向銅礦脈，旁邊顯示銅礦脈提示。'),
    'M008': ('機甲在熔爐旁移動，場景跟著位移。', '游標在機甲右下方、熔爐前的地面上。'),
    'M009': ('機甲走向銅礦脈，岸線與採礦機位置一起改變。', '游標指向銅礦脈，旁邊顯示銅礦脈提示。'),
    'M010': ('機甲由鐵礦採礦機附近走向銅礦脈。', '游標指向銅礦脈，旁邊顯示銅礦脈提示。'),
    'M011': ('機甲在鐵礦採礦機旁移動，鏡頭跟隨。', '游標在機甲右下方、採礦機右側的地面上。'),
    'M013': ('機甲與鏡頭在產線旁移動，兩座採礦機一起位移。', '游標在底部建造選單的製造台圖示附近。'),
    'M014': ('機甲離開鐵礦採礦機、走向銅礦脈，鏡頭跟隨。', '游標在銅礦脈右下方的地面上。'),
    'M015': ('機甲在熔爐旁移動，採礦機與岸線一起位移。', '游標停在鐵礦採礦機右側、兩座熔爐中左邊那座上。'),
    'M017': ('機甲在兩座採礦機之間移動，場景跟著改變。', '游標在機甲右上方的水面上。'),
    'M021': ('鏡頭明顯轉向，採礦機與岸線的角度改變。', '游標在機甲右下方、銅礦脈旁的地面上。'),
    'M023': ('鏡頭在產線旁轉動，研究站與採礦機的相對投影改變。', '游標在右下方熔爐左下側的地面上。'),
    'M024': ('機甲在兩座採礦機之間移動，鏡頭跟隨。', '游標在機甲右上方的水面上。'),
    'M025': ('機甲在兩座採礦機之間移動，兩座建築一起位移。', '游標在機甲下方、銅礦採礦機左側的地面上。'),
    'M027': ('前 0.5 秒機甲離開銅礦採礦機，後段才打開合成介面。', '游標在合成介面的齒輪配方圖示上。'),
    'M029': ('機甲朝銅礦脈移動，鏡頭跟隨。', '游標在機甲右下方、銅礦脈右側的地面上。'),
    'M031': ('機甲在鐵礦採礦機旁移動，場景跟著位移。', '游標在機甲上方、採礦機右側的地面上。'),
    'M035': ('機甲在熔爐之間移動，鏡頭跟隨。', '游標停在銅礦採礦機旁的熔爐上，顯示熔爐提示。'),
    'M038': ('機甲走向鐵礦採礦機，岸線與建築一起位移。', '游標在機甲右下方的地面上。'),
    'M041': ('前 0.5 秒鏡頭轉動；後段才打開合成介面。', '游標在合成介面左邊緣、配方格外側。'),
    'M042': ('機甲在鐵礦採礦機旁移動，場景跟著位移。', '游標停在鐵礦採礦機上，顯示採礦機提示。'),
    'M044': ('機甲朝銅礦脈移動，岸線與採礦機一起位移。', '游標在機甲右下方、銅礦脈旁的地面上。'),
    'M045': ('前 0.5 秒機甲與鏡頭移動；後段才打開製造台介面。', '游標在製造台介面的「請選定配方」文字附近。'),
}


def prepare():
    source_dir = ROOT / 'movement-supplement-source-01'
    source_export = load(source_dir / 'export.json')
    sources = load(source_dir / 'sources.json')
    receipt = load('docs/validation/movement-priority-01-confirmed-20260924.json')
    aggregate = load(receipt['draft']['path'])
    for value in (source_export, sources, receipt, aggregate):
        verify_seal(value)
    require(sources['artifact_id'] == source_export['source_batch_id'] == 'ed44dd815b9ee2029e736e1ca746542ce2d27786f3682cb8c12168206ee3ffa2', 'Wrong supplemental source')
    require(file_info(source_dir / 'sources.json') == source_export['files']['sources.json'], 'Changed sources')
    require(file_info(receipt['draft']['path']) == receipt['draft']['file'] and aggregate['artifact_id'] == receipt['draft']['artifact_id'], 'Changed human aggregate')
    common = {k: sources[k] for k in ('protocol_id', 'index_id', 'workbench_id', 'evaluation_inputs_id')}
    require(all(aggregate[k] == v for k, v in common.items()), 'Identity mismatch')
    samples = {s['id']: s for s in sources['samples']}
    proposals = [dict(source=samples[k], suggested_category='movement', category_basis=basis,
        suggested_regions=[[0, 0, 640, 360]], region_basis='camera_changes_scene',
        suggested_key_states=[dict(type='cursor', expected=expected)], key_state_step=15,
        classification_reviewed=False, reviewed=False, proposer='assistant')
        for k, (basis, expected) in PROPOSALS.items()]
    batch = seal(dict(schema='dsp-sequence-priority-proposals/1', **common, proposals=proposals,
        human_aggregate_id=aggregate['artifact_id'], source_batch_id=sources['artifact_id'],
        prescreened_ids=list(samples), deferred_ids=[k for k in samples if k not in PROPOSALS],
        prescreen_method='All 48 original triples inspected; 27 proposed triples rechecked at native resolution. Input activity only ordered inspection; no automatic labels or exclusions.',
        exclusion_policy='Original 400 and all 947 activity candidates retained; 21 deferred rows remain pending.',
        candidates_reviewed=0, status='pending', training_authorized=False))
    # The ten confirmed rows can now use the independently verified task mapping.
    confirmed = [r for r in aggregate['rows'] if r['reviewed']]
    fragment = seal(dict(schema='dsp-prediction-candidates/1', protocol_id=common['protocol_id'], index_id=common['index_id'],
        samples=[dict(artifact_id=r['source']['artifact_id'], start=r['source']['start'],
            task_id=sources['original_task_ids'][r['source']['id']], category=r['category'], reviewed=True,
            evidence=r['source']['evidence'], regions=r['regions'], key_states=r['key_states']) for r in confirmed]))
    require(len(proposals) == 27 and len(batch['deferred_ids']) == 21 and len(confirmed) == 10, 'Unexpected counts')
    template_dir = ROOT / 'movement-priority-review-01'
    template_export = load(template_dir / 'export.json')
    verify_seal(template_export)
    require(file_info(template_dir / 'index.html') == template_export['files']['index.html'], 'Changed player template')
    template = (template_dir / 'index.html').read_text(encoding='utf-8')
    cards = []
    for row in proposals:
        s = row['source']
        frames = ''.join(f'<figure><a href="{path}" target="_blank" rel="noopener"><img src="{path}" alt="{s["id"]} {label}" loading="lazy"></a><figcaption>{label}</figcaption></figure>'
            for path, label in zip(s['images'], ('起點原圖', '第 5 步：分類依據', '第 15 步：游標狀態依據')))
        cards.append(f'''<section id="{s['id']}"><h2>{s['id']}</h2>
<p><strong>① 分類建議：移動／視角。</strong>{html.escape(row['category_basis'])}</p>
<p><strong>② 評估範圍：整張畫面。</strong>鏡頭移動使場景整體改變。</p>
<p><strong>③ 最後一張原圖的狀態：</strong>{html.escape(row['suggested_key_states'][0]['expected'])}</p>
<video controls preload="none" aria-label="{s['id']} 原始片段" data-begin="{s['begin']}" data-boundary="{s['boundary']}" data-end="{s['end']}" src="{s['video']}#t={s['boundary']},{s['end']}"></video>
<div class="buttons"><button data-mode="boundary">播放這 1.5 秒</button><button data-mode="begin">連同前情播放</button></div>
<p class="message" role="status"></p><div class="frames">{frames}</div><a href="#top">回到題目索引</a></section>''')
    page = template.split('<h1>', 1)[0] + '''<h1 id="top">移動類剩餘 27 段：核對已填好的三項</h1>
<p>上一頁 10 題已確認。移動類目前 23／50；本頁若全部通過，分類數便達 50／50。不需要再錄製。</p>
<p class="notice">每題只核對三項。全數符合就回覆「27 題的三項都正確」；有誤只寫題號與第幾項，例如「M001：第 3 項，游標在……」。不確定可直接寫不確定，不用重寫整段操作。</p>
<p>① 看第 5 步（0.5 秒後）的主要變化。② 本批鏡頭改變，範圍為整張畫面。③ 看第 15 步游標指在哪裡。三張圖可點開放大，需要時才播放。</p>
<p>目前有 10 段三項都已確認；本頁全數通過後為 37 段。先前只有分類的其他片段，仍需由我整理範圍與狀態，再請你核對；這還不是全部 200 段標註完成。</p>
<nav aria-label="題目索引">''' + ' · '.join(f'<a href="#{k}">{k}</a>' for k in PROPOSALS) + '</nav>' + ''.join(cards) + '<script>' + template.split('<script>', 1)[1]
    out = ROOT / 'movement-supplement-review-01'
    require(not out.exists(), 'Refusing to overwrite review')
    out.mkdir()
    assets = sorted({p for r in proposals for p in [r['source']['video'], *r['source']['images']]})
    for relative in assets:
        require((source_dir / relative).resolve().is_relative_to(source_dir.resolve()), 'Asset escapes root')
        require(file_info(source_dir / relative) == source_export['files'][relative], 'Changed review asset')
        target = out / relative
        target.parent.mkdir(exist_ok=True)
        os.link(source_dir / relative, target)
    atomic_save(out / 'batch.json', batch)
    atomic_save(out / 'confirmed-candidates.json', fragment)
    (out / 'index.html').write_text(page, encoding='utf-8')
    files = {p: source_export['files'][p] for p in assets}
    files.update({p: file_info(out / p) for p in ('index.html', 'batch.json', 'confirmed-candidates.json')})
    output = seal(dict(schema='dsp-sequence-priority-export/1', **common, path=out.as_posix(),
        batch_id=batch['artifact_id'], source_batch_id=sources['artifact_id'], human_receipt_id=receipt['artifact_id'],
        confirmed_candidates_id=fragment['artifact_id'], proposed_ids=list(PROPOSALS), deferred_count=21,
        human_classification_counts=aggregate['classification_counts'], candidates_reviewed=10,
        proposed_candidates_reviewed=0, final_sampling_frozen=False, files=files,
        preparer=dict(path=Path(__file__).as_posix(), file=file_info(__file__)),
        source_extraction_counts={k: sources[k] for k in ('validation_table_sources_read', 'rgb_chunks_read', 'full_dataset_opens', 'video_bytes_copied')},
        status='pending', training_authorized=False))
    atomic_save(out / 'export.json', output)
    atomic_save('docs/validation/movement-supplement-review-01-prepared-20260924.json', output)
    print(f"Prepared {len(proposals)} pending proposals and {len(confirmed)} confirmed candidates: {batch['artifact_id']}")


if __name__ == '__main__':
    prepare()
