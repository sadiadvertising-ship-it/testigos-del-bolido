"""Track cards for the demo video, drawn from the project's own numbers: no pixel of any video is used.

For each oriented Chelyabinsk camera a 1920x1080 card shows the SAM 3.1 points in the camera's own image coordinates,
the frame outline, the horizon (elevation 0 deg) and the landmarks the camera was oriented on, the last two placed
through the calibrated camera, and for Kamensk-Uralskiy where Muse Spark put the chapel. A landmark that the camera
cannot show is left out, and the script prints which.
The script reads these files and no others:
  events/chelyabinsk-2013/picks.json             each camera's position, image size, calibration and landmarks
  out/sam/chelyabinsk-2013-<clip>.json           the SAM 3.1 points
  events/chelyabinsk-2013/witness/2.json         Muse Spark's reading of the Kamensk-Uralskiy video, for the chapel
  events/chelyabinsk-2013/credits.json           each video's site and credit, for the caption
  /System/Library/Fonts/Helvetica.ttc            the font, which macOS ships; --font and --bold name other files
The cards go to out/demo/cards/, which git ignores.
Usage: .venv/bin/python scripts/track_cards.py [--out DIR] [--font PATH] [--bold PATH] [clip numbers, default 2 10 48]
"""
import argparse
import json
import pathlib
import sys
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from testigos.camera import Camera  # noqa: E402
from testigos.geo import azel_between, azel_to_enu  # noqa: E402

EVENT = 'chelyabinsk-2013'
CLIPS = ('2', '10', '48')
HELVETICA = '/System/Library/Fonts/Helvetica.ttc'  # as scripts/demo_frames.py; face 1 of the collection is its bold
FONT, BOLD = (HELVETICA, 0), (HELVETICA, 1)  # (file, face) for the regular and the bold text; see use_fonts()
W, H, BAND = 1920, 1080, 120
SS = 2  # drawn at twice the size and scaled down, so lines and dots come out smooth
NIGHT, SKY, GROUND, LINE = (8, 17, 31), (15, 27, 46), (11, 20, 35), (28, 42, 65)
INK, INK2, INK3 = (230, 237, 246), (168, 181, 199), (117, 131, 154)
TRACK, MUSE, MUSE2, FRAME = (120, 188, 255), (88, 214, 157), (64, 160, 118), (64, 84, 112)
COMPASS = {0: 'N', 45: 'NE', 90: 'E', 135: 'SE', 180: 'S', 225: 'SW', 270: 'W', 315: 'NW'}
# Muse Spark's reading of a landmark that the calibration also used: clip -> (index in the witness landmarks, a word
# that names the same landmark in picks.json)
GUESSES = {'2': (0, 'chapel')}
# What the pixel marked for a surveyed point shows, keyed by a word of its name in picks.json. picks.json places the
# chapel's point at its "footprint centre at ground", so its marked pixel is the chapel's base, not the dome Muse Spark
# may have pointed at.
MARKED = {'chapel': "marked at the chapel's base"}


def plain(text):
    """Uploader names can hold emoji, which the font cannot draw: keep letters, digits and punctuation."""
    kept = ''.join(ch for ch in text if ord(ch) < 0x10000 and unicodedata.category(ch) not in ('So', 'Cs', 'Co'))
    return ' '.join(kept.split())


def use_fonts(regular=None, bold=None):
    """--font and --bold. A file given for the regular text also draws the bold text, unless --bold names another."""
    global FONT, BOLD
    if regular:
        FONT = BOLD = (str(regular), 0)
    if bold:
        BOLD = (str(bold), 0)


def font(size, bold=False):
    """The font at `size` px (drawn at SS times that). Stops with one line naming the file if it cannot be opened."""
    path, face = BOLD if bold else FONT
    try:
        if not pathlib.Path(path).is_file():  # else Pillow looks for a file of that name in the system's font folders
            raise OSError('no such file')
        return ImageFont.truetype(path, size * SS, index=face)
    except OSError as e:
        which = f'face {face} of the font {path}' if face else f'the font {path}'
        sys.exit(f'{pathlib.Path(sys.argv[0]).name}: cannot open {which} ({e}); name a TrueType or OpenType file with '
                 '--font PATH, and with --bold PATH for the bold text')


