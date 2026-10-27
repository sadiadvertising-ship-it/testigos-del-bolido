/* Testigos del Bólido: a static viewer for the cases in data/ (written by scripts/export_web.py).
   MapLibre draws the basemap (OpenFreeMap, no key); deck.gl draws the 3D geometry on top. */
'use strict';

// Camera colours in fixed order (blue, aqua, then orange), checked for colour-blind separation on the panel surface.
const SERIES = [[57, 135, 229], [25, 158, 112], [217, 89, 38]];
const GRAY = [125, 135, 150];
const INK = [230, 237, 246];
const WHITE = [242, 248, 255];
const GLOW = [108, 182, 255];
const PUBLISHED = [200, 211, 224];
const NIGHT = [8, 17, 31];
const FONT = '"IBM Plex Sans", system-ui, sans-serif';
const COMPASS = ['north', 'north-north-east', 'north-east', 'east-north-east', 'east', 'east-south-east', 'south-east',
  'south-south-east', 'south', 'south-south-west', 'south-west', 'west-south-west', 'west', 'west-north-west', 'north-west',
  'north-north-west'];

const $ = s => document.querySelector(s);
const rgb = c => `rgb(${c.join(',')})`;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = (x, d = 1) => Number(x).toFixed(d);
const span = (a, b, d = 1) => `${fmt(a, d)}–${fmt(b, d)}`;
const dir = az => COMPASS[Math.round((((az % 360) + 360) % 360) / 22.5) % 16];
const abbr = az => dir(az).split('-').map(w => w[0].toUpperCase()).join('');
const latlon = ([lon, lat]) => `${fmt(Math.abs(lat), 2)}° ${lat >= 0 ? 'N' : 'S'}, ${fmt(Math.abs(lon), 2)}° ${lon >= 0 ? 'E' : 'W'}`;
const dash = new deck.PathStyleExtension({dash: true});

const state = {data: null, t: null, playing: false, highlight: null, show: {sight: true, mc: true, published: true}};
const cache = {};
let cases = [];

