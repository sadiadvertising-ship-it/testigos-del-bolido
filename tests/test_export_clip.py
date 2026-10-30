"""The witness videos the viewer can play (scripts/export_web.py, witness_videos): their seconds against the SAM tracks and
the trim windows, the tie between an oriented camera's video and the exported camera clock, and that only ids, seconds and
credits leave the machine. No network: YouTube was checked when credits.json was written."""
import copy
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('export_web', ROOT / 'scripts' / 'export_web.py')
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

CASE = 'chelyabinsk-2013'
WEB = ROOT / 'web' / 'data'
KEYS = {'clip', 'site', 'camera', 'status', 'oriented', 'aligned', 'youtube_id', 'url', 'title', 'uploader', 'channel',
        'uploaded', 'trimmed_s', 'start_s', 'end_s', 'fireball_s', 'camera_moves', 'moves_measured', 'left_out', 'frame_px',
        'track'}


@pytest.fixture(scope='module')
def solved():
    case = ex.Case(CASE)
    log = json.loads((case.dir / 'agent_log.json').read_text())
    names = {str(c['catalog_no']): c['site'] for c in case.event['clips']}
    final = json.loads((case.dir / 'final_solution.json').read_text())['clips']
    sol, s0, s1 = ex.solution(case, final)
    return case, sol, s0, float((s1 - s0) / (sol.speed_kms * 1000)), final, log, names


@pytest.fixture(scope='module')
def fresh(solved):
    return ex.witness_videos(*solved)


def window(case, clip):
    return next(c['window_s'] for c in case.event['clips'] if str(c['catalog_no']) == clip)


def test_every_embeddable_video_and_only_those(fresh, solved):
    creds = ex.credits(solved[0])
    allowed = {k for k, c in creds.items() if (c.get('embed') or {}).get('allowed') is True}
    assert {v['clip'] for v in fresh['shown']} == allowed
    assert fresh['first'] == ex.FIRST[CASE] == fresh['shown'][0]['clip']
    oriented = [v['oriented'] for v in fresh['shown']]
    assert oriented == sorted(oriented, reverse=True)  # the oriented cameras' videos come first
    assert all(v['aligned'] == ('clock' if v['oriented'] else 'glow') for v in fresh['shown'])


def test_seconds_come_from_the_sam_tracks_and_the_trim_windows(fresh, solved):
    case = solved[0]
    for v in fresh['shown']:
        rows = [r for r in json.loads((ROOT / 'out' / 'sam' / f"{CASE}-{v['clip']}.json").read_text())['rows']
                if r['centroid'] is not None and not r['dup']]
        t, w = [r['t'] for r in rows], window(case, v['clip'])
        assert v['trimmed_s'] == w
        assert v['fireball_s'] == pytest.approx([w[0] + min(t), w[0] + max(t)], abs=0.006)


def test_an_oriented_cameras_video_starts_where_its_own_clock_reads_zero(fresh, solved):
    case, sol, s0, dur = solved[:4]
    data = json.loads((WEB / f'{CASE}.json').read_text())
    for v in (v for v in fresh['shown'] if v['aligned'] == 'clock'):  # Yekaterinburg's too, oriented after the run
        shift = ex.own_clock(sol, s0, ex.station(case, v['clip']))[3]
        assert v['start_s'] == pytest.approx(v['trimmed_s'][0] + shift, abs=5e-4)
        # the replay's zero falls at the trim window's start or just before it (Yekaterinburg's, 0.09 s), in the upload, and
        # there is room for the whole replay
        assert v['trimmed_s'][0] - 0.5 <= v['start_s'] and v['start_s'] + dur <= v['end_s']
        # the viewer's camera clock (stations[].track) reads 0 at start_s: its first point is fireball_s[0] - start_s
        track = next(s for s in data['stations'] if s['id'] == v['clip'])['track']
        assert track[0][0] == pytest.approx(v['fireball_s'][0] - v['start_s'], abs=0.01)


