"""The case agent: Muse Spark plans each step, Python runs the tool and reports back.

Muse proposes; the geometry decides. Tools return compact facts (residuals, convergence angles, rule outcomes)
and the rules in the tools override the model where they disagree (a clip with no surveyed landmark cannot be
calibrated, whatever the model thinks). Published trajectories are never visible to the agent.
"""
from __future__ import annotations

import json
import pathlib
import re

import numpy as np

from . import api

ROOT = pathlib.Path(__file__).resolve().parents[2]

ACTIONS = ['read_witness', 'track', 'calibration', 'planes', 'solve', 'check_satellite', 'missing_views',
           'drop_clip', 'write_report', 'done']

PLAN_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'why': {'type': 'string'},
        'action': {'type': 'string', 'enum': ACTIONS},
        'clip': {'type': ['string', 'null']},
        'clips': {'type': ['array', 'null'], 'items': {'type': 'string'}},
        'reason': {'type': ['string', 'null']},
    },
    'required': ['why', 'action', 'clip', 'clips', 'reason'],
}

SYSTEM = """You run a fireball case: witness videos in, a trajectory with error bars out, or an honest
"insufficient geometry" report. Each turn choose ONE action and say why in one sentence.
Tools:
- read_witness(clip): Muse reads the video (camera type, edits, clock, fireball window, landmarks). Cached after the first read.
- track(clip): SAM 3.1 tracking summary (frames with the fireball, span coverage).
- calibration(clip): whether the camera is oriented, from what evidence, fit residuals. A clip with no surveyed landmark cannot be calibrated.
- planes(clips): angle Q between the planes of sight of calibrated clips. Pairs below 10 degrees triangulate poorly; prefer the widest.
- solve(clips): triangulate 2+ calibrated clips; returns direction, slope, heights, speeds per camera, residuals, Q.
- check_satellite(): GOES GLM bolide detections near the event time.
- missing_views(): which towns' videos would close the geometry (use when fewer than two calibrated clips).
- drop_clip(clip, reason): exclude a clip from the solution.
- write_report(): write the case summary from what you found. Then done.
The case state already lists, per clip, whether it is calibrated, tracked and read: do not re-check those flags.
Typical order: planes over the calibrated clips, solve with the widest pair, consider a third camera, check_satellite,
write_report, done. Read witness videos only when a decision needs them. Before write_report, drop_clip each calibrated
clip you leave out of the final solution (uncalibrated clips never enter a solve: do not drop them). The final solution
is your last solve without the dropped clips.
Rules: never invent numbers; use only tool outputs. Prefer a two-camera solution with a wide Q over adding a camera that
lowers Q or raises residuals. Stop within the step budget."""


def _latlon(lat, lon):
    """Hemispheres spelled out: given bare signed numbers, Muse once wrote Chelyabinsk's longitudes as west."""
    return f"{abs(lat):.3f} {'N' if lat >= 0 else 'S'}, {abs(lon):.3f} {'E' if lon >= 0 else 'W'}"


