"""Contact sheet from original evidence for checking benchmark content coverage."""
from pathlib import Path
import json
from PIL import Image, ImageDraw
from storage_probe import RUNS, records, source_frames

out = Path(__file__).parent / 'out' / 'contact-sheet.png'
canvas = Image.new('RGB', (1280, 3 * 384), 'white')
draw = ImageDraw.Draw(canvas)
selection = [('20260901T024749Z', 0), ('20260901T024749Z', 400),
             ('20260901T024749Z', 1000), ('20260901T025133Z', 1200),
             ('20260902T145501Z', 150), ('20260902T145501Z', 350)]
for n, (run, ordinal) in enumerate(selection):
    captures = [e for e in records(RUNS / run / 'events.ndjson') if e['type'] == 'capture_written']
    b = next(source_frames(RUNS / run, [captures[ordinal]]))
    frame = Image.frombytes('RGBA', (640, 360), b).convert('RGB')
    x, y = n % 2 * 640, n // 2 * 384
    canvas.paste(frame, (x, y))
    draw.text((x + 5, y + 362), f'{run} capture_id={captures[ordinal]["capture_id"]}', fill='black')
canvas.save(out)
print(out.resolve())
