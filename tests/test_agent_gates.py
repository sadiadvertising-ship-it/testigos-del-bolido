"""The checks inside the agent's tools, the tool-calling loop and the replay, on a synthetic case with no network."""
import json
import pathlib
import re

import pytest

from synth import STATIONS, exact_station, path
from testigos import agent

SRC = pathlib.Path(agent.__file__).resolve().parent


@pytest.fixture
def case_with(tmp_path, monkeypatch):
    """A case whose cameras are the synthetic stations; `oriented` says which ones count as calibrated."""
    t, pts = path()

    def make(oriented):
        ev = tmp_path / 'events' / 'synthetic'
        ev.mkdir(parents=True, exist_ok=True)
        (ev / 'event.json').write_text(json.dumps({'id': 'synthetic', 'utc': '2013-02-15T03:20:20Z',
                                                   'clips': [{'id': n} for n in STATIONS]}))
        monkeypatch.setattr(agent, 'ROOT', tmp_path)
        monkeypatch.setattr(agent.Case, 'calibration', lambda self, clip, **_: {'calibrated': clip in oriented})
        monkeypatch.setattr(agent.Case, '_stations', lambda self, clips: [exact_station(n, t, pts) for n in clips])
        return agent.Case('synthetic')
    return make


def _report_from_facts(content, **_):
    """A stand-in for Muse: a report that quotes only the final heading, so the figure check passes."""
    az = re.search(r'"azimuth_deg": ([\d.]+)', content[0]['text'])
    return f'Rumbo final {az.group(1)} grados.' if az else 'No hay geometría suficiente para una trayectoria.'


def test_a_drop_needs_a_criterion_the_code_confirms(case_with):
    case = case_with(oriented=set(STATIONS))
    planes = case.call('planes', {'why': 'compare'})
    (a, b), third = planes['pairs'][0]['pair'], None
    third = next(n for n in STATIONS if n not in (a, b))
    first = case.call('finalize', {'clips': [a, b], 'why': 'widest pair'})
    assert not first['accepted'] and any(f'camera {third}' in p for p in first['problems'])
    missing = case.call('drop_clip', {'clip': third, 'reason': 'not needed', 'why': 'x'})
    assert 'criterion' in missing['error']  # a reason alone is not a criterion
    narrow = case.call('drop_clip', {'clip': third, 'criterion': 'narrow_planes', 'why': 'x'})
    assert not narrow['accepted'] and max(narrow['measured']['q_deg_with_kept'].values()) >= 10
    worse = case.call('drop_clip', {'clip': third, 'criterion': 'raises_residuals', 'why': 'x'})
    assert not worse['accepted'] and worse['refusals'] == 2 and not worse['escalated']
    assert case.dropped == {}
    still = case.call('finalize', {'clips': [a, b], 'why': 'widest pair'})
    assert not still['accepted'] and any(f'camera {third}' in p for p in still['problems'])
    assert case.call('finalize', {'clips': list(STATIONS), 'why': 'all of them'})['accepted']
    third_try = case.call('drop_clip', {'clip': third, 'criterion': 'narrow_planes', 'why': 'x'})
    assert third_try['escalated'] and case.block['reason'] == 'drop_refused'


def test_a_camera_that_adds_no_convergence_can_be_dropped(case_with, monkeypatch):
    case = case_with(oriented=set(STATIONS))
    a, b = case.call('planes', {'why': 'compare'})['pairs'][0]['pair']
    third = next(n for n in STATIONS if n not in (a, b))
    real = agent.Case.planes

    def narrow(self, clips=None, **_):  # the third camera sits next to the others: its planes cross theirs at 6-8 deg
        out = real(self, clips)
        for p in out['pairs']:
            if third in p['pair']:
                p['q_deg'] = 6.0 if a in p['pair'] else 8.0
        return out
    monkeypatch.setattr(agent.Case, 'planes', narrow)
    dropped = case.call('drop_clip', {'clip': third, 'criterion': 'narrow_planes', 'reason': 'no convergence', 'why': 'x'})
    assert dropped['accepted'] and dropped['measured']['q_deg_with_kept'] == {a: 6.0, b: 8.0}
    assert case.call('finalize', {'clips': [a, b], 'why': 'widest pair'})['accepted']
    assert json.loads((case.dir / 'final_solution.json').read_text())['clips'] == [a, b]


