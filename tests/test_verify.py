"""The report check: every figure and hemisphere must come from the run's tool results."""
import json
import pathlib

import pytest

from testigos import agent
from testigos.verify import check_report

EVENTS = pathlib.Path(__file__).resolve().parents[1] / 'events'


def _case(event, lang='es'):
    """A committed report's text without the code's verdict line, and the facts the agent wrote it from."""
    d = EVENTS / event
    case = agent.Case(event)
    case.log = json.loads((d / 'agent_log.json').read_text())
    case.final = {k: v for k, v in json.loads((d / 'final_solution.json').read_text()).items() if k != 'run_id'}
    verdict = 'none' if case.final.get('insufficient_geometry') else case.final.get('verdict')
    return agent.Case._body((d / f'agent_report_{lang}.md').read_text()), case.report_facts(), verdict


@pytest.mark.parametrize('lang', ['es', 'en'])
@pytest.mark.parametrize('event', ['chelyabinsk-2013', 'colombia-2025-07-30'])
def test_committed_reports_trace_every_figure(event, lang):
    text, facts, verdict = _case(event, lang)
    r = check_report(text, facts, verdict=verdict)
    assert r['passed'], r
    assert r['numbers'] >= 5


def test_an_invented_figure_and_a_swapped_hemisphere_are_caught():
    text, facts, _ = _case('chelyabinsk-2013')  # whatever the current wording, an added false sentence must be caught
    r = check_report(text + '\nRumbo 987,6 grados; final en 54,914 S.', facts)
    assert not r['passed'] and '987,6' in r['orphans']
    assert any(m.startswith('54,914 S') for m in r['hemisphere_mismatches'])


def test_a_changed_satellite_position_is_caught():
    text, facts, _ = _case('colombia-2025-07-30')
    r = check_report(text + ' El satélite lo ubicó en 6,64 N.', facts)
    assert not r['passed'] and '6,64' in r['orphans']


def test_list_numbers_and_sigma_names_are_not_figures():
    r = check_report('Pasos:\n1. revisar\n2. medir dentro de 2σ y 1 sigma', [])
    assert r['passed'] and r['numbers'] == 0


def test_a_time_inside_an_iso_timestamp_is_traceable():
    assert check_report('El destello fue a las 03:50 UTC.', [{'utc': '2025-07-31T03:50:24Z'}])['passed']


def test_a_figure_with_another_quantitys_unit_is_caught():
    facts = [{'q_deg': 66.3, 'speed_kms': 19.65}]
    wrong = check_report('The fireball flew at 66.3 km/s.', facts)
    assert not wrong['passed'] and wrong['orphans'] == ['66.3'] and wrong['wrong_kind'] == ['66.3 (speed)']
    assert check_report('The planes cross at 66.3° and it flew at 19.65 km/s.', facts)['passed']
    assert not check_report('Los planos se cruzan a 19,65 grados.', facts)['passed']
    assert check_report('Q de 66,3 grados; 19,65 kilómetros por segundo.', facts)['passed']


def test_a_range_shares_the_unit_printed_after_it():
    speed = [{'speed': {'1sigma': [15.64, 21.64]}}]
    assert check_report('1σ entre 15,6 y 21,6 km/s.', speed)['passed']
    assert check_report('a 1σ range of 15.6–21.6 km/s', speed)['passed']
    assert not check_report('15.6–21.6 km/s', [{'azimuth_deg': [15.64, 21.64]}])['passed']


def test_a_stated_verdict_must_be_the_codes():
    text = 'The speed was 14.77 km/s, below escape speed, so it was a re-entering satellite.'
    facts = [{'speed_kms': 14.77}]
    assert check_report(text, facts)['passed']  # without the code's verdict only the figures are checked
    r = check_report(text, facts, verdict='natural')
    assert not r['passed'] and r['verdict_mismatches'] == ['reentry']
    assert check_report(text, facts, verdict='reentry')['passed']
    for fine in ('Whether it was a meteor or space junk is not known yet.', 'No fue un satélite: es demasiado rápido.',
                 'Too fast for a re-entering satellite.'):
        assert check_report(fine, [], verdict='none')['passed'], fine
    assert not check_report('Fue un meteoroide natural.', [], verdict='none')['passed']
