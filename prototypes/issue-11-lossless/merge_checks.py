"""Failure/visual checks for the throwaway merger; mutates only new test copies."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from PIL import Image, ImageDraw
from merge_prototype import decode_verify, verify_published, require
from storage_probe import FFMPEG, FRAME_BYTES, records, save


parser = argparse.ArgumentParser()
parser.add_argument('--merged', type=Path, required=True)
parser.add_argument('--interrupted', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=False)
artifact = args.merged / 'artifact'
verify_published(artifact)
outcomes = {}
try:
    verify_published(args.interrupted / 'artifact')
except ValueError as error:
    outcomes['interrupted_publish_rejected'] = str(error)
require('interrupted_publish_rejected' in outcomes, 'interrupted artifact accepted')
# Truncate a fresh copy midway through the encoded stream.
truncated = args.out / 'truncated.mkv'
with (artifact / 'recording.mkv').open('rb') as source, truncated.open('xb') as target:
    remaining = (artifact / 'recording.mkv').stat().st_size // 2
    while remaining:
        data = source.read(min(1024 * 1024, remaining))
        target.write(data)
        remaining -= len(data)
frames = list(records(artifact / 'frames.ndjson'))
try:
    decode_verify(truncated, frames, args.out / 'truncated.stderr')
except ValueError as error:
    outcomes['truncated_video_rejected'] = str(error)
require('truncated_video_rejected' in outcomes, 'truncated video accepted')
# A published-shaped fixture with a same-length changed event file must fail hash validation.
fixture = args.out / 'corrupt-artifact'
shutil.copytree(artifact, fixture)
with (fixture / 'events.ndjson').open('r+b') as stream:
    first = stream.read(1)
    stream.seek(0)
    stream.write(bytes([first[0] ^ 1]))
try:
    verify_published(fixture)
except ValueError as error:
    outcomes['changed_event_rejected'] = str(error)
require('changed_event_rejected' in outcomes, 'changed event accepted')
targets = [0, 199, 200, 599, 600, len(frames) - 1]
sheet = Image.new('RGB', (960, 600), '#181818')
draw = ImageDraw.Draw(sheet)
for cell, ordinal in enumerate(targets):
    result = subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error',
                             '-ss', str(ordinal / 20), '-i', str(artifact / 'recording.mkv'),
                             '-frames:v', '1', '-pix_fmt', 'rgba', '-f', 'rawvideo', 'pipe:1'],
                            capture_output=True, check=True)
    require(len(result.stdout) == FRAME_BYTES, 'preview frame missing')
    picture = Image.frombytes('RGBA', (640, 360), result.stdout).convert('RGB')
    picture.thumbnail((480, 270))
    x, y = cell % 2 * 480, cell // 2 * 200
    picture.thumbnail((320, 180))
    sheet.paste(picture, (x, y))
    draw.text((x + 325, y + 10), f'frame {ordinal}\n{ordinal / 20:.2f}s', fill='white')
sheet.save(args.out / 'merged-preview.png')
outcomes['preview_frame_ordinals'] = targets
outcomes['limitations'] = ['Controlled stop before publication, not OS power loss.',
                           'Cleanup of sources remains unimplemented and untested.',
                           'FFmpeg playback decoding and seek tested, no interactive player UI.']
save(args.out / 'failure-report.json', outcomes)
print(json.dumps(outcomes))
