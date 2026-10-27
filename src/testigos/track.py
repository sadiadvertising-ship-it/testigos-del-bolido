"""Fireball pixels per frame: SAM 3.1 video tracking, a bright-core centroid, and a plain numpy baseline.

SAM's box finds the fireball; the centroid of the brightest 5% of pixels inside the box is the measurement,
because the mask of a saturated fireball also covers bloom and lens flare.
"""
from __future__ import annotations

import re
from collections import Counter

import numpy as np
from scipy import ndimage

from . import api

FRAME = re.compile(r'<(\d+)f>')
RECORD = re.compile(r'(\d+)<\|box;([^|]*)\|>')
# On six Chelyabinsk clips only 'bright light' found the fireball; 'fireball', 'meteor' and 'light streak'
# returned nothing, so they are not tried by default.
PHRASES = ('bright light',)


def parse(text):
    """SAM 3.1 token text -> {frame: [{'id', 'x1', 'y1', 'x2', 'y2', 'w', 'h', 'c'?}]}."""
    out = {}
    parts = FRAME.split(text)
    for frame, chunk in zip(parts[1::2], parts[2::2]):
        recs = out.setdefault(int(frame), [])
        for oid, fields in RECORD.findall(chunk):
            box = {k: float(v) for k, v in (kv.split('=', 1) for kv in fields.split(';') if '=' in kv)}
            recs.append({'id': int(oid), **box})
    return out


def dominant(frames):
    """Keep one object: the id seen in the most frames."""
    counts = Counter(r['id'] for recs in frames.values() for r in recs)
    if not counts:
        return {}
    best = counts.most_common(1)[0][0]
    return {f: next(r for r in recs if r['id'] == best) for f, recs in frames.items() if any(r['id'] == best for r in recs)}


def bright_centroid(gray, box, pct=95.0):
    """Intensity-weighted centroid of the brightest pixels inside a SAM box, in this frame's pixels."""
    crop, x1, y1 = _crop(gray, box)
    crop = crop.astype(float)
    if crop.size == 0:
        return None
    weights = np.where(crop >= np.percentile(crop, pct), crop, 0.0)
    if weights.sum() == 0:
        return None
    ys, xs = np.indices(crop.shape)
    return np.array([x1 + (xs * weights).sum() / weights.sum(), y1 + (ys * weights).sum() / weights.sum()])


def _crop(gray, box):
    h, w = gray.shape
    sx, sy = w / box.get('w', w), h / box.get('h', h)
    x1, y1 = max(int(box['x1'] * sx), 0), max(int(box['y1'] * sy), 0)
    x2, y2 = min(int(np.ceil((box['x2'] + 1) * sx)), w), min(int(np.ceil((box['y2'] + 1) * sy)), h)
    return gray[y1:y2, x1:x2], x1, y1


def head_point(gray, box, direction=None, lead_frac=0.1, streak_ratio=3.0):
    """The fireball's head inside a SAM box.

    A streak (head plus a train as bright as the head, as in daylight) is measured at its leading end along
    the motion; a round glow (the flare) is measured at its centre, since the glow surrounds the head.
    """
    crop, x1, y1 = _crop(gray, box)
    if crop.size == 0:
        return None
    crop = crop.astype(float)
    thr = max(np.percentile(crop, 99), 0.9 * crop.max())
    ys, xs = np.nonzero(crop >= thr)
    if len(xs) == 0:
        return None
    if direction is not None and len(xs) > 3:
        ev = np.linalg.eigvalsh(np.cov(np.vstack([xs, ys]).astype(float)) + 1e-6 * np.eye(2))
        if np.sqrt(ev[1] / ev[0]) >= streak_ratio:
            proj = xs * direction[0] + ys * direction[1]
            lead = proj >= np.percentile(proj, 100 * (1 - lead_frac))
            xs, ys = xs[lead], ys[lead]
    return np.array([x1 + xs.mean(), y1 + ys.mean()])


