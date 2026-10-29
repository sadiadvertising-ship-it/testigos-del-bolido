"""The witness video the viewer can play beside the replay (scripts/export_web.py, witness_video): its seconds against the
SAM track and the trim window, its tie to the exported camera clock, and that only ids, seconds and credits leave the
machine. No network: YouTube was checked when credits.json was written."""
import copy
import importlib.util
import json
import pathlib

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('export_web', ROOT / 'scripts' / 'export_web.py')
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

CASE = 'chelyabinsk-2013'
WEB = ROOT / 'web' / 'data'
KEYS = {'clip', 'site', 'camera', 'youtube_id', 'url', 'title', 'uploader', 'channel', 'uploaded', 'trimmed_s', 'start_s',
        'end_s', 'fireball_s', 'ahead_at_last_s', 'left_out', 'linked'}


@pytest.fixture(scope='module')
def solved():
    case = ex.Case(CASE)
    log = json.loads((case.dir / 'agent_log.json').read_text())
    names = {str(c['catalog_no']): c['site'] for c in case.event['clips']}
    final = json.loads((case.dir / 'final_solution.json').read_text())['clips']
    sol, s0, _ = ex.solution(case, final)
    return case, sol, s0, sol.speed_kms * 1000, final, log, names


@pytest.fixture(scope='module')
def fresh(solved):
    return ex.witness_video(*solved)


def test_seconds_come_from_the_sam_track_and_the_trim_window(fresh, solved):
    case = solved[0]
    clip = ex.SHOWN[CASE]
    window = next(c['window_s'] for c in case.event['clips'] if str(c['catalog_no']) == clip)
    rows = [r for r in json.loads((ROOT / 'out' / 'sam' / f'{CASE}-{clip}.json').read_text())['rows']
            if r['centroid'] is not None and not r['dup']]
    t = [r['t'] for r in rows]
    assert fresh['trimmed_s'] == window
    assert fresh['fireball_s'] == pytest.approx([window[0] + min(t), window[0] + max(t)], abs=0.006)


def test_start_is_the_trim_plus_the_cameras_own_clock_shift(fresh, solved):
    case, sol, s0 = solved[:3]
    st = case._stations([fresh['clip']])[0]
    shift = ex.own_clock(sol, s0, st)[3]
    assert fresh['start_s'] == pytest.approx(fresh['trimmed_s'][0] + shift, abs=5e-4)
    # the replay's whole flight fits inside the stretch of the upload that was measured
    dur = json.loads((WEB / f'{CASE}.json').read_text())['solution']['times'][-1]
    assert fresh['trimmed_s'][0] <= fresh['start_s'] and fresh['start_s'] + dur <= fresh['trimmed_s'][1]


def test_start_ties_to_the_exported_camera_clock(fresh):
    """The viewer's camera clock (stations[].track) reads 0 at start_s: its first point is fireball_s[0] - start_s."""
    data = json.loads((WEB / f'{CASE}.json').read_text())
    track = next(s for s in data['stations'] if s['id'] == fresh['clip'])['track']
    assert track[0][0] == pytest.approx(fresh['fireball_s'][0] - fresh['start_s'], abs=0.01)
    assert fresh['ahead_at_last_s'] > 0  # the fireball slowed; the replay flies one speed


def test_credits_and_links(fresh):
    assert fresh['youtube_id'] == '1ZdYf2vM5LA' and fresh['url'].endswith(fresh['youtube_id'])
    assert (fresh['uploader'], fresh['channel'], fresh['uploaded']) == ('Alexander Voronov', '@EastSide287', '2013-02-15')
    assert fresh['left_out']['criterion'] == 'near_parallel_pair'
    assert [(p['site'], p['q_deg']) for p in fresh['left_out']['pairs']] == [('Kamensk-Uralskiy', 7.5)]
    (kamensk,) = fresh['linked']
    assert kamensk['site'] == 'Kamensk-Uralskiy' and kamensk['at_s'] == 55
    assert kamensk['url'] == 'https://www.youtube.com/watch?v=kFlpCT3v12E&t=55s'


def test_no_window_unless_the_uploader_allows_embedding(solved):
    creds = ex.credits(solved[0])
    for embed in ({'allowed': False}, {}, None):
        other = copy.deepcopy(creds)
        if embed is None:
            other[ex.SHOWN[CASE]].pop('embed', None)
        else:
            other[ex.SHOWN[CASE]]['embed'] = embed
        assert ex.witness_video(*solved, creds=other) is None


def test_the_committed_data_is_current_and_holds_no_pixels(fresh):
    text = (WEB / f'{CASE}.json').read_text()
    committed = json.loads(text)['clip']
    assert set(committed) == KEYS
    assert committed == json.loads(json.dumps(fresh))  # a forgotten re-export fails here
    for word in ('"centroid"', '"box"', '"blob"'):
        assert word not in text


def test_colombia_links_the_post_and_plays_nothing():
    data = ex.colombia()
    creds = ex.credits(ex.Case('colombia-2025-07-30'))
    assert 'clip' not in data
    assert data['witness'][0]['post'] == {'url': creds['medellin']['source'], 'credit': creds['medellin']['credit']}
    assert np.all([w['site'] for w in data['witness']])