def camera(entry):
    """The calibrated camera, built as the agent builds it (src/testigos/agent.py)."""
    c, (w, h) = entry['camera'], entry['image']
    return Camera(w, h, yaw=c['yaw'], pitch=c['pitch'], roll=c.get('roll', 0.0), hfov=c['hfov'], k1=c.get('k1', 0.0),
                  fisheye=entry.get('lens') == 'fisheye')


def place(cam, v, tilt=0.01):
    """(pixel, None) for ENU direction v when the camera shows it inside the frame, else (None, why not).

    Far outside the field of view the k1 polynomial folds directions back into the frame: past the fold, a direction
    further from the optical axis lands nearer the image centre (and further out still, on the other side of it), on
    a pixel that unprojects to another direction. So a pixel counts only if tilting v `tilt` degrees further from the
    axis still moves it outward on v's own side of the centre. This is the round trip through cam.unproject, made
    exact: near the fold, the eight fixed-point steps of cam.unproject stop short even where the model has not
    folded."""
    p = cam.project(v)
    if p is None:
        return None, 'it is behind the camera'
    v = np.asarray(v, float) / np.linalg.norm(v)
    right, down, fwd = cam.axes()
    across = v - np.dot(v, fwd) * fwd  # v's part across the optical axis
    if np.linalg.norm(across) > 1e-9:
        theta = np.arctan2(np.linalg.norm(across), np.dot(v, fwd)) + np.radians(tilt)
        q = cam.project(np.cos(theta) * fwd + np.sin(theta) * across / np.linalg.norm(across))
        side = np.array([np.dot(across, right), np.dot(across, down)])  # v's side of the centre, in the image
        centre = np.array([cam.width / 2, cam.height / 2])
        if q is None or np.dot(q - centre, side) <= np.dot(p - centre, side):
            return None, 'it lies past the fold of the lens model, so its pixel stands for another direction'
    if not (0 <= p[0] <= cam.width and 0 <= p[1] <= cam.height):
        return None, 'it falls outside the frame'
    return p, None


def seen(cam, v):
    """The pixel of ENU direction v inside the frame, or None (see place)."""
    return place(cam, v)[0]


def horizon(cam, step=0.05):
    """Runs of pixels at elevation 0 across the field of view."""
    runs, run = [], []
    for az in np.arange(cam.yaw - 120.0, cam.yaw + 120.0, step):
        p = seen(cam, azel_to_enu(az, 0.0))
        if p is not None:
            run.append(p)
        elif run:
            runs.append(run)
            run = []
    return [np.array(r) for r in runs + [run] if len(r) > 1]


def compass(cam):
    """(name, pixel) of the compass points on the horizon inside the frame."""
    return [(name, p) for az, name in COMPASS.items() if (p := seen(cam, azel_to_enu(az, 0.0))) is not None]


def landmarks(entry, cam):
    """Each landmark of picks.json placed through the camera: directions (vanishing points) and surveyed points. Each
    goes through place(), as the horizon does; one the camera cannot show gets px None and the reason in 'why'."""
    out = []
    for lm in entry.get('landmarks', []):
        if 'azel' in lm:
            px, why = place(cam, azel_to_enu(*lm['azel']))
            out.append({'kind': 'vanishing', 'what': lm['what'], 'px': px, 'why': why})
        elif 'pos' in lm:
            px, why = place(cam, azel_to_enu(*azel_between(tuple(entry['camera_pos']), tuple(lm['pos']))))
            out.append({'kind': 'x_only' if 'px_x' in lm else 'point', 'what': lm['what'], 'px': px, 'why': why,
                        'marked': lm.get('px')})
    return out


def marked_words(what):
    """The words for the pixel marked for a surveyed point: 'marked', or what it shows when MARKED knows the point."""
    return next((words for word, words in MARKED.items() if word in what), 'marked')


def title(what):
    """'vanishing point of ulitsa Shcherbakova heading south-west' -> 'Vanishing point of ulitsa Shcherbakova'."""
    name = what.split(',')[0].split(' heading ')[0]
    return name[0].upper() + name[1:]