def contrast(gray, box, pad=0.5, min_pad_px=20):
    """Box peak minus the median sky in a ring around the box."""
    h, w = gray.shape
    crop, x1, y1 = _crop(gray, box)
    if crop.size == 0:
        return 0.0
    bh, bw = crop.shape
    px, py = max(int(bw * pad), min_pad_px), max(int(bh * pad), min_pad_px)
    X1, Y1, X2, Y2 = max(x1 - px, 0), max(y1 - py, 0), min(x1 + bw + px, w), min(y1 + bh + py, h)
    ring = gray[Y1:Y2, X1:X2].astype(float).copy()
    ring[y1 - Y1:y1 - Y1 + bh, x1 - X1:x1 - X1 + bw] = np.nan
    sky = np.nanmedian(ring) if np.isfinite(ring).any() else 0.0
    return float(crop.max()) - float(sky)


def motion_direction(track_):
    """Unit image-space direction of travel, from the first to the last box centre."""
    ks = sorted(track_)
    if len(ks) < 2:
        return None
    d = _center(track_[ks[-1]]) - _center(track_[ks[0]])
    n = np.linalg.norm(d)
    return d / n if n > 0 else None


def measure(track_, grays, min_contrast=30.0, max_resid_px=15.0, min_step_px=0.5):
    """Head point per frame from a SAM track.

    Drops frames whose box holds nothing brighter than the sky, points off a smooth path in time
    (cubic per axis, iterated), and a static tail where SAM held on to a pole after the fireball faded.
    """
    direction = motion_direction(track_)
    pts = {}
    for k in sorted(track_):
        if k >= len(grays):
            continue
        if contrast(grays[k], track_[k]) < min_contrast:
            continue
        p = head_point(grays[k], track_[k], direction)
        if p is not None:
            pts[k] = p
    for _ in range(4):
        if len(pts) < 8:
            break
        ks = np.array(sorted(pts))
        P = np.array([pts[k] for k in ks])
        t = ks.astype(float)
        resid = np.zeros(len(ks))
        for axis in (0, 1):
            resid = np.maximum(resid, np.abs(P[:, axis] - np.polyval(np.polyfit(t, P[:, axis], 3), t)))
        keep = resid <= max(max_resid_px, 3 * float(np.median(resid)))
        if keep.all():
            break
        pts = {int(k): pts[int(k)] for k, ok in zip(ks, keep) if ok}
    ks = sorted(pts)
    while len(ks) > 10 and np.linalg.norm(pts[ks[-1]] - pts[ks[-6]]) < 5 * min_step_px:
        ks.pop()
    return {k: pts[k] for k in ks}


def blob_track(frames, min_level=200, min_area=3):
    """Baseline without any model: the largest saturated blob per frame, kept only if it moves smoothly."""
    pts = []
    for f in frames:
        lab, n = ndimage.label(f >= min_level)
        if n == 0:
            pts.append(None)
            continue
        areas = ndimage.sum(np.ones_like(f), lab, range(1, n + 1))
        k = int(np.argmax(areas)) + 1
        if areas[k - 1] < min_area:
            pts.append(None)
            continue
        cy, cx = ndimage.center_of_mass(f.astype(float) * (lab == k))
        pts.append(np.array([cx, cy]))
    return pts


def coverage(frames, n_frames):
    return len(frames) / max(n_frames, 1)


def objects(frames):
    """{id: {frame: box}} from parsed SAM output."""
    out = {}
    for f, recs in frames.items():
        for r in recs:
            out.setdefault(r['id'], {})[f] = r
    return out


def _center(b):
    return np.array([(b['x1'] + b['x2']) / 2, (b['y1'] + b['y2']) / 2])


def pick_moving(frames, min_frames=10):
    """The object that travels farthest across the image: headlights and street lamps stay put, a fireball does not.

    Returns (id, {frame: box}, travel_px) or (None, {}, 0.0).
    """
    best = (None, {}, 0.0)
    for oid, track_ in objects(frames).items():
        if len(track_) < min_frames:
            continue
        ks = sorted(track_)
        travel = float(np.linalg.norm(_center(track_[ks[-1]]) - _center(track_[ks[0]])))
        if travel > best[2]:
            best = (oid, dict(sorted(track_.items())), travel)
    return best


