"""Kamensk-Uralskiy's head point: where its definition changes, and what each side gives with Korkino.

track.head_point measures the fireball inside SAM's box. Its brightest pixels are those at or above both the box's
99th percentile and 90 percent of its peak. When they spread at least 3 times farther along their long axis than across
it, the fireball is a streak, and its head is the mean position of the leading tenth of them along the motion.
Otherwise it is a round glow, and its head is the mean position of all of them.
The video frames are not in the repository. out/sam/chelyabinsk-2013-2.json keeps each frame's SAM box and head point,
but not which of the two the code used. The box shows where the fireball's shape in the image changes. The split frame
is the first frame whose box is not longer along the motion than across it. The motion is the image direction from the
first to the last box centre (track.motion_direction).
Kamensk-Uralskiy's points before the split frame, and from it on, are each solved with Korkino's points through
testigos.solve, with the stations the agent builds (Case._stations). The README's figures are compared with each side.
Every split frame within 20 tracked frames of the change is also tried, to find the ones that give the README's figures.
Writes validation/chelyabinsk-2013/head-point-split.json.
Usage: .venv/bin/python scripts/head_split.py
"""
import inspect
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stations import ROOT  # noqa: E402
from testigos import track  # noqa: E402
from testigos.agent import Case  # noqa: E402
from testigos.solve import Station, solve  # noqa: E402

SAM = ROOT / 'out' / 'sam' / 'chelyabinsk-2013-2.json'
OUT = ROOT / 'validation' / 'chelyabinsk-2013' / 'head-point-split.json'
README = {'source': 'README.md at commit 70c300a, "What these numbers do not say"',
          'before': {'slope_deg': 16.2, 'speed_kms': 16.8}, 'after': {'slope_deg': 20.3, 'speed_kms': 19.1}}
SCAN = 20  # tracked frames tried on each side of the change
BLOCK = 20  # tracked frames per block in the profile of where the head point sits in its box


def lengths(box, u):
    """Length of an image box along the unit direction u and across it, in pixels."""
    w, h = box[2] - box[0], box[3] - box[1]
    return abs(u[0]) * w + abs(u[1]) * h, abs(u[1]) * w + abs(u[0]) * h


def head_in_box(row, u):
    """Where the head point sits in its box along the motion: 0 at the box centre, 1 at its leading end."""
    x1, y1, x2, y2 = row['box']
    along = lengths(row['box'], u)[0]
    return float((np.array(row['centroid']) - [(x1 + x2) / 2, (y1 + y2) / 2]) @ u / (along / 2))


def result(sol):
    return {'heading_deg': round(sol.azimuth, 2), 'slope_deg': round(sol.slope, 2), 'speed_kms': round(sol.speed_kms, 2),
            'speed_per_camera_kms': {k: round(v[0], 2) for k, v in sol.station_speeds.items()},
            'residual_rms_deg': {k: round(v, 3) for k, v in sol.residual_rms_deg.items()}, 'q_deg': round(sol.q_max, 1)}


def matches(side, figures):
    """Each README figure equals the solution within half a unit of its last printed digit."""
    return all(abs(side[k] - v) <= 0.05 for k, v in figures.items())


