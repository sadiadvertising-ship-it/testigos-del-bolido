"""Export each case to web/data/<event>.json for the static 3D viewer.

Only derived numbers leave the machine: camera sites rounded to about 100 m, each line of sight as the point where it
passes closest to the solved path, the solutions the agent tried, the Monte Carlo lines, the agent log and report, and
published values (labelled; the agent never sees them). No video, frame or pixel track is exported.
Usage: .venv/bin/python scripts/export_web.py
"""
import datetime as dt
import inspect
import json
import pathlib
import re
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from testigos.agent import REPORT_MODEL, Case  # noqa: E402
from testigos.geo import to_ecef, to_geodetic  # noqa: E402
from testigos.solve import _closest, _fit_speed, solve  # noqa: E402

OUT = ROOT / 'web' / 'data'
# The share of a camera's track that the solver's speed fit uses, from its start: before the fireball slows.
SPEED_WINDOW = inspect.signature(_fit_speed).parameters['frac'].default
# A town sees the flash high when it would stand within this band of elevations at the lower height: the band of the
# agent's missing_views tool, read from its code so that the viewer and the agent cannot drift apart.
SKY_DEG = tuple(int(x) for x in re.search(r"(\d+) <= r\['el_at_40km_deg'\] <= (\d+)", inspect.getsource(Case.missing_views)).groups())
# Clips found but not analysed yet. No case file records them, so the export carries the fact: where they were posted,
# by whom and when (ISO date).
NOT_ANALYSED = {'colombia-2025-07-30': {'what': 'Security-camera and dashcam clips from Bogotá and Medellín', 'where': 'X',
                                        'by': '@ColombiaOscura', 'on': '2025-08-01'}}

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


def drop_reason(result, names):
    """An accepted drop in words, from the criterion the code measured (older runs kept only the model's reason)."""
    m, crit = result.get('measured') or {}, result.get('criterion')
    if crit == 'near_parallel_pair':
        return 'the weaker of a near-parallel pair: ' + '; '.join(
            f"its planes cross {names.get(k, k)}'s at {r['q_deg_with_it']}°, and {names.get(k, k)} crosses the other cameras "
            f"at up to {r['its_widest_q_deg']}° against its {r['this_widest_q_deg']}°" for k, r in m.get('near_parallel_with', {}).items())
    if crit == 'narrow_planes':
        return 'its planes cross every kept camera under 10°: ' + ', '.join(f'{names.get(k, k)} {q}°' for k, q in m.get('q_deg_with_kept', {}).items())
    if crit == 'raises_residuals':
        return 'it raises every other camera\'s residual by more than 25% and 0.1°'
    return result.get('reason') or crit


def verdict_rule(text):
    """The numbers of the verdict rule a run recorded (agent.VERDICT_RULE), so the viewer states the rule the code applied."""
    m = re.search(r'above ([\d.]+) km/s \(Earth escape speed is ([\d.]+) km/s\); re-entry if it lies below ([\d.]+) km/s '
                  r'and the passage is long \(more than ([\d.]+) s, or a slope under ([\d.]+) degrees\)', text or '')
    return m and {'natural_above_kms': float(m[1]), 'escape_kms': float(m[2]), 'reentry_below_kms': float(m[3]),
                  'long_s': float(m[4]), 'shallow_deg': float(m[5])}


def catalogue(case):
    """The catalogue the case's videos and camera positions come from, when the credits of every clip in the case name
    the same one (clips that were never available have no position source)."""
    f = case.dir / 'credits.json'
    clips = {str(c['catalog_no']) for c in case.event['clips']}
    sources = {c.get('position_source') for c in json.loads(f.read_text()) if c['clip'] in clips} if f.exists() else set()
    m = len(sources) == 1 and re.match(r'(.+?) \((.+?), A&A\)', sources.pop() or '')
    return {'name': m[1], 'cite': m[2]} if m else None


def when(event, where):
    """The event's time as a reader says it: local date and time first, then UTC, with its own date when that differs."""
    t = dt.datetime.fromisoformat(event['utc'].replace('Z', '+00:00'))
    loc = t + dt.timedelta(hours=event['local_time']['offset_h'])
    clock = f"{loc.hour % 12 or 12}:{loc:%M} {'am' if loc.hour < 12 else 'pm'}"
    return (f"{loc.day} {loc:%B %Y}, {clock} {where} ({t:%H:%M} UTC" + ('' if t.date() == loc.date() else f" on {t.day} {t:%B}") + ')')


