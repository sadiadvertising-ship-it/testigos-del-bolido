"""Export each case to web/data/<event>.json for the static 3D viewer.

Only derived numbers leave the machine: camera sites rounded to about 100 m, each line of sight as the point where it
passes closest to the solved path, the solutions the agent tried, the Monte Carlo lines, the agent log and report, and
published values (labelled; the agent never sees them). No video, frame or pixel track is exported.
Usage: .venv/bin/python scripts/export_web.py
"""
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from testigos.agent import Case  # noqa: E402
from testigos.geo import to_ecef, to_geodetic  # noqa: E402
from testigos.solve import _closest, solve  # noqa: E402

OUT = ROOT / 'web' / 'data'

TOWNS = {'Bucaramanga': (7.119, -73.123), 'Floridablanca': (7.064, -73.089), 'Cúcuta': (7.894, -72.508), 'Pamplona': (7.378, -72.648),
         'Arauca': (7.084, -70.759), 'Saravena': (6.954, -71.873), 'Yopal': (5.339, -72.394), 'Sogamoso': (5.716, -72.927),
         'Duitama': (5.826, -73.034), 'Tunja': (5.535, -73.367), 'Málaga': (6.698, -72.732), 'San Gil': (6.556, -73.134),
         'Barrancabermeja': (7.065, -73.854), 'Bogotá (Colina)': (4.73, -74.06), 'Villavicencio': (4.142, -73.627),
         'Medellín': (6.244, -75.581)}  # town centres, for placing the rows of city-geometry.json


def site(lat, lon):
    """A camera site to about 100 m: enough for the geometry on screen, never a witness's doorstep."""
    return [round(lon, 3), round(lat, 3)]


def geo(p):
    lat, lon, h = to_geodetic(p)
    return [round(lon, 5), round(lat, 5), round(h)]


def nearest(sol, origin, ray):
    """Closest approach of a line of sight to the solved line: (distance along the line, distance along the ray)."""
    return _closest(sol.point, sol.direction, origin, ray)[:2]


def between_heights(row, top, bottom):
    """A Monte Carlo line cut to the heights of the final path, so the bundle shows the spread in direction, not in extent."""
    p0, p1 = to_ecef(*row[:3]), to_ecef(*row[3:])
    d = p1 - p0

    def at(h):  # heights fall along the line over this range, so bisection finds the crossing
        lo, hi = -1.0, 2.0
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if to_geodetic(p0 + mid * d)[2] > h else (lo, mid)
        return geo(p0 + (lo + hi) / 2 * d)

    return [at(top), at(bottom)]


def solution(case, clips):
    sts = case._stations(clips)
    sol = solve(sts)
    s = np.concatenate([[nearest(sol, st.origin, r)[0] for r in st.rays] for st in sts])
    return sol, float(s.min()), float(s.max())


def miss_deg(sol, st):
    """RMS angle between a camera's lines of sight and the plane through the camera and the solved line."""
    n = np.cross(sol.point - st.origin, sol.direction)
    n /= np.linalg.norm(n)
    return float(np.degrees(np.sqrt(np.mean(np.arcsin(np.clip(st.rays @ n, -1, 1)) ** 2))))


