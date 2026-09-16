"""Build two guided practice questions from verified, unchanged validation evidence."""
import argparse
import json
from pathlib import Path
import runpy
import shutil
import subprocess

# Reuse the stdlib-only contract without loading the dataset package and its native codecs.
contract = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'dsp_dreamer/contract.py'))
atomic_save, file_info, load, require, sha = (contract[k] for k in ('atomic_save', 'file_info', 'load', 'require', 'sha'))


def verified_workbench(workbench):
    receipt = load(workbench / 'export.json')
    expected_seal = '61aa26a1ff81fbd9e4ca832228d104aa8d58bc8734c31f4ec702a561c774d8c9'
    require(receipt['artifact_id'] == expected_seal == sha(json.dumps(
        {k: v for k, v in receipt.items() if k != 'artifact_id'}, sort_keys=True, allow_nan=False).encode()),
        'Different workbench needs new questions')
    require(file_info(workbench / 'data.js') == receipt['files']['data.js'], 'Workbench data changed')
    raw = (workbench / 'data.js').read_text(encoding='utf-8')
    work = json.loads(raw.removeprefix('const WORK = ').strip().removesuffix(';'))
    return receipt, work


def export_lesson(workbench, out, ffmpeg):
    workbench, out = (p.resolve() for p in (workbench, out))
    require(out != workbench and out not in workbench.parents and workbench not in out.parents,
            'Lesson output must not overlap its sources')
    require(not out.exists(), 'Refusing lesson overwrite')
    receipt, work = verified_workbench(workbench)
    picture = next(r for r in work['reconstruction'] if r['id'] == 'R021')
    sequence = next(r for r in work['prediction'] if r['id'] == 'P002')
    # These two questions describe these exact reviewed captures, not arbitrary R021/P002 rows.
    require(picture['artifact_id'] == sequence['artifact_id'] == '459bbfb3-4a69-4489-990a-401951348463'
            and picture['observation_index'] == 400 and sequence['start'] == 134
            and sequence['observation_index'] == 426, 'Different evidence needs new questions')
    observations = list(range(396, 427, 2))
    original_frames = [f"images/{sequence['artifact_id']}-{n}.png" for n in observations]
    require([original_frames[i] for i in (0, 5, 15)] == sequence['images'], 'Unexpected lesson anchors')
    for relative in [picture['image'], sequence['video'], *original_frames]:
        require(file_info(workbench / relative) == receipt['files'][relative], 'Lesson evidence changed')
    require(file_info(ffmpeg)['sha256'] == contract['FFMPEG_SHA'], 'Unknown FFmpeg executable hash')
    out.mkdir(parents=True)
    shutil.copyfile(workbench / picture['image'], out / 'picture.png')
    frames = []
    for step, observation in enumerate(observations):
        name = f'frame-{step:02}.png'
        shutil.copyfile(workbench / original_frames[step], out / name)
        require(file_info(out / name) == receipt['files'][original_frames[step]], 'Copied frame differs')
        frames.append(dict(image=name, observation_index=observation, seconds=step / 10))
    require(file_info(out / 'picture.png') == receipt['files'][picture['image']], 'Copied picture differs')
    subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-n', '-ss', str(sequence['begin']),
        '-i', str(workbench / sequence['video']), '-t', str(sequence['end'] - sequence['begin']), '-an',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '15', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
        str(out / 'sequence.mp4')], check=True, timeout=120)
    data = dict(schema='dsp-annotation-lesson/1', workbench_id=receipt['artifact_id'],
        evaluation_inputs_id=work['evaluation_inputs_id'], picture=picture, sequence=sequence, frames=frames,
        boundary_seconds=sequence['boundary'] - sequence['begin'],
        picture_box=[0, 203, 82, 226], queue_box=[335, 31, 604, 66],
        reference=dict(item='iron', count=10, category='ui', before='empty', after='present'),
        reference_author='assistant_visual_review', status='practice', training_authorized=False)
    (out / 'lesson-data.js').write_text('const LESSON = ' + json.dumps(data, ensure_ascii=False).replace('<', '\\u003c') + ';\n', encoding='utf-8')
    shutil.copyfile(Path(__file__).with_name('annotation-lesson.html'), out / 'index.html')
    exported = dict(schema='dsp-annotation-lesson-export/1', workbench_id=receipt['artifact_id'],
        files={p.name: file_info(p) for p in out.iterdir() if p.is_file()}, status='practice', training_authorized=False)
    exported['artifact_id'] = sha(json.dumps(exported, sort_keys=True, allow_nan=False).encode())
    atomic_save(out / 'export.json', exported)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='匯出一張圖片與一段影片的引導練習，不產生正式標註')
    for name in ('workbench', 'out', 'ffmpeg'):
        parser.add_argument('--' + name, required=True, type=Path)
    export_lesson(**vars(parser.parse_args()))