class Case:
    def __init__(self, event_id):
        self.id = event_id
        self.dir = ROOT / 'events' / event_id
        self.event = json.loads((self.dir / 'event.json').read_text())
        self.picks = json.loads((self.dir / 'picks.json').read_text()) if (self.dir / 'picks.json').exists() else {}
        self.dropped = {}
        self.log = []
        self.last_solution = None

    def clip_ids(self):
        return [str(c.get('catalog_no', c.get('id'))) for c in self.event['clips']]

    def key(self, clip):
        return f'{self.id}-{clip}'

    # tools ---------------------------------------------------------------------------------
    def read_witness(self, clip, **_):
        cache = self.dir / 'witness' / f'{clip}.json'
        if cache.exists():
            w = json.loads(cache.read_text())
        else:
            from . import witness, clip as cliplib
            small = ROOT / 'out' / 'sam' / f'{self.key(clip)}.mp4'
            if not small.exists():
                return {'error': f'no trimmed video for clip {clip}'}
            w = witness.read(api.upload(small), cliplib.probe(small)['duration'], purpose=f'{self.key(clip)} agent read')
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(w, ensure_ascii=False, indent=1))
        return {'clip_kind': w['clip_kind'], 'camera_moves': w['camera_moves'], 'multiple_cuts': w['edits']['multiple_cuts'],
                'clock': (w['onscreen_clock'] or {}).get('text'), 'fireball_s': [w['fireball']['first_s'], w['fireball']['last_s']],
                'landmarks': [f"{l['name_guess'][:50]} ({l['kind']}, conf {l['confidence']})" for l in w['landmarks']][:6],
                'model_says_usable': w['usable_for_geometry']}

    def track(self, clip, **_):
        f = ROOT / 'out' / 'sam' / f'{self.key(clip)}.json'
        if not f.exists():
            return {'error': f'clip {clip} has not been tracked yet'}
        s = json.loads(f.read_text())['summary']
        return {k: s[k] for k in ('phrase', 'frames', 'detected', 'first_last', 'coverage_of_span') if k in s}

    def calibration(self, clip, **_):
        e = self.picks.get(self.key(clip))
        if not e or 'camera' not in e:
            return {'calibrated': False, 'why': 'no surveyed landmark or line set confirmed for this camera'}
        c = e['camera']
        out = {'calibrated': True, 'lens': e.get('lens', 'pinhole'), 'hfov': round(c['hfov'], 1), 'k1': round(c.get('k1', 0.0), 3),
               'evidence': (e.get('camera_note') or e.get('lines') or 'landmarks')[:200]}
        fits = self.dir / 'calibration.json'  # fit residuals, written by scripts/calibration_report.py
        if fits.exists():
            fit = json.loads(fits.read_text()).get(clip)
            if fit:
                out['fit_rms_deg'] = fit['rms_deg']
        return out

    def _stations(self, clips):
        from .camera import Camera
        from .solve import Station
        out = []
        for clip in clips:
            e = self.picks.get(self.key(clip))
            if not e or 'camera' not in e:
                raise ValueError(f'clip {clip} is not calibrated')
            c, (w, h) = e['camera'], e['image']
            cam = Camera(w, h, yaw=c['yaw'], pitch=c['pitch'], roll=c.get('roll', 0.0), hfov=c['hfov'], k1=c.get('k1', 0.0),
                         fisheye=e.get('lens') == 'fisheye')
            rows = [r for r in json.loads((ROOT / 'out' / 'sam' / f'{self.key(clip)}.json').read_text())['rows']
                    if r['centroid'] is not None and not r['dup']]
            out.append(Station(clip, tuple(e['camera_pos']), np.array([r['t'] for r in rows]),
                               np.array([cam.unproject(p['centroid']) for p in rows])))
        return out

    def planes(self, clips=None, **_):
        from .solve import convergence, plane_normal
        clips = [c for c in (clips or self.clip_ids()) if c not in self.dropped and self.calibration(c)['calibrated']]
        st = self._stations(clips)
        n = {s.name: plane_normal(s.rays) for s in st}
        pairs = [{'pair': [a, b], 'q_deg': round(convergence(n[a], n[b]), 1)} for i, a in enumerate(n) for b in list(n)[i + 1:]]
        return {'calibrated_clips': clips, 'pairs': sorted(pairs, key=lambda p: -p['q_deg'])}

    def solve(self, clips=None, **_):
        from .solve import solve
        from .verdict import decide
        clips = [c for c in (clips or []) if c not in self.dropped]
        stations = self._stations(clips)
        sol = solve(stations)
        self.last_solution = sol
        # a clock that solve() keeps out of the speed cannot vouch for the duration either
        seen_s = max((float(st.times.max() - st.times.min()) for st in stations
                      if len(st.times) and st.name not in sol.left_out), default=0.0)
        if sol.speed_kms is None:
            verdict, reason = 'inconclusive', 'no camera gave a speed'
        else:  # slope and duration let a slow, long passage read as a re-entry
            v = decide(sol.speed_kms, sol.speed_sigma or 1.0, duration_s=seen_s, slope_deg=sol.slope,
                       end_height_km=sol.end[2] / 1000)
            verdict, reason = v.kind, v.reason
        return {'clips': clips, 'q_max_deg': round(sol.q_max, 1), 'warnings': sol.warnings, 'seen_for_s': round(seen_s, 1),
                'azimuth_deg': round(sol.azimuth, 2), 'slope_deg': round(sol.slope, 2),
                'begin': f'{_latlon(sol.begin[0], sol.begin[1])}, {sol.begin[2] / 1000:.1f} km',
                'end': f'{_latlon(sol.end[0], sol.end[1])}, {sol.end[2] / 1000:.1f} km',
                'speed_kms': round(sol.speed_kms, 2) if sol.speed_kms else None,
                'speed_per_camera': {k: round(s, 2) for k, (s, _) in sol.station_speeds.items()},
                'residual_rms_deg': {k: round(r, 3) for k, r in sol.residual_rms_deg.items()},
                'verdict': verdict, 'verdict_reason': reason}

    def check_satellite(self, **_):
        import datetime as dt
        window = self.dir / 'glm-window.json'  # the committed excerpt, so the check works without the 30 MB catalog
        catalog = ROOT / 'out' / 'cache' / 'glm-bolides.json'
        if window.exists():
            events = json.loads(window.read_text())['events']
        elif catalog.exists():
            events = json.loads(catalog.read_text())['data']
        else:
            return {'error': 'GLM catalog not downloaded (run scripts/fetch_glm.py)'}
        t0 = dt.datetime.fromisoformat(self.event['utc'].replace('Z', '+00:00')).timestamp()
        hits = [e for e in events if abs(e['datetime'] / 1000 - t0) < 1800]

        def utc(ms):
            return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        return {'detections': [{'utc': utc(e['datetime']),
                                'where': _latlon(e['latitude'], e['longitude']),
                                'class': e.get('humanClassification'), 'brightness': list((e.get('brightness') or {}).values())[:1],
                                'duration_s': e.get('duration')} for e in hits][:5],
                'note': 'GLM covers the Americas from 2017; older or other-region events will show nothing'}

    def missing_views(self, **_):
        f = self.dir / 'city-geometry.json'
        if not f.exists():
            return {'error': 'no city geometry for this event'}
        rows = json.loads(f.read_text())
        return {'best_towns': [f"{r['city']} ({r['km']} km, look {r['look_az_deg']} deg, flash {r['el_at_40km_deg']}-{r['el_at_80km_deg']} deg up)"
                               for r in rows if 10 <= r['el_at_40km_deg'] <= 60][:8]}

    def drop_clip(self, clip, reason=None, **_):
        self.dropped[clip] = reason
        return {'dropped': clip, 'reason': reason}

    def write_report(self, **_):
        facts = json.dumps([{k: v for k, v in step.items() if k in ('action', 'clip', 'clips', 'result')} for step in self.log], default=str)[:12000]
        text = api.spark([{'type': 'input_text', 'text':
                           'Write a short case report (Spanish, 120-180 words) for an astronomy group from these tool results. '
                           'Use only these numbers; say what is solid, what is uncertain and what is missing.\n' + facts}],
                          max_output_tokens=6000, effort='low', input_tokens_guess=5000, purpose=f'{self.id} agent report')
        if not text.strip():  # Muse spent the budget thinking; keep a plain record instead of an empty file
            text = 'Resultados de las herramientas (sin redacción):\n' + facts
        (self.dir / 'agent_report_es.md').write_text(text)
        return {'written': str((self.dir / 'agent_report_es.md').relative_to(ROOT)), 'chars': len(text)}

    # loop ----------------------------------------------------------------------------------
    def inventory(self, clip):
        return {'clip': clip, 'calibrated': self.calibration(clip)['calibrated'],
                'tracked': (ROOT / 'out' / 'sam' / f'{self.key(clip)}.json').exists(),
                'witness_read': (self.dir / 'witness' / f'{clip}.json').exists(), 'dropped': self.dropped.get(clip)}

    def state(self):
        clips = [self.inventory(c) for c in self.clip_ids()]
        steps = [{'action': s['action'], 'clip': s.get('clip'), 'clips': s.get('clips'), 'result': s['result']} for s in self.log[-10:]]
        return json.dumps({'event': self.event.get('id'), 'utc': self.event.get('utc'), 'clips': clips, 'steps_so_far': steps}, default=str)

    def run(self, planner=None, max_steps=14):
        planner = planner or muse_planner
        for i in range(max_steps):
            plan = planner(self.state(), i, max_steps)
            action = plan['action']
            try:
                result = {'done': True} if action == 'done' else getattr(self, action)(clip=plan.get('clip'), clips=plan.get('clips'), reason=plan.get('reason'))
            except Exception as exc:  # a failed tool is a fact for the planner, not a crash
                result = {'error': str(exc)[:300]}
            self.log.append({'step': i + 1, 'action': action, 'clip': plan.get('clip'), 'clips': plan.get('clips'),
                             'why': plan['why'], 'result': result})
            if action in ('done', 'write_report') and 'error' not in result:
                break  # the report is the end of a case; Muse kept rewriting it when allowed to continue
        (self.dir / 'agent_log.json').write_text(json.dumps(self.log, ensure_ascii=False, indent=1, default=str))
        return self.log


def muse_planner(state, step, max_steps):
    content = [{'type': 'input_text', 'text': f'{SYSTEM}\nStep {step + 1} of at most {max_steps}.\nCase state:\n{state}'}]
    try:
        return api.spark(content, schema=PLAN_SCHEMA, max_output_tokens=1500, effort='low', input_tokens_guess=4000,
                         purpose='agent plan')
    except api.BudgetExceeded:
        raise
    except RuntimeError:  # 1.2 has looped on progress sentences instead of the JSON; one retry on 1.3
        return api.spark(content, schema=PLAN_SCHEMA, model='muse-spark-1.3', max_output_tokens=1500, effort='low',
                         input_tokens_guess=4000, purpose='agent plan retry 1.3')