class Card:
    """A 1920x1080 canvas with the camera frame scaled into the space above the caption band: centred, or pushed to one
    side ('left' or 'right') to leave room for an inset."""

    def __init__(self, cam, align='centre', top=70, bottom=30, side=120):
        self.cam = cam
        room_w, room_h = W - 2 * side, H - BAND - top - bottom
        self.s = min(room_w / cam.width, room_h / cam.height)
        wide = cam.width * self.s
        self.x0 = {'left': 60, 'right': W - 60 - wide}.get(align, (W - wide) / 2)
        self.y0 = top + (room_h - cam.height * self.s) / 2
        self.x1, self.y1 = self.x0 + wide, self.y0 + cam.height * self.s
        self.img = Image.new('RGB', (W * SS, H * SS), NIGHT)
        self.d = ImageDraw.Draw(self.img, 'RGBA')

    def at(self, p):
        """Camera pixel -> canvas pixel (1920x1080 units)."""
        return self.x0 + p[0] * self.s, self.y0 + p[1] * self.s

    def line(self, pts, fill, width=2):
        self.d.line([(x * SS, y * SS) for x, y in pts], fill=fill, width=round(width * SS), joint='curve')

    def dashed(self, a, b, fill, width=2, dash=10, gap=8):
        a, b = np.asarray(a, float), np.asarray(b, float)
        length = float(np.linalg.norm(b - a))
        u, s = (b - a) / length, 0.0
        while s < length:
            self.line([a + u * s, a + u * min(s + dash, length)], fill, width)
            s += dash + gap

    def dot(self, xy, r, fill):
        x, y = xy
        self.d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=fill)

    def ring(self, xy, r, fill, width=3):
        x, y = xy
        self.d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], outline=fill, width=round(width * SS))

    def cross(self, xy, r, fill, width=2, gap=6):
        x, y = xy
        for (ax, ay), (bx, by) in (((-r, 0), (-gap, 0)), ((gap, 0), (r, 0)), ((0, -r), (0, -gap)), ((0, gap), (0, r))):
            self.line([(x + ax, y + ay), (x + bx, y + by)], fill, width)

    def box(self, x0, y0, x1, y1, fill=None, outline=None, width=2):
        self.d.rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=fill, outline=outline,
                         width=round(width * SS) if outline else 0)

    def polygon(self, pts, fill):
        self.d.polygon([(x * SS, y * SS) for x, y in pts], fill=fill)

    def width_of(self, s, f):
        return f.getlength(s) / SS

    def text(self, xy, s, f, fill, anchor='la'):
        self.d.text((xy[0] * SS, xy[1] * SS), s, font=f, fill=fill, anchor=anchor)

    def block(self, xy, lines, align='l', gap=7):
        """Lines of (text, font, colour) stacked down from xy, aligned l, m or r on x."""
        x, y = xy
        for s, f, fill in lines:
            self.text((x, y), s, f, fill, anchor=align + 't')
            y += f.size / SS + gap

    def extent(self, xy, lines, align='l', gap=7):
        """The box (x0, y0, x1, y1) that block() fills with these lines."""
        wide = max(self.width_of(s, f) for s, f, _ in lines)
        x0 = {'l': xy[0], 'm': xy[0] - wide / 2, 'r': xy[0] - wide}[align]
        return x0, xy[1], x0 + wide, xy[1] + sum(f.size / SS for _, f, _ in lines) + gap * (len(lines) - 1)

    def clear(self, box, pts, margin=12):
        """True when the box lies inside the frame and none of the points (canvas pixels) comes within margin of it."""
        x0, y0, x1, y1 = box
        if x0 < self.x0 + margin or y0 < self.y0 + margin or x1 > self.x1 - margin or y1 > self.y1 - margin:
            return False
        return not ((pts[:, 0] > x0 - margin) & (pts[:, 0] < x1 + margin) &
                    (pts[:, 1] > y0 - margin) & (pts[:, 1] < y1 + margin)).any()

    def save(self, path):
        self.img.resize((W, H), Image.LANCZOS).save(path)


