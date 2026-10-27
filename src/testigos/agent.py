"""The case agent: Muse Spark chooses each tool call, Python runs it, checks the result and keeps the record.

"An agent is a model that uses tools in a loop" (Meta's agent workshop). The model decides; the code carries the call
out and decides whether the work may move on. Three checks sit inside the tools, where the model cannot skip them:
finalize re-solves the chosen cameras and refuses a pair or a set that the evidence does not support; write_report
refuses a report with a figure or a hemisphere that no tool returned; request_evidence refuses to stop the case while the
evidence at hand is enough. A run ends waiting for a person: review of the report, or the evidence it asked for.
Published trajectories are never visible to the agent (they live in validation/, which nothing here reads).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import uuid

import numpy as np

from . import api
from .verify import check_report

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLANNER_MODEL = 'muse-spark-1.3'

SYSTEM = """You run a fireball case for an astronomy group: witness videos in, a trajectory with error bars out, or an
honest "insufficient geometry" answer that says which videos would close it. You decide which tool to call next; the code
runs it and keeps the record. Give every call a one-sentence why.
How a case closes. The code enforces these rules; you cannot skip them:
- finalize(clips) re-solves the cameras you choose and accepts them only if every oriented camera you leave out was
  dropped with a reason that cites a measured number, no wider pair was left aside, and no added camera raises the
  others' residuals. With fewer than two oriented cameras it records insufficient geometry instead.
- write_report() writes the report in Spanish and English from the tool results. Every number and hemisphere in it must
  match a tool result, or it is refused.
- request_evidence(kind, ...) records what a person must supply (videos from given towns, a camera position, a landmark
  confirmation) and stops the run until it arrives. It is refused while the evidence at hand is enough.
The case ends when the report is accepted for human review, or when the run is blocked waiting for evidence.
Never state a number that no tool returned. The published solutions are not available to you."""

_CLIP = {'type': 'string', 'description': 'clip id as listed in the case state'}
_WHY = {'type': 'string', 'description': 'one sentence: why this call, now'}


def _tool(name, description, props=None, required=()):
    props = dict(props or {}, why=_WHY)
    return {'type': 'function', 'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': props, 'required': list(required) + ['why'], 'additionalProperties': False}}


TOOLS = [
    _tool('read_witness', 'Muse Spark reads the clip: camera type, edits, on-screen clock, when the fireball shows, landmarks a map '
          'could locate. Cached after the first read.', {'clip': _CLIP}, ['clip']),
    _tool('track', 'Summary of the SAM 3.1 track of the fireball in the clip (frames with it, coverage of its span).', {'clip': _CLIP}, ['clip']),
    _tool('calibration', 'Whether the camera is oriented, from what evidence, and its fit residual. A camera with no surveyed '
          'landmark or line set cannot be oriented.', {'clip': _CLIP}, ['clip']),
    _tool('planes', 'Angle Q between the planes of sight of every pair of oriented cameras. Under 10 degrees a pair triangulates '
          'poorly.', {'clips': {'type': 'array', 'items': {'type': 'string'}, 'description': 'optional subset'}}),
    _tool('solve', 'Triangulate two or more oriented cameras: direction, slope, begin and end, speed per camera, residuals, Q '
          'and the verdict rule outcome.', {'clips': {'type': 'array', 'items': {'type': 'string'}}}, ['clips']),
    _tool('check_satellite', 'GOES GLM bolide detections within 30 minutes of the event (the Americas, from 2017).'),
    _tool('missing_views', 'Towns whose videos would see the flash 10 to 60 degrees up and close the geometry.'),
    _tool('drop_clip', 'Leave an oriented camera out of the final solution. The reason must cite a measured number.',
          {'clip': _CLIP, 'reason': {'type': 'string'}}, ['clip', 'reason']),
    _tool('finalize', 'Submit the cameras of the final solution (an empty list when none is oriented). Checked by the code; '
          'see the rules.', {'clips': {'type': 'array', 'items': {'type': 'string'}}}),
    _tool('write_report', 'Write the Spanish and English report from the tool results. Checked by the code; see the rules.'),
    _tool('request_evidence', 'Ask a person for missing evidence and stop the run until it arrives.',
          {'kind': {'type': 'string', 'enum': ['videos_from_towns', 'camera_position', 'landmark_confirmation']},
           'clip': _CLIP, 'towns': {'type': 'array', 'items': {'type': 'string'}}}, ['kind']),
]
TOOL_NAMES = [t['name'] for t in TOOLS]

# The single-turn JSON planner, kept as a fallback and for scripted tests.
PLAN_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'why': {'type': 'string'},
        'action': {'type': 'string', 'enum': TOOL_NAMES + ['done']},
        'clip': {'type': ['string', 'null']},
        'clips': {'type': ['array', 'null'], 'items': {'type': 'string'}},
        'reason': {'type': ['string', 'null']},
        'kind': {'type': ['string', 'null']},
    },
    'required': ['why', 'action', 'clip', 'clips', 'reason', 'kind'],
}

VERDICT_RULE = ('natural if v - 2 sigma > 11 km/s (Earth escape speed is 11.2 km/s); re-entry if v + 2 sigma < 8.5 km/s and the '
                'passage is long (more than 20 s, or a slope under 10 degrees); inconclusive otherwise')


def _latlon(lat, lon):
    """Hemispheres spelled out: given bare signed numbers, Muse once wrote Chelyabinsk's longitudes as west."""
    return f"{abs(lat):.3f} {'N' if lat >= 0 else 'S'}, {abs(lon):.3f} {'E' if lon >= 0 else 'W'}"


