import json,sys,shutil,subprocess,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import load,file_info,save
from dsp_dreamer.archive import capacity_preflight
original=Path('runs/live/9a3dccda-e332-4a6d-80f3-d99c16485c12.source.evidence')
source=Path('runs/issue21-merge-replay/source')
ffmpeg=Path(r'E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe')
m=load(original/'manifest.json')
capacity_preflight(source,sum(x['bytes'] for x in m['files'].values()),copies=4)
source.mkdir(parents=True,exist_ok=False)
frames=[json.loads(l) for l in (original/'frames.ndjson').open()]
boundaries=[i for i in range(1,len(frames)) if frames[i]['segment']!=frames[i-1]['segment']]
subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-n','-i',str(original/'recording.mkv'),'-map','0:v:0','-c','copy','-f','segment','-segment_frames',','.join(map(str,boundaries)),'-reset_timestamps','1','-segment_start_number','0','-segment_format','matroska',str(source/'segment-%06d.mkv')],check=True,stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
for name in ('frames.ndjson','events.ndjson'):
 shutil.copyfile(original/name,source/name)
 assert file_info(source/name)==m['files'][name]
segments=list(dict.fromkeys(f['segment'] for f in frames))
assert {p.name for p in source.glob('segment-*.mkv')}==set(segments)
metadata={k:v for k,v in m.items() if k not in ('artifact_id','encoder_parameters','event_count','ffmpeg_sha256','files','frame_count','publication','sealed_files','source_files','state','validation')}
metadata['benchmark_replay']=dict(source_manifest=file_info(original/'manifest.json'),original_evidence=str(original),purpose='Offline publication resource measurement; not a new live capture')
metadata['sealed_files']={name:file_info(source/name) for name in ['frames.ndjson','events.ndjson',*segments]}
save(source/'SOURCE.json',metadata)
save('runs/issue21-merge-replay/preparation.json',dict(original_manifest=file_info(original/'manifest.json'),source_metadata=file_info(source/'SOURCE.json'),frames=len(frames),segments=len(segments),boundaries=boundaries))
print(json.dumps(dict(source=str(source),frames=len(frames),segments=len(segments))))
