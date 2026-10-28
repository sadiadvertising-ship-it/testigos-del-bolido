"""Tyumen as a held-out witness: how well does the Kamensk + Korkino path explain a camera that did not shape it?

The agent leaves Tyumen out of the trajectory fit (its planes nearly coincide with Kamensk's). Its rays and its own clock
are still evidence: each ray's angular miss of the Kamensk + Korkino line, and the speed Tyumen's frame times give along
that line over the first 60% of its track (the solver's speed window, before the fireball slows). No published value is
used. Its calibration was curated with CBET 3423 in view, so the check is independent of the fit, not of CBET.
Writes validation/chelyabinsk-2013/holdout-tyumen.json.
Usage: .venv/bin/python scripts/holdout.py
"""
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stations import ROOT  # noqa: E402
from testigos.agent import Case  # noqa: E402
from testigos.solve import _closest, _fit_speed, solve  # noqa: E402

OUT = ROOT / 'validation' / 'chelyabinsk-2013' / 'holdout-tyumen.json'


def main(fit=('2', '10'), held='48'):
    case = Case('chelyabinsk-2013')
    sol = solve(case._stations(list(fit)))
    st = case._stations([held])[0]
    miss, along = [], []
    for r in st.rays:
        s, _, q, p = _closest(sol.point, sol.direction, st.origin, r)
        v = p - st.origin  # the point on the ray nearest the line
        miss.append(np.degrees(np.arctan2(np.linalg.norm(q - p), np.linalg.norm(v))))
        along.append(s)
    speed, err = _fit_speed(st.times, np.array(along))
    out = {'fit_cameras': list(fit), 'held_out': held, 'rays': len(miss),
           'miss_deg': {'median': round(float(np.median(miss)), 2), 'p90': round(float(np.percentile(miss, 90)), 2)},
           'own_clock_speed_kms': round(speed / 1000, 2), 'own_clock_speed_sigma_kms': round(err / 1000, 2),
           'fit_speed_kms': round(sol.speed_kms, 2), 'note': __doc__.split('Writes')[0].strip()}
    OUT.write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps({k: v for k, v in out.items() if k != 'note'}))


if __name__ == '__main__':
    main()
