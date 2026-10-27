"""Draw OpenStreetMap features into a video frame through a candidate camera, to see whether a calibration fits.

This is the picture behind "the user confirms": if the projected buildings, roads, lamps and chimneys
sit on top of the real ones, the camera is right; if not, you can see which way it is off.
"""
from __future__ import annotations

import json
import re
import subprocess

import numpy as np

from .geo import enu_basis, to_ecef

COLORS = {'building': (255, 210, 0), 'highway': (0, 200, 255), 'lamp': (255, 60, 200), 'tower': (255, 40, 40),
          'church': (60, 255, 60), 'power': (200, 120, 255)}


def _height(tags, default):
    for k in ('height', 'est_height'):
        m = re.match(r'[\d.]+', str(tags.get(k, '')))
        if m:
            return float(m.group())
    m = re.match(r'[\d.]+', str(tags.get('building:levels', '')))
    return float(m.group()) * 3.0 if m else default


def features(osm_json_path):
    """OSM elements (Overpass 'out geom tags') -> drawable features with heights in metres."""
    out = []
    for e in json.load(open(osm_json_path))['elements']:
        t = e.get('tags', {})
        if e['type'] == 'way' and 'geometry' in e:
            pts = [(p['lat'], p['lon']) for p in e['geometry']]
            if t.get('amenity') == 'place_of_worship':
                out.append({'kind': 'church', 'pts': pts, 'h': _height(t, 15.0), 'tags': t})
            elif 'building' in t:
                out.append({'kind': 'building', 'pts': pts, 'h': _height(t, 6.0), 'tags': t})
            elif 'highway' in t and t['highway'] not in ('footway', 'path', 'steps', 'service', 'track', 'cycleway'):
                out.append({'kind': 'highway', 'pts': pts, 'h': 0.0, 'tags': t})
            elif t.get('power') == 'line':
                out.append({'kind': 'power', 'pts': pts, 'h': _height(t, 12.0), 'tags': t})
            elif 'man_made' in t:
                c = np.mean(pts, axis=0)
                out.append({'kind': 'tower', 'pts': [tuple(c)], 'h': _height(t, 30.0), 'tags': t})
        elif e['type'] == 'node':
            pt = [(e['lat'], e['lon'])]
            if t.get('highway') == 'street_lamp':
                out.append({'kind': 'lamp', 'pts': pt, 'h': 9.0, 'tags': t})
            elif t.get('highway') == 'traffic_signals':
                out.append({'kind': 'lamp', 'pts': pt, 'h': 5.0, 'tags': t})
            elif t.get('power') in ('pole', 'tower'):
                out.append({'kind': 'power', 'pts': pt, 'h': _height(t, 12.0 if t.get('power') == 'pole' else 30.0), 'tags': t})
            elif 'man_made' in t:
                out.append({'kind': 'tower', 'pts': pt, 'h': _height(t, 30.0), 'tags': t})
            elif t.get('amenity') == 'place_of_worship':
                out.append({'kind': 'church', 'pts': pt, 'h': _height(t, 15.0), 'tags': t})
    return out


class Projector:
    def __init__(self, cam, cam_pos, cam_height=1.3, ground=0.0):
        self.cam, self.basis = cam, enu_basis(cam_pos[0], cam_pos[1])
        self.origin = to_ecef(cam_pos[0], cam_pos[1], ground + cam_height)
        self.ground = ground

    def __call__(self, lat, lon, h):
        v = self.basis @ (to_ecef(lat, lon, self.ground + h) - self.origin)
        return self.cam.project(v / np.linalg.norm(v)), float(np.linalg.norm(v))


def _draw_line(img, p, q, color, width=1):
    h, w = img.shape[:2]
    n = int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) + 1
    if n > 4 * (w + h):
        return
    xs = np.linspace(p[0], q[0], n).round().astype(int)
    ys = np.linspace(p[1], q[1], n).round().astype(int)
    for dx in range(-(width // 2), width // 2 + 1):
        for dy in range(-(width // 2), width // 2 + 1):
            ok = (xs + dx >= 0) & (xs + dx < w) & (ys + dy >= 0) & (ys + dy < h)
            img[ys[ok] + dy, xs[ok] + dx] = color


def _segment(img, proj, a, b, color, steps=12, width=1):
    """Draw a 3D segment a-b ((lat, lon, h) each), sampled so lens distortion bends it correctly."""
    prev = None
    for s in np.linspace(0, 1, steps):
        lat, lon, h = (a[i] + s * (b[i] - a[i]) for i in range(3))
        px, _ = proj(lat, lon, h)
        if px is not None and prev is not None:
            _draw_line(img, prev, px, color, width)
        prev = px


def render(rgb, proj, feats, max_dist=3000.0, kinds=None):
    img = rgb.copy()
    for f in feats:
        if kinds and f['kind'] not in kinds:
            continue
        pts, h, col = f['pts'], f['h'], COLORS[f['kind']]
        d0 = proj(pts[0][0], pts[0][1], 0)[1]
        if d0 > max_dist:
            continue
        if f['kind'] in ('building', 'church'):
            for (a, b) in zip(pts, pts[1:]):
                _segment(img, proj, (*a, h), (*b, h), col)
                _segment(img, proj, (*a, 0), (*b, 0), tuple(c // 2 for c in col))
            for p in pts[:-1]:
                _segment(img, proj, (*p, 0), (*p, h), col, steps=4)
        elif f['kind'] == 'highway':
            for (a, b) in zip(pts, pts[1:]):
                _segment(img, proj, (*a, 0), (*b, 0), col, steps=20)
        elif f['kind'] == 'power' and len(pts) > 1:
            for (a, b) in zip(pts, pts[1:]):
                _segment(img, proj, (*a, h), (*b, h), col)
        else:
            _segment(img, proj, (*pts[0], 0), (*pts[0], h), col, steps=4, width=3)
    return img


def read_rgb(path):
    meta = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                      'stream=width,height', '-of', 'json', str(path)],
                                     capture_output=True, text=True, check=True).stdout)['streams'][0]
    w, h = meta['width'], meta['height']
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-frames:v', '1', '-f', 'rawvideo',
                          '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).copy()


def write_png(path, rgb):
    h, w = rgb.shape[:2]
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}',
                    '-i', '-', str(path)], input=rgb.tobytes(), check=True)
