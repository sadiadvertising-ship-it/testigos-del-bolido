"""How often does a satellite detect a bolide over Colombia? NASA's GLM bolide catalogue, counted per year.

Reads the catalogue that scripts/fetch_glm.py downloads (out/cache/glm-bolides.json, not committed) and counts the
events whose latitude and longitude fall inside a coarse outline of mainland Colombia, written below by hand. No
country boundary file is used. The outline can be tens of kilometres off, so every count is repeated with the outline
grown by 30 km (an event counts when it is inside or within 30 km of the line) and shrunk by 30 km (inside and farther
than 30 km from it). The catalogue fills up from 2019 on, so the counts are per year and the first full year is named.
Each listed event also gets its angle from sun glint. Glint is the geometry in which the satellite sees sunlight
reflected by water or a roof, and a flash seen in it can be reflected sunlight rather than a bolide. Events near glint
are counted and named, and they stay in every count.
Writes events/colombia-2025-07-30/glm-colombia.json, which lists every event inside the grown outline.
Usage: .venv/bin/python scripts/glm_by_country.py [path/to/glm-bolides.json]
"""
import collections
import datetime as dt
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'out' / 'cache' / 'glm-bolides.json'
WINDOW = ROOT / 'events' / 'colombia-2025-07-30' / 'glm-window.json'  # holds the catalogue's download date
OUT = ROOT / 'events' / 'colombia-2025-07-30' / 'glm-colombia.json'
EARTH_KM = 6371.0088
MARGIN_KM = 30
BANDS = (f'shrunk_{MARGIN_KM}km', 'outline', f'grown_{MARGIN_KM}km')
WGS84_A_KM = 6378.137  # equatorial radius of the WGS84 ellipsoid
WGS84_F = 1 / 298.257223563  # its flattening
GEO_HEIGHT_KM = 35786.0234  # every catalogue record puts its satellite this high above the equator, at latitude 0
GOES_EAST = {'GLM-16': -75.2, 'GLM-19': -75.2}  # used only for a record that gives no satellite position
NEAR_GLINT_DEG = 2

