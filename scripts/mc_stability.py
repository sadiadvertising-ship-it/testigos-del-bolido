"""Monte Carlo stability: how many draws slide off the heading, with Tyumen and without it.

events/chelyabinsk-2013/montecarlo-2-10-48.json holds the draws of Kamensk-Uralskiy (2), Korkino (10) and Tyumen (48).
montecarlo-2-10.json holds the draws of Kamensk-Uralskiy and Korkino. Each file keeps one line per draw, from its first
to its last observed point. This script measures each draw's heading and slope at the last point, as solve() does. It
checks that their percentiles give back the stats each file stores.
A draw slides when its heading is more than 10 degrees from a reference heading, or its slope is under 12 degrees.
There are two references: the fitted heading of the same cameras, and the fitted heading of Kamensk-Uralskiy and
Korkino. Both come from the solve steps of run 20261027T185758-cee8.
The files keep no angle between planes of sight. With --rerun, every three-camera draw and the first 20 two-camera
draws are run again with the seed, priors and camera order of scripts/montecarlo.py. Each line is compared with the
stored one. Each draw's angles between planes go to validation/chelyabinsk-2013/montecarlo-rerun.json, which also
records how long the re-run took. No file in events/ is written.
Writes validation/chelyabinsk-2013/montecarlo-stability.json.
Usage: .venv/bin/python scripts/mc_stability.py [--rerun]
"""
import hashlib
import inspect
import json
import pathlib
import re
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stations import EVENT, ROOT, station  # noqa: E402
from testigos.geo import enu_basis, enu_to_azel, to_ecef  # noqa: E402
from testigos.solve import GeometryError, convergence, plane_normal, solve  # noqa: E402

RUN = EVENT / 'runs' / '20261027T185758-cee8.json'
OUT = ROOT / 'validation' / 'chelyabinsk-2013' / 'montecarlo-stability.json'
RERUN = ROOT / 'validation' / 'chelyabinsk-2013' / 'montecarlo-rerun.json'
THREE, TWO = ('2', '10', '48'), ('2', '10')  # camera order as scripts/montecarlo.py runs them
OFF_DEG, MIN_SLOPE_DEG = 10.0, 12.0
RERUN_TWO = 20  # the 500 two-camera draws take about half an hour; the first ones show whether that file reproduces
PERCENTILES = (2.5, 16, 50, 84, 97.5)
COLUMNS = ['lat0', 'lon0', 'h0_m', 'lat1', 'lon1', 'h1_m']


def rel(path):
    return str(pathlib.Path(path).relative_to(ROOT))