def chelyabinsk():
    case = Case('chelyabinsk-2013')
    log = json.loads((case.dir / 'agent_log.json').read_text())
    dropped = {s['clip']: s['result'].get('reason') for s in log if s['action'] == 'drop_clip'}
    solves = [s for s in log if s['action'] == 'solve' and 'error' not in s['result']]
    recorded = case.dir / 'final_solution.json'  # what finalize accepted; older runs left only the log
    verdict = json.loads(recorded.read_text()) if recorded.exists() else solves[-1]['result']
    final = verdict['clips'] if recorded.exists() else [c for c in solves[-1]['result']['clips'] if c not in dropped]
    sol, s0, s1 = solution(case, final)
    v = sol.speed_kms * 1000

    stations = []
    for c in case.event['clips']:
        clip = str(c['catalog_no'])
        calibrated = case.calibration(clip)['calibrated']
        row = {'id': clip, 'site': c['site'], 'lonlat': site(c['lat'], c['lon']), 'camera': c['camera'], 'lens': c['lens'],
               'status': 'used' if clip in final else 'dropped' if clip in dropped else 'calibrated' if calibrated else 'not calibrated',
               'reason': dropped.get(clip)}
        if calibrated:
            st = case._stations([clip])[0]
            near = [nearest(sol, st.origin, r) for r in st.rays]
            s = np.array([n[0] for n in near])
            early = st.times <= st.times.min() + 0.6 * np.ptp(st.times)  # the solver's speed window, before the deceleration
            k = np.polyfit(st.times[early], s[early], 1)  # s = k0 t + k1: this camera's own speed and clock offset
            tau = st.times - (s0 - k[1]) / k[0]  # its clock shifted so that every camera reads 0 at the first point
            pick = np.unique(np.linspace(0, len(s) - 1, 16).round().astype(int))
            row.update(lonlat=site(st.pos[0], st.pos[1]), height_m=round(st.pos[2], -1),
                       rays=[[round(float((s[i] - s0) / v), 2)] + geo(st.origin + near[i][1] * st.rays[i]) for i in pick],
                       track=[[round(float(tau[i]), 3), round(to_geodetic(sol.point + s[i] * sol.direction)[2] / 1000, 2)]
                              for i in range(0, len(s), 2)],
                       speed_kms=round(k[0] / 1000, 2), miss_deg=round(miss_deg(sol, st), 3))
        stations.append(row)

    tried, seen = [], set()
    for step in solves:
        key = tuple(sorted(step['result']['clips'], key=int))
        if key in seen:
            continue
        seen.add(key)
        t_sol, t0, t1 = solution(case, list(key))
        tried.append({'step': step['step'], 'clips': list(key), 'path': [geo(t_sol.point + t0 * t_sol.direction), geo(t_sol.point + t1 * t_sol.direction)],
                      'azimuth_deg': round(t_sol.azimuth, 2), 'slope_deg': round(t_sol.slope, 2), 'speed_kms': round(t_sol.speed_kms, 2)})

    mc_file = case.dir / f"montecarlo-{'-'.join(final)}.json"
    mc = json.loads(mc_file.read_text()) if mc_file.exists() else None
    truth = json.loads((ROOT / 'validation' / case.id / 'truth.json').read_text())
    path_s = np.linspace(s0, s1, 80)
    top, bottom = (to_geodetic(sol.point + s * sol.direction)[2] for s in (s0, s1))
    return {
        'id': case.id, 'title': 'Chelyabinsk superbolide', 'when_utc': '2013-02-15T03:20:20Z', 'role': 'validation',
        'when': '15 February 2013, 9:20 am local time (03:20 UTC)',
        'view': {'center': [62.55, 55.2], 'zoom': 6.8, 'pitch': 58, 'bearing': 16},
        'solution': {'clips': final, 'path': [geo(sol.point + s * sol.direction) for s in path_s],
                     'times': [round(float((s - s0) / v), 3) for s in path_s],
                     'azimuth_deg': round(sol.azimuth, 2), 'slope_deg': round(sol.slope, 2), 'speed_kms': round(sol.speed_kms, 2),
                     'speed_sigma_kms': round(sol.speed_sigma, 2), 'q_deg': round(sol.q_max, 1),
                     'verdict': verdict['verdict'], 'verdict_reason': verdict['verdict_reason']},
        'stations': stations,
        'tried': tried,
        'montecarlo': mc and {'draws': mc['draws'], 'stats': mc['stats'],
                              'lines': [between_heights(r, top, bottom) for r in mc['lines']['rows']]},
        'published': {
            'path': [[p['lon'], p['lat'], round(p['h_km'] * 1000)] for p in truth['trajectory']],
            'points': [{'lonlat': [p['lon'], p['lat']], 'h_km': p['h_km'], 'note': p.get('note', '')} for p in truth['trajectory']],
            'values': [{'who': 'CBET 3423: Borovička, Spurný & Shrbený 2013', 'how': '7 casual videos', 'azimuth_deg': truth['azimuth_deg'],
                        'slope_deg': truth['slope_deg'], 'speed_kms': truth['apparent_radiant']['v_kms']},
                       {'who': 'Zuluaga, Ferrín & Geens 2013, arXiv:1303.1796', 'how': '4 videos', 'azimuth_deg': 285.0, 'slope_deg': 15.8,
                        'speed_kms': None}]},
        'agent_log': log,
        'report_es': (case.dir / 'agent_report_es.md').read_text(),
        **reports_and_run(case),
    }