def track_fireball(file_id, n_frames, phrases=PHRASES, min_span_coverage=0.8, min_travel_px=50,
                   purpose='', cache_prefix=None):
    """Try each phrase until a moving object is tracked through most of its span.

    Returns a dict with the phrase, every object SAM returned, and the chosen object's track.
    """
    best = None
    for phrase in phrases:
        text = api.sam_video(file_id, phrase, n_frames, metadata={'include_confidence': 'true'},
                             purpose=f'{purpose} {phrase}'.strip(),
                             cache_key=f'{cache_prefix}-{phrase.replace(" ", "_")}' if cache_prefix else None)
        frames = parse(text)
        oid, chosen, travel = pick_moving(frames)
        ks = sorted(chosen)
        span_cov = len(ks) / (ks[-1] - ks[0] + 1) if ks else 0.0
        result = {'phrase': phrase, 'objects': len(objects(frames)), 'id': oid, 'track': chosen,
                  'travel_px': round(travel, 1), 'span_coverage': round(span_cov, 3),
                  'coverage_of_clip': round(coverage(chosen, n_frames), 3)}
        if best is None or result['travel_px'] * result['span_coverage'] > best['travel_px'] * best['span_coverage']:
            best = result
        if span_cov >= min_span_coverage and travel >= min_travel_px:
            break
    return best


def track_video(small, name, out_dir, window=None, max_usd=0.10):
    """SAM 3.1 on a trimmed clip, or on a window of it: the chosen object's head per frame and the numpy baseline,
    written to out_dir/<name>.json in the format of scripts/sam_probe.py. Times stay on the trimmed clip's clock.

    The agent's `track` tool calls this for a clip nobody has tracked yet; a clip that would cost more than `max_usd`
    is refused before any call.
    """
    import json
    import pathlib

    from . import clip as cliplib

    out_dir, src, offset = pathlib.Path(out_dir), pathlib.Path(small), 0.0
    if window:
        src, offset = out_dir / f'{name}-window.mp4', float(window[0])
        cliplib.normalize(small, src, window[0], window[1])
    times = cliplib.frame_times(src)
    n = len(times)
    usd = max(n, 50) * api.SAM_VIDEO_FRAME
    if usd > max_usd:
        raise ValueError(f'{n} frames would cost about US$ {usd:.2f}; trim the clip first')
    res = track_fireball(api.upload(src), n, purpose=name, cache_prefix=api.file_sha(src))
    grays = list(cliplib.gray_frames(src))
    dup = cliplib.duplicate_flags(grays)
    blobs = blob_track(grays)
    raw_hits = len(res['track'])
    heads = measure(res['track'], grays)
    frames = {k: res['track'][k] for k in heads}
    rows, dists = [], []
    for i in range(len(grays)):
        box, cen, blob = frames.get(i), heads.get(i), blobs[i]
        d = float(np.hypot(*(cen - blob))) if cen is not None and blob is not None else None
        if d is not None:
            dists.append(d)
        rows.append({'frame': i, 't': offset + float(times[i]) if i < n else None, 'dup': bool(dup[i]),
                     'box': [box[k] for k in ('x1', 'y1', 'x2', 'y2')] if box else None, 'c': box.get('c') if box else None,
                     'centroid': cen.tolist() if cen is not None else None,
                     'blob': blob.tolist() if blob is not None else None, 'sam_vs_blob_px': d})
    hit = [r['frame'] for r in rows if r['box']]
    summary = {'clip': name, 'phrase': res['phrase'], 'objects': res['objects'], 'chosen_id': res['id'],
               'travel_px': res['travel_px'], 'frames': n, 'sam_frames': raw_hits, 'detected': len(hit),
               'coverage_of_clip': round(res['coverage_of_clip'], 3), 'first_last': [hit[0], hit[-1]] if hit else None,
               'coverage_of_span': round(len(hit) / (hit[-1] - hit[0] + 1), 3) if hit else 0.0,
               'duplicates': int(dup.sum()), 'window_s': [round(w, 2) for w in window] if window else None,
               'median_sam_vs_blob_px': round(float(np.median(dists)), 2) if dists else None,
               'agree_within_5px': round(float(np.mean(np.array(dists) < 5)), 3) if dists else None}
    out = {'summary': summary, 'rows': rows}
    (out_dir / f'{name}.json').write_text(json.dumps(out, indent=1))
    return out
