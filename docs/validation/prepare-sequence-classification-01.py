"""Prepare the first five existing prediction candidates for human classification."""
import html
import json
import math
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import read_protocol, seal, verify_seal

integration_root = Path('runs/catalog-v4/corpus-integration-20260921')
workbench = integration_root / 'workbench'
export = load(workbench / 'export.json')
verify_seal(export)
require(export['artifact_id'] == 'f88618ed686130fa4a21501ec24c6439077dbedc60682782072171ef9fb2366e', 'Different workbench')
require(file_info(workbench / 'data.js') == export['files']['data.js'], 'Workbench changed')
workbench_data = json.loads((workbench / 'data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
require(read_protocol('protocols/evaluation-v2.json')['artifact_id'] == workbench_data['protocol_id'], 'Protocol changed')
samples = workbench_data['prediction'][:5]
require([s['id'] for s in samples] == ['P001','P002','P003','P004','P005'], 'Unexpected queue order')
for sample in samples:
    require(all(isinstance(sample[k], (float,int)) and math.isfinite(sample[k]) for k in ('begin','boundary','end'))
            and 0 <= sample['begin'] < sample['boundary'] < sample['end'] and len(sample['images']) == 3, 'Invalid clip')
assets = sorted({relative for sample in samples for relative in [sample['video'], *sample['images']]})
for relative in assets:
    require((workbench / relative).resolve().is_relative_to(workbench.resolve()), 'Asset escapes workbench')
    require(file_info(workbench / relative) == export['files'][relative], 'Asset changed')
batch = seal(dict(schema='dsp-guided-sequence-classification-batch/1', workbench_id=export['artifact_id'],
    protocol_id=workbench_data['protocol_id'], index_id=workbench_data['index_id'],
    evaluation_inputs_id=workbench_data['evaluation_inputs_id'], samples=samples,
    categories=['movement','ui','interaction','waiting'], scope='classification_only',
    status='pending', training_authorized=False, candidates_reviewed=0))
out = integration_root / 'sequence-classification-01'
out.mkdir(exist_ok=False)
for relative in assets:
    target = out / relative
    target.parent.mkdir(exist_ok=True)
    os.link(workbench / relative, target)
    require(os.path.samefile(workbench / relative,target), 'Media must reuse existing storage')
cards = []
for sample in samples:
    identity = html.escape(sample['id'])
    images = ''.join(f'<figure><a href="{html.escape(relative,quote=True)}" target="_blank" rel="noopener"><img src="{html.escape(relative,quote=True)}" alt="{identity} {label}" loading="lazy"></a><figcaption>{label}</figcaption></figure>'
        for relative,label in zip(sample['images'],('起點原圖','第 5 步（0.5 秒後）','第 15 步（1.5 秒後）')))
    cards.append(f'''<section><h2>{identity}</h2><p>只分類起點後 1.5 秒；若有混合操作，以第 5 步畫面主要改變的內容為準。</p>
<video controls preload="none" aria-label="{identity} 原始片段" data-begin="{sample['begin']}" data-boundary="{sample['boundary']}" data-end="{sample['end']}" src="{html.escape(sample['video'],quote=True)}#t={sample['boundary']},{sample['end']}"></video>
<div class="buttons"><button data-mode="boundary">播放要分類的 1.5 秒</button><button data-mode="begin">連同前情一起播放（約 8 秒）</button></div><p class="message" role="status"></p>
<div class="frames">{images}</div></section>''')
page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>五段影片的操作分類</title><style>
body{font:18px/1.7 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;background:#f2f5f6;color:#20313f}section{background:white;padding:20px;margin:24px 0;border:1px solid #ccd5dd;border-radius:10px}h1,h2{line-height:1.4}video{display:block;width:100%;max-width:960px;background:#142734}.frames{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}figure{margin:12px 0}img{width:100%;display:block}.buttons{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}button{font:inherit;padding:10px;cursor:pointer}button:focus-visible,a:focus-visible{outline:3px solid #007c91}.notice{padding:16px;background:#fff3cc}table{border-collapse:collapse}td,th{border:1px solid #ccd5dd;text-align:left;padding:8px}figcaption{font-size:15px}@media(max-width:600px){.frames{grid-template-columns:1fr}}
</style><h1>五段影片：發生了哪一類操作？</h1>
<p>目前只分類 P001–P005。先按「播放要分類的 1.5 秒」；看不懂前因時，再連同前情播放。下方三張是無損原圖，可點開放大。</p>
<table><tr><th>回答</th><th>主要可見變化</th></tr><tr><td>移動／視角</td><td>角色位置或鏡頭改變</td></tr><tr><td>UI</td><td>開關面板、切換選項等介面操作</td></tr><tr><td>建造／物品</td><td>放置、拆除、建築連接、拿取或放入物品</td></tr><tr><td>等待</td><td>等待狀態，沒有上述主要操作；不要求畫面完全靜止</td></tr></table>
<p class="notice">看完直接回到對話，逐行填「P001：類別」到「P005：類別」。混合操作以第 5 步的主要變化為準；不確定可寫「Pxxx：不確定＋原因」。沒有預設答案，也不用填座標。</p>
''' + ''.join(cards) + '''<p>這批只收操作分類；受影響範圍與關鍵狀態仍待後續確認，不會把分類回答當成完整序列標註。</p>
<script>
for(const section of document.querySelectorAll('section')){
 const video=section.querySelector('video'),message=section.querySelector('.message');
 video.addEventListener('timeupdate',()=>{if(video.currentTime>=Number(video.dataset.end))video.pause()});
 video.addEventListener('error',()=>{message.textContent='影片載入失敗，請告訴我；不要把載入失敗當成等待。'});
 for(const button of section.querySelectorAll('button'))button.addEventListener('click',()=>{
  const start=Number(video.dataset[button.dataset.mode]);
  for(const other of document.querySelectorAll('video'))if(other!==video)other.pause();
  const play=()=>{video.currentTime=start;message.textContent=button.dataset.mode==='begin'?'先播放約 6.4 秒前情，最後 1.5 秒是本題。':'正在播放要分類的 1.5 秒。';video.play().catch(()=>{message.textContent='請按影片本身的播放鍵繼續。'})};
  if(video.readyState===0){video.addEventListener('loadedmetadata',play,{once:true});video.load()}else play();
 });
}
</script></html>'''
require(page.count('<video ') == 5 and page.count('<figure>') == 15, 'Invalid review page')
(out / 'index.html').write_text(page,encoding='utf-8')
atomic_save(out / 'batch.json',batch)
files = {relative:export['files'][relative] for relative in assets}
files.update({name:file_info(out / name) for name in ('index.html','batch.json')})
receipt = seal(dict(schema='dsp-guided-sequence-classification-export/1',batch_id=batch['artifact_id'],path=out.as_posix(),
    files=files,assets_storage='hard_links',media_bytes_copied=0,preparer=dict(path=Path(__file__).as_posix(),file=file_info(__file__)),
    status='pending',training_authorized=False,historical_datasets_opened=0,corpus_rebuilt=False))
atomic_save(out / 'export.json',receipt)
atomic_save('docs/validation/sequence-classification-01-prepared-20260921.json',receipt)
print(batch['artifact_id'])