def draw_frame(card, runs, f_label, f_small):
    """Frame, sky above the horizon, horizon line, compass points."""
    cam = card.cam
    card.box(card.x0, card.y0, card.x1, card.y1, fill=GROUND)
    if len(runs) == 1 and runs[0][0][0] <= 2 and runs[0][-1][0] >= cam.width - 2:  # the sky: top edge to horizon
        line = [card.at(p) for p in runs[0]]
        card.polygon([(card.x0, card.y0), (card.x0, line[0][1])] + line + [(card.x1, line[-1][1]), (card.x1, card.y0)],
                     SKY)
    card.box(card.x0, card.y0, card.x1, card.y1, outline=FRAME, width=2)
    for run in runs:
        card.line([card.at(p) for p in run], INK3, 2)
    for name, p in compass(cam):
        cx, cy = card.at(p)
        card.line([(cx, cy - 9), (cx, cy + 9)], INK3, 2)
        card.text((cx, cy + 17), name, f_small, INK3, anchor='mt')
    if runs:  # the label rides above the horizon's left end, clear of the line wherever it rises
        pts = np.array([card.at(p) for p in runs[0]])
        label = 'Horizon, elevation 0°'
        x = pts[0][0] + 16
        under = pts[(pts[:, 0] >= x) & (pts[:, 0] <= x + card.width_of(label, f_label))][:, 1]
        card.text((x, (under.min() if len(under) else pts[0][1]) - 12), label, f_label, INK2, anchor='ls')


def inset_side(px, cam):
    """None when the track reads at the frame's scale; else the side ('left' or 'right') its enlarged inset goes on."""
    lo, hi = px.min(axis=0), px.max(axis=0)
    if np.hypot(*(hi - lo)) >= 0.15 * np.hypot(cam.width, cam.height):
        return None
    return 'left' if (lo[0] + hi[0]) / 2 < cam.width / 2 else 'right'


def window_start(lo, hi, n, side):
    """Where an inset window of `side` camera pixels starts along one axis, given the points' range lo..hi on an axis
    n pixels long: centred on the points, but an edge of the frame near the window is brought a tenth of a side inside,
    so the inset shows where the frame ends."""
    start = (lo + hi - side) / 2
    if start < 0.05 * side and hi <= 0.85 * side:
        start = min(start, -0.1 * side)
    if start + side > n - 0.05 * side and lo >= n - 0.85 * side:
        start = max(start, n - 0.9 * side)
    return float(start)


def draw_track(card, rows, f_label_b, f_label, f_note):
    """The SAM 3.1 points, dots as measured; a track too small to read at the frame's scale gets an enlarged inset."""
    cam = card.cam
    px = np.array([r['centroid'] for r in rows], float)
    pts = np.array([card.at(p) for p in px])
    for p in pts:
        card.dot(p, 3.2 if card.s < 2 else 4.0, TRACK + (235,))
    label = f'{len(rows)} SAM 3.1 points, one per frame'
    side_of = inset_side(px, cam)
    if side_of is None:  # under the first stretch of the track, clear of its dots
        x = pts[0][0] + 6
        wide = card.width_of(label, f_label_b)
        near = pts[(pts[:, 0] >= x - 10) & (pts[:, 0] <= x + wide + 10)][:, 1]
        card.block((x, near.max() + 22), [(label, f_label_b, TRACK)])
        return
    # the inset: a square window around the points, enlarged a whole number of times, beside the frame
    left = side_of == 'left'
    lo, hi = px.min(axis=0), px.max(axis=0)
    size = min((card.x0 if left else W - card.x1) - 110, 440)
    times = max(2, int(size / ((max(hi - lo) * 1.3 + 8) * card.s)))
    zoom = times * card.s
    side = size / zoom  # the window's side in camera pixels
    wx0, wy0 = [window_start(a, b, n, side) for a, b, n in zip(lo, hi, (cam.width, cam.height))]
    ix0, iy0 = (card.x0 - 50 - size) if left else (card.x1 + 50), card.y0

    def inset(p):
        return ix0 + (p[0] - wx0) * zoom, iy0 + (p[1] - wy0) * zoom

    # the window, as far as it lies inside the frame, and one connector to the inset through the empty sky
    a = card.at((max(wx0, 0.0), max(wy0, 0.0)))
    b = card.at((min(wx0 + side, cam.width), min(wy0 + side, cam.height)))
    card.box(a[0], a[1], b[0], b[1], outline=TRACK + (150,), width=1.5)
    card.line([(a[0] if left else b[0], (a[1] + b[1]) / 2), (ix0 + size if left else ix0, iy0 + size / 2)],
              TRACK + (110,), 1.5)
    card.box(ix0, iy0, ix0 + size, iy0 + size, fill=SKY)
    # the frame's own edges where they cross the window, with the outside left dark
    for edge, name in ((0.0, 'top of the frame'), (cam.height, 'bottom of the frame')):
        if wy0 < edge < wy0 + side:
            y = inset((0, edge))[1]
            card.box(ix0, *((iy0, ix0 + size, y) if edge == 0.0 else (y, ix0 + size, iy0 + size)), fill=NIGHT)
            card.line([(ix0, y), (ix0 + size, y)], FRAME, 2)
            card.text((ix0 + size - 12, y + 10 if edge == 0.0 else y - 10), name, f_note, INK3,
                      anchor='rt' if edge == 0.0 else 'rb')
    for edge in (0.0, cam.width):
        if wx0 < edge < wx0 + side:
            x = inset((edge, 0))[0]
            card.line([(x, iy0), (x, iy0 + size)], FRAME, 2)
    for p in px:
        card.dot(inset(p), 5.0, TRACK + (235,))
    card.box(ix0, iy0, ix0 + size, iy0 + size, outline=TRACK + (150,), width=1.5)
    card.block((ix0, iy0 + size + 16), [(label, f_label_b, TRACK), (f'enlarged {times} times', f_label, INK2)])