function km([lon1, lat1], [lon2, lat2]) {
  const r = Math.PI / 180;
  const a = Math.sin((lat2 - lat1) * r / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin((lon2 - lon1) * r / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}

// ---- map -------------------------------------------------------------------------------------------------------------

const bare = new URLSearchParams(location.search).get('panel') === '0';  // ?panel=0 for screen recordings
document.body.classList.toggle('bare', bare);
const narrow = matchMedia('(max-width: 760px)');
const padding = () => (document.body.classList.contains('bare') ? {top: 0, bottom: 0, left: 0, right: 0}
  : narrow.matches ? {top: 0, bottom: innerHeight * 0.5, left: 0, right: 0} : {top: 0, bottom: 0, left: 412, right: 0});

const map = new maplibregl.Map({
  container: 'map', style: 'https://tiles.openfreemap.org/styles/dark', center: [62.6, 55.0], zoom: 5, pitch: 55,
  maxPitch: 80, attributionControl: {compact: true},
});
map.addControl(new maplibregl.NavigationControl({visualizePitch: true}), 'top-right');
map.on('error', e => console.warn('map:', e.error && e.error.message));
const overlay = new deck.MapboxOverlay({interleaved: false, layers: [], getTooltip: tooltip});
map.addControl(overlay);

map.on('style.load', () => {
  const night = {background: ['background-color', '#08111f'], water: ['fill-color', '#0b1b30']};
  for (const [id, [prop, value]] of Object.entries(night)) if (map.getLayer(id)) map.setPaintProperty(id, prop, value);
  // Quiet place names in the Latin script and sentence case, so the case's own labels lead; no region names.
  for (const l of map.getStyle().layers) {
    if (l.type !== 'symbol' || !l.id.startsWith('place')) continue;
    if (l.id === 'place_state' || l.id === 'place_other') { map.setLayoutProperty(l.id, 'visibility', 'none'); continue; }
    map.setLayoutProperty(l.id, 'text-field', ['coalesce', ['get', 'name:latin'], ['get', 'name']]);
    map.setLayoutProperty(l.id, 'text-transform', 'none');
    map.setPaintProperty(l.id, 'text-color', '#5d6c84');
    map.setPaintProperty(l.id, 'text-halo-color', '#08111f');
  }
  try {
    map.setSky({'sky-color': '#02060d', 'horizon-color': '#132944', 'fog-color': '#08111f', 'sky-horizon-blend': 0.6,
      'horizon-fog-blend': 0.7, 'fog-ground-blend': 0.8});
  } catch (e) { /* the map works without a sky */ }
});

const ON_TOP = {parameters: {depthCompare: 'always', depthWriteEnabled: false}};  // labels and markers stay readable over the 3D lines

function text(id, data, getPosition, getText, extra = {}) {
  return new deck.TextLayer({
    id, data, getPosition, getText, getSize: 12, sizeUnits: 'pixels', sizeMinPixels: 11, sizeMaxPixels: 13, fontFamily: FONT,
    fontWeight: 500, characterSet: 'auto',
    background: true, getBackgroundColor: [...NIGHT, 215], backgroundPadding: [4, 2, 4, 2], getColor: [...INK, 255],
    getTextAnchor: 'start', getAlignmentBaseline: 'center', getPixelOffset: [9, 0], billboard: true, ...ON_TOP, ...extra,
  });
}

function camColor(d, s) {
  const i = d.solution.clips.indexOf(s.id);
  return i >= 0 ? SERIES[i] : GRAY;
}

function headAt(d, t) {  // the fireball on the solved path at t seconds, between samples
  const {path, times} = d.solution;
  for (let i = 1; i < times.length; i++) {
    if (t <= times[i]) {
      const f = Math.max(0, (t - times[i - 1]) / (times[i] - times[i - 1]));
      return path[i - 1].map((v, k) => v + f * (path[i][k] - v));
    }
  }
  return path[path.length - 1];
}

function solvedLayers(d) {
  const sol = d.solution, t = state.t, live = t !== null;
  const seen = d.stations.filter(s => s.rays);
  const at = s => [...s.lonlat, s.height_m || 0];
  const rays = seen.flatMap(s => s.rays.filter(r => !live || r[0] <= t).map(r => ({s, path: [at(s), r.slice(1)]})));
  const planes = seen.map(s => {  // during a replay each plane opens as its camera sees more of the flight
    const upTo = s.rays.filter(r => !live || r[0] <= t);
    return upTo.length > 1 && {s, polygon: [at(s), upTo[0].slice(1), upTo[upTo.length - 1].slice(1)]};
  }).filter(Boolean);
  const flown = live ? sol.path.filter((_, i) => sol.times[i] <= t).concat([headAt(d, t)]) : sol.path;
  const tried = state.highlight && d.tried.find(x => x.step === state.highlight);
  const first = sol.path[0], last = sol.path[sol.path.length - 1];
  const layers = [];
  if (state.show.mc && d.montecarlo && !live) {
    layers.push(new deck.PathLayer({id: 'mc', data: d.montecarlo.lines, getPath: l => l, getColor: [...GLOW, 26], getWidth: 1,
      widthUnits: 'pixels', billboard: true}));
  }
  if (state.show.sight) {
    layers.push(new deck.SolidPolygonLayer({id: 'planes', data: planes, getPolygon: p => p.polygon, _full3d: true,
      getFillColor: p => [...camColor(d, p.s), p.s.status === 'used' ? 24 : 10]}));
    layers.push(new deck.PathLayer({id: 'rays', data: rays, getPath: r => r.path, widthUnits: 'pixels', billboard: true,
      getColor: r => [...camColor(d, r.s), r.s.status === 'used' ? 115 : 95], getWidth: 1,
      getDashArray: r => (r.s.status === 'used' ? [0, 0] : [4, 3]), extensions: [dash]}));
  }
  layers.push(new deck.PathLayer({id: 'ground-track', data: [sol.path.map(p => [p[0], p[1], 0])], getPath: p => p,
    getColor: [...GLOW, 110], getWidth: 1.5, widthUnits: 'pixels', getDashArray: [3, 3], extensions: [dash]}));
  layers.push(new deck.LineLayer({id: 'curtain', data: sol.path.filter((_, i) => i % 4 === 0), getSourcePosition: p => p,
    getTargetPosition: p => [p[0], p[1], 0], getColor: [...GLOW, 38], getWidth: 1}));
  if (state.show.published && d.published && !live) {
    layers.push(new deck.PathLayer({id: 'published', data: [d.published.path], getPath: p => p, getColor: [...PUBLISHED, 220],
      getWidth: 2, widthUnits: 'pixels', billboard: true, getDashArray: [6, 4], extensions: [dash]}));
  }
  if (tried) {
    layers.push(new deck.PathLayer({id: 'tried', data: [tried.path], getPath: p => p, getColor: [255, 255, 255, 170], getWidth: 2,
      widthUnits: 'pixels', billboard: true, getDashArray: [2, 3], extensions: [dash]}));
  }
  layers.push(new deck.PathLayer({id: 'glow', data: [flown], getPath: p => p, getColor: [...GLOW, 90], getWidth: 12,
    widthUnits: 'pixels', billboard: true, capRounded: true, jointRounded: true}));
  layers.push(new deck.PathLayer({id: 'path', data: [flown], getPath: p => p, getColor: [...WHITE, 255], getWidth: 3,
    widthUnits: 'pixels', billboard: true, capRounded: true, jointRounded: true}));
  if (live) {
    layers.push(new deck.ScatterplotLayer({id: 'head', data: [headAt(d, t)], getPosition: p => p, getRadius: 6, radiusUnits: 'pixels',
      getFillColor: [255, 255, 255], stroked: true, getLineColor: [...GLOW, 150], getLineWidth: 7, lineWidthUnits: 'pixels', billboard: true,
      ...ON_TOP}));
  }
  layers.push(new deck.ScatterplotLayer({id: 'cams', data: d.stations, pickable: true, getPosition: s => [...s.lonlat, 0],
    getRadius: s => (s.rays ? 5.5 : 4), radiusUnits: 'pixels', radiusMinPixels: 3.5, radiusMaxPixels: 6, getFillColor: s => (s.rays ? [...camColor(d, s), 255] : [...NIGHT, 255]),
    stroked: true, getLineColor: s => (s.rays ? [...NIGHT, 255] : [...GRAY, 255]), getLineWidth: 1.5, lineWidthUnits: 'pixels',
    billboard: true, ...ON_TOP}));
  layers.push(text('cam-labels', d.stations, s => [...s.lonlat, 0], s => s.site,
    {getColor: s => (s.rays ? [...INK, 255] : [150, 160, 175, 255]), updateTriggers: {getColor: d.id}}));
  layers.push(text('heights', [first, last], p => p, p => `${fmt(p[2] / 1000, 0)} km`, {getPixelOffset: [0, -16],
    getTextAnchor: 'middle'}));
  if (state.show.published && d.published && !live) {
    layers.push(text('published-label', [d.published.path[1]], p => p, () => 'CBET 3423, published', {getColor: [...PUBLISHED, 255],
      getPixelOffset: [0, 20], getTextAnchor: 'middle', getSize: 11.5}));
  }
  return layers;
}

function openLayers(d) {
  const g = d.satellite, [lon, lat] = g.lonlat, [dlon, dlat] = g.extent_deg;
  const box = [[lon - dlon / 2, lat - dlat / 2], [lon + dlon / 2, lat - dlat / 2], [lon + dlon / 2, lat + dlat / 2], [lon - dlon / 2, lat + dlat / 2]];
  const high = d.towns.filter(t => t.sees_it_high);
  const witness = d.witness.filter(w => /calibrat|orient/.test(w.status));
  const named = [...high].sort((a, b) => a.km - b.km).slice(0, 5).concat(d.towns.filter(t => witness.some(w => w.site === t.city)));
  return [
    new deck.PolygonLayer({id: 'glm-box', data: [box], getPolygon: b => b, getFillColor: [...SERIES[1], 45], getLineColor: [...SERIES[1], 210],
      getLineWidth: 1, lineWidthUnits: 'pixels'}),
    new deck.SolidPolygonLayer({id: 'sight', data: high, _full3d: true, getFillColor: [...SERIES[0], 22],
      getPolygon: t => [[...t.lonlat, 0], [lon, lat, 40000], [lon, lat, 80000]]}),
    new deck.PathLayer({id: 'sight-edges', data: high, getPath: t => [[lon, lat, 40000], [...t.lonlat, 0], [lon, lat, 80000]],
      getColor: [...SERIES[0], 120], getWidth: 1, widthUnits: 'pixels', billboard: true}),
    new deck.PathLayer({id: 'witness', data: witness, getPath: w => [[...w.lonlat, 0], [lon, lat, 60000]], getColor: [...GRAY, 200],
      getWidth: 1.5, widthUnits: 'pixels', billboard: true, getDashArray: [4, 3], extensions: [dash]}),
    new deck.LineLayer({id: 'column', data: [[lon, lat]], getSourcePosition: p => [...p, 0], getTargetPosition: p => [...p, 100000],
      getColor: [...SERIES[1], 120], getWidth: 1.5}),
    new deck.LineLayer({id: 'column-band', data: [[lon, lat]], getSourcePosition: p => [...p, 40000], getTargetPosition: p => [...p, 80000],
      getColor: [...SERIES[1], 255], getWidth: 4}),
    new deck.ScatterplotLayer({id: 'glm', data: [g], pickable: true, getPosition: () => [lon, lat, 0], getRadius: 6, radiusUnits: 'pixels',
      getFillColor: [255, 255, 255], stroked: true, getLineColor: [...SERIES[1], 230], getLineWidth: 4, lineWidthUnits: 'pixels',
      billboard: true, ...ON_TOP}),
    new deck.ScatterplotLayer({id: 'towns', data: d.towns, pickable: true, getPosition: t => [...t.lonlat, 0], getRadius: 4.5,
      radiusUnits: 'pixels', getFillColor: t => [...(t.sees_it_high ? SERIES[0] : GRAY), 255], stroked: true, getLineColor: [...NIGHT, 255],
      getLineWidth: 1.5, lineWidthUnits: 'pixels', billboard: true, ...ON_TOP}),
    text('town-labels', named, t => [...t.lonlat, 0], t => (t.sees_it_high ? `${t.city}  ${span(t.el_at_40km_deg, t.el_at_80km_deg, 0)}° up` : t.city),
      {getColor: t => (t.sees_it_high ? [...INK, 255] : [150, 160, 175, 255])}),
    text('glm-label', [g], () => [lon, lat, 100000], () => 'GOES-19 flash', {getColor: [...INK, 255]}),
  ];
}

function redraw() {
  if (state.data) overlay.setProps({layers: state.data.solution ? solvedLayers(state.data) : openLayers(state.data)});
}

const TIP = {background: 'rgba(8, 16, 29, 0.96)', color: '#e6edf6', border: '1px solid #1c2a41', borderRadius: '8px', padding: '8px 10px',
  font: `13px/1.45 ${FONT}`, maxWidth: '280px'};

function status(s) {
  return {used: 'used in the final solution', dropped: `dropped by the agent${s.reason ? `: ${s.reason}` : ''}`,
    'not calibrated': 'not oriented: no confirmed landmark or line set', calibrated: 'oriented, not used'}[s.status] || s.status;
}

function tooltip({object, layer}) {
  if (!object || !layer) return null;
  let html = '';
  if (layer.id === 'cams') {
    html = `<b>${esc(object.site)}</b><br>${esc(object.camera)}<br>${esc(status(object))}`
      + (object.speed_kms ? `<br>${fmt(object.speed_kms, 2)} km/s on its own clock, ${fmt(object.miss_deg, 2)}° RMS miss` : '');
  } else if (layer.id === 'towns') {
    html = `<b>${esc(object.city)}</b><br>${object.km} km from the flash; look ${dir(object.look_az_deg)} (${Math.round(object.look_az_deg)}°)`
      + `<br>${fmt(object.el_at_40km_deg, 0)}° up if it was 40 km high, ${fmt(object.el_at_80km_deg, 0)}° at 80 km`;
  } else if (layer.id === 'glm') {
    html = `<b>GOES-19 GLM bolide</b><br>${esc(object.start_utc.replace('T', ' ').replace('Z', ' UTC'))}, ${fmt(object.duration_s, 2)} s`
      + `<br>${esc(object.source)}; classified ${esc(object.classification)}`;
  }
  return html ? {html, style: TIP} : null;
}

// ---- panel -----------------------------------------------------------------------------------------------------------

function name(d, id) {
  const s = d.stations?.find(x => x.id === id);
  if (s) return s.site;
  const w = d.witness?.find(x => x.site.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase() === String(id).toLowerCase());
  return w ? w.site : id;
}

function leadSolved(d) {
  const s = d.solution, mc = d.montecarlo && d.montecarlo.stats;
  const [a, b] = s.clips.map(id => d.stations.find(x => x.id === id));
  const oriented = d.stations.filter(x => x.rays).length, dropped = d.stations.filter(x => x.status === 'dropped');
  const top = s.path[0][2] / 1000, low = s.path[s.path.length - 1][2] / 1000, dur = s.times[s.times.length - 1];
  const speed = mc ? `Speed ${fmt(s.speed_kms, 1)} km/s by the fit; the Monte Carlo puts it at ${fmt(mc.speed.median, 1)} km/s `
    + `(1σ ${span(...mc.speed['1sigma'])}). Satellites and rocket stages re-enter at under 8 km/s, and even the low end of our 2σ range, `
    + `${fmt(mc.speed['2sigma'][0], 1)} km/s, is above Earth's 11.2 km/s escape speed: <b>a natural meteor</b>.`
    : `Speed ${fmt(s.speed_kms, 1)} km/s: ${esc(s.verdict_reason)}.`;
  return `<p class="when">${esc(d.when)} · validation case</p>
    <p>${d.stations.length} witness videos, as anyone finds them online. In ${oriented} of them, AI annotators measured street lines
    and poles and matched landmarks to OpenStreetMap during development, so those cameras could be oriented; SAM 3.1 tracked the
    fireball in each. The agent took it from there: it compared the cameras' planes of sight, tried ${d.tried.length}
    combinations${dropped.length ? `, left out ${dropped.map(x => esc(x.site)).join(', ')} on a criterion the code measured` : ''},
    and chose <b>${esc(a.site)}</b> and <b>${esc(b.site)}</b>, ${Math.round(km(a.lonlat, b.lonlat))} km apart, whose planes cross at
    ${fmt(s.q_deg, 0)}°. The code re-solved that choice before accepting it.</p>
    <p class="big">Heading <span class="num">${fmt(s.azimuth_deg, 1)}°</span> (${dir(s.azimuth_deg)}), descending at
    <span class="num">${fmt(s.slope_deg, 1)}°</span>, from <span class="num">${fmt(top, 0)}</span> km down to
    <span class="num">${fmt(low, 0)}</span> km in <span class="num">${fmt(dur, 1)}</span> s.</p>
    <p>${speed}</p>`;
}

function compareSolved(d) {
  const s = d.solution, mc = d.montecarlo && d.montecarlo.stats, [cbet, zul] = d.published.values;
  const cell = (v, unit = '') => (v === null || v === undefined ? '—' : `${fmt(v, 1)}${unit}`);
  const range = k => (mc ? `<span class="range">1σ ${span(...mc[k]['1sigma'])}</span>` : '');
  const row = (label, k, ours, key, unit) => `<tr><th scope="row">${label}</th>
    <td class="r ours"><span class="num">${fmt(ours, 1)}${unit}</span>${range(k)}</td>
    <td class="r"><span class="num">${cell(cbet[key], unit)}</span></td><td class="r"><span class="num">${cell(zul[key], unit)}</span></td></tr>`;
  const notes = [];
  if (mc) {
    const az = mc.azimuth, sl = mc.slope;
    notes.push(az.cbet_within_1sigma ? "CBET 3423's heading is inside our 1σ range."
      : az.cbet_within_2sigma ? "CBET 3423's heading is inside our 2σ range, not our 1σ."
        : "CBET 3423's heading is outside our 2σ range.");
    if (!sl.cbet_within_2sigma) {
      notes.push(`Our slope is ${fmt(Math.abs(s.slope_deg - cbet.slope_deg), 1)}° ${s.slope_deg > cbet.slope_deg ? 'steeper' : 'shallower'}
        than theirs and outside our 2σ range: an error the Monte Carlo does not model.`);
    }
    notes.push(`Their main flare, at ${fmt(mc.flare_h_km.cbet, 1)} km, sits at ${fmt(mc.flare_h_km.median, 1)} km on our line
      (1σ ${span(...mc.flare_h_km['1sigma'])}), and their end point lies ${fmt(mc.end_off_km.median, 1)} km from it.`);
    notes.push(`Our speed range is the Monte Carlo's (median ${fmt(mc.speed.median, 1)} km/s): it is the least certain number.`);
  }
  if (d.refereed) {
    notes.push(`CBET 3423 was a preliminary telegram; refereed solutions published later in 2013 give ${d.refereed.map(r =>
      `${fmt(r.v_kms, 2)} km/s (${esc(r.who)})`).join(' and ')}. That comparison was added after the run and does not change its grade.`);
  }
  const held = d.stations.find(x => x.status === 'dropped' && x.rays);
  if (held) {
    notes.push(`${esc(held.site)}, left out of the fit, is a check on it: its lines of sight miss the path by ${fmt(held.miss_deg, 2)}°
      RMS, and its own clock gives ${fmt(held.speed_kms, 2)} km/s along it.`);
  }
  const sam = d.sam_vs_threshold && d.sam_vs_threshold.solutions[s.clips.join('+')];
  if (sam && sam.threshold && !sam.threshold.error) {
    notes.push(`Without SAM 3.1, a plain brightness threshold on the same frames gives a heading of ${fmt(sam.threshold.azimuth_deg, 1)}°
      and a speed of ${fmt(sam.threshold.speed_kms, 2)} km/s: it locks onto glare.`);
  }
  return `<h2>Against the published solutions</h2>
    <table class="compare"><thead><tr><th></th><th class="r">This agent</th><th class="r">CBET 3423</th><th class="r">Zuluaga et al.</th></tr></thead>
    <tbody>${row('Heading', 'azimuth', s.azimuth_deg, 'azimuth_deg', '°')}${row('Slope', 'slope', s.slope_deg, 'slope_deg', '°')}
    ${row('Speed, km/s', 'speed', s.speed_kms, 'speed_kms', '')}
    <tr class="src"><th scope="row">From</th><td class="r">2 cameras${mc ? `, ${d.montecarlo.draws} Monte Carlo draws` : ''}</td>
    <td class="r">${esc(cbet.how)}</td><td class="r">${esc(zul.how)}</td></tr></tbody></table>
    <p class="note" style="margin-top:8px">${notes.join(' ')} The agent never saw these published values${d.grade ? `: a separate
    script graded the run afterwards, ${esc(d.grade.passed)} criteria (${Object.entries(d.grade.gate).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v ? 'passes' : 'fails'}`).join(', ')})` : ''}.</p>
    <p class="note">${d.published.values.map(v => esc(v.who)).join('. ')}.</p>`;
}

function leadOpen(d) {
  const g = d.satellite, nearest = [...d.towns].sort((a, b) => a.km - b.km)[0];
  const med = d.towns.find(t => t.city === 'Medellín');
  return `<p class="when">${esc(d.when)} · open case</p>
    <p>A green fireball crossed the night sky over north-eastern Colombia. The lightning mapper on the GOES-19 weather satellite
    recorded a ${fmt(g.duration_s, 2)} s flash at <span class="num">${latlon(g.lonlat)}</span>, ${nearest.km} km from ${esc(nearest.city)}.</p>
    <p>NASA's analysts classified it as a bolide, with medium confidence and lightning nearby. The one video analysed so far was
    filmed in Medellín${med ? `, ${med.km} km away` : ''}: a handheld phone video that replays the moment in cuts. Muse judged it
    usable, but nothing in view can be located on a map and the filming spot is unknown, so the code cannot orient it. Security
    and dashcam clips from Bogotá and Medellín, reposted on 1 August 2025, have not been analysed yet. With fewer than two oriented
    cameras there is no trajectory, and the agent says so instead of guessing${d.run && d.run.block && d.run.block.request ? `: it
    asked for videos from ${esc((d.run.block.request.towns || []).join(', '))}, and the run stays blocked until they arrive` : ''}.</p>
    <p class="big">Phones in the towns marked in blue would have seen the flash 10° to 60° above the horizon. Two of those videos,
    from different sides, would give its path, its speed, and whether it was a meteor or a re-entering satellite.</p>`;
}

function compareOpen(d) {
  const rows = d.towns.filter(t => t.sees_it_high).slice(0, 9).map(t => `<tr><td>${esc(t.city)}</td><td class="r num">${t.km}</td>
    <td class="r">${abbr(t.look_az_deg)} <span class="num">${Math.round(t.look_az_deg)}°</span></td>
    <td class="r num">${span(t.el_at_40km_deg, t.el_at_80km_deg, 0)}°</td></tr>`).join('');
  const seen = d.witness.map(w => `<li><b>${esc(w.site)}</b>: ${esc(w.status)}</li>`).join('');
  return `<h2>Where a video would close the case</h2>
    <table><thead><tr><th>Town</th><th class="r">km away</th><th class="r">Look toward</th><th class="r">Up in the sky</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="note" style="margin-top:8px">Height above the horizon if the flash was 40–80 km up; the satellite gives the place, not the height.</p>
    <h2 style="margin-top:16px">What the witnesses left</h2><ul class="method">${seen}</ul>`;
}

function drawChart(el, d) {
  const series = d.solution.clips.map((id, k) => {
    const s = d.stations.find(x => x.id === id);
    return {name: s.site, color: SERIES[k], pts: s.track, speed: s.speed_kms};
  });
  const W = 360, H = 218, L = 30, R = 10, T = 10, B = 32;
  // the axis runs past the constant-speed solution: the late points fall behind it as the fireball slows
  const tmax = Math.ceil(Math.max(d.solution.times[d.solution.times.length - 1], ...series.map(s => s.pts[s.pts.length - 1][0]))), hmax = 100;
  const x = t => L + (t / tmax) * (W - L - R), y = h => T + (1 - h / hmax) * (H - T - B);
  const model = d.solution.times.map((t, i) => [t, d.solution.path[i][2] / 1000]);
  const pts = p => p.map(([t, h]) => `${x(t).toFixed(1)},${y(h).toFixed(1)}`).join(' ');
  const ticksX = Array.from({length: Math.floor(tmax / 2) + 1}, (_, i) => i * 2);
  const lastOf = s => s.pts[s.pts.length - 1];
  el.innerHTML = `<h2>Height over time, as each camera saw it</h2>
    <div class="legend-row">${series.map(s => `<span><span class="dot" style="background:${rgb(s.color)}"></span>${esc(s.name)}</span>`).join('')}
      <span><span class="line"></span>Solution</span></div>
    <figure>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Height of the fireball against time for each camera, with the solved path">
        ${[0, 20, 40, 60, 80, 100].map(h => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(h)}" y2="${y(h)}"/>
          <text class="tick" x="${L - 6}" y="${y(h) + 3.5}" text-anchor="end">${h}</text>`).join('')}
        ${ticksX.map(t => `<text class="tick" x="${x(t)}" y="${H - B + 14}" text-anchor="middle">${t}</text>`).join('')}
        <text class="axis-title" x="${L}" y="${H - 2}">seconds, each camera on its own clock</text>
        <text class="axis-title" x="${L + 4}" y="${T + 12}">km up</text>
        ${series.map(s => `<g fill="${rgb(s.color)}">${s.pts.map(([t, h]) => `<circle cx="${x(t).toFixed(1)}" cy="${y(h).toFixed(1)}" r="1.8"/>`).join('')}</g>`).join('')}
        <polyline class="model" style="stroke:${rgb(NIGHT)};stroke-width:4" points="${pts(model)}"/>
        <polyline class="model" points="${pts(model)}"/>
        ${series.map(s => `<text class="label" x="${x(lastOf(s)[0]) - 6}" y="${y(lastOf(s)[1]) + 15}" text-anchor="end">${esc(s.name)}</text>`).join('')}
        <line class="cross" x1="0" x2="0" y1="${T}" y2="${H - B}" style="display:none"/>
        <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/>
      </svg>
      <div class="chart-tip" hidden></div>
    </figure>
    ${cameraTable(d)}`;

  const svg = el.querySelector('svg'), cross = svg.querySelector('.cross'), tip = el.querySelector('.chart-tip');
  const near = (p, t) => p.reduce((best, q) => (Math.abs(q[0] - t) < Math.abs(best[0] - t) ? q : best), p[0]);
  svg.addEventListener('pointermove', e => {
    const box = svg.getBoundingClientRect(), px = (e.clientX - box.left) * (W / box.width);
    const t = Math.max(0, Math.min(tmax, ((px - L) / (W - L - R)) * tmax));
    cross.setAttribute('x1', x(t)); cross.setAttribute('x2', x(t)); cross.style.display = '';
    const rows = series.map(s => {
      const q = near(s.pts, t);
      return Math.abs(q[0] - t) < 0.25 ? `<div><span class="dot" style="background:${rgb(s.color)}"></span>${esc(s.name)} <span class="num">${fmt(q[1], 1)}</span> km</div>` : '';
    }).join('');
    const m = near(model, t);
    tip.innerHTML = `<div class="num">${fmt(t, 1)} s</div>${rows}<div><span class="line" style="display:inline-block;width:12px;height:2px;background:#e6edf6;margin-right:6px;vertical-align:3px"></span>solution <span class="num">${fmt(m[1], 1)}</span> km</div>`;
    tip.hidden = false;
    const fx = (x(t) / W) * box.width;
    tip.style.left = `${Math.min(fx + 12, box.width - tip.offsetWidth - 2)}px`;
    tip.style.top = '6px';
  });
  svg.addEventListener('pointerleave', () => { cross.style.display = 'none'; tip.hidden = true; });
}

function cameraTable(d) {
  const rows = d.stations.filter(s => s.rays).map(s => {
    const i = d.solution.clips.indexOf(s.id);
    const dot = i >= 0 ? `<span class="dot" style="background:${rgb(SERIES[i])}"></span>` : '<span class="dot dashed"></span>';
    const h0 = s.track[0][1], h1 = s.track[s.track.length - 1][1];
    const drop = d.agent_log.find(x => x.action === 'drop_clip' && x.clip === s.id);
    const how = s.status === 'used' ? s.camera : drop ? `dropped by the agent at step ${drop.step}` : status(s);
    return `<tr><td>${dot}${esc(s.site)}<span class="how">${esc(how)}</span></td>
      <td class="num">${span(h0, h1, 0)} km</td><td class="num">${fmt(s.speed_kms, 2)}</td><td class="num">${fmt(s.miss_deg, 2)}°</td></tr>`;
  }).join('');
  return `<table class="cams" style="margin-top:10px"><thead><tr><th>Oriented camera</th><th class="r">Saw it</th><th class="r">km/s</th>
    <th class="r">Miss</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="note" style="margin-top:8px">Each camera keeps its own clock; speeds use the first 60% of its track, before the fireball
    slows. Miss is the RMS angle between its lines of sight and the plane through the camera and the final path.</p>`;
}

function measuredText(d, m) {
  if (!m) return '';
  const n = id => esc(name(d, id));
  if (m.near_parallel_with) {
    return '. ' + Object.entries(m.near_parallel_with).map(([k, r]) => `Its planes cross ${n(k)}'s at <span class="num">${fmt(r.q_deg_with_it, 1)}°</span>;
      ${n(k)} crosses the other cameras at up to <span class="num">${fmt(r.its_widest_q_deg, 1)}°</span>, it at <span class="num">${fmt(r.this_widest_q_deg, 1)}°</span>`).join('. ');
  }
  if (m.q_deg_with_kept) {
    return `. Its planes cross ${Object.entries(m.q_deg_with_kept).map(([k, q]) => `${n(k)}'s at <span class="num">${fmt(q, 1)}°</span>`).join(' and ')} (all must be under 10°)`;
  }
  if (m.residual_rms_deg_with_and_without) {
    return `. Residual with and without it: ${Object.entries(m.residual_rms_deg_with_and_without).map(([k, [a, b]]) =>
      `${n(k)} <span class="num">${fmt(a, 3)}°</span> against <span class="num">${fmt(b, 3)}°</span>`).join(', ')} (every one must rise by 25% and 0.1°)`;
  }
  return m.note ? `. ${esc(m.note)}` : '';
}

function result(d, s) {
  const r = s.result || {}, n = id => esc(name(d, id));
  if (r.error) return `Tool error: ${esc(r.error)}`;
  switch (s.action) {
    case 'planes': return `Angle between planes: ${r.pairs.map(p => `${n(p.pair[0])}–${n(p.pair[1])} <span class="num">${fmt(p.q_deg, 1)}°</span>`).join(', ')}`;
    case 'solve': return `Heading <span class="num">${fmt(r.azimuth_deg, 1)}°</span>, slope <span class="num">${fmt(r.slope_deg, 1)}°</span>,
      <span class="num">${fmt(r.speed_kms, 2)}</span> km/s; per camera ${Object.entries(r.speed_per_camera || {}).map(([k, v]) => `${n(k)} <span class="num">${fmt(v, 2)}</span>`).join(', ')}`;
    case 'drop_clip': return r.accepted === false
      ? `<b>Refused by the code</b>: ${esc((r.problems || []).join('; '))}${measuredText(d, r.measured)}`
      : r.criterion ? `<b>Dropped ${n(r.dropped)}</b>: ${esc(r.criterion.replace(/_/g, ' '))}, confirmed by the code${measuredText(d, r.measured)}`
        : `Dropped ${n(r.dropped)}: ${esc(r.reason || '')}`;
    case 'track': return `SAM 3.1 found the fireball in <span class="num">${r.detected}</span> of <span class="num">${r.frames}</span> frames`
      + (r.window_s ? ` of the window ${fmt(r.window_s[0], 1)}–${fmt(r.window_s[1], 1)} s` : '');
    case 'finalize': return r.accepted
      ? `<b>Accepted by the code</b>${r.insufficient_geometry ? ': fewer than two oriented cameras, so insufficient geometry is recorded' : '.'}`
      : `<b>Refused by the code</b>: ${esc((r.problems || []).join('; '))}`;
    case 'request_evidence': return r.accepted
      ? `<b>Request recorded</b>; the run stops until a person supplies it (${esc((r.request.towns || []).join(', ') || r.request.kind)}).`
      : `<b>Refused by the code</b>: ${esc((r.problems || []).join('; '))}`;
    case 'check_satellite': return r.detections && r.detections.length
      ? r.detections.map(g => `${esc(g.class || 'Detection')} at ${esc(g.utc)}, ${esc(g.where || `${g.lat}, ${g.lon}`)}, ${fmt(g.duration_s, 2)} s`).join('; ')
      : `No detection. ${esc(r.note || '')}`;
    case 'read_witness': return `${esc(String(r.clip_kind).replace(/_/g, ' '))}${r.camera_moves ? ', camera moving' : ''}${r.multiple_cuts ? ', several cuts' : ''};
      fireball from ${fmt(r.fireball_s[0], 1)} to ${fmt(r.fireball_s[1], 1)} s; ${r.landmarks.length} landmark guesses`;
    case 'calibration': return r.calibrated ? `Oriented (${esc(r.lens)}, ${fmt(r.hfov, 1)}° wide)` : `Not oriented: ${esc(r.why)}`;
    case 'missing_views': return `Best towns: ${r.best_towns.slice(0, 5).map(t => esc(t.split(' (')[0])).join(', ')}`;
    case 'write_report': return r.accepted === false ? `<b>Refused by the code</b>: ${esc((r.problems || []).join('; '))}`
      : r.reports ? `Report written; every figure checked against the tool results: `
      + Object.entries(r.reports).filter(([, v]) => v && v.figures !== undefined).map(([lang, v]) => `${lang} ${v.traced} of ${v.figures}${v.passed ? '' : ' (refused)'}`
        + (v.refused_drafts ? `, after ${v.refused_drafts} refused draft${v.refused_drafts > 1 ? 's' : ''}` : '')).join(', ')
      : 'Wrote the report below.';
    default: return '';
  }
}

function drawLog(el, d) {
  const target = s => (s.clips && s.clips.length ? s.clips : s.clip ? [s.clip] : []).map(id => esc(name(d, id))).join(' + ');
  const run = d.run || {}, label = {awaiting_review: 'waiting for a person to sign the report off', approved: 'report signed off',
    blocked: run.block && run.block.reason === 'missing_evidence' ? 'blocked, waiting for the evidence it asked for' : 'blocked for a person',
    failed: 'failed'}[run.status] || run.status;
  el.innerHTML = `<h2>What the agent did</h2>
    <p class="note">Muse Spark 1.3 chose each of these ${d.agent_log.length} steps by calling a tool and said why; the code ran the tool,
    checked what had to be checked and kept the record. ${d.tried ? 'Hover a solve step to see that solution on the map.' : ''}</p>
    ${run.run_id ? `<p class="note">Run <span class="num">${esc(run.run_id)}</span>: ${esc(label)}${run.history && run.history.length ? ` (${esc(run.history[run.history.length - 1].by || '')})` : ''}.
    Code ${esc((run.git || {}).commit || '')}${(run.git || {}).dirty ? ' with local changes' : ''}, API cost US$ <span class="num">${fmt(run.cost_usd || 0, 2)}</span>.</p>` : ''}
    <ol class="steps">${d.agent_log.map(s => `<li data-step="${s.step}" class="${s.action === 'solve' ? 'solve' : ''}" ${s.action === 'solve' ? 'tabindex="0"' : ''}>
      <span class="action">${esc(s.action)}</span><span class="clips">${target(s)}</span>
      <div class="why">${esc(s.why)}</div><div class="result">${result(d, s)}</div></li>`).join('')}</ol>`;
  el.querySelectorAll('li.solve').forEach(li => {
    const on = () => { state.highlight = Number(li.dataset.step); li.classList.add('on'); redraw(); };
    const off = () => { state.highlight = null; li.classList.remove('on'); redraw(); };
    li.addEventListener('mouseenter', on);
    li.addEventListener('mouseleave', off);
    li.addEventListener('focus', on);
    li.addEventListener('blur', off);
  });
}

function md(src) {
  const inline = s => s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  return esc(src).split(/\n{2,}/).map(block => {
    const lines = block.trim().split('\n').map(l => l.replace(/^#+\s*/, ''));
    if (lines.every(l => /^\s*[-*] /.test(l))) return `<ul>${lines.map(l => `<li>${inline(l.replace(/^\s*[-*] /, ''))}</li>`).join('')}</ul>`;
    return `<p>${inline(lines.join('<br>'))}</p>`;
  }).join('');
}

function drawLegend(d) {
  const toggle = (key, sw, label) => `<label><input type="checkbox" data-key="${key}" ${state.show[key] ? 'checked' : ''}>
    <span class="sw ${sw}"></span><span>${label}</span></label>`;
  if (d.solution) {
    const used = d.solution.clips.map(id => d.stations.find(s => s.id === id));
    const dropped = d.stations.filter(s => s.status === 'dropped').map(s => esc(s.site));
    $('#legend').innerHTML = `<details ${narrow.matches ? '' : 'open'}><summary>Map key</summary>
      <div class="key"><span class="sw glow"></span>Trajectory found by the agent</div>
      ${toggle('sight', '" style="border-top-color:' + rgb(SERIES[0]), `Lines of sight from ${used.map((s, k) => `<span class="dot" style="background:${rgb(SERIES[k])};margin:0 3px 0 0"></span>${esc(s.site)}`).join(' and ')}${dropped.length ? `; ${dropped.join(', ')} dropped, dashed` : ''}`)}
      ${d.montecarlo ? toggle('mc', 'faint', `Monte Carlo, ${d.montecarlo.draws} draws`) : ''}
      ${toggle('published', 'dash" style="border-top-color:' + rgb(PUBLISHED), 'Published path, CBET 3423')}</details>`;
  } else {
    $('#legend').innerHTML = `<details ${narrow.matches ? '' : 'open'}><summary>Map key</summary>
      <div class="key"><span class="sw box"></span>GOES-19 flash and its extent</div>
      <div class="key"><span class="sw dot" style="background:${rgb(SERIES[0])}"></span>Towns that would see it 10–60° up</div>
      <div class="key"><span class="sw dot" style="background:${rgb(GRAY)}"></span>Other towns: too low in their sky</div>
      <div class="key"><span class="sw dash" style="border-top-color:${rgb(GRAY)}"></span>Medellín video, cannot be oriented</div></details>`;
  }
  $('#legend').querySelectorAll('input').forEach(i => i.addEventListener('change', () => { state.show[i.dataset.key] = i.checked; redraw(); }));
}

// ---- replay ----------------------------------------------------------------------------------------------------------

let raf = 0, started = 0;

function readout() {
  const d = state.data;
  if (!d || !d.solution) return;
  const dur = d.solution.times[d.solution.times.length - 1];
  $('#readout').textContent = state.t === null ? `${fmt(dur, 1)} s of flight, in real time`
    : `t ${fmt(state.t, 1)} s · ${fmt(headAt(d, state.t)[2] / 1000, 0)} km up`;
}

function play() {
  const d = state.data;
  if (!d || !d.solution) return;
  if (state.playing) return stop(false);
  const dur = d.solution.times[d.solution.times.length - 1];
  const from = state.t !== null && state.t < dur ? state.t : 0;
  state.playing = true;
  $('#play').textContent = 'Pause';
  started = performance.now() - from * 1000;
  map.easeTo({bearing: map.getBearing() + 16 * (1 - from / dur), duration: (dur - from) * 1000 + 1200, easing: k => k});
  const tick = now => {
    state.t = Math.min((now - started) / 1000, dur);
    readout();
    redraw();
    if (!state.playing) return;
    if (state.t < dur) raf = requestAnimationFrame(tick);
    else setTimeout(() => stop(true), 900);
  };
  raf = requestAnimationFrame(tick);
}

function stop(finished) {
  cancelAnimationFrame(raf);
  if (state.playing) map.stop();
  state.playing = false;
  if (finished) state.t = null;
  $('#play').textContent = state.t === null ? 'Replay' : 'Resume';
  readout();
  redraw();
}

// ---- cases -----------------------------------------------------------------------------------------------------------

let firstView = true;

async function show(id) {
  const known = cases.find(c => c.id === id) || cases[0];
  if (state.playing) stop(false);
  state.t = null;
  state.highlight = null;
  const d = cache[known.id] || (cache[known.id] = await (await fetch(`data/${known.id}.json`)).json());
  state.data = d;
  document.querySelectorAll('#cases button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.id === known.id)));
  $('#lead').innerHTML = d.solution ? leadSolved(d) : leadOpen(d);
  $('#compare').innerHTML = d.solution ? compareSolved(d) : compareOpen(d);
  if (d.solution) drawChart($('#chart'), d); else $('#chart').innerHTML = '';
  drawLog($('#log'), d);
  $('#report').innerHTML = (d.report_en ? `<details><summary>The agent's report, as Muse Spark wrote it</summary>
    <div class="report">${md(d.report_en)}</div></details>` : '') + `<details><summary>${d.report_en ? 'El mismo reporte en español' : "The agent's report, as Muse Spark wrote it (Spanish)"}</summary>
    <div class="report">${md(d.report_es)}</div></details>`;
  $('#hud').hidden = !d.solution;
  $('#play').textContent = 'Replay';
  drawLegend(d);
  readout();
  const view = {...d.view, zoom: d.view.zoom - (narrow.matches ? 1.3 : 0), padding: padding()};
  if (firstView) map.jumpTo(view); else map.flyTo({...view, duration: 2200, essential: true});
  firstView = false;
  redraw();
}

addEventListener('keydown', e => {
  if (e.target.closest('input, textarea, button')) return;
  if (e.code === 'Space') { e.preventDefault(); play(); }
  if (e.key === 'h') { document.body.classList.toggle('bare'); map.easeTo({padding: padding(), duration: 600}); }
});

(async function init() {
  cases = await (await fetch('data/cases.json')).json();
  $('#cases').innerHTML = cases.map(c => `<button type="button" data-id="${c.id}" aria-pressed="false">${esc(c.title)}<small>${esc(c.role)}</small></button>`).join('');
  $('#cases').querySelectorAll('button').forEach(b => b.addEventListener('click', () => { location.hash = b.dataset.id; }));
  $('#play').addEventListener('click', play);
  addEventListener('hashchange', () => show(location.hash.slice(1)));
  try { await document.fonts.load(`500 12px ${FONT}`); } catch (e) { /* labels fall back to the system font */ }
  show(location.hash.slice(1));
})();
