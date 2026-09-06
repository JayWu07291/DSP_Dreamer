"""Render indexed decoded frames to a local contact sheet; source remains read-only."""
import argparse
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw
from storage_probe import FFMPEG, FRAME_BYTES, sha

p = argparse.ArgumentParser()
p.add_argument('--run', type=Path, required=True)
p.add_argument('--index', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
rows = json.loads(a.index.read_text(encoding='utf-8'))
sheet = Image.new('RGB', (1280, ((len(rows)+1)//2)*384), 'white')
draw = ImageDraw.Draw(sheet)
for n, row in enumerate(rows):
    c = row['capture']
    b = subprocess.check_output([FFMPEG, '-v', 'error', '-nostdin', '-threads', '4', '-i', str(a.run/c['segment']),
        '-vf', f'select=eq(n\\,{c["decoded_frame_index"]})', '-frames:v', '1',
        '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1'], stderr=subprocess.DEVNULL)
    if len(b) != FRAME_BYTES or sha(b) != c['rgba_sha256']:
        raise ValueError('Preview does not match indexed RGBA')
    x, y = n % 2 * 640, n // 2 * 384
    sheet.paste(Image.frombytes('RGBA', (640,360), b).convert('RGB'), (x,y))
    draw.text((x+5,y+362), f'{row["label"]} capture={c["capture_id"]}', fill='black')
sheet.save(a.out)
