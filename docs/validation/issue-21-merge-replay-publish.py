import json,os,sys,time,threading
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dsp_dreamer import publish
from dsp_dreamer.contract import load,file_info,save,require
root=Path('runs/issue21-merge-replay')
source=root/'source'; destination=root/'evidence'
ffmpeg=Path(r'E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe')
original=Path('runs/live/9a3dccda-e332-4a6d-80f3-d99c16485c12.source.evidence')
identity=file_info(original/'manifest.json')
samples=root/'owned-storage.ndjson'; stop=threading.Event()
sample_stream=samples.open('x',encoding='utf8',newline='\n')
sampling_errors=[]
def sample_storage():
 try:
  with sample_stream as stream:
   while True:
    total=count=0
    for directory,_,files in os.walk(root):
     for name in files:
      try: total+=os.stat(os.path.join(directory,name)).st_size;count+=1
      except FileNotFoundError: pass
    stream.write(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(),bytes=total,files=count))+'\n');stream.flush()
    if stop.wait(5):break
 except Exception as error: sampling_errors.append(error)
worker=threading.Thread(target=sample_storage);worker.start()
report=dict(pid=os.getpid(),start_utc=datetime.now(timezone.utc).isoformat(),original_manifest=identity,kind='offline replay of original live pixels/events; not a new live recording')
print(json.dumps(report),flush=True)
start=time.perf_counter()
try: publish(source,destination,ffmpeg,cleanup=True)
finally:
 stop.set();worker.join()
if sampling_errors: raise RuntimeError('Storage sampling failed; no measurement report published') from sampling_errors[0]
report.update(publication_and_cleanup_seconds=time.perf_counter()-start,end_utc=datetime.now(timezone.utc).isoformat())
m=load(destination/'manifest.json'); old=load(original/'manifest.json')
require(m['recording_session_id']==old['recording_session_id'] and
        m['benchmark_replay']['source_manifest']==identity, 'Replay marker/session identity changed')
require(file_info(original/'manifest.json')==identity,'Original identity changed')
for name in ('frames.ndjson','events.ndjson'):
 require(m['files'][name]==old['files'][name],'Original sidecar differs')
require(m['frame_count']==old['frame_count'] and m['episodes']==old['episodes'],'Replay identity/count differs')
require(not any(p.is_file() for p in source.rglob('*')),'Source cleanup incomplete')
report.update(frame_count=m['frame_count'],validation=m['validation'],evidence_manifest=file_info(destination/'manifest.json'),owned_storage_samples=file_info(samples),source_cleaned=True,original_sidecars_identical=True)
save('docs/validation/issue-21-merge-replay.json',report)
print(json.dumps(report),flush=True)