# A coarse outline of mainland Colombia, in (longitude, latitude), written by hand from what is known of its coast and
# borders. It is not taken from a boundary file. It runs clockwise from the Panama border on the Caribbean. Vertices on
# the coast sit on or just off the shore, and vertices on the border sit on the rivers and ridges it follows. Between
# vertices the line can be tens of kilometres off. Islands (San Andrés, Providencia, Gorgona, Malpelo) are left out.
COLOMBIA = [
    # Caribbean coast, west to east
    (-77.37, 8.68),   # Cabo Tiburón, Panama border
    (-76.80, 7.95),   # Gulf of Urabá, south end
    (-76.87, 8.62),   # Punta Caribana
    (-76.43, 8.86),   # Arboletes
    (-75.92, 9.40),   # San Bernardo del Viento
    (-75.62, 9.45),   # Gulf of Morrosquillo
    (-75.56, 10.42),  # Cartagena
    (-74.85, 11.11),  # Bocas de Ceniza, Barranquilla
    (-74.27, 11.00),  # Ciénaga
    (-74.23, 11.25),  # Santa Marta
    (-73.55, 11.26),  # Palomino
    (-72.90, 11.58),  # Riohacha
    (-72.17, 12.21),  # Cabo de la Vela
    (-71.67, 12.46),  # Punta Gallinas
    (-71.13, 12.10),  # Punta Espada
    (-71.33, 11.84),  # Castilletes, Venezuela border
    # Venezuela border: across La Guajira, along the Perijá range, the Catatumbo and the Táchira river
    (-71.96, 11.60),
    (-72.24, 11.10),  # Montes de Oca
    (-72.90, 10.45),  # Perijá range
    (-73.28, 9.20),   # south end of the Perijá range
    (-72.79, 9.08),   # Río de Oro
    (-72.62, 8.62),   # Catatumbo
    (-72.39, 8.37),   # Puerto Santander
    (-72.45, 7.80),   # Táchira river at Cúcuta
    (-72.44, 7.42),   # Páramo de Tamá
    (-72.20, 7.34),
    # then the Arauca river, a straight line to the Meta, the Meta, the Orinoco, the Atabapo and the Guainía
    (-71.96, 7.00),   # Arauca river
    (-70.75, 7.10),   # Arauca
    (-70.10, 7.02),
    (-69.40, 6.10),   # Meta river
    (-67.70, 6.27),
    (-67.44, 6.21),   # the Meta meets the Orinoco at Puerto Carreño
    (-67.645, 5.66),  # the Orinoco at Puerto Ayacucho
    (-67.84, 4.55),
    (-67.72, 4.05),   # the Atabapo meets the Orinoco
    (-67.32, 3.40),
    (-67.80, 2.82),   # Guainía river
    (-67.18, 2.25),
    (-66.86, 1.22),   # Piedra del Cocuy on the Río Negro, Brazil border
    # Brazil border, first in a straight line from the Piedra del Cocuy
    (-67.35, 2.09),
    (-67.88, 1.70),
    (-69.82, 1.72),
    (-69.82, 1.08),   # Querarí river
    (-69.22, 0.98),   # Vaupés river
    (-69.20, 0.60),   # Yavaraté
    (-70.03, 0.54),   # Papurí river
    (-70.03, -0.20),
    (-69.60, -0.55),  # Taraira river
    (-69.44, -1.50),  # the Apaporis meets the Caquetá
    (-69.93, -4.24),  # Leticia on the Amazon, Peru border
    # Peru border: the Amazon, the west side of the Leticia trapezium, the Putumayo
    (-70.38, -3.79),  # Puerto Nariño
    (-70.70, -3.75),  # Atacuari river
    (-70.05, -2.73),  # Putumayo river
    (-70.81, -2.26),
    (-73.07, -2.31),
    (-73.66, -1.26),
    (-74.12, -1.00),
    (-74.78, -0.22),  # Puerto Leguízamo
    (-75.25, -0.10),  # Güeppí, Ecuador border
    # Ecuador border: the Putumayo, the San Miguel, the Rumichaca bridge, the Mataje
    (-76.30, 0.40),
    (-77.42, 0.40),
    (-77.67, 0.82),   # Rumichaca bridge, Ipiales
    (-78.88, 1.43),   # mouth of the Mataje river
    # Pacific coast, south to north
    (-79.03, 1.60),   # Cabo Manglares
    (-78.80, 1.83),   # Tumaco
    (-78.43, 2.62),   # Patía delta
    (-77.93, 2.70),   # Guapi
    (-77.15, 3.85),   # Buenaventura
    (-77.48, 4.10),   # San Juan delta
    (-77.35, 4.70),
    (-77.55, 5.50),   # Cabo Corrientes
    (-77.30, 5.72),   # Nuquí
    (-77.42, 6.25),   # Bahía Solano
    (-77.48, 6.70),   # Cupica
    (-77.90, 7.22),   # Panama border
    # Panama border, along the Darién range
    (-77.75, 7.70),
    (-77.28, 7.90),
    (-77.45, 8.50),
]


def edges(outline):
    return zip(outline, outline[1:] + outline[:1])


