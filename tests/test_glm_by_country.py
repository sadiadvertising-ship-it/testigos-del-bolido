"""The coarse outline of mainland Colombia in scripts/glm_by_country.py, its Sun and glint geometry, and the counts it
wrote. No catalogue needed."""
import collections
import datetime as dt
import importlib.util
import json
import math
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('glm_by_country', ROOT / 'scripts' / 'glm_by_country.py')
glm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(glm)
COMMITTED = ROOT / 'events' / 'colombia-2025-07-30' / 'glm-colombia.json'

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


def test_sun_position_matches_meeus_example_25a():
    # Meeus, Astronomical Algorithms, 2nd edition (Willmann-Bell, 1998), example 25.a. By the low-accuracy method, on
    # 1992 October 13.0 TD (JDE 2448908.5) the Sun's apparent right ascension is 198.38083 degrees (13h 13m 31.4s)
    # and its apparent declination is -7.78507 degrees (-7° 47' 06").
    ra, dec = glm.sun_radec(2448908.5)
    assert ra == pytest.approx(198.38083, abs=1e-5)
    assert dec == pytest.approx(-7.78507, abs=1e-5)


def test_sidereal_time_matches_meeus_example_12a():
    # Meeus (1998), example 12.a: on 1987 April 10 at 0h UT, Greenwich apparent sidereal time is 13h 10m 46.1351s.
    # The script keeps only the main term of the nutation, so allow 0.0005 degree (0.12 s).
    assert glm.sidereal_deg(2446895.5) == pytest.approx((13 + 10 / 60 + 46.1351 / 3600) * 15, abs=5e-4)


def test_subsolar_point_gives_meeus_equation_of_time():
    # Meeus (1998), example 28.a: the equation of time on 1992 October 13.0 TD is +13m 42.6s. At 0h UT the Sun then
    # stands overhead at 180 degrees east less the equation of time, counted at a quarter of a degree a minute.
    # Meeus works that example with his full theory of the Sun, so allow the low-accuracy method's 0.01 degree.
    lat, lon = glm.subsolar_point(dt.datetime(1992, 10, 13, tzinfo=dt.timezone.utc))
    assert lon == pytest.approx(180 - (13 + 42.6 / 60) / 4, abs=0.01)
    assert lat == pytest.approx(-7.78507, abs=1e-5)  # the declination of example 25.a, the same instant


def test_glint_is_zero_with_the_sun_overhead_at_the_sub_satellite_point():
    assert glm.glint_deg(0.0, -75.2, (0.0, -75.2), -75.2) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize('zenith', [10.0, 30.0, 60.0])
def test_glint_under_the_satellite_equals_the_sun_zenith_angle(zenith):
    # The satellite is overhead, and a level surface sends the sunlight up at the Sun's zenith angle on the other side.
    assert glm.glint_deg(0.0, -75.2, (0.0, -75.2 + zenith), -75.2) == pytest.approx(zenith, abs=1e-9)
    assert glm.glint_deg(0.0, -75.2, (zenith, -75.2), -75.2) == pytest.approx(zenith, abs=1e-9)


@pytest.mark.parametrize('east', [5.0, 20.0, 40.0])
def test_glint_is_zero_when_the_sun_mirrors_the_satellite(east):
    # A point on the equator east of the satellite sees it to the west at zenith angle z, all in the equator's plane.
    # With the Sun at z to the east, the satellite sees the Sun's mirror image. With the Sun at z to the west, the
    # reflected light leaves 2z away from the satellite.
    a, r, d = glm.WGS84_A_KM, glm.WGS84_A_KM + glm.GEO_HEIGHT_KM, math.radians(east)
    z = math.degrees(math.atan2(r * math.sin(d), r * math.cos(d) - a))
    lon = -75.2 + east
    assert glm.glint_deg(0.0, lon, (0.0, lon + z), -75.2) == pytest.approx(0.0, abs=1e-9)
    assert glm.glint_deg(0.0, lon, (0.0, lon - z), -75.2) == pytest.approx(2 * z, abs=1e-9)


def test_glint_is_none_when_the_sun_is_below_the_horizon():
    assert glm.glint_deg(0.0, -75.2, (0.0, -75.2 + 90.5), -75.2) is None
    assert glm.glint_deg(4.7, -74.1, (0.0, 105.0), -75.2) is None


def test_satellite_longitude_comes_from_the_record_and_else_from_goes_east():
    sat = {'latitude': 0, 'longitude': -75.19999694824219, 'height': 35786.0234375}
    seen = {'_id': 'a', 'detectedBy': 'GLM-16', 'attachments': [{'platformId': 'G16', 'satellite': sat}]}
    assert glm.satellite_lons(seen) == [(-75.19999694824219, 'catalogue')]
    assert glm.satellite_lons({'_id': 'b', 'detectedBy': 'GLM-19', 'attachments': []}) == [(-75.2, 'GOES-East')]
    with pytest.raises(SystemExit):  # no position, and no fallback for GLM-18
        glm.satellite_lons({'_id': 'c', 'detectedBy': 'GLM-18', 'attachments': []})
    with pytest.raises(SystemExit):  # no GLM named
        glm.satellite_lons({'_id': 'e', 'detectedBy': '', 'attachments': []})
    with pytest.raises(SystemExit):  # glint_deg assumes a satellite at latitude 0 and GEO_HEIGHT_KM
        glm.satellite_lons({'_id': 'd', 'detectedBy': 'GLM-16',
                            'attachments': [{'platformId': 'G16', 'satellite': dict(sat, latitude=0.5)}]})


def test_committed_glint_values_match_the_script():
    out = json.loads(COMMITTED.read_text())
    for e in out['events']:
        t = dt.datetime.strptime(e['utc'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
        g = glm.glint_deg(e['lat'], e['lon'], glm.subsolar_point(t), e['sat_lon'])
        if g is None:
            assert e['glint_deg'] is None, e['id']
        else:  # rounded to 0.1, and utc drops the milliseconds the script used; the Earth turns 0.0042 degree a second
            assert e['glint_deg'] == pytest.approx(g, abs=0.06), e['id']
    nights = sum(e['glint_deg'] is None for e in out['events'])
    assert f'for {nights} of the {len(out["events"])} listed events' in out['glint_note']
    assert out['near_glint_deg'] == glm.NEAR_GLINT_DEG
    near = [e for e in out['events'] if e['glint_deg'] is not None and e['glint_deg'] <= glm.NEAR_GLINT_DEG]
    assert set(re.findall(r'\b[0-9a-f]{24}\b', out['near_glint_note'])) == {e['id'] for e in near}
    reviewed = {'685c240fc37fbbdc3dc012c6', '68702784676cc8e13b244915', '68c59c0d02ba848d609b86e1'}
    assert reviewed <= {e['id'] for e in near}  # the three that a reviewer found at the glint point of GOES-East
    first, last = out['first_full_year'], out['last_full_year']
    for b in glm.BANDS:
        rows = [e for e in near if glm.where(e['lon'], e['lat'])[b]]
        c = out['counts'][b]
        assert {y: n for y, n in c['near_glint_per_year'].items() if n} == \
            dict(collections.Counter(e['utc'][:4] for e in rows))
        assert c['full_years']['near_glint'] == sum(first <= int(e['utc'][:4]) <= last for e in rows)