def main():
    rows = [r for r in json.loads(SAM.read_text())['rows'] if r['centroid'] is not None and not r['dup']]  # as Case._stations
    kamensk, korkino = Case('chelyabinsk-2013')._stations(['2', '10'])
    assert np.allclose(kamensk.times, [r['t'] for r in rows]), 'the SAM rows do not line up with the station'
    frames = np.array([r['frame'] for r in rows])
    u = track.motion_direction({r['frame']: dict(zip(('x1', 'y1', 'x2', 'y2'), r['box'])) for r in rows})
    longer = [bool(along > across) for along, across in (lengths(r['box'], u) for r in rows)]
    segments = []
    for r, is_long in zip(rows, longer):
        if segments and segments[-1]['longer_along_the_motion'] == is_long:
            segments[-1]['last'], segments[-1]['frames'] = r['frame'], segments[-1]['frames'] + 1
        else:
            segments.append({'first': r['frame'], 'last': r['frame'], 'frames': 1, 'longer_along_the_motion': is_long})
    i = longer.index(False)
    split = int(frames[i])

    def halves(f):
        before, after = frames < f, frames >= f
        return [result(solve([Station(kamensk.name, kamensk.pos, kamensk.times[m], kamensk.rays_enu[m]), korkino]))
                for m in (before, after)]

    def box(r):
        along, across = lengths(r['box'], u)
        return {'frame': r['frame'], 't_s': round(r['t'], 3), 'box_px': [round(v) for v in r['box']],
                'length_along_motion_px': round(along), 'length_across_px': round(across)}

    before, after = halves(split)
    place = [round(head_in_box(r, u), 2) for r in rows]
    run_end = next((j for j in range(i, len(rows)) if longer[j]), len(rows))  # the first run of boxes that are not longer
    where = {'meaning': 'where the head point sits in its box along the motion: 0 at the box centre, 1 at its leading end',
             'median_before': round(float(np.median(place[:i])), 2),
             'median_from_the_split': round(float(np.median(place[i:])), 2),
             f'median_frames_{split}_to_{int(frames[run_end - 1])}': round(float(np.median(place[i:run_end])), 2),
             f'median_per_block_of_{BLOCK}_frames': [[int(frames[j]), int(frames[min(j + BLOCK, len(rows)) - 1]),
                                                       round(float(np.median(place[j:j + BLOCK])), 2)]
                                                      for j in range(0, len(rows), BLOCK)],
             'per_frame': [[int(f), p] for f, p in zip(frames, place)]}
    blocks_before = [b for b in where[f'median_per_block_of_{BLOCK}_frames'] if b[1] < split]
    peak = max(blocks_before, key=lambda b: b[2])
    trough = min([b for b in blocks_before if b[0] > peak[0]] or [peak], key=lambda b: b[2])
    last = blocks_before[-1]
    scan = []
    for j in range(max(i - SCAN, 1), min(i + SCAN, len(rows) - 1) + 1):
        b, a = halves(int(frames[j]))
        scan.append({'split_frame': int(frames[j]), 't_s': round(rows[j]['t'], 3),
                     'before': {'slope_deg': b['slope_deg'], 'speed_kms': b['speed_kms']},
                     'after': {'slope_deg': a['slope_deg'], 'speed_kms': a['speed_kms']},
                     'gives_the_readme_figures': matches(b, README['before']) and matches(a, README['after'])})
    hits = [s['split_frame'] for s in scan if s['gives_the_readme_figures']]
    out = {
        'note': __doc__.split('Writes')[0].strip(),
        'head_point_rule': {**{k: inspect.signature(track.head_point).parameters[k].default
                               for k in ('streak_ratio', 'lead_frac')}, 'source': 'src/testigos/track.py, head_point'},
        'split_rule': 'the first frame whose SAM box is not longer along the motion than across it',
        'motion_direction_px': [round(float(x), 4) for x in u],
        'split_frame': split, 'split_t_s': round(rows[i]['t'], 3),
        'last_box_before': box(rows[i - 1]), 'first_box_after': box(rows[i]),
        'box_shape_segments': segments,
        'head_point_in_its_box': where,
        'frames': {'before': {'first': int(frames[0]), 'last': int(frames[i - 1]), 'count': i},
                   'after': {'first': split, 'last': int(frames[-1]), 'count': len(rows) - i}},
        'kamensk_uralskiy_and_korkino': {'all_frames': result(solve([kamensk, korkino])), 'before': before, 'after': after},
        'readme_figures': README,
        'reproduces_the_readme': matches(before, README['before']) and matches(after, README['after']),
        'split_frames_tried': [scan[0]['split_frame'], scan[-1]['split_frame']],
        'split_frames_that_give_the_readme_figures': hits,
        'scan': scan,
    }
    lb, fa = out['last_box_before'], out['first_box_after']
    summary = [f"Kamensk-Uralskiy's SAM box is longer along the motion than across it in frames {frames[0]} to "
               f"{frames[i - 1]}. At frame {split} (t = {rows[i]['t']:.2f} s) it is not: its length along the motion "
               f"falls from {lb['length_along_motion_px']} px to {fa['length_along_motion_px']} px, against "
               f"{fa['length_across_px']} px across it.",
               f"Along the motion, the head point sits a median {where['median_before']} of the way from the box centre "
               f"to its leading end before the split, and {where[f'median_frames_{split}_to_{int(frames[run_end - 1])}']} "
               f"in frames {split} to {int(frames[run_end - 1])}, while the box is not longer along the motion.",
               f"Before the split, while the box is still longer along the motion, the head point already moves in it: "
               f"in blocks of {BLOCK} frames its median goes from {peak[2]} (frames {peak[0]} to {peak[1]}) down to "
               f"{trough[2]} (frames {trough[0]} to {trough[1]}), and back to {last[2]} (frames {last[0]} to {last[1]}). "
               f"The track does not record which of the two definitions each frame used, so the box rule is a proxy.",
               f"Solved with Korkino, Kamensk-Uralskiy's {i} frames before frame {split} give a "
               f"{before['slope_deg']:.1f} degree slope and {before['speed_kms']:.1f} km/s. Its {len(rows) - i} frames "
               f"from frame {split} on give {after['slope_deg']:.1f} degrees and {after['speed_kms']:.1f} km/s."]
    tried = f"{out['split_frames_tried'][0]} to {out['split_frames_tried'][1]}"
    found = ', '.join(f"{s['split_frame']} (t = {s['t_s']:.2f} s)" for s in scan if s['gives_the_readme_figures'])
    if len(hits) == 1:
        summary.append(f"Of the split frames from {tried}, only {found} gives the README's four figures.")
    elif hits:
        summary.append(f"Of the split frames from {tried}, these give the README's four figures: {found}.")
    else:
        summary.append(f"No split frame from {tried} gives the README's four figures.")
    out['summary'] = summary
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print('\n'.join(summary))


if __name__ == '__main__':
    main()