def git(*args):
    """A query on this repository's history; empty where there is none (a copy without .git)."""
    try:
        return subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def first_commit(*args):
    """The oldest commit a git log query lists: its short hash and its time, as git records it (ISO, with the offset).
    Newest first, as git lists them: git's --reverse finds nothing together with --follow."""
    rows = git('log', '--format=%h %cI', *args).splitlines()
    return dict(zip(('commit', 'at'), rows[-1].split())) if rows else None


def criteria(case_id, truth):
    """When the grading criteria were fixed, from the repository's history. The four geometric tolerances came with the
    published solution (its gate entry in truth.json); the first camera fit is the oldest one kept in history/; the speed
    criterion came with the speed check in scripts/grade.py."""
    gate = next((k for k in truth if k.startswith('gate_')), None)
    fits = [first_commit('--follow', '--diff-filter=A', '--', str(p.relative_to(ROOT)))
            for p in sorted((ROOT / 'validation' / case_id / 'history').glob('cam-*.json'))]
    fits = sorted((f for f in fits if f), key=lambda f: f['at'])
    return {'geometric': {'gates': ['azimuth', 'slope', 'flare_height', 'end_point'], **((gate and first_commit('-S', gate)) or {})},
            'first_camera_fit': fits[0] if fits else None,
            'speed': {'gates': ['speed'], **(first_commit('-S', 'abs(speed - ref) <= 1.5', '--', 'scripts/grade.py') or {})}}


def chelyabinsk():
    case = Case('chelyabinsk-2013')
    log = json.loads((case.dir / 'agent_log.json').read_text())
    names = {str(c['catalog_no']): c['site'] for c in case.event['clips']}
    dropped = {s['clip']: drop_reason(s['result'], names) for s in log
               if s['action'] == 'drop_clip' and s['result'].get('accepted', True) and 'error' not in s['result']}
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
        # a camera that was never oriented stays 'not calibrated', even when the agent also dropped it as not oriented
        left_out = calibrated and clip in dropped and clip not in final
        row = {'id': clip, 'site': c['site'], 'lonlat': site(c['lat'], c['lon']), 'camera': c['camera'], 'lens': c['lens'],
               'status': 'used' if clip in final else 'dropped' if left_out else 'calibrated' if calibrated else 'not calibrated',
               'reason': dropped.get(clip) if left_out else None}
        if calibrated:
            st = case._stations([clip])[0]
            near = [nearest(sol, st.origin, r) for r in st.rays]
            s = np.array([n[0] for n in near])
            early = st.times <= st.times.min() + SPEED_WINDOW * np.ptp(st.times)  # the solver's speed window, before the deceleration
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
    vs_file = ROOT / 'validation' / case.id / f"montecarlo-{'-'.join(final)}-vs-cbet.json"
    if mc and vs_file.exists():  # the viewer's comparison table shows the published values, labelled as such
        mc = {**mc, 'stats': json.loads(vs_file.read_text())['stats']}
    sam_file = ROOT / 'validation' / case.id / 'sam-vs-threshold.json'
    sam_vs = json.loads(sam_file.read_text()) if sam_file.exists() else None
    ref_file = ROOT / 'validation' / case.id / 'refereed.json'
    refereed = [{'who': r['who'].split(',')[0] + ', ' + r['who'].split(', ')[1].split()[0], 'v_kms': r['v_initial_kms']}
                for r in json.loads(ref_file.read_text())['solutions']] if ref_file.exists() else None
    truth = json.loads((ROOT / 'validation' / case.id / 'truth.json').read_text())
    history = ROOT / 'validation' / case.id / 'history'  # the camera fits as they were compared with CBET 3423
    path_s = np.linspace(s0, s1, 80)
    top, bottom = (to_geodetic(sol.point + s * sol.direction)[2] for s in (s0, s1))
    return {
        'id': case.id, 'title': 'Chelyabinsk superbolide', 'when_utc': case.event['utc'], 'role': 'validation',
        'when': when(case.event, 'local time'),
        'view': {'center': [62.55, 55.2], 'zoom': 6.8, 'pitch': 58, 'bearing': 16},
        # times: the fitted line flown at the fitted speed; seen_for_s: the longest time one camera tracked the fireball
        'solution': {'clips': final, 'path': [geo(sol.point + s * sol.direction) for s in path_s],
                     'times': [round(float((s - s0) / v), 3) for s in path_s],
                     'azimuth_deg': round(sol.azimuth, 2), 'slope_deg': round(sol.slope, 2), 'speed_kms': round(sol.speed_kms, 2),
                     'speed_sigma_kms': round(sol.speed_sigma, 2), 'q_deg': round(sol.q_max, 1), 'seen_for_s': verdict.get('seen_for_s'),
                     'speed_band_95_kms': verdict.get('speed_band_95_kms'), 'speed_band_source': verdict.get('speed_band_source'),
                     'speed_window': SPEED_WINDOW, 'verdict': verdict['verdict'], 'verdict_reason': verdict['verdict_reason'],
                     'rule': verdict_rule(verdict.get('verdict_rule'))},
        'catalogue': catalogue(case),
        'calibration_history': f'{history.relative_to(ROOT)}/' if history.is_dir() else None,
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
        'sam_vs_threshold': sam_vs and {'solutions': sam_vs['solutions'], 'off_cbet_plane': sam_vs['off_cbet_plane']},
        'refereed': refereed,
        'agent_log': log,
        'report_es': (case.dir / 'agent_report_es.md').read_text(),
        **reports_and_run(case),
    }