def test_the_near_parallel_pair_on_the_real_case():
    """Kamensk (2) and Tyumen (48) planes cross at 7.5 deg; Korkino (10) crosses Kamensk at 66.3 and Tyumen at 58.9.

    Run 20261027T132419-a996 dropped Tyumen citing that pair and residual rises the code's own rule does not count; the
    code now measures the criterion: Tyumen may go as the weaker of a near-parallel pair, Kamensk may not.
    """
    case = agent.Case('chelyabinsk-2013')
    case.replaying = True  # no writes into the committed case
    if set(case.oriented()) != {'2', '10', '48'}:
        pytest.skip('the committed Chelyabinsk calibrations are not all present')
    assert not case.call('drop_clip', {'clip': '48', 'criterion': 'narrow_planes', 'why': 'x'})['accepted']
    assert not case.call('drop_clip', {'clip': '48', 'criterion': 'raises_residuals', 'why': 'x'})['accepted']
    assert not case.call('drop_clip', {'clip': '2', 'criterion': 'near_parallel_pair', 'why': 'x'})['accepted']
    assert case.call('finalize', {'clips': ['2', '10'], 'why': 'x'})['accepted'] is False
    kept = case.call('drop_clip', {'clip': '48', 'criterion': 'near_parallel_pair', 'why': 'x'})
    assert kept['accepted'] and kept['measured']['near_parallel_with']['2']['its_widest_q_deg'] > 60
    final = case.call('finalize', {'clips': ['2', '10'], 'why': 'x'})
    assert final['accepted'] and final['final']['verdict'] == 'natural'
    assert 'cbet' not in json.dumps(final).lower()


def test_three_refusals_escalate_to_a_person(case_with):
    case = case_with(oriented=set(STATIONS))
    for _ in range(3):
        r = case.call('finalize', {'clips': list(STATIONS)[:2], 'why': 'x'})
    assert not r['accepted'] and r['escalated'] and case.status == 'blocked' and case.block['reason'] == 'finalize_refused'


def test_too_few_cameras_ends_in_a_request_for_evidence(case_with, monkeypatch):
    monkeypatch.setattr(agent.api, 'spark', _report_from_facts)
    case = case_with(oriented={'south'})
    closed = case.call('finalize', {'clips': ['south'], 'why': 'x'})
    assert closed['insufficient_geometry'] and closed['next'].startswith('check_satellite and missing_views')
    early = case.call('write_report', {'why': 'x'})
    assert not early['accepted'] and len(early['problems']) == 2  # neither the satellite nor the towns were checked
    refused = case.call('request_evidence', {'kind': 'videos_from_towns', 'towns': ['Málaga'], 'why': 'x'})
    assert not refused['accepted'] and any('satellite' in p for p in refused['problems'])
    for tool in ('check_satellite', 'missing_views'):
        case._record(tool, {}, 'x', case.call(tool, {'why': 'x'}))
    report = case.call('write_report', {'why': 'x'})
    assert report['reports']['es']['passed'] and case.status == 'running'
    assert (case.dir / 'agent_report_en.md').read_text().startswith('Verdict, written by the code: none.')
    accepted = case.call('request_evidence', {'kind': 'videos_from_towns', 'towns': ['Málaga'], 'why': 'x'})
    assert accepted['blocked'] and case.status == 'blocked' and case.block['reason'] == 'missing_evidence'
    assert json.loads((case.dir / 'requests.json').read_text())[0]['towns'] == ['Málaga']


def test_a_report_that_states_another_verdict_is_refused(case_with, monkeypatch):
    def says_satellite(content, **_):
        az = re.search(r'"azimuth_deg": ([\d.]+)', content[0]['text']).group(1)
        return f'Rumbo final {az} grados. Fue un satélite que reingresaba.'
    monkeypatch.setattr(agent.api, 'spark', says_satellite)
    case = case_with(oriented={'chelyabinsk', 'south'})
    final = case.call('finalize', {'clips': ['chelyabinsk', 'south'], 'why': 'x'})
    assert final['final']['verdict'] == 'natural'
    r = case.call('write_report', {'why': 'x'})
    assert not r['reports']['es']['passed'] and case.block['reason'] == 'report_refused'
    drafts = case.reports['es']['drafts']
    assert len(drafts) == 2 and all(d['verdict_mismatches'] == ['reentry'] for d in drafts)


def test_an_accepted_report_opens_with_the_codes_verdict(case_with, monkeypatch):
    monkeypatch.setattr(agent.api, 'spark', _report_from_facts)
    case = case_with(oriented={'chelyabinsk', 'south'})
    case.call('finalize', {'clips': ['chelyabinsk', 'south'], 'why': 'x'})
    r = case.call('write_report', {'why': 'x'})
    assert r['status'] == 'awaiting_review'
    en = (case.dir / 'agent_report_en.md').read_text()
    assert en.startswith('Verdict, written by the code: natural meteoroid.') and '95% range (fit error with a 10% floor)' in en
    assert (case.dir / 'agent_report_es.md').read_text().startswith('Veredicto, escrito por el código: meteoroide natural.')


def test_the_verdict_reads_a_95_percent_range_with_a_floor(case_with):
    case = case_with(oriented=set(STATIONS))
    r = case.call('solve', {'clips': list(STATIONS), 'why': 'x'})
    lo, hi = r['speed_band_95_kms']
    assert r['speed_band_source'] == 'fit error with a 10% floor' and r['uncertainty'] == 'no Monte Carlo for these cameras'
    assert hi - lo == pytest.approx(4 * 0.10 * r['speed_kms'], rel=0.02)  # exact synthetic rays: the floor decides