def _sha(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16] if path.exists() else None


class Case:
    def __init__(self, event_id):
        self.id = event_id
        self.dir = ROOT / 'events' / event_id
        self.event = json.loads((self.dir / 'event.json').read_text())
        self.picks = json.loads((self.dir / 'picks.json').read_text()) if (self.dir / 'picks.json').exists() else {}
        self.dropped = {}
        self.log = []
        self.last_solution = None
        self.final = None
        self.status = 'running'
        self.block = None
        self.refusals = {'finalize': 0, 'write_report': 0}
        self.reports = {}
        self.run_id = None
        self.replaying = False  # replay re-runs the tools with no model calls and no writes
        self.echo = None

    def clip_ids(self):
        return [str(c.get('catalog_no', c.get('id'))) for c in self.event['clips']]

    def key(self, clip):
        return f'{self.id}-{clip}'

    def oriented(self):
        return [c for c in self.clip_ids() if self.calibration(c)['calibrated'] and c not in self.dropped]

    # tools ---------------------------------------------------------------------------------
    def read_witness(self, clip, **_):
        cache = self.dir / 'witness' / f'{clip}.json'
        if cache.exists():
            w = json.loads(cache.read_text())
        else:
            from . import witness, clip as cliplib
            small = ROOT / 'out' / 'sam' / f'{self.key(clip)}.mp4'
            if not small.exists() or self.replaying:
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
        clips = [str(c) for c in (clips or []) if str(c) not in self.dropped]
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
                'speed_sigma_kms': round(sol.speed_sigma, 2) if sol.speed_sigma else None,
                'speed_per_camera': {k: round(s, 2) for k, (s, _) in sol.station_speeds.items()},
                'residual_rms_deg': {k: round(r, 3) for k, r in sol.residual_rms_deg.items()},
                'verdict': verdict, 'verdict_reason': reason, 'verdict_rule': VERDICT_RULE}

    def check_satellite(self, **_):
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

    # the three checks ----------------------------------------------------------------------------
    def _earlier_results(self):
        return [s['result'] for s in self.log]

    def finalize(self, clips=None, **_):
        oriented = self.oriented()
        if len(oriented) < 2:
            self.final = {'insufficient_geometry': True, 'oriented_clips': oriented}
            self._write('final_solution.json', {'run_id': self.run_id, **self.final})
            return {'accepted': True, 'insufficient_geometry': True, 'oriented_clips': oriented,
                    'next': 'write_report, then request_evidence for the views that would close the geometry'}
        clips = [str(c) for c in (clips or [])]
        problems = []
        strays = [c for c in clips if c not in oriented]
        if strays:
            problems.append(f'not oriented, or dropped: {strays}')
        for c in [c for c in oriented if c not in clips]:
            problems.append(f'camera {c} is oriented but left out without drop_clip')
        for c, reason in self.dropped.items():
            if self.calibration(c)['calibrated']:
                cited = check_report(reason or '', self._earlier_results())
                if not cited['numbers'] or not cited['passed']:
                    problems.append(f'the reason for dropping camera {c} cites no number that a tool returned')
        result = None
        if not problems:
            if len(clips) < 2:
                problems.append('a trajectory needs two oriented cameras')
            else:
                try:
                    result = self.solve(clips)
                except Exception as exc:  # Q under 5 degrees for two cameras, for one
                    problems.append(str(exc)[:200])
        if result and len(clips) == 2:
            best = self.planes(oriented)['pairs'][0]
            if best['q_deg'] - result['q_max_deg'] > 15:
                problems.append(f"a wider pair exists: {best['pair']} at Q {best['q_deg']} deg against {result['q_max_deg']} deg")
        if result and len(clips) >= 3:
            for c in clips:
                rest = [x for x in clips if x != c]
                without = self.solve(rest)['residual_rms_deg']
                worse = {k: (result['residual_rms_deg'][k], v) for k, v in without.items()
                         if result['residual_rms_deg'][k] > 1.25 * v and result['residual_rms_deg'][k] - v > 0.1}
                if worse and len(worse) == len(without):
                    problems.append(f'camera {c} raises the residuals of every other camera: '
                                    + ', '.join(f'{k} {a} deg against {b} deg without it' for k, (a, b) in worse.items()))
        if problems:
            self.refusals['finalize'] += 1
            if self.refusals['finalize'] >= 3:
                self._block('finalize_refused', problems=problems)
            return {'accepted': False, 'problems': problems, 'refusals': self.refusals['finalize'],
                    'escalated': self.status == 'blocked'}
        self.final = {'clips': clips, **result}
        self._write('final_solution.json', {'run_id': self.run_id, **self.final})
        return {'accepted': True, 'final': result}

    def write_report(self, **_):
        if self.final is None:
            return {'error': 'refused: finalize the solution first'}
        facts = [{k: v for k, v in step.items() if k in ('action', 'clip', 'clips', 'result')} for step in self.log]
        facts.append({'event_utc': self.event.get('utc'), 'final': self.final})
        facts_json = json.dumps(facts, default=str, ensure_ascii=False)[:14000]
        out = {}
        for lang, name in (('es', 'Spanish'), ('en', 'English')):
            ask = (f'Write a short case report ({name}, 120-180 words) for an astronomy group from the tool results below. '
                   'Write for people: never name tools, JSON fields or flags (say "no camera could be oriented", not '
                   f'"calibrated false"), and write units and directions in {name}. Use only numbers from the results, rounded '
                   'as they are, each coordinate with the hemisphere letter the results give it; leave out raw instrument '
                   'values. Say what is solid, what is uncertain and what is missing.')
            check, text, feedback = None, '', ''
            for attempt in range(2):
                if self.replaying:
                    text = (self.reports.get(lang) or {}).get('text', '')
                else:
                    text = api.spark([{'type': 'input_text', 'text': ask + feedback + '\n' + facts_json}], max_output_tokens=6000,
                                     effort='low', input_tokens_guess=6000, purpose=f'{self.id} report {lang}')
                check = check_report(text, facts)
                if text.strip() and check['passed']:
                    break
                feedback = (' A previous draft was refused because these figures match no tool result: '
                            f"{check['orphans'] + check['hemisphere_mismatches']}. Use only figures from the results.")
            if not (text.strip() and check['passed']):  # keep the plain record rather than an unchecked text
                self.refusals['write_report'] += 1
                text = ('Resultados de las herramientas (sin redacción):\n' if lang == 'es' else 'Tool results (no prose):\n') + facts_json
            self.reports[lang] = {'text': text, 'check': check}
            self._write(f'agent_report_{lang}.md', text)
            out[lang] = {'figures': check['numbers'], 'traced': check['traced'], 'passed': check['passed']}
        if self.refusals['write_report']:
            self._block('report_refused', checks=out)
        elif self.final.get('insufficient_geometry'):
            out['next'] = 'request_evidence for the views that would close the geometry'
        else:
            self.status = 'awaiting_review'
        return {'reports': out, 'status': self.status}

    def request_evidence(self, kind=None, clip=None, towns=None, why=None, **_):
        problems, oriented = [], self.oriented()
        if kind == 'videos_from_towns':
            if len(oriented) >= 2:
                problems.append(f'{len(oriented)} cameras are oriented: solve and finalize with them first')
            if not any(s['action'] == 'check_satellite' for s in self.log):
                problems.append('check the satellite detections first')
            unread = [c for c in self.clip_ids() if (ROOT / 'out' / 'sam' / f'{self.key(c)}.mp4').exists()
                      and not (self.dir / 'witness' / f'{c}.json').exists()]
            if unread:
                problems.append(f'clips with video not read yet: {unread}')
            if not towns:
                towns = [t.split(' (')[0] for t in self.missing_views().get('best_towns', [])]
        elif kind == 'camera_position':
            e = next((c for c in self.event['clips'] if str(c.get('catalog_no', c.get('id'))) == str(clip)), None)
            if e is None:
                problems.append(f'no clip {clip}')
            elif (self.picks.get(self.key(clip)) or {}).get('camera_pos') or (e.get('lat') is not None and e.get('lon') is not None):
                problems.append(f'the position of clip {clip} is already known')
        elif kind == 'landmark_confirmation':
            if not (self.dir / 'witness' / f'{clip}.json').exists():
                problems.append(f'read clip {clip} first: its landmark guesses are what a person would confirm')
            elif self.calibration(clip)['calibrated']:
                problems.append(f'clip {clip} is already oriented')
        else:
            problems.append(f'unknown kind {kind}')
        if problems:
            return {'accepted': False, 'problems': problems}
        request = {'run_id': self.run_id, 'at': dt.datetime.now().isoformat(timespec='seconds'), 'kind': kind, 'why': why,
                   'clip': clip, 'towns': towns}
        if not self.replaying:
            f = self.dir / 'requests.json'
            prior = json.loads(f.read_text()) if f.exists() else []
            f.write_text(json.dumps(prior + [request], ensure_ascii=False, indent=1) + '\n')  # appended, never rewritten
        self._block('missing_evidence', request=request)
        return {'accepted': True, 'blocked': True, 'request': request}

    def _block(self, reason, **detail):
        self.status = 'blocked'
        self.block = {'reason': reason, **detail}

    def _write(self, name, content):
        if self.replaying:
            return
        path = self.dir / name
        path.write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=1, default=str) + '\n')

    # loop ----------------------------------------------------------------------------------
    def call(self, name, args):
        """Run one tool call; a bad name or argument, or a failing tool, comes back as a fact for the model."""
        if name not in TOOL_NAMES:
            return {'error': f'no tool named {name}'}
        if not isinstance(args, dict):
            return {'error': 'arguments must be a JSON object'}
        spec = next(t for t in TOOLS if t['name'] == name)['parameters']
        missing = [k for k in spec['required'] if k != 'why' and args.get(k) in (None, '', [])]
        if missing:
            return {'error': f'missing arguments: {missing}'}
        if 'clip' in args and args['clip'] is not None and str(args['clip']) not in self.clip_ids():
            return {'error': f"no clip {args['clip']} in this case"}
        try:
            return getattr(self, name)(**{k: v for k, v in args.items() if k in spec['properties']})
        except Exception as exc:
            return {'error': str(exc)[:300]}

    def inventory(self, clip):
        return {'clip': clip, 'calibrated': self.calibration(clip)['calibrated'],
                'tracked': (ROOT / 'out' / 'sam' / f'{self.key(clip)}.json').exists(),
                'witness_read': (self.dir / 'witness' / f'{clip}.json').exists(), 'dropped': self.dropped.get(clip)}

    def state(self):
        clips = [self.inventory(c) for c in self.clip_ids()]
        steps = [{'action': s['action'], 'clip': s.get('clip'), 'clips': s.get('clips'), 'result': s['result']} for s in self.log[-10:]]
        return json.dumps({'event': self.event.get('id'), 'utc': self.event.get('utc'), 'clips': clips,
                           'counts': {'clips': len(clips), 'oriented': sum(c['calibrated'] for c in clips),
                                      'tracked': sum(c['tracked'] for c in clips), 'read': sum(c['witness_read'] for c in clips)},
                           'steps_so_far': steps}, default=str)

    def _record(self, action, args, why, result, resp=None):
        step = {'step': len(self.log) + 1, 'action': action, 'clip': (args or {}).get('clip'), 'clips': (args or {}).get('clips'),
                'args': args, 'why': why, 'result': result}
        if resp is not None:
            step.update(model=resp.get('model'), response_id=resp.get('id'), usage=resp.get('usage'))
        self.log.append(step)
        if self.echo:
            self.echo(step)

    def run(self, planner=None, max_steps=16, notes=None, resumed_from=None):
        """planner None runs native tool calling on /v1/responses; a callable (state, i, n) -> plan runs the JSON loop."""
        self._start(resumed_from, notes, 'native' if planner is None else 'json')
        try:
            if planner is None:
                self._run_native(max_steps, notes, resumed_from)
            else:
                self._run_json(planner, max_steps)
            if self.status == 'running':
                self.status = 'turn_limit'
        except Exception as exc:  # an API or code failure ends the run on the record, not as 'running'
            self.status, self.block = 'failed', {'reason': 'error', 'error': str(exc)[:500]}
            raise
        finally:
            self._finish()
        return self.log

    def _opening(self, notes, resumed_from):
        text = f'Case state:\n{self.state()}'
        if resumed_from:
            prior = json.loads((self.dir / 'runs' / f'{resumed_from}.json').read_text())
            text += f"\nThis run resumes {resumed_from}, which ended {prior['status']}: {json.dumps(prior.get('block'), default=str)[:1500]}"
        if notes:
            text += f'\nNotes from the reviewer: {notes}'
        return text

    def _run_native(self, max_steps, notes, resumed_from):
        # The whole conversation goes with every turn (the model's calls and the tools' outputs), so the loop does not
        # depend on the server keeping earlier responses: a previous_response_id was once "not found or expired"
        # mid-run. Prompt caching still applies to the repeated prefix.
        convo = [{'role': 'user', 'content': [{'type': 'input_text', 'text': self._opening(notes, resumed_from)}]}]
        for _ in range(max_steps):
            resp = api.respond(convo, TOOLS, SYSTEM, model=PLANNER_MODEL, purpose=f'{self.id} agent turn')
            calls = api.function_calls(resp)
            if not calls:
                self._record('no_tool_call', {}, api.text_of(resp)[:300], {'error': 'no tool call'}, resp)
                convo.append({'role': 'user', 'content': [{'type': 'input_text', 'text':
                              'Call a tool. The case ends when write_report is accepted, or when request_evidence blocks it.'}]})
                continue
            for c in calls:
                try:
                    args = json.loads(c.get('arguments') or '{}')
                except json.JSONDecodeError:
                    args = None
                result = self.call(c['name'], args)
                self._record(c['name'], args, (args or {}).get('why', ''), result, resp)
                convo.append({'type': 'function_call', 'call_id': c['call_id'], 'name': c['name'], 'arguments': c.get('arguments') or '{}'})
                convo.append({'type': 'function_call_output', 'call_id': c['call_id'],
                              'output': json.dumps(result, default=str, ensure_ascii=False)[:8000]})
            if self.status != 'running':
                return

    def _run_json(self, planner, max_steps):
        for i in range(max_steps):
            plan = planner(self.state(), i, max_steps)
            if plan['action'] == 'done':
                self._record('done', {}, plan['why'], {'done': True})
                self.status = 'stopped'
                return
            args = {k: plan.get(k) for k in ('clip', 'clips', 'reason', 'kind') if plan.get(k) is not None}
            args['why'] = plan['why']
            self._record(plan['action'], args, plan['why'], self.call(plan['action'], args))
            if self.status != 'running':
                return

    # run record ------------------------------------------------------------------------------
    def _inputs(self):
        paths = [self.dir / n for n in ('event.json', 'picks.json', 'calibration.json', 'glm-window.json', 'city-geometry.json')]
        for c in self.clip_ids():
            paths += [ROOT / 'out' / 'sam' / f'{self.key(c)}.json', self.dir / 'witness' / f'{c}.json']
        return {str(p.relative_to(ROOT)): _sha(p) for p in paths}

    def _start(self, resumed_from, notes, planner):
        self.run_id = dt.datetime.now().strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:4]
        api.RUN_ID = self.run_id
        git = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--', 'src', 'scripts'],
                                    capture_output=True, text=True).stdout.strip())
        self.record = {'run_id': self.run_id, 'event': self.id, 'started': dt.datetime.now().isoformat(timespec='seconds'),
                       'git': {'commit': git, 'dirty': dirty}, 'planner': planner,
                       'planner_model': PLANNER_MODEL if planner == 'native' else 'scripted or muse-spark-1.2',
                       'instructions_sha': hashlib.sha1(SYSTEM.encode()).hexdigest()[:12],
                       'tools_sha': hashlib.sha1(json.dumps(TOOLS, sort_keys=True).encode()).hexdigest()[:12],
                       'inputs': self._inputs(), 'resumed_from': resumed_from, 'notes': notes, 'history': []}

    def _finish(self):
        api.RUN_ID = None
        rows = [json.loads(l) for l in api.LEDGER.read_text().splitlines()] if api.LEDGER.exists() else []
        self.record.update(finished=dt.datetime.now().isoformat(timespec='seconds'), status=self.status, block=self.block,
                           final=self.final, dropped=self.dropped, steps=self.log,
                           reports={k: {'check': v['check']} for k, v in self.reports.items()},
                           cost_usd=round(sum(r['usd'] for r in rows if r.get('run_id') == self.run_id), 4))
        if self.replaying:
            return
        runs = self.dir / 'runs'
        runs.mkdir(exist_ok=True)
        (runs / f'{self.run_id}.json').write_text(json.dumps(self.record, ensure_ascii=False, indent=1, default=str) + '\n')
        if self.reports or self.status == 'stopped':  # agent_log.json is the log of the run whose report is current
            (self.dir / 'agent_log.json').write_text(json.dumps(self.log, ensure_ascii=False, indent=1, default=str))


