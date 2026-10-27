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
PHRASES = ('fireball', 'meteor', 'bright light', 'light streak')


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
    h, w = gray.shape
    sx, sy = w / box.get('w', w), h / box.get('h', h)
    x1, y1 = max(int(box['x1'] * sx), 0), max(int(box['y1'] * sy), 0)
    x2, y2 = min(int(np.ceil((box['x2'] + 1) * sx)), w), min(int(np.ceil((box['y2'] + 1) * sy)), h)
    crop = gray[y1:y2, x1:x2].astype(float)
    if crop.size == 0:
        return None
    weights = np.where(crop >= np.percentile(crop, pct), crop, 0.0)
    if weights.sum() == 0:
        return None
    ys, xs = np.indices(crop.shape)
    return np.array([x1 + (xs * weights).sum() / weights.sum(), y1 + (ys * weights).sum() / weights.sum()])


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


def track_fireball(file_id, n_frames, phrases=PHRASES, min_coverage=0.8, purpose=''):
    """Try each phrase until one object covers enough frames; returns (phrase, {frame: box}, coverage)."""
    best = (None, {}, 0.0)
    for phrase in phrases:
        text = api.sam_video(file_id, phrase, n_frames, metadata={'include_confidence': 'true'},
                             purpose=f'{purpose} {phrase}'.strip())
        frames = dominant(parse(text))
        cov = coverage(frames, n_frames)
        if cov > best[2]:
            best = (phrase, frames, cov)
        if cov >= min_coverage:
            break
    return best