def reports_and_run(case):
    """The English report when there is one, and the newest run record's status, checks and cost."""
    out = {'report_model': REPORT_MODEL}  # the model that writes the reports' text; the code writes their verdict line
    if (case.dir / 'agent_report_en.md').exists():
        out['report_en'] = (case.dir / 'agent_report_en.md').read_text()
    runs = sorted((case.dir / 'runs').glob('*.json')) if (case.dir / 'runs').exists() else []
    if runs:  # the run whose log and report are current
        log_ids = {s.get('response_id') for s in json.loads((case.dir / 'agent_log.json').read_text())}
        rec = next((json.loads(p.read_text()) for p in reversed(runs)
                    if {s.get('response_id') for s in json.loads(p.read_text())['steps']} == log_ids), json.loads(runs[-1].read_text()))
        out['run'] = {k: rec.get(k) for k in ('run_id', 'status', 'block', 'git', 'planner', 'planner_model', 'cost_usd', 'history')}
        out['run']['reports'] = {lang: {k: v for k, v in r.items() if k != 'text'} for lang, r in (rec.get('reports') or {}).items()}
        out['run']['resumed_from'], out['run']['notes'] = rec.get('resumed_from'), rec.get('notes')
        before = case.dir / 'runs' / f"{rec.get('resumed_from')}.json"
        if rec.get('resumed_from') and before.exists():  # the run this one resumed: its state and its last review
            b = json.loads(before.read_text())
            last = (b.get('history') or [None])[-1]
            out['run']['resumed'] = {'run_id': b['run_id'], 'status': b['status'],
                                     'last_review': last and {k: last.get(k) for k in ('at', 'review', 'by', 'notes', 'withdraws')}}
        grade = ROOT / 'validation' / case.id / f"grade-{rec['run_id']}.json"
        if grade.exists():  # graded afterwards by scripts/grade.py; the agent never reads validation/
            g = json.loads(grade.read_text())
            first = json.loads(sorted((ROOT / 'validation' / case.id).glob('grade-*.json'))[0].read_text())
            truth = json.loads((ROOT / 'validation' / case.id / 'truth.json').read_text())
            # the fitted line's values: its height where CBET puts the major flare (ours, CBET's), and how far CBET's end
            # point lies from it; the Monte Carlo's medians and ranges are in montecarlo.stats
            out['grade'] = {'passed': g['passed'], 'gate': g['gate'], 'criteria': criteria(case.id, truth),
                            'first_graded_run': first['run_id'], 'our_height_near_flare_km': g['our_height_near_flare_km'],
                            'cbet_end_point_off_our_line_km': g['cbet_end_point_off_our_line_km']}
    return out