def review(event_id, run_id, approve, notes=None, by=None):
    """A person signs the report off, or sends it back with notes (then `resume --notes`)."""
    path = ROOT / 'events' / event_id / 'runs' / f'{run_id}.json'
    rec = json.loads(path.read_text())
    if rec['status'] != 'awaiting_review':
        raise ValueError(f"run {run_id} is {rec['status']}, not awaiting review")
    rec['history'].append({'at': dt.datetime.now().isoformat(timespec='seconds'), 'review': 'approved' if approve else 'rejected',
                           'by': by, 'notes': notes})
    rec['status'] = 'approved' if approve else 'rejected'
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str) + '\n')
    return rec


def changed_inputs(event_id, run_id):
    """Inputs whose content changed since the run; a blocked run resumes only when something did."""
    rec = json.loads((ROOT / 'events' / event_id / 'runs' / f'{run_id}.json').read_text())
    now = Case(event_id)._inputs()
    return [k for k, v in now.items() if rec['inputs'].get(k) != v]


def replay(event_id, run_id):
    """Re-run every recorded tool call with today's code and no model; report results that differ."""
    rec = json.loads((ROOT / 'events' / event_id / 'runs' / f'{run_id}.json').read_text())
    case = Case(event_id)
    case.replaying, case.run_id = True, run_id
    case.reports = {lang: {'text': (case.dir / f'agent_report_{lang}.md').read_text()}
                    for lang in ('es', 'en') if (case.dir / f'agent_report_{lang}.md').exists()}
    diffs = []
    for step in rec['steps']:
        if step['action'] in ('no_tool_call', 'done'):
            continue
        got = case.call(step['action'], step.get('args') or {})
        case.log.append({**step, 'result': got})
        if step['action'] == 'write_report':
            passed = {lang: v['check']['passed'] for lang, v in case.reports.items()}
            if not all(passed.values()):
                diffs.append({'step': step['step'], 'action': 'write_report', 'report_check': passed})
        elif not _same(got, step['result']):
            diffs.append({'step': step['step'], 'action': step['action'], 'recorded': step['result'], 'replayed': got})
    return {'run_id': run_id, 'steps': len(rec['steps']), 'differences': diffs}


def _same(a, b, tol=1e-6):
    if isinstance(a, dict) and isinstance(b, dict):  # 'at' is the wall-clock time of a request, not a result
        return a.keys() == b.keys() and all(_same(a[k], b[k], tol) for k in a if k != 'at')
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
    return a == b


def muse_planner(state, step, max_steps):
    """The single-turn JSON planner (Muse Spark 1.2), kept as a fallback for the tool-calling loop."""
    content = [{'type': 'input_text', 'text': f'{SYSTEM}\nStep {step + 1} of at most {max_steps}.\nCase state:\n{state}'}]
    try:
        return api.spark(content, schema=PLAN_SCHEMA, max_output_tokens=1500, effort='low', input_tokens_guess=4000,
                         purpose='agent plan')
    except api.BudgetExceeded:
        raise
    except RuntimeError:  # 1.2 has looped on progress sentences instead of the JSON; one retry on 1.3
        return api.spark(content, schema=PLAN_SCHEMA, model='muse-spark-1.3', max_output_tokens=1500, effort='low',
                         input_tokens_guess=4000, purpose='agent plan retry 1.3')
