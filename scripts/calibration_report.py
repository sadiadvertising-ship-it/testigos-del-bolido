"""Fit residuals of the three oriented Chelyabinsk cameras, as the solution uses them -> events/chelyabinsk-2013/calibration.json.

The plan's acceptance gate (0.3 deg, and 0.5 deg leaving one landmark out) was written for cameras fitted to a few
landmarks. These cameras are fitted mostly to annotated lines (verticals, and street edges whose bearing comes from
OSM), so the record is each evidence group's RMS residual, plus how far a refit from the same evidence lands from the
camera stored in picks.json (zero means picks.json holds exactly this fit).
Usage: .venv/bin/python scripts/calibration_report.py
"""
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stations import EVENT, PICKS, kamensk_camera_v2, korkino_camera, tyumen_camera  # noqa: E402

BUILDERS = {'2': lambda: kamensk_camera_v2(with_report=True), '10': lambda: korkino_camera(79.5, with_report=True),
            '48': lambda: tyumen_camera(with_report=True)}


def main():
    out = {}
    for no, build in BUILDERS.items():
        cam, _, report = build()
        groups = {k: g for k, g in report.items() if g['n']}
        n = sum(g['n'] for g in groups.values())
        rms_px = math.sqrt(sum(g['n'] * g['rms_px'] ** 2 for g in groups.values()) / n)
        used = PICKS[f'chelyabinsk-2013-{no}']['camera']
        out[no] = {'evidence': {k: {'residuals': g['n'], 'rms_px': round(g['rms_px'], 2), 'rms_deg': round(g['rms_deg'], 3)}
                                for k, g in groups.items()},
                   'rms_px': round(rms_px, 2), 'rms_deg': round(math.degrees(rms_px / cam.focal), 3),
                   'refit_minus_picks': {k: float(round(getattr(cam, k) - used.get(k, 0.0), 3)) + 0.0 for k in ('yaw', 'pitch', 'roll', 'hfov', 'k1')}}
        print(f"{no}: {out[no]['rms_deg']} deg RMS over {n} residuals; refit minus picks.json {out[no]['refit_minus_picks']}")
    (EVENT / 'calibration.json').write_text(json.dumps(out, indent=1) + '\n')


if __name__ == '__main__':
    main()
