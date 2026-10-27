"""Day-1 probe: does SAM 3.1 track the fireball in real witness clips?

Usage: .venv/bin/python scripts/sam_probe.py <event_id> <catalog_no> [<catalog_no> ...]
For each clip: trim to the event window, upload, track with the phrase fallback chain, then compare
SAM's bright-core centroids with a model-free blob tracker and write proof sheets for a visual check.
Everything lands in out/sam/; every call is priced and capped by api.py.
"""
import json
import pathlib
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from testigos import api, clip, track  # noqa: E402

OUT = ROOT / 'out' / 'sam'


def write_pgm(path, img):
    h, w = img.shape
    path.write_bytes(f'P5 {w} {h} 255\n'.encode() + img.astype(np.uint8).tobytes())


def mark(img, box_px, cross=None):
    out = img.copy()
    if box_px is not None:
        x1, y1, x2, y2 = (int(round(v)) for v in box_px)
        out[max(y1, 0):y2 + 1, max(x1, 0):max(x1, 0) + 2] = 255
        out[max(y1, 0):y2 + 1, max(x2 - 1, 0):x2 + 1] = 255
        out[max(y1, 0):max(y1, 0) + 2, max(x1, 0):x2 + 1] = 255
        out[max(y2 - 1, 0):y2 + 1, max(x1, 0):x2 + 1] = 255
    if cross is not None:
        cx, cy = (int(round(v)) for v in cross)
        out[max(cy - 6, 0):cy + 7, cx:cx + 1] = 0
        out[cy:cy + 1, max(cx - 6, 0):cx + 7] = 0
    return out


def tile(paths, dst, cols):
    """Grid of same-size images with ffmpeg xstack; offsets are multiples of the first image's size."""
    if len(paths) == 1:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(paths[0]), str(dst)], check=True)
        return
    layout = '|'.join(f'{"+".join(["w0"] * (i % cols)) or "0"}_{"+".join(["h0"] * (i // cols)) or "0"}'
                      for i in range(len(paths)))
    args = ['ffmpeg', '-v', 'error', '-y']
    for p in paths:
        args += ['-i', str(p)]
    args += ['-filter_complex', f'xstack=inputs={len(paths)}:layout={layout}:fill=black', str(dst)]
    subprocess.run(args, check=True)


def probe_clip(event, c):
    name = f"{event['id']}-{c['catalog_no']}"
    raw = ROOT / 'data' / event['id'].split('-')[0] / 'raw' / f"{c['catalog_no']}.mp4"
    small = OUT / f'{name}.mp4'
    OUT.mkdir(parents=True, exist_ok=True)
    start, end = c['window_s']
    clip.normalize(raw, small, start, end)
    times = clip.frame_times(small)
    n = len(times)
    file_id = api.upload(small)
    res = track.track_fireball(file_id, n, purpose=name, cache_prefix=api.file_sha(small))
    phrase, frames, cov = res['phrase'], res['track'], res['coverage_of_clip']
    (OUT / f'{name}.frames.json').write_text(json.dumps({k: v for k, v in res.items()}))

    grays = list(clip.gray_frames(small))
    dup = clip.duplicate_flags(grays)
    blobs = track.blob_track(grays)
    raw_hits = len(frames)
    heads = track.measure(frames, grays)
    frames = {k: frames[k] for k in heads}
    rows, dists = [], []
    for i, g in enumerate(grays):
        box = frames.get(i)
        cen = heads.get(i)
        blob = blobs[i]
        d = float(np.hypot(*(cen - blob))) if cen is not None and blob is not None else None
        if d is not None:
            dists.append(d)
        rows.append({'frame': i, 't': float(times[i]) if i < n else None, 'dup': bool(dup[i]),
                     'box': [box[k] for k in ('x1', 'y1', 'x2', 'y2')] if box else None,
                     'c': box.get('c') if box else None,
                     'centroid': cen.tolist() if cen is not None else None,
                     'blob': blob.tolist() if blob is not None else None, 'sam_vs_blob_px': d})
    hit = [r['frame'] for r in rows if r['box']]
    summary = {'clip': name, 'phrase': phrase, 'objects': res['objects'], 'chosen_id': res['id'],
               'travel_px': res['travel_px'], 'frames': n, 'sam_frames': raw_hits, 'detected': len(hit),
               'coverage_of_clip': round(cov, 3),
               'first_last': [hit[0], hit[-1]] if hit else None,
               'coverage_of_span': round(len(hit) / (hit[-1] - hit[0] + 1), 3) if hit else 0.0,
               'duplicates': int(dup.sum()),
               'median_sam_vs_blob_px': round(float(np.median(dists)), 2) if dists else None,
               'agree_within_5px': round(float(np.mean(np.array(dists) < 5)), 3) if dists else None}
    (OUT / f'{name}.json').write_text(json.dumps({'summary': summary, 'rows': rows}, indent=1))

    # Proof sheets: 6 full frames with the SAM box, and 10 zoomed crops with a cross on the centroid.
    if hit:
        picks = np.linspace(hit[0], hit[-1], 6).astype(int)
        sx = grays[0].shape[1] / frames[hit[0]]['w']
        sy = grays[0].shape[0] / frames[hit[0]]['h']
        paths = []
        for k, i in enumerate(picks):
            b = frames.get(int(i))
            bp = [b['x1'] * sx, b['y1'] * sy, b['x2'] * sx, b['y2'] * sy] if b else None
            p = OUT / f'{name}-full-{k}.pgm'
            write_pgm(p, mark(grays[int(i)], bp)[::2, ::2])
            paths.append(p)
        tile(paths, OUT / f'{name}-full.jpg', 3)
        crops = []
        for k, i in enumerate(np.linspace(hit[0], hit[-1], 10).astype(int)):
            r = rows[int(i)]
            if r['centroid'] is None:
                continue
            cx, cy = r['centroid']
            g = mark(grays[int(i)], None, (cx, cy))
            x0, y0 = int(max(cx - 40, 0)), int(max(cy - 40, 0))
            crop = g[y0:y0 + 80, x0:x0 + 80]
            crop = np.pad(crop, ((0, 80 - crop.shape[0]), (0, 80 - crop.shape[1])))
            p = OUT / f'{name}-crop-{k}.pgm'
            write_pgm(p, np.kron(crop, np.ones((3, 3), np.uint8)))
            crops.append(p)
        if crops:
            tile(crops, OUT / f'{name}-crops.jpg', 5)
        for p in paths + crops:
            p.unlink()
    return summary


if __name__ == '__main__':
    event_id, nos = sys.argv[1], [int(x) for x in sys.argv[2:]]
    event = json.loads((ROOT / 'events' / event_id / 'event.json').read_text())
    for c in event['clips']:
        if c['catalog_no'] in nos:
            print(json.dumps(probe_clip(event, c)))
    print(f'spent today: US$ {api.spent_today():.3f} of {api.budget():.2f}')
