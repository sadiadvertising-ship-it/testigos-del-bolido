"""The coarse outline of mainland Colombia in scripts/glm_by_country.py and the counts it wrote. No catalogue needed."""
import collections
import datetime as dt
import importlib.util
import json
import math
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('glm_by_country', ROOT / 'scripts' / 'glm_by_country.py')
glm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(glm)

INSIDE = {  # (longitude, latitude)
    'GLM flash of 30 July 2025': (-72.2121, 6.4605),
    'Bogotá': (-74.0721, 4.7110),
    'Medellín': (-75.5812, 6.2442),
    'Cali': (-76.5320, 3.4516),
    'Leticia': (-69.9406, -4.2153),
    'Riohacha': (-72.9072, 11.5444),
    'Cúcuta': (-72.5078, 7.8939),
    'Pasto': (-77.2811, 1.2136),
    'Puerto Carreño': (-67.4858, 6.1894),
    'Mitú': (-70.2342, 1.2533),
    'Tumaco': (-78.7639, 1.7986),
}
OUTSIDE = {
    'Caracas': (-66.9036, 10.4806),
    'Maracaibo': (-71.6406, 10.6545),
    'San Cristóbal, Venezuela': (-72.2250, 7.7669),
    'Panama City': (-79.5199, 8.9824),
    'Quito': (-78.4678, -0.1807),
    'Iquitos': (-73.2516, -3.7437),
    'Manaus': (-60.0217, -3.1190),
}


@pytest.mark.parametrize('place', INSIDE)
def test_place_inside_the_outline(place):
    assert glm.inside(*INSIDE[place])


@pytest.mark.parametrize('place', OUTSIDE)
def test_place_outside_the_outline(place):
    assert not glm.inside(*OUTSIDE[place])


def _turn(p, q, r):
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def test_outline_is_coarse_and_does_not_cross_itself():
    n = len(glm.COLOMBIA)
    assert 40 <= n <= 80
    assert len(set(glm.COLOMBIA)) == n
    segs = list(glm.edges(glm.COLOMBIA))
    for i in range(n):
        for j in range(i + 2, n - (i == 0)):  # edges that share no vertex
            (a, b), (c, d) = segs[i], segs[j]
            assert not (_turn(a, b, c) * _turn(a, b, d) < 0 and _turn(c, d, a) * _turn(c, d, b) < 0), (i, j)
    assert 1.0e6 < glm.area_km2() < 1.3e6  # mainland Colombia covers about 1.14 million km²


def test_area_of_a_one_degree_cell_on_the_equator():
    cell = [(0, 0), (1, 0), (1, 1), (0, 1)]
    exact = glm.EARTH_KM ** 2 * math.radians(1) * math.sin(math.radians(1))
    assert glm.area_km2(cell) == pytest.approx(exact, rel=1e-12)


def test_bands_on_a_square():
    square = [(0, 0), (0, 2), (2, 2), (2, 0)]
    degree_km = math.radians(1) * glm.EARTH_KM
    assert glm.boundary_km(1, 1, square) == pytest.approx(degree_km * math.cos(math.radians(1)), rel=1e-9)
    shrunk, drawn, grown = glm.BANDS
    centre = glm.where(1, 1, square)
    near_edge_inside = glm.where(0.1, 1, square)  # about 11 km inside
    near_edge_outside = glm.where(-0.2, 1, square)  # about 22 km outside
    far_outside = glm.where(-0.5, 1, square)  # about 56 km outside
    assert centre == {shrunk: True, drawn: True, grown: True}
    assert near_edge_inside == {shrunk: False, drawn: True, grown: True}
    assert near_edge_outside == {shrunk: False, drawn: False, grown: True}
    assert far_outside == {shrunk: False, drawn: False, grown: False}


def test_full_years_start_after_the_catalogue_began_and_end_before_its_newest_year():
    def ms(year, month):
        return dt.datetime(year, month, 1, tzinfo=dt.timezone.utc).timestamp() * 1000
    catalog = [{'datetime': ms(2017, 7), 'createdDate': '2019-06-07T21:35:19.846Z'},
               {'datetime': ms(2022, 3), 'createdDate': '2022-03-02T10:00:00.000Z'},
               {'datetime': ms(2026, 10), 'createdDate': '2026-10-08T10:40:51.624Z'}]
    assert glm.full_years(catalog) == (2020, 2025)


def test_committed_counts_agree_with_the_outline_and_the_events_listed():
    out = json.loads((ROOT / 'events' / 'colombia-2025-07-30' / 'glm-colombia.json').read_text())
    assert out['outline']['lonlat'] == [list(v) for v in glm.COLOMBIA]
    assert out['outline']['vertices'] == len(glm.COLOMBIA)
    assert out['margin_km'] == glm.MARGIN_KM
    per_year = {b: collections.Counter() for b in glm.BANDS}
    bolide = collections.Counter()
    for e in out['events']:
        w = glm.where(e['lon'], e['lat'])
        assert w[glm.BANDS[2]], e['id']  # only events inside the grown outline are listed
        assert w['outline'] == e['inside'], e['id']
        assert glm.boundary_km(e['lon'], e['lat']) == pytest.approx(e['edge_km'], abs=0.051)
        for b in glm.BANDS:
            if w[b]:
                per_year[b][e['utc'][:4]] += 1
                bolide[b] += e['humanClassification'] == 'Bolide'
    first, last = out['first_full_year'], out['last_full_year']
    for b in glm.BANDS:
        c = out['counts'][b]
        assert {y: n for y, n in c['per_year'].items() if n} == dict(per_year[b])
        assert c['total'] == sum(per_year[b].values())
        assert c['classified_bolide'] == bolide[b]
        full = [per_year[b][str(y)] for y in range(first, last + 1)]
        assert (c['full_years']['events'], c['full_years']['min_per_year'], c['full_years']['max_per_year']) == \
            (sum(full), min(full), max(full))
    for y in out['counts']['outline']['per_year']:
        s, o, g = (out['counts'][b]['per_year'][y] for b in glm.BANDS)
        assert s <= o <= g
    flash = [e for e in out['events'] if e['utc'] == '2025-07-31T03:50:24Z']
    assert len(flash) == 1 and flash[0]['inside'] and flash[0]['humanClassification'] == 'Bolide'