def inside(lon, lat, outline=COLOMBIA):
    """Even-odd ray casting along the parallel, with straight edges in longitude and latitude."""
    hit = False
    for (x1, y1), (x2, y2) in edges(outline):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def boundary_km(lon, lat, outline=COLOMBIA):
    """Distance from the point to the nearest edge, in km, in a flat frame centred on the point. A degree of longitude
    is shortened by the cosine of the point's latitude; at 30 km the error is far below a kilometre."""
    k = math.cos(math.radians(lat))
    best = math.inf
    for (x1, y1), (x2, y2) in edges(outline):
        ax, ay, bx, by = (x1 - lon) * k, y1 - lat, (x2 - lon) * k, y2 - lat
        dx, dy = bx - ax, by - ay
        t = min(1.0, max(0.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return math.radians(best) * EARTH_KM


def where(lon, lat, outline=COLOMBIA):
    """Which of the three outlines hold the point: shrunk by MARGIN_KM, as written, grown by MARGIN_KM."""
    is_in, km = inside(lon, lat, outline), boundary_km(lon, lat, outline)
    return dict(zip(BANDS, (is_in and km > MARGIN_KM, is_in, is_in or km <= MARGIN_KM)))


def area_km2(outline=COLOMBIA):
    """Area on a sphere of the outline with straight edges in longitude and latitude: R² times the integral of
    sin(latitude) d(longitude) around it."""
    s = 0.0
    for (x1, y1), (x2, y2) in edges(outline):
        p1, p2, dl = math.radians(y1), math.radians(y2), math.radians(x2 - x1)
        s += dl * math.sin(p1) if p1 == p2 else dl * (math.cos(p1) - math.cos(p2)) / (p2 - p1)
    return abs(s) * EARTH_KM ** 2


def julian_day(t):
    """Julian day of an aware datetime."""
    return 2440587.5 + t.timestamp() / 86400


def _nutation_and_obliquity(T):
    """The main term of the nutation in longitude and the true obliquity of the ecliptic, in degrees, T Julian
    centuries after J2000. From Meeus, Astronomical Algorithms (2nd edition, 1998), equation 22.2 and chapter 25."""
    omega = math.radians(125.04 - 1934.136 * T)
    eps0 = 23 + 26 / 60 + (21.448 - T * (46.8150 + T * (0.00059 - 0.001813 * T))) / 3600
    return -0.00478 * math.sin(omega), eps0 + 0.00256 * math.cos(omega)


def sun_radec(jd):
    """The Sun's apparent right ascension and declination in degrees at Julian day jd. This is the low-accuracy method
    of Meeus, Astronomical Algorithms (2nd edition, 1998), chapter 25, which he gives as accurate to 0.01 degree."""
    T = (jd - 2451545.0) / 36525
    L0 = 280.46646 + T * (36000.76983 + 0.0003032 * T)  # geometric mean longitude
    M = math.radians(357.52911 + T * (35999.05029 - 0.0001537 * T))  # mean anomaly
    C = ((1.914602 - T * (0.004817 + 0.000014 * T)) * math.sin(M) + (0.019993 - 0.000101 * T) * math.sin(2 * M)
         + 0.000289 * math.sin(3 * M))  # equation of the centre
    nutation, obliquity = _nutation_and_obliquity(T)
    lam = math.radians(L0 + C - 0.00569 + nutation)  # apparent longitude: true longitude, aberration, nutation
    eps = math.radians(obliquity)
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360
    return ra, math.degrees(math.asin(math.sin(eps) * math.sin(lam)))


def sidereal_deg(jd):
    """Greenwich apparent sidereal time in degrees at Julian day jd. It is the mean sidereal time of Meeus' equation
    12.4 plus the nutation in longitude times the cosine of the obliquity."""
    T = (jd - 2451545.0) / 36525
    mean = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + T * T * (0.000387933 - T / 38710000)
    nutation, obliquity = _nutation_and_obliquity(T)
    return (mean + nutation * math.cos(math.radians(obliquity))) % 360


def subsolar_point(t):
    """Latitude and longitude where the Sun stands overhead at t, an aware datetime. The method wants Terrestrial Time
    for the Sun and UT1 for the Earth's turn. UTC stands in for both, and the error that makes is smaller than the
    method's own."""
    jd = julian_day(t)
    ra, dec = sun_radec(jd)
    return dec, (ra - sidereal_deg(jd) + 180) % 360 - 180


def _ecef(lat, lon, h_km=0.0):
    """Earth-centred coordinates, in km, of the point h_km above the WGS84 ellipsoid at geodetic lat, lon."""
    la, lo = math.radians(lat), math.radians(lon)
    e2 = WGS84_F * (2 - WGS84_F)
    n = WGS84_A_KM / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return ((n + h_km) * math.cos(la) * math.cos(lo), (n + h_km) * math.cos(la) * math.sin(lo),
            (n * (1 - e2) + h_km) * math.sin(la))


def _unit(lat, lon):
    """The unit vector at latitude lat and longitude lon. It is the ellipsoid's upward normal at that geodetic point,
    and also the direction of a body overhead there."""
    la, lo = math.radians(lat), math.radians(lon)
    return math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)


def glint_deg(lat, lon, sun, sat_lon):
    """Angle in degrees between two directions at the ground point lat, lon: the line to a geostationary satellite at
    longitude sat_lon, and the sunlight that a level surface there reflects. sun is the (latitude, longitude) where the
    Sun stands overhead. At 0 the satellite sees the Sun's mirror image at the point. Returns None when the Sun is
    below the horizon. The level surface is the WGS84 ellipsoid's. Refraction is left out: at glint the Sun and the
    satellite stand at the same elevation, where refraction bends both lines alike."""
    up, s = _unit(lat, lon), _unit(*sun)
    cos_zenith = sum(a * b for a, b in zip(up, s))
    if cos_zenith < 0:
        return None
    mirror = [2 * cos_zenith * a - b for a, b in zip(up, s)]  # the reflected sunlight
    p, q = _ecef(lat, lon), _ecef(0.0, sat_lon, GEO_HEIGHT_KM)
    v = [b - a for a, b in zip(p, q)]  # from the point to the satellite
    cross = (mirror[1] * v[2] - mirror[2] * v[1], mirror[2] * v[0] - mirror[0] * v[2],
             mirror[0] * v[1] - mirror[1] * v[0])
    return math.degrees(math.atan2(math.sqrt(sum(c * c for c in cross)), sum(a * b for a, b in zip(mirror, v))))


def satellite_lons(e):
    """For each GLM that saw catalogue event e, the longitude of its satellite and where it comes from. The catalogue
    record gives the satellite's position (attachments, satellite); for a record that gives none, GLM-16 and GLM-19
    are taken as GOES-East at 75.2 W. The script stops if a position is missing for another GLM, or if a record puts
    its satellite anywhere but latitude 0 and GEO_HEIGHT_KM, which glint_deg assumes."""
    recorded = {a.get('platformId'): a.get('satellite') for a in e.get('attachments') or []}
    lons = []
    for glm in (d.strip() for d in e.get('detectedBy', '').split(',') if d.strip()):
        sat = recorded.get('G' + glm.rsplit('-', 1)[-1])
        if sat:
            if abs(sat['latitude']) > 0.01 or abs(sat['height'] - GEO_HEIGHT_KM) > 0.01:
                sys.exit(f'{e["_id"]}: the catalogue puts {glm} at latitude {sat["latitude"]} and {sat["height"]} '
                         f'km, and glint_deg assumes latitude 0 and {GEO_HEIGHT_KM} km')
            lons.append((sat['longitude'], 'catalogue'))
        elif glm in GOES_EAST:
            lons.append((GOES_EAST[glm], 'GOES-East'))
        else:
            sys.exit(f'{e["_id"]}: the catalogue gives no satellite position for {glm}')
    if not lons:
        sys.exit(f'{e["_id"]}: the catalogue names no GLM that saw the event')
    return lons


def _place(lat, lon):
    return f'{abs(lat):.2f} {"N" if lat >= 0 else "S"}, {abs(lon):.2f} {"W" if lon < 0 else "E"}'


def _and(items):
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' and ' + items[-1]


def utc(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)


def full_years(catalog):
    """First and last calendar year the catalogue covers in full. Its first entry was created in mid-2019
    (createdDate), and few of the events dated before then were added later, so the first full year is the next one.
    The newest year is partial, because events are published weeks after they happen."""
    first_created = min(e['createdDate'] for e in catalog if e.get('createdDate'))
    return int(first_created[:4]) + 1, utc(max(e['datetime'] for e in catalog)).year - 1


def _json(v, pad=''):
    """indent=1, except that a flat dict, and each item of a list of lists or dicts, goes on one line"""
    def flat(x):
        return not isinstance(x, (dict, list))
    if isinstance(v, dict) and not all(flat(x) for x in v.values()):
        body = ',\n'.join(f'{pad} {json.dumps(k)}: {_json(x, pad + " ")}' for k, x in v.items())
        return '{\n' + body + '\n' + pad + '}'
    if isinstance(v, list) and v and not all(flat(x) for x in v):
        return '[\n' + ',\n'.join(pad + ' ' + json.dumps(x, ensure_ascii=False) for x in v) + '\n' + pad + ']'
    return json.dumps(v, ensure_ascii=False)


def main(path=CATALOG):
    window = json.loads(WINDOW.read_text())
    catalog = json.loads(pathlib.Path(path).read_text())['data']
    if len(catalog) != window['catalog_events']:
        sys.exit(f'{path} holds {len(catalog)} events and glm-window.json says {window["catalog_events"]}: '
                 'run scripts/fetch_glm.py again so that the download date matches the catalogue')
    first_full, last_full = full_years(catalog)
    first_created = min(e['createdDate'] for e in catalog if e.get('createdDate'))[:10]
    classified = min(e['datetime'] for e in catalog if e.get('humanClassification'))
    newest = utc(max(e['datetime'] for e in catalog))
    years = range(utc(min(e['datetime'] for e in catalog)).year, newest.year + 1)
    world = collections.Counter(utc(e['datetime']).year for e in catalog)
    early = ' and '.join(f'{world[y]} in {y}' for y in range(years[0], int(first_created[:4])))
    xs, ys = [x for x, _ in COLOMBIA], [y for _, y in COLOMBIA]
    box = (min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1)  # 1 degree is more than MARGIN_KM everywhere here
    listed, bands, sources = [], [], collections.Counter()
    for e in sorted(catalog, key=lambda e: e['datetime']):
        lon, lat = e['longitude'], e['latitude']
        if not (box[0] <= lon <= box[1] and box[2] <= lat <= box[3]):
            continue
        w = where(lon, lat)
        if not w[BANDS[2]]:
            continue
        sats = satellite_lons(e)
        sources.update({source for _, source in sats})  # events, not GLMs
        sun = subsolar_point(utc(e['datetime']))
        angles = [(glint_deg(lat, lon, sun, x), x) for x, _ in sats]  # an event seen by two GLMs keeps the smaller
        glint, sat_lon = angles[0] if angles[0][0] is None else min(angles)  # at night every angle is None
        listed.append({'id': e['_id'], 'utc': utc(e['datetime']).strftime('%Y-%m-%dT%H:%M:%SZ'), 'lat': lat,
                       'lon': lon, 'detectedBy': e.get('detectedBy', ''),
                       'humanClassification': e.get('humanClassification', ''),
                       'confidenceRating': e.get('confidenceRating', ''), 'inside': w['outline'],
                       'edge_km': round(boundary_km(lon, lat), 1), 'sat_lon': round(sat_lon, 2),
                       'glint_deg': None if glint is None else round(glint, 1)})
        bands.append(w)

    def tally(rows, key):
        return dict(sorted(collections.Counter(r[key] for r in rows).items()))

    def near(r):
        return r['glint_deg'] is not None and r['glint_deg'] <= NEAR_GLINT_DEG

    counts = {}
    for b in BANDS:
        rows = [r for r, w in zip(listed, bands) if w[b]]
        per_year = {str(y): sum(r['utc'][:4] == str(y) for r in rows) for y in years}
        full = [r for r in rows if first_full <= int(r['utc'][:4]) <= last_full]
        full_counts = [per_year[str(y)] for y in range(first_full, last_full + 1)]
        counts[b] = {'total': len(rows), 'classified_bolide': sum(r['humanClassification'] == 'Bolide' for r in rows),
                     'per_year': per_year,
                     'near_glint_per_year': {str(y): sum(r['utc'][:4] == str(y) and near(r) for r in rows)
                                             for y in years},
                     'per_detector': tally(rows, 'detectedBy'), 'per_confidence': tally(rows, 'confidenceRating'),
                     'full_years': {'from': first_full, 'to': last_full, 'events': len(full),
                                    'min_per_year': min(full_counts), 'max_per_year': max(full_counts),
                                    'per_confidence': tally(full, 'confidenceRating'),
                                    'near_glint': sum(near(r) for r in full)}}
    day = [r for r in listed if r['glint_deg'] is not None]
    close = [r for r in listed if near(r)]
    farther = sorted(r['glint_deg'] for r in day if not near(r))
    two_glm = sum(',' in r['detectedBy'] for r in listed)
    sat_lons = sorted({r['sat_lon'] for r in listed})
    glint_note = (
        'glint_deg is the angle between the line from an event to the satellite that saw it and the sunlight that a '
        'level surface at the event would reflect. At 0 the satellite sees the Sun\'s mirror image in still water or '
        'on a flat roof, so a flash seen near that geometry can be reflected sunlight rather than a bolide. The Sun\'s '
        'position comes from the low-accuracy method in chapter 25 of Meeus, Astronomical Algorithms (2nd edition, '
        '1998), which he gives as accurate to 0.01 degree, and sidereal time from his chapter 12. The reflecting point '
        'is the event\'s catalogue latitude and longitude, on the WGS84 ellipsoid. glint_deg is null when the centre '
        f'of the Sun was below the horizon, as it was for {len(listed) - len(day)} of the {len(listed)} listed events.')
    satellite_note = (
        'The satellite\'s position comes from each event\'s catalogue record (attachments, satellite), because the '
        'record says where the satellite was when it saw that event. '
        + (f'All {len(listed)} listed events were seen by one GLM each. ' if not two_glm else
           f'{two_glm} of the {len(listed)} listed events were seen by two GLMs, and glint_deg keeps the smaller of '
           'their two angles. ')
        + f'The records place the satellite at latitude 0, {GEO_HEIGHT_KM:.2f} km above the equator, at longitude '
        + _and([f'{abs(x):g} {"W" if x < 0 else "E"}' for x in sat_lons]) + '. '
        + ('That is the GOES-East position, held first by GOES-16, which carries GLM-16, and then by GOES-19, which '
           'carries GLM-19. ' if set(sat_lons) == set(GOES_EAST.values()) else '')
        + 'Where a record gives no position, the script takes GLM-16 and GLM-19 as GOES-East at 75.2 W; '
        + (f'{sources["GOES-East"]} listed events needed that.' if sources['GOES-East'] else
           'no listed event needed that.'))

    def named(r):
        return (f'{r["id"]} ({r["utc"][:10]} {r["utc"][11:16]} UTC, {_place(r["lat"], r["lon"])}, '
                f'{r["glint_deg"]} degrees)')
    if close:
        near_note = (f'{len(close)} listed event{"s lie" if len(close) > 1 else " lies"} within {NEAR_GLINT_DEG} '
                     f'degrees of glint: {_and([named(r) for r in close])}.')
    else:
        near_note = f'No listed event lies within {NEAR_GLINT_DEG} degrees of glint.'
    if farther:
        near_note += f' Every other listed event seen in daylight is at least {farther[0]} degrees from glint.'
    if close:
        near_note += ' They stay in every count.' if len(close) > 1 else ' It stays in every count.'
    near_note += (f' near_glint_per_year counts, in each outline, the events whose glint_deg is {NEAR_GLINT_DEG} '
                  'or less.')
    coarse = [r for r in listed if all(abs(v * 10 - round(v * 10)) < 1e-6 for v in (r['lat'], r['lon']))]
    out = {
        'source': 'NASA neo-bolide catalogue (GOES GLM)',
        'source_url': window['source'],
        'catalog_downloaded': window['catalog_downloaded'],
        'catalog_events': len(catalog),
        'catalog_first_event_utc': utc(min(e['datetime'] for e in catalog)).strftime('%Y-%m-%d'),
        'catalog_last_event_utc': newest.strftime('%Y-%m-%d'),
        'catalog_per_year': {str(y): world[y] for y in years},
        'first_full_year': first_full,
        'last_full_year': last_full,
        'coverage_note': (
            f'The catalogue\'s first entry was created on {first_created}. Events dated before then were added '
            f'later, and few were: worldwide it holds {early}, against {world[first_full]} in {first_full}, the '
            f'first calendar year after that date. {newest.year} is partial: its newest event is from '
            f'{newest.strftime("%Y-%m-%d")}, and events are published weeks after they happen. per_detector says '
            'which GLM saw each event.'),
        'classification_note': (
            f'humanClassification is empty for every event before {utc(classified).strftime("%Y-%m-%d")} and for '
            'events the pipeline published without review (confidenceRating "auto"), so classified_bolide counts '
            'only events that an analyst classified as a bolide after that date.'),
        'outline': {
            'name': 'mainland Colombia, coarse',
            'vertices': len(COLOMBIA),
            'area_km2': int(round(area_km2(), -3)),
            'note': ('Written by hand in scripts/glm_by_country.py from the coast and borders as known, not from a '
                     'boundary file. It can be tens of kilometres off between vertices, so every count is repeated '
                     f'with the outline grown and shrunk by {MARGIN_KM} km. An event counts in the grown outline '
                     f'when it is inside or within {MARGIN_KM} km of the line, and in the shrunk outline when it is '
                     f'inside and farther than {MARGIN_KM} km from the line. Islands are left out.'),
            'lonlat': [list(v) for v in COLOMBIA],
        },
        'margin_km': MARGIN_KM,
        'near_glint_deg': NEAR_GLINT_DEG,
        'counts': counts,
        'glint_note': glint_note,
        'satellite_note': satellite_note,
        'near_glint_note': near_note,
        'events_note': (
            f'Every catalogued event inside the outline grown by {MARGIN_KM} km. edge_km is the distance to the '
            'outline; inside says on which side of it the event lies. sat_lon is the longitude of the satellite that '
            'saw the event, and glint_note says what glint_deg is. The catalogue gives '
            f'{len(coarse)} of these positions to 0.1 degree only, about 11 km, the newest from '
            f'{max(r["utc"] for r in coarse)[:10] if coarse else "none"}.'),
        'events': listed,
    }
    OUT.write_text(_json(out) + '\n')
    for b in BANDS:
        c = counts[b]
        print(f'{b:12s} total {c["total"]:3d}  classified bolide {c["classified_bolide"]:3d}  '
              f'{first_full}-{last_full}: {c["full_years"]["events"]} events, {c["full_years"]["min_per_year"]} to '
              f'{c["full_years"]["max_per_year"]} a year, {c["full_years"]["per_confidence"]}, '
              f'{c["full_years"]["near_glint"]} near glint')
        print(' ' * 13 + f'per year {c["per_year"]}')
    print(f'near glint, within {NEAR_GLINT_DEG} degrees: '
          + (', '.join(f'{r["id"]} {r["utc"]} {r["glint_deg"]}' for r in close) or 'none')
          + f'; the next daytime event is {farther[0] if farther else "none"}')
    print('wrote', OUT.relative_to(ROOT))


if __name__ == '__main__':
    main(*sys.argv[1:2])