def sha1(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()


def mc_file(nos):
    return EVENT / f"montecarlo-{'-'.join(nos)}.json"


def sites():
    return {str(c['catalog_no']): c['site'] for c in json.loads((EVENT / 'event.json').read_text())['clips']}


def heading_slope(row):
    """Heading and slope of a stored line at its last point, as solve() measures them."""
    lat0, lon0, h0, lat1, lon1, h1 = row
    d = to_ecef(lat1, lon1, h1) - to_ecef(lat0, lon0, h0)
    motion = enu_basis(lat1, lon1) @ (d / np.linalg.norm(d))
    return enu_to_azel(motion)[0], float(np.degrees(np.arctan2(-motion[2], np.hypot(motion[0], motion[1]))))


def fitted():
    """The run's solve steps, by camera set: step, cameras, heading and slope."""
    out = {}
    for s in json.loads(RUN.read_text())['steps']:
        r = s['result']
        if s['action'] == 'solve' and 'azimuth_deg' in r:
            out[frozenset(r['clips'])] = {'step': s['step'], 'clips': r['clips'], 'heading_deg': r['azimuth_deg'],
                                          'slope_deg': r['slope_deg']}
    return out


def off_by(az, ref):
    """Angle between headings, 0 to 180 degrees."""
    return np.abs((np.asarray(az, float) - np.asarray(ref, float) + 180.0) % 360.0 - 180.0)


def slide_mask(az, slope, ref):
    return (off_by(az, ref) > OFF_DEG) | (np.asarray(slope) < MIN_SLOPE_DEG)


def slides(az, slope, ref):
    off, low = off_by(az, ref) > OFF_DEG, np.asarray(slope) < MIN_SLOPE_DEG
    return {'reference_heading_deg': ref, 'draws_that_slide': int((off | low).sum()),
            f'heading_off_by_more_than_{OFF_DEG:g}_deg': int(off.sum()), f'slope_under_{MIN_SLOPE_DEG:g}_deg': int(low.sum()),
            'both': int((off & low).sum())}


def percentiles(values):
    p = np.percentile(values, PERCENTILES)
    return p, {'median': round(float(p[2]), 2), '1sigma': [round(float(p[1]), 2), round(float(p[3]), 2)],
               '2sigma': [round(float(p[0]), 2), round(float(p[4]), 2)]}


def check_stats(values, stored):
    """Percentiles of the values against the stats the file stores, which montecarlo.py rounded to 0.01."""
    p, computed = percentiles(values)
    flat = [stored['2sigma'][0], stored['1sigma'][0], stored['median'], stored['1sigma'][1], stored['2sigma'][1]]
    return {'computed': computed, 'stored': stored, 'largest_difference': round(float(np.max(np.abs(p - flat))), 3)}


def seed():
    """The seed scripts/montecarlo.py gives its random generator."""
    return int(re.search(r'default_rng\((\d+)\)', (ROOT / 'scripts' / 'montecarlo.py').read_text()).group(1))


def rerun_draws(nos, n, stored):
    """Draws 0 to n-1 of scripts/montecarlo.py for these cameras, each with its angles between planes.

    The loop is montecarlo.main's: the same priors (CAMERAS), the same station() arguments and the same order of random
    numbers. Building the stations before solve() takes the numbers in the order montecarlo.py takes them.
    """
    from montecarlo import CAMERAS
    rng = np.random.default_rng(seed())
    pairs = [(a, b) for a in range(len(nos)) for b in range(a + 1, len(nos))]
    rows, t0 = [], time.time()
    for i in range(n):
        cams = [(no, *CAMERAS[no](rng)) for no in nos]
        stations = [station(f'chelyabinsk-2013-{no}', cam, pos, rng, 1.5, clock_sigma=0.01, jitter_frames=0.5)
                    for no, cam, pos in cams]
        try:
            sol = solve(stations)
        except GeometryError:  # montecarlo.py skips the draw and keeps no line for it
            continue
        line = [round(sol.begin[0], 4), round(sol.begin[1], 4), round(sol.begin[2]),
                round(sol.end[0], 4), round(sol.end[1], 4), round(sol.end[2])]
        normals = [plane_normal(st.rays) for st in stations]
        rows.append([i, line == stored[len(rows)]] + [round(convergence(normals[a], normals[b]), 3) for a, b in pairs]
                    + [round(sol.azimuth, 3), round(sol.slope, 3), round(sol.speed_kms, 3) if sol.speed_kms else None])
        if (i + 1) % 10 == 0:
            print(f"{'-'.join(nos)}: {i + 1} of {n} draws, {sum(r[1] for r in rows)} of {len(rows)} lines identical, "
                  f'{time.time() - t0:.0f} s', flush=True)
    columns = ['draw', 'line_matches_stored'] + [f'q_{nos[a]}_{nos[b]}_deg' for a, b in pairs] + \
        ['heading_deg', 'slope_deg', 'speed_kms']
    return {'monte_carlo_file': rel(mc_file(nos)), 'sha1': sha1(mc_file(nos)), 'cameras': list(nos), 'seed': seed(),
            'draws_rerun': n, 'lines': len(rows), 'lines_identical': sum(r[1] for r in rows),
            'seconds': round(time.time() - t0), 'columns': columns, 'rows': rows}


def rerun():
    runs = []
    for nos, n in ((THREE, None), (TWO, RERUN_TWO)):
        stored = json.loads(mc_file(nos).read_text())
        runs.append(rerun_draws(nos, n or stored['draws'], stored['lines']['rows']))
    RERUN.write_text(json.dumps({
        'note': 'Monte Carlo draws run again by scripts/mc_stability.py --rerun, with the angle between each pair of '
                'planes of sight. q_2_48_deg is the angle between the planes of Kamensk-Uralskiy and Tyumen. '
                'line_matches_stored says whether the draw gives back its stored line exactly.',
        'runs': runs}) + '\n')


def angles(nos, stored_rows, masks, site):
    """What the re-run says about these cameras, when it was made from the current file."""
    if not RERUN.exists():
        return {'rerun': 'not run; scripts/mc_stability.py --rerun makes it'}
    run = next((r for r in json.loads(RERUN.read_text())['runs'] if r['cameras'] == list(nos)), None)
    if run is None:
        return {'rerun': 'not run for these cameras'}
    if run['sha1'] != sha1(mc_file(nos)):
        return {'rerun': f"made from another version of {run['monte_carlo_file']}; run --rerun again"}
    col = {c: i for i, c in enumerate(run['columns'])}
    rows = run['rows']
    whole = run['lines'] == len(stored_rows)
    out = {'rerun_file': rel(RERUN), 'draws_rerun': run['draws_rerun'], 'draws_stored': len(stored_rows),
           'lines_identical_to_stored': run['lines_identical'], 'seconds': run['seconds']}
    line = np.array([heading_slope(stored_rows[j]) for j in range(len(rows))])  # the j-th line kept is the j-th stored
    out['solver_against_stored_line_deg'] = {
        'largest_heading_difference': round(float(np.max(off_by([r[col['heading_deg']] for r in rows], line[:, 0]))), 3),
        'largest_slope_difference': round(float(np.max(np.abs(np.array([r[col['slope_deg']] for r in rows]) - line[:, 1]))), 3)}
    min_q, warn_q = (inspect.signature(solve).parameters[k].default for k in ('min_q', 'warn_q'))
    out['solve_thresholds_deg'] = {'warns_under': warn_q, 'refuses_two_cameras_under': min_q}
    out['angle_between_planes_deg'] = {}
    for c in run['columns']:
        if not c.startswith('q_'):
            continue
        a, b = c[2:-4].split('_')
        q = np.array([r[col[c]] for r in rows])
        entry = {'cameras': f'{site[a]} and {site[b]}', 'min': round(float(q.min()), 2), **percentiles(q)[1],
                 'max': round(float(q.max()), 2), 'draws_under_warn': int((q < warn_q).sum()),
                 'draws_under_min': int((q < min_q).sum())}
        if whole and len(nos) > 2:
            for key, mask in masks.items():
                entry[f'median_of_draws_that_slide_{key}'] = round(float(np.median(q[mask])), 2) if mask.any() else None
                entry[f'median_of_the_other_draws_{key}'] = round(float(np.median(q[~mask])), 2) if (~mask).any() else None
        out['angle_between_planes_deg'][c] = entry
    if 'q_2_48_deg' in col:
        r = min(rows, key=lambda x: x[col['q_2_48_deg']])
        out['smallest_2_48'] = {'draw': r[0], 'q_deg': r[col['q_2_48_deg']], 'heading_deg': r[col['heading_deg']],
                                'slope_deg': r[col['slope_deg']]}
    return out


def main(do_rerun):
    if do_rerun:
        rerun()
    site, fits = sites(), fitted()
    two = fits[frozenset(TWO)]
    configs, summary = [], []
    for nos in (THREE, TWO):
        m = json.loads(mc_file(nos).read_text())
        assert m['lines']['columns'] == COLUMNS and m['stations'] == [f'chelyabinsk-2013-{no}' for no in nos]
        rows = m['lines']['rows']
        hs = np.array([heading_slope(r) for r in rows])
        own = fits[frozenset(nos)]
        a = slides(hs[:, 0], hs[:, 1], own['heading_deg'])
        entry = {'file': rel(mc_file(nos)), 'cameras': [f'{no} {site[no]}' for no in nos], 'draws': m['draws'],
                 'lines': len(rows), 'each_draw_keeps': m['lines']['columns'], 'fitted': own,
                 'check_against_stored_stats': {'heading_deg': check_stats(hs[:, 0], m['stats']['azimuth']),
                                                'slope_deg': check_stats(hs[:, 1], m['stats']['slope'])},
                 'slides_from_own_fitted_heading': a}
        masks = {'from_own_heading': slide_mask(hs[:, 0], hs[:, 1], own['heading_deg'])}
        who = ', '.join(site[no] for no in nos[:-1]) + f' and {site[nos[-1]]}'
        if nos == TWO:
            summary.append(f"With {who}, {a['draws_that_slide']} of {len(rows)} draws slide from the fitted heading, "
                           f"{own['heading_deg']} degrees.")
        else:
            b = slides(hs[:, 0], hs[:, 1], two['heading_deg'])
            entry['slides_from_two_camera_heading'] = b
            masks['from_two_camera_heading'] = slide_mask(hs[:, 0], hs[:, 1], two['heading_deg'])
            summary.append(f"With {who}, {a['draws_that_slide']} of {len(rows)} draws slide from their own fitted "
                           f"heading, {own['heading_deg']} degrees, and {b['draws_that_slide']} from the two-camera "
                           f"heading, {two['heading_deg']} degrees.")
        entry['angles'] = angles(nos, rows, masks, site)
        rr = entry['angles']
        if 'lines_identical_to_stored' in rr:
            n, k = rr['draws_rerun'], rr['lines_identical_to_stored']
            which = f'all {n} draws' if n == len(rows) else f'the first {n} draws'
            summary.append(f"Run again with the seed of scripts/montecarlo.py, {which} give back their stored lines "
                           f"exactly ({rr['seconds']} s)." if k == n else
                           f"Run again with the seed of scripts/montecarlo.py, {k} of {which} give back their stored "
                           f"line exactly ({rr['seconds']} s).")
        q = rr.get('angle_between_planes_deg', {}).get('q_2_48_deg')
        if q:
            th, low = rr['solve_thresholds_deg'], rr['smallest_2_48']
            summary.append(f"In those draws the planes of {site['2']} and {site['48']} cross at {q['min']} to "
                           f"{q['max']} degrees, median {q['median']}. They cross under {th['warns_under']:g} degrees, "
                           f"where solve() warns, in {q['draws_under_warn']} draws, and under "
                           f"{th['refuses_two_cameras_under']:g} degrees, where solve() refuses two cameras, in "
                           f"{q['draws_under_min']}.")
            summary.append(f"The smallest angle, {low['q_deg']:.2f} degrees, is in draw {low['draw']}, whose line heads "
                           f"{low['heading_deg']:.2f} degrees at a slope of {low['slope_deg']:.2f} degrees.")
            summary.append(f"The draws that slide from the two-camera heading have a median angle of "
                           f"{q['median_of_draws_that_slide_from_two_camera_heading']} degrees between those planes, "
                           f"the other draws {q['median_of_the_other_draws_from_two_camera_heading']} degrees.")
        configs.append(entry)
    out = {'note': __doc__.split('Writes')[0].strip(),
           'convention': 'heading and slope at the last point of each line, where solve() measures them',
           'rule': f'a draw slides when its heading is more than {OFF_DEG:g} degrees from the reference heading, '
                   f'or its slope is under {MIN_SLOPE_DEG:g} degrees',
           'fitted_headings_from': rel(RUN), 'configurations': configs, 'summary': summary}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print('\n'.join(summary))


if __name__ == '__main__':
    main('--rerun' in sys.argv[1:])