def test_track_runs_sam_on_an_untracked_clip_within_the_fireball_window(tmp_path, monkeypatch):
    ev = tmp_path / 'events' / 'open'
    (ev / 'witness').mkdir(parents=True)
    (ev / 'event.json').write_text(json.dumps({'id': 'open', 'utc': '2025-07-31T03:50:24Z', 'clips': [{'id': 'm'}]}))
    (ev / 'witness' / 'm.json').write_text(json.dumps({'fireball': {'first_s': 2.2, 'last_s': 3.2}}))
    sam = tmp_path / 'out' / 'sam'
    sam.mkdir(parents=True)
    (sam / 'open-m.mp4').write_bytes(b'')
    monkeypatch.setattr(agent, 'ROOT', tmp_path)
    calls = []

    def fake(small, name, out_dir, window=None, **_):
        calls.append((name, window))
        (out_dir / f'{name}.json').write_text(json.dumps({'summary': {'phrase': 'bright light', 'frames': 180, 'detected': 41,
                                                                      'first_last': [60, 120], 'coverage_of_span': 0.67,
                                                                      'window_s': window}, 'rows': []}))
    from testigos import track
    monkeypatch.setattr(track, 'track_video', fake)
    case = agent.Case('open')
    assert case.call('track', {'clip': 'm', 'why': 'x'})['detected'] == 41
    assert calls == [('open-m', [1.2, 4.2])] or calls[0][1] == pytest.approx([1.2, 4.2])
    case.replaying = True
    (sam / 'open-m.json').unlink()
    assert 'error' in case.call('track', {'clip': 'm', 'why': 'x'})  # a replay never calls SAM


def test_a_report_with_an_invented_figure_is_refused(case_with, monkeypatch):
    monkeypatch.setattr(agent.api, 'spark', lambda *a, **k: 'El rumbo fue 999,9 grados.')
    case = case_with(oriented={'chelyabinsk', 'south'})
    assert case.call('finalize', {'clips': ['chelyabinsk', 'south'], 'why': 'x'})['accepted']
    r = case.call('write_report', {'why': 'x'})
    assert not r['reports']['es']['passed'] and case.status == 'blocked' and case.block['reason'] == 'report_refused'
    assert (case.dir / 'agent_report_es.md').read_text().startswith('Resultados de las herramientas')


def test_the_tool_calling_loop_runs_until_review_and_replays(case_with, monkeypatch):
    monkeypatch.setattr(agent.api, 'spark', _report_from_facts)
    script = iter([('planes', {}), ('finalize', {'clips': ['chelyabinsk', 'south']}), ('write_report', {})])
    seen = []

    def respond(items, tools, instructions, **kw):
        seen.append(items)
        name, args = next(script)
        n = len(seen)
        return {'id': f'resp_{n}', 'model': 'muse-spark-1.3', 'usage': {},
                'output': [{'type': 'function_call', 'call_id': f'call_{n}', 'name': name, 'arguments': json.dumps({**args, 'why': f'step {n}'})}]}

    monkeypatch.setattr(agent.api, 'respond', respond)
    case = case_with(oriented={'chelyabinsk', 'south'})
    log = case.run()
    assert [s['action'] for s in log] == ['planes', 'finalize', 'write_report']
    assert case.status == 'awaiting_review'
    second = seen[1]  # the whole conversation goes with every turn: the call and its output, matched by call_id
    assert [i.get('type') for i in second[1:3]] == ['function_call', 'function_call_output']
    assert second[1]['call_id'] == second[2]['call_id'] == 'call_1'
    record = json.loads((case.dir / 'runs' / f'{case.run_id}.json').read_text())
    assert record['status'] == 'awaiting_review' and record['planner'] == 'native' and len(record['steps']) == 3
    assert agent.replay('synthetic', case.run_id)['differences'] == []
    assert agent.rejection_notes('synthetic', case.run_id) is None
    approved = agent.review('synthetic', case.run_id, approve=True, by='Diego')
    assert approved['status'] == 'approved' and approved['history'][-1]['by'] == 'Diego'


def test_a_rejected_report_resumes_with_the_reviewers_notes(case_with, monkeypatch):
    monkeypatch.setattr(agent.api, 'spark', _report_from_facts)
    case = case_with(oriented={'chelyabinsk', 'south'})
    case._start(None, None, 'json')
    case.call('finalize', {'clips': ['chelyabinsk', 'south'], 'why': 'x'})
    case.call('write_report', {'why': 'x'})
    case._finish()
    rejected = agent.review('synthetic', case.run_id, approve=False, notes='Quiten la frase sobre la base corta.', by='Diego')
    assert rejected['status'] == 'rejected'
    assert agent.rejection_notes('synthetic', case.run_id) == 'Quiten la frase sobre la base corta.'


def test_no_agent_code_reads_the_published_answer():
    for f in SRC.glob('*.py'):
        assert not re.search(r"""['"]validation\b|truth\.json""", f.read_text()), f.name
