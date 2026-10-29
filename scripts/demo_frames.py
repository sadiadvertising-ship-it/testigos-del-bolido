"""Still frames of each witness video with the SAM 3.1 track of the fireball drawn over it, with its credit, for checking
the tracks by eye; the demo video does not use them (it shows the cards of scripts/track_cards.py and
scripts/title_cards.py, drawn from the measurements). Frames come from the trimmed clips in out/sam/ and go to out/demo/;
neither is committed. Each frame is cut to the sky and skyline above the track's lowest point, which keeps streets, cars
and their plates out of the picture.
Usage: .venv/bin/python scripts/demo_frames.py [clip numbers, default every tracked Chelyabinsk clip]
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unicodedata

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVENT = 'chelyabinsk-2013'
OUT = ROOT / 'out' / 'demo'
FONT = '/System/Library/Fonts/Helvetica.ttc'
TRACK, NIGHT, INK = (120, 188, 255), (8, 17, 31), (230, 237, 246)


def plain(text):
    """Uploader names can hold emoji, which the font cannot draw: keep letters, digits and punctuation."""
    kept = ''.join(ch for ch in text if ord(ch) < 0x10000 and unicodedata.category(ch) not in ('So', 'Cs', 'Co'))
    return ' '.join(kept.split())


def frame_at(video, t):
    with tempfile.TemporaryDirectory() as d:
        png = pathlib.Path(d) / 'f.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', str(video), '-frames:v', '1', str(png)], check=True)
        return Image.open(png).convert('RGB')


def make(no, credits):
    key = f'{EVENT}-{no}'
    video, track = ROOT / 'out' / 'sam' / f'{key}.mp4', ROOT / 'out' / 'sam' / f'{key}.json'
    if not video.exists() or not track.exists():
        return None
    rows = [r for r in json.loads(track.read_text())['rows'] if r['centroid'] is not None and not r['dup']]
    if len(rows) < 5:
        return None
    shown = rows[int(0.7 * (len(rows) - 1))]  # late enough to show most of the path, early enough to keep the fireball
    img = frame_at(video, shown['t'])
    w, h = img.size
    # SAM's points of the last 3 s only: a car still stopping moves the camera early in some clips, so older points
    # would not line up with this frame; and dots, not a line, show the measurements as they are, jitter included.
    points = [tuple(r['centroid']) for r in rows if shown['t'] - 3.0 <= r['t'] <= shown['t']]
    bottom = min(h, int(max(max(y for _, y in points) + 0.08 * h, 0.45 * h)))
    img = img.crop((0, 0, w, bottom))
    draw = ImageDraw.Draw(img)
    dot = max(2, w // 320)
    for px, py in points[:-1]:
        draw.ellipse((px - dot, py - dot, px + dot, py + dot), fill=TRACK)
    x, y = points[-1]
    r = max(5, w // 160)
    draw.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255), width=2)
    scale = 1920 / w
    img = img.resize((1920, int(bottom * scale)), Image.LANCZOS)
    band = 120
    canvas = Image.new('RGB', (1920, img.height + band), NIGHT)
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    big, small = ImageFont.truetype(FONT, 40), ImageFont.truetype(FONT, 28)
    c = credits.get(no, {})
    draw.text((40, img.height + 18), f"{c.get('site', no)}: SAM 3.1 finds the fireball from \"bright light\" (last 3 s of its track)",
              font=big, fill=INK)
    draw.text((40, img.height + 70), f"{plain(c.get('credit', ''))}. Catalogued by Borovička et al. 2016.", font=small, fill=(168, 181, 199))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f'{key}.png'
    canvas.save(path)
    return path


def main(nos):
    credits = {c['clip']: c for c in json.loads((ROOT / 'events' / EVENT / 'credits.json').read_text())}
    nos = nos or [c for c in credits if credits[c].get('source')]
    for no in nos:
        path = make(no, credits)
        print(no, path.relative_to(ROOT) if path else 'no trimmed clip or track')


if __name__ == '__main__':
    main(sys.argv[1:])