def test_a_video_aligned_by_glow_puts_its_widest_glow_where_the_oriented_cameras_have_theirs(fresh, solved):
    case, sol, s0 = solved[:3]
    glows = []
    for k in ('2', '48'):  # the oriented cameras whose tracks run to their end
        rows = ex.sam_rows(case, k)
        glows.append(ex.widest_glow_t(rows) - ex.own_clock(sol, s0, case._stations([k])[0])[3])
    assert list(fresh['glow_from']) == ['Kamensk-Uralskiy', 'Tyumen']
    assert list(fresh['glow_from'].values()) == pytest.approx(glows, abs=0.006)
    assert fresh['glow_replay_s'] == pytest.approx(sum(glows) / 2, abs=0.006)
    for v in (v for v in fresh['shown'] if v['aligned'] == 'glow'):
        glow = v['trimmed_s'][0] + ex.widest_glow_t(ex.sam_rows(case, v['clip']))
        assert glow - v['start_s'] == pytest.approx(fresh['glow_replay_s'], abs=0.01)
        assert v['end_s'] >= v['start_s'] + solved[3]  # room for the whole replay
    # the camera oriented after the run tests that alignment: lined up on its largest box, its video would run this far ahead
    (yek,) = (v for v in fresh['shown'] if v['status'] == 'after run')
    glow = yek['trimmed_s'][0] + ex.widest_glow_t(ex.sam_rows(case, yek['clip'])) - fresh['glow_replay_s']
    assert fresh['glow_check_s'] == {'Yekaterinburg': pytest.approx(glow - yek['start_s'], abs=0.01)}
    assert fresh['glow_check_s']['Yekaterinburg'] > 3  # far more than the second the texts allowed before


def test_tracks_are_shares_of_the_frame_on_the_uploads_clock(fresh):
    for v in fresh['shown'] + fresh['linked']:
        track = v['track']
        assert 20 <= len(track) <= 160
        assert all(0 <= x <= 1 and 0 <= y <= 1 and 0 <= r <= 1 for _, x, y, r in track)  # no pixel leaves the machine
        assert [p[0] for p in track] == sorted(p[0] for p in track)
        if 'fireball_s' in v:  # SAM's first and last points are where the video's fireball seconds come from
            assert track[0][0] == pytest.approx(v['fireball_s'][0], abs=0.006)


def test_credits_and_links(fresh):
    tyumen = next(v for v in fresh['shown'] if v['clip'] == '48')
    assert tyumen['youtube_id'] == '1ZdYf2vM5LA' and tyumen['url'].endswith(tyumen['youtube_id'])
    assert (tyumen['uploader'], tyumen['channel'], tyumen['uploaded']) == ('Alexander Voronov', '@EastSide287', '2013-02-15')
    assert tyumen['status'] == 'left out' and tyumen['left_out']['criterion'] == 'near_parallel_pair'
    assert [(p['site'], p['q_deg']) for p in tyumen['left_out']['pairs']] == [('Kamensk-Uralskiy', 7.5)]
    assert next(v for v in fresh['shown'] if v['clip'] == '10')['status'] == 'used'
    yek = next(v for v in fresh['shown'] if v['clip'] == '81')
    assert (yek['status'], yek['oriented'], yek['aligned'], yek['left_out']) == ('after run', True, 'clock', None)
    assert {v['site'] for v in fresh['shown'] if v['camera_moves']} == {'Beloretsk', 'Chebarkul', 'Magnitogorsk'}
    # Muse Spark's reading against the frames compared after the run: two of the three do not move
    assert {v['site'] for v in fresh['shown'] if v['moves_measured'] is False} == {'Chebarkul', 'Magnitogorsk', 'Yekaterinburg'}
    (kamensk,) = fresh['linked']
    assert kamensk['site'] == 'Kamensk-Uralskiy' and kamensk['at_s'] == 55
    assert kamensk['url'] == 'https://www.youtube.com/watch?v=kFlpCT3v12E&t=55s'


def test_no_video_unless_its_uploader_allows_embedding(solved):
    creds = ex.credits(solved[0])
    for embed in ({'allowed': False}, {}, None):
        other = copy.deepcopy(creds)
        for c in other.values():
            if embed is None:
                c.pop('embed', None)
            else:
                c['embed'] = embed
        assert ex.witness_videos(*solved, creds=other) is None
    other = copy.deepcopy(creds)
    other['48']['embed'] = {'allowed': False}
    assert '48' not in {v['clip'] for v in ex.witness_videos(*solved, creds=other)['shown']}


def test_the_committed_data_is_current_and_holds_no_pixels(fresh):
    text = (WEB / f'{CASE}.json').read_text()
    committed = json.loads(text)['videos']
    assert all(set(v) == KEYS for v in committed['shown'])
    assert committed == json.loads(json.dumps(fresh))  # a forgotten re-export fails here
    for word in ('"centroid"', '"box"', '"blob"'):
        assert word not in text


def test_colombia_links_the_post_and_plays_nothing():
    data = ex.colombia()
    creds = ex.credits(ex.Case('colombia-2025-07-30'))
    assert 'videos' not in data
    assert data['witness'][0]['post'] == {'url': creds['medellin']['source'], 'credit': creds['medellin']['credit']}
