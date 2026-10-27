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


def test_finalize_needs_every_left_out_camera_dropped_with_a_number(case_with):
    case = case_with(oriented=set(STATIONS))
    planes = case.call('planes', {'why': 'compare'})
    case._record('planes', {}, 'compare', planes)
    (a, b), third = planes['pairs'][0]['pair'], None
    third = next(n for n in STATIONS if n not in (a, b))
    first = case.call('finalize', {'clips': [a, b], 'why': 'widest pair'})
    assert not first['accepted'] and any(f'camera {third}' in p for p in first['problems'])
    case.call('drop_clip', {'clip': third, 'reason': 'not needed', 'why': 'x'})
    second = case.call('finalize', {'clips': [a, b], 'why': 'widest pair'})
    assert not second['accepted'] and any('cites no number' in p for p in second['problems'])
    q = next(p['q_deg'] for p in planes['pairs'] if third in p['pair'])
    case.call('drop_clip', {'clip': third, 'reason': f'its planes cross the others at {q} deg at most', 'why': 'x'})
    third_try = case.call('finalize', {'clips': [a, b], 'why': 'widest pair'})
    assert third_try['accepted'], third_try
    assert json.loads((case.dir / 'final_solution.json').read_text())['clips'] == [a, b]


def test_three_refusals_escalate_to_a_person(case_with):
    case = case_with(oriented=set(STATIONS))
    for _ in range(3):
        r = case.call('finalize', {'clips': list(STATIONS)[:2], 'why': 'x'})
    assert not r['accepted'] and r['escalated'] and case.status == 'blocked' and case.block['reason'] == 'finalize_refused'


def test_too_few_cameras_ends_in_a_request_for_evidence(case_with, monkeypatch):
    monkeypatch.setattr(agent.api, 'spark', _report_from_facts)
    case = case_with(oriented={'south'})
    assert case.call('finalize', {'clips': ['south'], 'why': 'x'})['insufficient_geometry']
    report = case.call('write_report', {'why': 'x'})
    assert report['reports']['es']['passed'] and case.status == 'running'
    refused = case.call('request_evidence', {'kind': 'videos_from_towns', 'towns': ['Málaga'], 'why': 'x'})
    assert not refused['accepted'] and any('satellite' in p for p in refused['problems'])
    case._record('check_satellite', {}, 'x', case.call('check_satellite', {'why': 'x'}))
    accepted = case.call('request_evidence', {'kind': 'videos_from_towns', 'towns': ['Málaga'], 'why': 'x'})
    assert accepted['blocked'] and case.status == 'blocked' and case.block['reason'] == 'missing_evidence'
    assert json.loads((case.dir / 'requests.json').read_text())[0]['towns'] == ['Málaga']


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
    approved = agent.review('synthetic', case.run_id, approve=True, by='Diego')
    assert approved['status'] == 'approved' and approved['history'][-1]['by'] == 'Diego'


def test_no_agent_code_reads_the_published_answer():
    for f in SRC.glob('*.py'):
        assert not re.search(r"""['"]validation\b|truth\.json""", f.read_text()), f.name
