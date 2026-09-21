"""Prepare another contiguous slice of the existing, fixed validation review queue."""
import argparse
import html
import json
import math
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import read_protocol, seal, verify_seal

parser = argparse.ArgumentParser(description='沿用已匯出素材與播放頁，準備下一段固定候選佇列')
parser.add_argument('--start', type=int, required=True, help='First one-based queue position')
parser.add_argument('--count', type=int, required=True)
args = parser.parse_args()
root = Path('runs/catalog-v4/corpus-integration-20260921')
workbench = root / 'workbench'
export = load(workbench / 'export.json')
verify_seal(export)
require(export['artifact_id'] == 'f88618ed686130fa4a21501ec24c6439077dbedc60682782072171ef9fb2366e', 'Different workbench')
require(file_info(workbench / 'data.js') == export['files']['data.js'], 'Workbench changed')
work = json.loads((workbench / 'data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
require(read_protocol('protocols/evaluation-v2.json')['artifact_id'] == work['protocol_id'], 'Protocol changed')
require(1 <= args.start <= len(work['prediction']) and 1 <= args.count <= len(work['prediction'])-args.start+1, 'Invalid queue range')
samples = work['prediction'][args.start-1:args.start-1+args.count]
require([s['id'] for s in samples] == [f'P{n:03}' for n in range(args.start,args.start+args.count)], 'Unexpected queue order')
for sample in samples:
    require(all(type(sample[k]) in (float,int) and math.isfinite(sample[k]) for k in ('begin','boundary','end'))
            and 0 <= sample['begin'] < sample['boundary'] < sample['end'] and len(sample['images']) == 3, 'Invalid clip')
assets = sorted({relative for sample in samples for relative in [sample['video'], *sample['images']]})
for relative in assets:
    require((workbench / relative).resolve().is_relative_to(workbench.resolve()), 'Asset escapes workbench')
    require(file_info(workbench / relative) == export['files'][relative], 'Asset changed')

# Reuse the sealed first page's styles, category definitions and playback code.
template_folder = root / 'sequence-classification-01'
template_export = load(template_folder / 'export.json')
verify_seal(template_export)
require(template_export['batch_id'] == 'b0374d5b7341ccdf9477b5afcf6ed0762d6968ffabdcaa2878deaf5fa69243df', 'Different template')
require(file_info(template_folder / 'index.html') == template_export['files']['index.html'], 'Template changed')
template = (template_folder / 'index.html').read_text(encoding='utf-8')
require(template.count('<h1>') == template.count('<table>') == template.count('</table>') == template.count('<script>') == 1, 'Unknown template layout')
head = template.split('<h1>',1)[0].replace('<title>五段影片的操作分類</title>', f'<title>{samples[0]["id"]}–{samples[-1]["id"]} 操作分類</title>')
categories = '<table>' + template.split('<table>',1)[1].split('</table>',1)[0] + '</table>'
playback = '<script>' + template.split('<script>',1)[1]
batch = seal(dict(schema='dsp-guided-sequence-classification-batch/1',workbench_id=export['artifact_id'],
    protocol_id=work['protocol_id'],index_id=work['index_id'],evaluation_inputs_id=work['evaluation_inputs_id'],
    samples=samples,categories=['movement','ui','interaction','waiting'],scope='classification_only',
    status='pending',training_authorized=False,candidates_reviewed=0))
out = root / f'sequence-classification-{args.start:03}-{args.start+args.count-1:03}'
out.mkdir(exist_ok=False)
for relative in assets:
    target = out / relative
    target.parent.mkdir(exist_ok=True)
    os.link(workbench / relative,target)
    require(os.path.samefile(workbench / relative,target), 'Media must reuse existing storage')
cards = []
for sample in samples:
    identity = html.escape(sample['id'])
    frames = ''.join(f'<figure><a href="{html.escape(relative,quote=True)}" target="_blank" rel="noopener"><img src="{html.escape(relative,quote=True)}" alt="{identity} {label}" loading="lazy"></a><figcaption>{label}</figcaption></figure>'
        for relative,label in zip(sample['images'],('起點原圖','第 5 步（0.5 秒後）','第 15 步（1.5 秒後）')))
    cards.append(f'''<section><h2>{identity}</h2><p>只分類起點後 1.5 秒；若有混合操作，以第 5 步畫面主要改變的內容為準。</p>
<video controls preload="none" aria-label="{identity} 原始片段" data-begin="{sample['begin']}" data-boundary="{sample['boundary']}" data-end="{sample['end']}" src="{html.escape(sample['video'],quote=True)}#t={sample['boundary']},{sample['end']}"></video>
<div class="buttons"><button data-mode="boundary">播放要分類的 1.5 秒</button><button data-mode="begin">連同前情一起播放（約 8 秒）</button></div><p class="message" role="status"></p><div class="frames">{frames}</div></section>''')
page = head + f'''<h1>{samples[0]['id']}–{samples[-1]['id']}：影片操作分類</h1>
<p>這組共 {len(samples)} 段，沿用相同回答方式。先播放要分類的 1.5 秒，需要前因時再連同前情播放；下方無損原圖可點開放大。</p>''' + categories + f'''
<p class="notice">直接回到對話逐行回答「{samples[0]['id']}：類別＋簡短說明」到「{samples[-1]['id']}：類別＋簡短說明」。可分次回答，不確定就寫原因，不用填座標或匯出 JSON。</p>
''' + ''.join(cards) + '<p>這批只收操作分類；受影響範圍與關鍵狀態仍待後續確認，不會把分類回答當成完整序列標註。</p>' + playback
require(page.count('<video ') == len(samples) and page.count('<figure>') == 3*len(samples)
        and all(page.count(f'<h2>{s["id"]}</h2>') == 1 for s in samples), 'Invalid review page')
(out / 'index.html').write_text(page,encoding='utf-8')
atomic_save(out / 'batch.json',batch)
files = {relative:export['files'][relative] for relative in assets}
files.update({name:file_info(out / name) for name in ('index.html','batch.json')})
receipt = seal(dict(schema='dsp-guided-sequence-classification-export/1',batch_id=batch['artifact_id'],path=out.as_posix(),
    queue_range=dict(start=args.start,count=args.count),files=files,assets_storage='hard_links',media_bytes_copied=0,
    preparer=dict(path=Path(__file__).as_posix(),file=file_info(__file__)),
    reused_template=dict(export_id=template_export['artifact_id'],file=template_export['files']['index.html']),
    status='pending',training_authorized=False,historical_datasets_opened=0,corpus_rebuilt=False))
atomic_save(out / 'export.json',receipt)
atomic_save(f'docs/validation/{out.name}-prepared.json',receipt)
print(batch['artifact_id'])