def make(no, picks, credits, out):
    """Draw one camera's card; returns (path, notes) or None when the camera is not oriented."""
    key = f'{EVENT}-{no}'
    entry = picks.get(key)
    if not entry or 'camera' not in entry:
        return None
    rows = [r for r in json.loads((ROOT / 'out' / 'sam' / f'{key}.json').read_text())['rows']
            if r['centroid'] is not None and not r['dup']]
    cam = camera(entry)
    side_of = inset_side(np.array([r['centroid'] for r in rows], float), cam)
    card = Card(cam, align={'left': 'right', 'right': 'left'}.get(side_of, 'centre'))
    big, small = font(40), font(26)
    label, label_b, note = font(24), font(24, bold=True), font(20)

    draw_frame(card, horizon(cam), label, note)
    card.text((card.x0, card.y0 - 14), f'Camera frame, {cam.width} × {cam.height} pixels', label, INK2, anchor='ls')
    card.text((card.x1, card.y0 - 14), 'Horizon and landmarks placed through the calibrated camera', label, INK2,
              anchor='rs')

    # the landmarks the camera was oriented on, placed through the camera
    notes, marks = [], landmarks(entry, cam)
    for lm in marks:
        if lm['px'] is None:
            notes.append(f"{title(lm['what'])} is not drawn: {lm['why']}")
            continue
        lx, ly = card.at(lm['px'])
        if lm['kind'] == 'vanishing':  # flagged to the left of a leader, below the compass letters
            card.ring((lx, ly), 7, INK, 2)
            card.line([(lx, ly + 12), (lx, ly + 104)], INK3, 1.5)
            card.block((lx - 12, ly + 84), [(title(lm['what']), label_b, INK),
                                            ('its direction from OpenStreetMap', label, INK2)], align='r')
        elif lm['kind'] == 'x_only':  # an object of unknown height: the fit used only its column
            card.dashed((lx, card.y0 + 6), (lx, card.y1 - 6), INK2, 2)
            card.block((lx - 16, card.y0 + 20), [(title(lm['what']).removesuffix(' top'), label_b, INK),
                                                 ('from OpenStreetMap; only its x counts', label, INK2)], align='r')
        else:
            # the surveyed point through the camera (a dot) inside a cross on the pixel marked for it: the fit leaves
            # them a residual apart, a few pixels for the chapel
            card.dot((lx, ly), 3.0, INK)
            mx, my = card.at(lm['marked']) if lm['marked'] else (lx, ly)
            card.cross((mx, my), 18, INK, 2)
            # labels hang below the marker, clear of the horizon it sits on; the marked pixel gives both fractions, as
            # Muse Spark's guess does, so the gap between the two reads as base against chapel, not as a miss
            card.block((mx - 30, my + 2), [(marked_words(lm['what']), label, INK)] +
                       ([(f"{lm['marked'][0] / cam.width:.3f} of the width, "
                          f"{lm['marked'][1] / cam.height:.3f} of the height", label, INK2)] if lm['marked'] else []),
                       align='r')
            detail = lm['what'].partition(',')[2].strip()
            card.block((mx + 18, my + 80), [(title(lm['what']), label_b, INK),
                                            (f'{detail}, from OpenStreetMap' if detail else 'from OpenStreetMap',
                                             label, INK2)], align='r')
            if lm['marked']:
                miss = np.hypot(*(lm['px'] - np.array(lm['marked'])))
                notes.append(f"{title(lm['what'])}: its OSM point through the camera is {miss:.1f} px from the marked "
                             'pixel')

    # Muse Spark's guess for the same landmark
    if no in GUESSES:
        i, word = GUESSES[no]
        g = json.loads((ROOT / 'events' / EVENT / 'witness' / f'{no}.json').read_text())['landmarks'][i]
        gx, gy = card.at((g['x_frac'] * cam.width, g['y_frac'] * cam.height))
        same = [lm for lm in marks if word in lm['what'] and lm.get('marked') and lm['px'] is not None]
        if same:  # a faint guide down to the marked landmark: the two share a column
            mx, my = card.at(same[0]['marked'])
            card.dashed((gx, gy + 22), (mx, my - 24), INK3 + (150,), 1.5, dash=4, gap=6)
        card.ring((gx, gy), 17, MUSE, 3)
        lines = [("Muse Spark's guess", label, MUSE),
                 (f"{g['x_frac']} of the width, {g['y_frac']} of the height", label, MUSE2)]
        # beside the ring, or above it when the SAM points run beside it
        dots = np.array([card.at(r['centroid']) for r in rows])
        spots = [(gx - 30, gy - 22), (gx + 18, gy - 30 - (card.extent((0, 0), lines)[3]))]
        card.block(next((xy for xy in spots if card.clear(card.extent(xy, lines, 'r'), dots)), spots[-1]), lines,
                   align='r')
        notes.append(f"Muse Spark's guess at ({g['x_frac']}, {g['y_frac']}) of the frame")

    draw_track(card, rows, label_b, label, note)

    # caption band, as scripts/demo_frames.py draws it
    card.line([(0, H - BAND), (W, H - BAND)], LINE, 1)
    c = credits.get(no, {})
    card.text((40, H - BAND + 18), f"{c.get('site', no)}: SAM 3.1 points from the phrase \"bright light\"", big, INK)
    card.text((40, H - BAND + 72), 'Drawn from the measurements; no frame of the video is shown. Video: '
              f"{plain(c.get('credit') or '')}", small, INK2)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f'{key}.png'
    card.save(path)
    return path, notes


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('clips', nargs='*', default=list(CLIPS))
    ap.add_argument('--out', type=pathlib.Path, default=ROOT / 'out' / 'demo' / 'cards')
    ap.add_argument('--font', type=pathlib.Path, metavar='PATH',
                    help=f'font file for the text (default {HELVETICA}, which macOS ships)')
    ap.add_argument('--bold', type=pathlib.Path, metavar='PATH',
                    help='font file for the bold text (default face 1 of Helvetica.ttc; with --font alone, that font)')
    args = ap.parse_args(argv)
    use_fonts(args.font, args.bold)
    picks = json.loads((ROOT / 'events' / EVENT / 'picks.json').read_text())
    credits = {c['clip']: c for c in json.loads((ROOT / 'events' / EVENT / 'credits.json').read_text())}
    for no in args.clips:
        made = make(no, picks, credits, args.out)
        if made is None:
            print(no, 'not oriented')
            continue
        path, notes = made
        print(no, path)
        for line in notes:
            print('  ', line)


if __name__ == '__main__':
    main(sys.argv[1:])
