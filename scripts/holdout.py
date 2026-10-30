"""Witnesses held out of the fit: how well does the Kamensk + Korkino path explain cameras that did not shape it?

Tyumen, which the agent leaves out of the fit, writes validation/chelyabinsk-2013/holdout-tyumen.json (TYUMEN below).
The cameras oriented after the signed run (validation/chelyabinsk-2013/after-run/cameras.json) write
validation/chelyabinsk-2013/holdout-after-run.json: the same numbers, the RMS angle between the rays and the plane through
the camera and the line (the viewer's miss), how each camera's planes cross the fit's cameras', and, for a camera judged
oriented, what the solver gives with it and how its miss changes with Korkino's field of view. Their annotators worked without the fit or CBET 3423 in view, so for those the
check is independent of both; the rough ones show what a rough orientation does to it. No published value is used.
Usage: .venv/bin/python scripts/holdout.py
"""
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import stations  # noqa: E402
from export_web import after_run, miss_deg, station  # noqa: E402
from stations import ROOT  # noqa: E402
from testigos.agent import Case  # noqa: E402
from testigos.solve import _closest, _fit_speed, solve  # noqa: E402

OUT = ROOT / 'validation' / 'chelyabinsk-2013' / 'holdout-tyumen.json'
AFTER = ROOT / 'validation' / 'chelyabinsk-2013' / 'holdout-after-run.json'
TYUMEN = """Tyumen as a held-out witness: how well does the Kamensk + Korkino path explain a camera that did not shape it?

The agent leaves Tyumen out of the trajectory fit (its planes nearly coincide with Kamensk's). Its rays and its own clock
are still evidence: each ray's angular miss of the Kamensk + Korkino line, and the speed Tyumen's frame times give along
that line over the first 60% of its track (the solver's speed window, before the fireball slows). No published value is
used. Its calibration was curated with CBET 3423 in view, so the check is independent of the fit, not of CBET."""


def held(sol, st):
    """Each ray's angular miss of the line, and the speed its own clock gives along it (the solver's speed window)."""
    miss, along = [], []
    for r in st.rays:
        s, _, q, p = _closest(sol.point, sol.direction, st.origin, r)
        v = p - st.origin  # the point on the ray nearest the line
        miss.append(np.degrees(np.arctan2(np.linalg.norm(q - p), np.linalg.norm(v))))
        along.append(s)
    speed, err = _fit_speed(st.times, np.array(along))
    return {'rays': len(miss), 'miss_deg': {'median': round(float(np.median(miss)), 2), 'p90': round(float(np.percentile(miss, 90)), 2)},
            'own_clock_speed_kms': round(speed / 1000, 2), 'own_clock_speed_sigma_kms': round(err / 1000, 2)}


def solved(sol):
    return {'azimuth_deg': round(sol.azimuth, 2), 'slope_deg': round(sol.slope, 2), 'speed_kms': round(sol.speed_kms, 2),
            'q_max_deg': round(sol.q_max, 1)}


def main(fit=('2', '10'), tyumen='48'):
    case = Case('chelyabinsk-2013')
    fits = case._stations(list(fit))
    sol = solve(fits)
    out = {'fit_cameras': list(fit), 'held_out': tyumen, **held(sol, case._stations([tyumen])[0]),
           'fit_speed_kms': round(sol.speed_kms, 2), 'note': TYUMEN}
    OUT.write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps({k: v for k, v in out.items() if k != 'note'}))

    cams = {}
    for clip, e in after_run(case, None).items():
        if e['outcome'] == 'aimed':  # aimed with the path itself: nothing to hold out
            continue
        st = station(case, clip)
        row = {'site': e['site'], 'outcome': e['outcome'], **held(sol, st), 'plane_rms_deg': round(miss_deg(sol, st), 3),
               'q_deg_with': {f.name: round(solve([f, st]).q_max, 1) for f in fits}}
        if e['outcome'] == 'oriented':  # what the solver gives with it, which the agent has not been asked
            row['solver_with_it'] = {'+'.join(fit + (clip,)): solved(solve(fits + [st])),
                                     **{f'{f.name}+{clip}': solved(solve([f, st])) for f in fits}}
            # how much it says about Korkino's field of view, settled with CBET in view: its miss of the path that each
            # field of view gives with Kamensk-Uralskiy (76 to 95 deg is the Monte Carlo's range)
            row['miss_if_korkino_hfov'] = {}
            for hfov in (76.0, 79.5, 85.5, 91.9, 95.0):
                other = solve([fits[0], stations.station('chelyabinsk-2013-10', *stations.korkino_camera(hfov))])
                row['miss_if_korkino_hfov'][str(hfov)] = {'azimuth_deg': round(other.azimuth, 2),
                                                          'plane_rms_deg': round(miss_deg(other, st), 3)}
        cams[clip] = row
        print(clip, json.dumps(row))
    AFTER.write_text(json.dumps({'fit_cameras': list(fit), 'fit_speed_kms': round(sol.speed_kms, 2),
                                 'note': __doc__.split('Usage')[0].strip(), 'cameras': cams}, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()