def reports_and_run(case):
    """The English report when there is one, and the newest run record's status, checks and cost."""
    out = {}
    if (case.dir / 'agent_report_en.md').exists():
        out['report_en'] = (case.dir / 'agent_report_en.md').read_text()
    runs = sorted((case.dir / 'runs').glob('*.json')) if (case.dir / 'runs').exists() else []
    if runs:  # the run whose log and report are current
        log_ids = {s.get('response_id') for s in json.loads((case.dir / 'agent_log.json').read_text())}
        rec = next((json.loads(p.read_text()) for p in reversed(runs)
                    if {s.get('response_id') for s in json.loads(p.read_text())['steps']} == log_ids), json.loads(runs[-1].read_text()))
        out['run'] = {k: rec.get(k) for k in ('run_id', 'status', 'block', 'git', 'planner', 'planner_model', 'cost_usd', 'reports', 'history')}
        grade = ROOT / 'validation' / case.id / f"grade-{rec['run_id']}.json"
        if grade.exists():  # graded afterwards by scripts/grade.py; the agent never reads validation/
            g = json.loads(grade.read_text())
            out['grade'] = {'passed': g['passed'], 'gate': g['gate']}
    return out


def colombia():
    case = Case('colombia-2025-07-30')
    glm = json.loads((case.dir / 'glm.json').read_text())
    towns = []
    for r in json.loads((case.dir / 'city-geometry.json').read_text()):
        if r['city'] not in TOWNS:
            print('  no coordinates for', r['city'])
            continue
        lat, lon = TOWNS[r['city']]
        towns.append({**r, 'lonlat': [lon, lat], 'sees_it_high': 10 <= r['el_at_40km_deg'] <= 60})
    return {
        'id': case.id, 'title': 'Green fireball over Colombia', 'when_utc': '2025-07-31T03:50:24Z', 'role': 'open case',
        'when': '30 July 2025, 10:50 pm in Colombia (03:50 UTC on 31 July)',
        'view': {'center': [-73.25, 5.95], 'zoom': 6.85, 'pitch': 52, 'bearing': 8},
        'satellite': {'lonlat': [round(glm['longitude'], 3), round(glm['latitude'], 3)],
                      'extent_deg': [glm['longitudeDelta'], glm['latitudeDelta']], 'duration_s': round(glm['duration'], 2),
                      'start_utc': '2025-07-31T03:50:23.7Z', 'source': 'NASA neo-bolide catalog, GOES-19 GLM',
                      'classification': glm.get('humanClassification', 'Bolide')},
        'towns': towns,
        'witness': [{'site': 'Medellín', 'lonlat': [TOWNS['Medellín'][1], TOWNS['Medellín'][0]],
                     'status': 'video read by Muse; no surveyed landmark, and the clip replays the moment, so it cannot be calibrated'},
                    {'site': 'Bucaramanga', 'lonlat': [TOWNS['Bucaramanga'][1], TOWNS['Bucaramanga'][0]], 'status': 'video gone (account suspended)'},
                    {'site': 'Floridablanca', 'lonlat': [TOWNS['Floridablanca'][1], TOWNS['Floridablanca'][0]], 'status': 'text report only'}],
        'agent_log': json.loads((case.dir / 'agent_log.json').read_text()),
        'report_es': (case.dir / 'agent_report_es.md').read_text(),
        **reports_and_run(case),
    }


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [chelyabinsk(), colombia()]
    for case in cases:
        (OUT / f"{case['id']}.json").write_text(json.dumps(case, ensure_ascii=False, separators=(',', ':')))
        print(case['id'], (OUT / f"{case['id']}.json").stat().st_size // 1024, 'KB')
    (OUT / 'cases.json').write_text(json.dumps([{'id': c['id'], 'title': c['title'], 'role': c['role']} for c in cases], ensure_ascii=False))