def medellin_track(case):
    f = ROOT / 'out' / 'sam' / f'{case.key("medellin")}.json'
    if not f.exists():
        return ''
    s = json.loads(f.read_text())['summary']
    return f"; SAM 3.1 found the flash in {s['detected']} of its {s['frames']} frames"


def reentries(log):
    """The re-entry listing the agent's satellite check read, with the database named as a sentence says it."""
    r = next((s['result'].get('reentries') for s in log if s['action'] == 'check_satellite'), None)
    if r:
        org, db = (r['source'].split(', ') + [''])[:2]  # 'The Aerospace Corporation', 'CORDS reentry database'
        r = {**r, 'database': f"{org[:1].lower()}{org[1:]}'s {db.split()[0]} database" if db else r['source']}
    return r


def colombia():
    case = Case('colombia-2025-07-30')
    log = json.loads((case.dir / 'agent_log.json').read_text())
    glm = json.loads((case.dir / 'glm.json').read_text())
    # the flash's first light, to a tenth of a second, as the case report took it from the catalogue
    start = json.loads((case.dir / 'report.json').read_text())['satellite']['start_utc']
    start_utc = re.sub(r'(\.\d)\d*Z$', r'\1Z', start)
    rows = json.loads((case.dir / 'city-geometry.json').read_text())
    # the heights the town geometry assumes for the flash, from its columns (el_at_40km_deg and el_at_80km_deg)
    heights = sorted({int(m[1]) for m in (re.fullmatch(r'el_at_(\d+)km_deg', k) for k in rows[0]) if m})
    towns = []
    for r in rows:
        if r['city'] not in TOWNS:
            print('  no coordinates for', r['city'])
            continue
        lat, lon = TOWNS[r['city']]
        towns.append({**r, 'lonlat': [lon, lat], 'sees_it_high': SKY_DEG[0] <= r['el_at_40km_deg'] <= SKY_DEG[1]})
    return {
        'id': case.id, 'title': 'Green fireball over Colombia', 'when_utc': case.event['utc'], 'role': 'open case',
        'when': when(case.event, 'in Colombia'),
        # close enough that each requested town's two-line label fits beside its own dot without covering a neighbour's
        # (Málaga sits between San Gil and the flash), with Medellín still in view on the left; where the map area beside
        # the panel is narrower (a desktop window under about 1200 px), the viewer moves and steps back from it (fitView)
        'view': {'center': [-73.4, 6.0], 'zoom': 7.2, 'pitch': 52, 'bearing': 8},
        # a phone's map is small: it comes closer to the flash and tilts less, so the requested towns' labels have room
        'view_narrow': {'center': [-72.65, 6.4], 'zoom': 6.35, 'pitch': 40, 'bearing': 8},
        'satellite': {'lonlat': [round(glm['longitude'], 3), round(glm['latitude'], 3)],
                      'extent_deg': [glm['longitudeDelta'], glm['latitudeDelta']], 'duration_s': round(glm['duration'], 2),
                      'start_utc': start_utc, 'source': f"NASA neo-bolide catalog, GOES-{glm['detectedBy'].split('-')[-1]} GLM",
                      'classification': glm.get('humanClassification', 'Bolide'), 'confidence': glm.get('confidenceRating'),
                      'lightning_nearby': glm.get('nearbyLightningActivity')},
        # how high the towns would see the flash: the band that counts as high, at the lowest of the assumed heights
        'sky': {'high_deg': list(SKY_DEG), 'heights_km': heights},
        'towns': towns,
        'witness': [{'site': 'Medellín', 'lonlat': [TOWNS['Medellín'][1], TOWNS['Medellín'][0]], 'video': True,
                     'status': 'a handheld phone video with cuts, read by Muse; nothing in view can be located on a map and the '
                               'filming spot is unknown, so the code cannot orient it' + medellin_track(case)},
                    {'site': 'Bucaramanga', 'lonlat': [TOWNS['Bucaramanga'][1], TOWNS['Bucaramanga'][0]], 'video': False,
                     'status': 'no video: a text-only post, from an account now suspended'},
                    {'site': 'Floridablanca', 'lonlat': [TOWNS['Floridablanca'][1], TOWNS['Floridablanca'][0]], 'video': False,
                     'status': 'text report only'}],
        'not_analysed': NOT_ANALYSED.get(case.id),
        'agent_log': log,
        'reentries': reentries(log),
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
