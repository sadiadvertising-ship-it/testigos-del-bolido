/* Testigos del Bólido: a static viewer for the cases in data/ (written by scripts/export_web.py).
   MapLibre draws the basemap (OpenFreeMap, no key); deck.gl draws the 3D geometry on top. */
'use strict';

// Camera colours in fixed order (blue, aqua, then orange), checked for colour-blind separation on the panel surface.
const SERIES = [[57, 135, 229], [25, 158, 112], [217, 89, 38]];
const GRAY = [125, 135, 150];
const INK = [230, 237, 246];
const MUTED = [150, 160, 175];
const FAINT = [112, 123, 140];
const WHITE = [242, 248, 255];
const GLOW = [108, 182, 255];
const ACCENT = [120, 188, 255];  // var(--accent)
const PUBLISHED = [201, 133, 0];  // var(--published): the palette's yellow, which the validator separates from both cameras' hues
const NIGHT = [8, 17, 31];
const FONT = '"IBM Plex Sans", system-ui, sans-serif';
const COMPASS = ['north', 'north-north-east', 'north-east', 'east-north-east', 'east', 'east-south-east', 'south-east',
  'south-south-east', 'south', 'south-south-west', 'south-west', 'west-south-west', 'west', 'west-north-west', 'north-west',
  'north-north-west'];

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November',
  'December'];

const $ = s => document.querySelector(s);
const rgb = c => `rgb(${c.join(',')})`;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = (x, d = 1) => Number(x).toFixed(d);
const span = (a, b, d = 1) => `${fmt(a, d)}–${fmt(b, d)}`;
const between = (a, b, d = 1) => `${fmt(a, d)} to ${fmt(b, d)}`;  // a range inside a sentence
const list = xs => (xs.length > 1 ? `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}` : xs.join(''));  // 'A, B and C'
const two = n => String(n).padStart(2, '0');
// A time as git or a run records it, in its own offset: {day: '26 October', time: '20:33'}.
const localTime = iso => { const m = /^\d{4}-(\d\d)-(\d\d)T(\d\d):(\d\d)/.exec(iso || ''); return m && {day: `${+m[2]} ${MONTHS[m[1] - 1]}`, time: `${m[3]}:${m[4]}`}; };
const utcTime = iso => { const t = new Date(iso); return `${two(t.getUTCHours())}:${two(t.getUTCMinutes())} UTC on ${t.getUTCDate()} ${MONTHS[t.getUTCMonth()]}`; };
const isoDay = iso => { const [y, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };  // '2025-08-01': '1 August 2025'
const modelName = id => String(id || 'muse-spark').split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ');  // 'Muse Spark 1.3'
const dir = az => COMPASS[Math.round((((az % 360) + 360) % 360) / 22.5) % 16];
const abbr = az => dir(az).split('-').map(w => w[0].toUpperCase()).join('');
const latlon = ([lon, lat]) => `${fmt(Math.abs(lat), 2)}° ${lat >= 0 ? 'N' : 'S'}, ${fmt(Math.abs(lon), 2)}° ${lon >= 0 ? 'E' : 'W'}`;
const dash = new deck.PathStyleExtension({dash: true});

// stage: in video mode, how much of the Colombia map shows (keys 1 to 3); 0 shows everything, as it always does outside it.
// spots: where each town label of the open case sits, by town (placeTowns).
const state = {data: null, t: null, playing: false, highlight: null, stage: 0, spots: new Map(), show: {sight: true, mc: true, published: true}};
const cache = {};
let cases = [];

function km([lon1, lat1], [lon2, lat2]) {
  const r = Math.PI / 180;
  const a = Math.sin((lat2 - lat1) * r / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin((lon2 - lon1) * r / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}

// ---- map -------------------------------------------------------------------------------------------------------------

const params = new URLSearchParams(location.search);
const bare = params.get('panel') === '0';  // ?panel=0 hides the panel and the map key, for screen recordings
const video = params.get('video') === '1';  // ?video=1: larger type and a wider trajectory, for recording at 1920x1080
// The Chelyabinsk replay runs once on load, unless the viewer prefers reduced motion or the URL says ?replay=0.
const autoplay = params.get('replay') !== '0' && !matchMedia('(prefers-reduced-motion: reduce)').matches;
document.body.classList.toggle('bare', bare);
document.body.classList.toggle('video', video);
// The witness video's window (d.clip): off in ?panel=0 (the README's GIF) and, unless &clip=1, in ?video=1 (the demo's
// screen recording), so neither carries witness footage; ?clip=0 turns it off anywhere.
const clipOn = !bare && (video ? params.get('clip') === '1' : params.get('clip') !== '0');
const narrow = matchMedia('(max-width: 760px)');
const padding = () => (document.body.classList.contains('bare') ? {top: 0, bottom: 0, left: 0, right: 0}
  : narrow.matches ? {top: 0, bottom: innerHeight * 0.5, left: 0, right: 0}
    : {top: 0, bottom: 0, left: $('#panel').getBoundingClientRect().right, right: 0});

// Sizes on the map, in pixels.
const LOOK = video
  ? {text: 17, pad: [6, 3, 6, 3], gap: 12, heights: 24, path: 5, pathColor: [255, 255, 255], glow: 130, glowWidth: 18, published: 3, dot: 1.35}
  : {text: 12, pad: [4, 2, 4, 2], gap: 9, heights: 12, path: 3, pathColor: WHITE, glow: 90, glowWidth: 12, published: 2, dot: 1};

const map = new maplibregl.Map({
  container: 'map', style: 'https://tiles.openfreemap.org/styles/dark', center: [62.6, 55.0], zoom: 5, pitch: 55,
  maxPitch: 80, attributionControl: {compact: true},
});
map.addControl(new maplibregl.NavigationControl({visualizePitch: true}), 'top-right');
map.on('error', e => console.warn('map:', e.error && e.error.message));
const overlay = new deck.MapboxOverlay({interleaved: false, layers: [], getTooltip: tooltip});
map.addControl(overlay);

const placeFilters = {};  // the basemap's own filters on its place names
// Each place layer has an invisible copy that draws every name, overlaps included, so the map can say which names would
// show under the case's labels (namesUnderLabels).
const PROBE = '-probe';

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
    placeFilters[l.id] = l.filter || true;
  }
  for (const l of map.getStyle().layers.filter(x => x.id in placeFilters)) {
    map.addLayer({...l, id: l.id + PROBE, paint: {'text-opacity': 0, 'icon-opacity': 0}, layout: {...l.layout,
      'text-allow-overlap': true, 'text-ignore-placement': true, 'icon-allow-overlap': true, 'icon-ignore-placement': true}});
  }
  quietNames();
  try {
    map.setSky({'sky-color': '#02060d', 'horizon-color': '#132944', 'fog-color': '#08111f', 'sky-horizon-blend': 0.6,
      'horizon-fog-blend': 0.7, 'fog-ground-blend': 0.8});
  } catch (e) { /* the map works without a sky */ }
});

// The basemap leaves out the places the case labels itself, so no name shows twice, and the names that would show under
// one of the case's labels or dots, where only a piece of them would show.
let quieted = '', under = [];
const placeName = ['coalesce', ['get', 'name:latin'], ['get', 'name']];
function quietNames() {
  const d = state.data;
  const own = !d ? [] : d.solution ? d.stations.map(s => s.site)
    : d.towns.filter(t => state.spots.has(t.city) && townShows(d, t)).map(t => t.city);
  const names = [...new Set([...own, ...under])].sort(), applied = JSON.stringify([names, Object.keys(placeFilters)]);
  if (applied === quieted) return;
  quieted = applied;
  for (const [id, filter] of Object.entries(placeFilters)) {
    map.setFilter(id, names.length ? ['all', filter, ['!', ['in', placeName, ['literal', names]]]] : filter);
  }
}

// Once the map has drawn: the basemap names whose box, on the invisible copies, meets a label or a dot of the case.
function namesUnderLabels() {
  const d = state.data, layers = Object.keys(placeFilters).map(id => id + PROBE).filter(id => map.getLayer(id));
  if (!d || !layers.length) return;
  const found = new Set();
  for (const [b, own] of caseBoxes(d, viewport(currentView()))) {
    for (const f of map.queryRenderedFeatures([[b[0], b[1]], [b[2], b[3]]], {layers})) {
      const n = f.properties['name:latin'] || f.properties.name;
      if (n !== own) found.add(n);
    }
  }
  under = [...found];
  quietNames();
}
map.on('idle', namesUnderLabels);

const ON_TOP = {parameters: {depthCompare: 'always', depthWriteEnabled: false}};  // labels and markers stay readable over the 3D lines
// Translucent planes and the Monte Carlo lines hide nothing behind them: the lines of sight lie inside their camera's
// plane and would flicker out, and the band of Monte Carlo lines would cover the paths drawn along it. (deck.gl 9 takes
// luma.gl's WebGPU-style parameter names: depthWriteEnabled.)
const SHEER = {parameters: {depthWriteEnabled: false}};

// How each kind of label is drawn: text size and weight, line height, where it sits from its point, background padding.
// The same numbers give the labels' boxes on screen (labelBox).
const TAG = () => ({size: LOOK.text, weight: 500, lineHeight: 1, anchor: 'start', offset: [LOOK.gap, 0], pad: LOOK.pad});
const TOWN_TAG = () => ({...TAG(), lineHeight: LINE});
const HEIGHT_TAG = () => ({...TAG(), size: LOOK.heights, weight: video ? 600 : 500, anchor: 'middle', offset: [0, -Math.round(LOOK.heights * 1.35)]});
// CBET's label sits at its path's east end, clear of the crossing of the lines of sight: below and to the right, under
// the height label. Where that would run off the map (always on a phone), it sits higher up and left of the height
// label, above both paths and the camera names beside them.
function publishedTag(d) {
  const tag = {...TAG(), size: LOOK.text - 0.5, pad: LOOK.pad.map(v => v + 1)}, p = publishedEnd(d);
  const right = {...tag, anchor: 'start', offset: [LOOK.gap, LOOK.heights + LOOK.gap]};
  const left = {...tag, anchor: 'end', offset: [-(LOOK.gap + 2.5 * LOOK.heights), -2 * LOOK.heights]};
  if (narrow.matches) return left;
  const vp = viewport(currentView()), {xy, scale} = projector(vp);
  return labelBox(xy(p, p[2]), scale(p, p[2]), publishedText(d), right)[2] < vp.width - 6 ? right : left;
}

function text(id, data, getPosition, getText, tag = TAG(), extra = {}) {
  return new deck.TextLayer({
    id, data, getPosition, getText, getSize: tag.size, sizeUnits: 'pixels', sizeMinPixels: tag.size - 1, sizeMaxPixels: tag.size + 1,
    fontFamily: FONT, fontWeight: tag.weight, lineHeight: tag.lineHeight, characterSet: 'auto',
    background: true, getBackgroundColor: [...NIGHT, 215], backgroundPadding: tag.pad, getColor: [...INK, 255],
    getTextAnchor: tag.anchor, getAlignmentBaseline: 'center', getPixelOffset: tag.offset, billboard: true, ...ON_TOP, ...extra,
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
  if (state.show.mc && d.montecarlo && !live) {  // faint: with no depth written, every line adds to the band where they overlap
    layers.push(new deck.PathLayer({id: 'mc', data: d.montecarlo.lines, getPath: l => l, getColor: [...GLOW, 8], getWidth: 1,
      widthUnits: 'pixels', billboard: true, ...SHEER}));
  }
  if (state.show.sight) {
    layers.push(new deck.SolidPolygonLayer({id: 'planes', data: planes, getPolygon: p => p.polygon, _full3d: true,
      getFillColor: p => [...camColor(d, p.s), p.s.status === 'used' ? 24 : 10], ...SHEER}));
    layers.push(new deck.PathLayer({id: 'rays', data: rays, getPath: r => r.path, widthUnits: 'pixels', billboard: true,
      getColor: r => [...camColor(d, r.s), r.s.status === 'used' ? 115 : 95], getWidth: 1,
      getDashArray: r => (r.s.status === 'used' ? [0, 0] : [4, 3]), extensions: [dash]}));
  }
  layers.push(new deck.PathLayer({id: 'ground-track', data: [sol.path.map(p => [p[0], p[1], 0])], getPath: p => p,
    getColor: [...GLOW, 110], getWidth: 1.5, widthUnits: 'pixels', getDashArray: [3, 3], extensions: [dash]}));
  layers.push(new deck.LineLayer({id: 'curtain', data: sol.path.filter((_, i) => i % 4 === 0), getSourcePosition: p => p,
    getTargetPosition: p => [p[0], p[1], 0], getColor: [...GLOW, 38], getWidth: 1}));
  // The paths draw over the planes of sight: the solved line is where those planes meet, and they would hide it.
  layers.push(new deck.PathLayer({id: 'glow', data: [flown], getPath: p => p, getColor: [...GLOW, LOOK.glow], getWidth: LOOK.glowWidth,
    widthUnits: 'pixels', billboard: true, capRounded: true, jointRounded: true, ...ON_TOP}));
  layers.push(new deck.PathLayer({id: 'path', data: [flown], getPath: p => p, getColor: [...LOOK.pathColor, 255], getWidth: LOOK.path,
    widthUnits: 'pixels', billboard: true, capRounded: true, jointRounded: true, ...ON_TOP}));
  if (state.show.published && d.published && !live) {
    layers.push(new deck.PathLayer({id: 'published', data: [d.published.path], getPath: p => p, getColor: [...PUBLISHED, 235],
      getWidth: LOOK.published, widthUnits: 'pixels', billboard: true, getDashArray: [6, 4], extensions: [dash], ...ON_TOP}));
  }
  if (tried) {
    layers.push(new deck.PathLayer({id: 'tried', data: [tried.path], getPath: p => p, getColor: [255, 255, 255, 170], getWidth: 2,
      widthUnits: 'pixels', billboard: true, getDashArray: [2, 3], extensions: [dash], ...ON_TOP}));
  }
  if (live) {
    layers.push(new deck.ScatterplotLayer({id: 'head', data: [headAt(d, t)], getPosition: p => p, getRadius: 6 * LOOK.dot,
      radiusUnits: 'pixels', getFillColor: [255, 255, 255], stroked: true, getLineColor: [...GLOW, 150], getLineWidth: 7 * LOOK.dot,
      lineWidthUnits: 'pixels', billboard: true, ...ON_TOP}));
  }
  layers.push(new deck.ScatterplotLayer({id: 'cams', data: d.stations, pickable: true, getPosition: s => [...s.lonlat, 0],
    getRadius: s => (s.rays ? 5.5 : 4) * LOOK.dot, radiusUnits: 'pixels', radiusMinPixels: 3.5 * LOOK.dot, radiusMaxPixels: 6 * LOOK.dot,
    getFillColor: s => (s.rays ? [...camColor(d, s), 255] : [...NIGHT, 255]),
    stroked: true, getLineColor: s => (s.rays ? [...NIGHT, 255] : [...GRAY, 255]), getLineWidth: 1.5, lineWidthUnits: 'pixels',
    billboard: true, ...ON_TOP}));
  const side = camSides(d), sides = JSON.stringify([...side.values()].map(t => t.anchor));
  layers.push(text('cam-labels', d.stations, s => [...s.lonlat, 0], s => s.site, TAG(),
    {getColor: s => (s.rays ? [...INK, 255] : [...MUTED, 255]), getTextAnchor: s => side.get(s.id).anchor,
      getPixelOffset: s => side.get(s.id).offset, updateTriggers: {getColor: d.id, getTextAnchor: sides, getPixelOffset: sides}}));
  layers.push(text('heights', [first, last], p => p, heightText, HEIGHT_TAG()));
  if (state.show.published && d.published && !live) {  // its border carries the path's colour
    layers.push(text('published-label', [publishedEnd(d)], p => p, () => publishedText(d), publishedTag(d),
      {getBorderColor: [...PUBLISHED, 255], getBorderWidth: 1}));
  }
  return layers;
}

const heightText = p => `${fmt(p[2] / 1000, 0)} km`;
const cbet = d => d.published.values[0].who.split(':')[0];  // 'CBET 3423', as the published values name it
const publishedText = d => `${cbet(d)}, published`;
const publishedEnd = d => d.published.path.reduce((a, b) => (b[0] > a[0] ? b : a));  // the published path's east end

// Video mode, Colombia: keys 1 to 3 build the map up for a recording (1 the GOES-19 flash, 2 the Medellín line, 3 the town
// wedges); 0 or Escape shows everything. A layer marked n shows from stage n on; n = 4 marks what only "everything" shows.
const shows = n => state.stage === 0 || state.stage >= n;

const asked = d => new Set(d.run?.block?.request?.towns || []);  // the towns the agent asked for videos from
const filmedSites = d => d.witness.filter(w => /calibrat|orient/.test(w.status));  // witness videos with a camera site
const townShows = (d, t) => (filmedSites(d).some(w => w.site === t.city) ? shows(2) : t.sees_it_high ? shows(3) : shows(4));
const townRadius = (d, t) => (asked(d).has(t.city) ? 6 : 4.5) * LOOK.dot;
// On a phone the dots stand too close for more than a name: the table under the map gives the nearest towns' height in
// the sky and a tap on a dot gives any town's. The towns the agent asked for still say why they are bright.
const townLabel = (d, t) => (narrow.matches || !t.sees_it_high ? t.city : `${t.city}  ${span(t.el_at_40km_deg, t.el_at_80km_deg, 0)}° up`)
  + (!asked(d).has(t.city) ? '' : narrow.matches ? '\nrequested' : '\nrequested by the agent');
const LINE = 1.15;  // line height of the town labels; a requested town's runs to two lines
const satellite = d => (/GOES-\d+/.exec(d.satellite.source) || ['the satellite'])[0];  // 'GOES-19'
const glmText = d => `${satellite(d)} flash`;
const COLUMN_TOP = 100000;  // the flash's column on the map rises to 100 km
const skyKm = d => d.sky.heights_km;  // the heights the town geometry assumes for the flash

function openLayers(d) {
  const g = d.satellite, [lon, lat] = g.lonlat, [dlon, dlat] = g.extent_deg, [h0, h1] = skyKm(d).map(h => h * 1000);
  const box = [[lon - dlon / 2, lat - dlat / 2], [lon + dlon / 2, lat - dlat / 2], [lon + dlon / 2, lat + dlat / 2], [lon - dlon / 2, lat + dlat / 2]];
  const wanted = asked(d), witness = shows(2) ? filmedSites(d) : [];
  const towns = d.towns.filter(t => townShows(d, t));
  const high = towns.filter(t => t.sees_it_high);
  const named = towns.filter(t => state.spots.has(t.city));
  const tone = t => (wanted.has(t.city) ? 'asked' : t.sees_it_high ? 'high' : 'low');
  const fill = {asked: [...ACCENT, 255], high: [...SERIES[0], 160], low: [...GRAY, 170]};
  const ink = {asked: [...INK, 255], high: [...MUTED, 255], low: [...FAINT, 255]};
  return [
    new deck.PolygonLayer({id: 'glm-box', data: [box], getPolygon: b => b, getFillColor: [...SERIES[1], 45], getLineColor: [...SERIES[1], 210],
      getLineWidth: 1, lineWidthUnits: 'pixels'}),
    new deck.SolidPolygonLayer({id: 'sight', data: high, _full3d: true, getFillColor: t => [...SERIES[0], wanted.has(t.city) ? 34 : 14],
      getPolygon: t => [[...t.lonlat, 0], [lon, lat, h0], [lon, lat, h1]], ...SHEER}),
    new deck.PathLayer({id: 'sight-edges', data: high, getPath: t => [[lon, lat, h0], [...t.lonlat, 0], [lon, lat, h1]],
      getColor: t => (wanted.has(t.city) ? [...ACCENT, 170] : [...SERIES[0], 85]), getWidth: t => (wanted.has(t.city) ? 1.5 : 1),
      widthUnits: 'pixels', billboard: true}),
    new deck.PathLayer({id: 'witness', data: witness, getPath: w => [[...w.lonlat, 0], [lon, lat, (h0 + h1) / 2]], getColor: [...GRAY, 200],
      getWidth: 1.5 * LOOK.dot, widthUnits: 'pixels', billboard: true, getDashArray: [4, 3], extensions: [dash]}),
    new deck.LineLayer({id: 'column', data: [[lon, lat]], getSourcePosition: p => [...p, 0], getTargetPosition: p => [...p, COLUMN_TOP],
      getColor: [...SERIES[1], 120], getWidth: 1.5 * LOOK.dot, ...ON_TOP}),
    new deck.LineLayer({id: 'column-band', data: [[lon, lat]], getSourcePosition: p => [...p, h0], getTargetPosition: p => [...p, h1],
      getColor: [...SERIES[1], 255], getWidth: 4 * LOOK.dot, ...ON_TOP}),
    new deck.ScatterplotLayer({id: 'glm', data: [g], pickable: true, getPosition: () => [lon, lat, 0], getRadius: 6 * LOOK.dot,
      radiusUnits: 'pixels', getFillColor: [255, 255, 255], stroked: true, getLineColor: [...SERIES[1], 230], getLineWidth: 4 * LOOK.dot,
      lineWidthUnits: 'pixels', billboard: true, ...ON_TOP}),
    new deck.ScatterplotLayer({id: 'towns', data: towns, pickable: true, getPosition: t => [...t.lonlat, 0], getRadius: t => townRadius(d, t),
      radiusUnits: 'pixels', getFillColor: t => fill[tone(t)], stroked: true, getLineColor: t => (wanted.has(t.city) ? [...INK, 255] : [...NIGHT, 255]),
      getLineWidth: 1.5, lineWidthUnits: 'pixels', billboard: true, ...ON_TOP}),
    text('town-labels', named, t => [...t.lonlat, 0], t => townLabel(d, t), TOWN_TAG(), {getColor: t => ink[tone(t)],
      getTextAnchor: t => state.spots.get(t.city).anchor, getPixelOffset: t => state.spots.get(t.city).offset}),
    text('glm-label', [g], () => [lon, lat, COLUMN_TOP], () => glmText(d), TAG()),
  ];
}

// ---- labels on the map -----------------------------------------------------------------------------------------------

const ruler = document.createElement('canvas').getContext('2d');

function viewport(view) {  // the map's projection for a camera, reached or not
  const c = map.getCanvas();
  return new deck.WebMercatorViewport({width: c.clientWidth, height: c.clientHeight, longitude: view.center[0], latitude: view.center[1],
    zoom: view.zoom, pitch: view.pitch, bearing: view.bearing, padding: view.padding});
}

const currentView = () => ({center: map.getCenter().toArray(), zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing(),
  padding: map.getPadding()});

// Where a point falls on screen, and how large deck.gl draws a size given in pixels there: labels and dots face the
// camera and shrink with distance, by the focal distance over the point's depth, as the map's own perspective does.
function projector(vp) {
  const m = vp.viewProjectionMatrix;
  return {
    xy: (ll, z = 0) => vp.project([ll[0], ll[1], z]),
    scale: (ll, z = 0) => {
      const p = vp.projectPosition([ll[0], ll[1], z]);
      return vp.focalDistance / (m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15]);
    },
  };
}

// deck.gl lays each row of a label out 1.2 em tall (the row of its font atlas), times the layer's line height.
const ROW = 1.2;

// The screen box a label's background covers, for a label at screen point `at`, drawn at scale `s` as `tag` says.
function labelBox(at, s, label, tag) {
  ruler.font = `${tag.weight} ${tag.size}px ${FONT}`;
  const rows = String(label).split('\n'), w = Math.max(...rows.map(r => ruler.measureText(r).width));
  const h = rows.length * tag.size * tag.lineHeight * ROW;
  const [pl, pt, pr, pb] = tag.pad, [ox, oy] = tag.offset, x = ox + {start: 0, end: -w, middle: -w / 2}[tag.anchor];
  return [at[0] + s * (x - pl), at[1] + s * (oy - h / 2 - pt), at[0] + s * (x + w + pr), at[1] + s * (oy + h / 2 + pb)];
}

// How far a screen point lies outside a box (0 inside it).
const boxGap = (b, c) => Math.hypot(Math.max(b[0] - c[0], 0, c[0] - b[2]), Math.max(b[1] - c[1], 0, c[1] - b[3]));

// A camera's name sits right of its dot, or left of it where the right would cover another camera's dot.
function camSides(d) {
  const {xy, scale} = projector(viewport(currentView()));
  const dots = d.stations.map(s => ({s, at: xy(s.lonlat), k: scale(s.lonlat)}));
  return new Map(dots.map(me => {
    const sides = [TAG(), {...TAG(), anchor: 'end', offset: [-LOOK.gap, 0]}];
    const free = sides.find(tag => {
      const b = labelBox(me.at, me.k, me.s.site, tag);
      return dots.every(o => o === me || boxGap(b, o.at) > 6 * LOOK.dot * o.k);
    });
    return [me.s.id, free || sides[0]];
  }));
}

// Every label and dot of the case now on the map, as screen boxes, each with the basemap name it may leave alone: a dot
// leaves its own town's name, which the basemap writes beside it. A dot counts by its middle only, so that it hides the
// names it cuts into and not those that only touch it.
function caseBoxes(d, vp) {
  const {xy, scale} = projector(vp), box = (p, label, tag) => [labelBox(xy(p, p[2]), scale(p, p[2]), label, tag), null];
  const dot = (ll, r, own) => { const [x, y] = xy(ll), e = 0.6 * r * scale(ll); return [[x - e, y - e, x + e, y + e], own]; };
  if (d.solution) {
    const side = camSides(d), path = d.solution.path, boxes = d.stations.map(s => box([...s.lonlat, 0], s.site, side.get(s.id)));
    boxes.push(...[path[0], path[path.length - 1]].map(p => box(p, heightText(p), HEIGHT_TAG())));
    if (state.show.published && d.published && state.t === null) boxes.push(box(publishedEnd(d), publishedText(d), publishedTag(d)));
    return boxes.concat(d.stations.map(s => dot(s.lonlat, 6 * LOOK.dot, s.site)));
  }
  const towns = d.towns.filter(t => townShows(d, t));
  return [box([...d.satellite.lonlat, COLUMN_TOP], glmText(d), TAG()), dot(d.satellite.lonlat, 8 * LOOK.dot, null),
    ...towns.filter(t => state.spots.has(t.city)).map(t => box([...t.lonlat, 0], townLabel(d, t), {...TOWN_TAG(), ...state.spots.get(t.city)})),
    ...towns.map(t => dot(t.lonlat, townRadius(d, t) + 0.75, t.city.replace(/\s*\(.*\)$/, '')))];  // 'Bogotá (Colina)': Bogotá
}

// Around its dot a label tries the right first, then the left, then a half or a whole height higher or lower on either
// side, then above or below: [anchor, shift up or down, gaps out from the dot, shift sideways in label widths].
const SPOTS = [['start', 0], ['end', 0], ['start', -1], ['start', 1], ['end', -1], ['end', 1], ['middle', -1], ['middle', 1],
  ['start', -2], ['start', 2], ['end', -2], ['end', 2]].map(([anchor, dy]) => [anchor, dy, 1, 0]);
// A label that must show also tries spots above or below its dot moved a little to one side, then farther out, to step
// past a neighbour's dot or a line.
const FAR = [...SPOTS, ...[0.15, -0.15, 0.3, -0.3].flatMap(sx => [['middle', 1, 1, sx], ['middle', -1, 1, sx]]),
  ...[2, 3.5, 5].flatMap(k => [0, -1, 1, -2, 2, -3, 3].flatMap(dy => [['start', dy, k, 0], ['end', dy, k, 0]])),
  ...[-2, 2, -3, 3, -4, 4].map(dy => ['middle', dy, 1, 0])];
const NEAR = 6;  // pixels: another dot should stand twice as far from a label as its own dot, and this much farther still
const BREAK = 100;  // a broken rule weighs more than any number of dots inside that margin

// Where the open case's town labels go in one view. A label must read as the name of its own dot: its own dot is the
// nearest to it, by a clear margin, and it covers no other dot. The labels that must show (the towns the agent asked for
// and the filmed one) are placed together and may sit farther out, but stay on the map, clear of the map key and the zoom
// buttons, wherever a spot there exists: of every combination of their spots, the one that breaks fewest rules, then
// leaves fewest other dots inside the margin. Then every other blue dot, from the nearest out, takes the first spot that
// breaks no rule, keeps the margin and covers no label, line, map key, zoom button or edge of the map. A blue dot with no
// such spot keeps no label. The spots come back with their `cost`: BREAK for each rule the labels that must show break,
// for each requested town left without a label and for the flash or its label out of view, and 1 for each dot inside a
// margin.
function placeTowns(d, view) {
  const vp = viewport(view), {xy, scale} = projector(vp), g = d.satellite.lonlat, [h0, h1] = skyKm(d).map(h => h * 1000);
  const pad = view.padding, edge = [pad.left + 6, pad.top + 6, vp.width - pad.right - 6, vp.height - pad.bottom - 6];
  const wanted = asked(d), filmed = new Set(filmedSites(d).map(w => w.site));
  // the dots on screen, the flash's too, out to where their stroke reaches
  const dots = d.towns.map(t => ({t, at: xy(t.lonlat), s: scale(t.lonlat), r: (townRadius(d, t) + 0.75) * scale(t.lonlat)}));
  const flash = {at: xy(g), r: 8 * LOOK.dot * scale(g)};
  dots.push(flash);
  const lines = [[xy(g), xy(g, COLUMN_TOP), 3], ...filmedSites(d).map(w => [xy(w.lonlat), xy(g, (h0 + h1) / 2), 2.5])];
  const ui = [];  // the map key and the zoom buttons
  for (const el of [document.body.classList.contains('bare') ? null : $('#legend'), $('.maplibregl-ctrl-top-right')]) {
    const r = el && el.getBoundingClientRect();
    if (r && r.width) ui.push([r.left - 6, r.top - 6, r.right + 6, r.bottom + 6]);
  }
  const glm = labelBox(xy(g, COLUMN_TOP), scale(g, COLUMN_TOP), glmText(d), TAG()), placed = [glm, ...ui];
  const gapTo = boxGap, overlaps = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
  const onMap = b => b[0] >= edge[0] && b[1] >= edge[1] && b[2] <= edge[2] && b[3] <= edge[3];
  const inView = b => onMap(b) && !ui.some(u => overlaps(b, u));
  const dotInView = ([x, y]) => x > edge[0] && x < edge[2] && y > edge[1] && y < edge[3];
  const crosses = (b, [p, q, hw]) => {
    const n = Math.ceil(Math.hypot(q[0] - p[0], q[1] - p[1]) / 3);
    for (let i = 0; i <= n; i++) {
      const x = p[0] + ((q[0] - p[0]) * i) / n, y = p[1] + ((q[1] - p[1]) * i) / n;
      if (x > b[0] - hw && x < b[2] + hw && y > b[1] - hw && y < b[3] + hw) return true;
    }
    return false;
  };
  // Each broken rule weighs BREAK: another label under this one, the edge of the map, the flash's column or the witness
  // line under it, and every other dot that the label covers or that stands as near to it as its own dot. A dot only a
  // little farther than its own (within the margin) weighs 1: it still lets the eye pair the label with the wrong dot. The
  // margin keeps a pixel in hand, as drawn edges land on whole pixels.
  const clashes = (me, b) => {
    const own = Math.max(gapTo(b, me.at) - me.r, 0), margin = 2 * own + NEAR * LOOK.dot + 1;
    const near = dots.filter(o => o !== me).map(o => gapTo(b, o.at) - o.r);
    return BREAK * (placed.filter(p => overlaps(b, p)).length + !onMap(b) + lines.filter(l => crosses(b, l)).length
      + near.filter(x => x < Math.max(own, 1)).length) + near.filter(x => x >= Math.max(own, 1) && x < margin).length;
  };
  const tries = (t, spots) => {
    const me = dots.find(o => o.t === t), label = townLabel(d, t), [, pt] = LOOK.pad, tag = TOWN_TAG();
    const h = label.split('\n').length * LOOK.text * LINE * ROW, gap = LOOK.gap + townRadius(d, t) - 4.5 * LOOK.dot;  // clear of a larger dot
    const lift = townRadius(d, t) + 1.75;  // a label above or below starts just clear of the dot's stroke
    const box0 = labelBox([0, 0], 1, label, {...tag, anchor: 'start', offset: [0, 0]}), w = box0[2] - box0[0];
    return spots.map(([anchor, dy, k, sx]) => {
      const offset = [{start: k * gap, end: -k * gap, middle: sx * w}[anchor], dy * (anchor === 'middle' ? lift + h / 2 + pt : h / 2 + pt)];
      const box = labelBox(me.at, me.s, label, {...tag, anchor, offset});
      return {t, anchor, offset, box, cost: clashes(me, box)};
    });
  };
  const spots = new Map(), take = r => { spots.set(r.t.city, {anchor: r.anchor, offset: r.offset}); placed.push(r.box); };
  const must = d.towns.filter(t => (wanted.has(t.city) || filmed.has(t.city)) && dotInView(xy(t.lonlat))).map(t => {
    const all = tries(t, FAR), seen = all.filter(r => inView(r.box));
    return (seen.length ? seen : all).sort((a, b) => a.cost - b.cost).slice(0, 24);
  });
  let best = [], least = Infinity;
  const search = (i, chosen, cost) => {  // branch and bound over the spots of the labels that must show
    if (cost >= least) return;
    if (i === must.length) { best = chosen; least = cost; return; }
    for (const r of must[i]) search(i + 1, [...chosen, r], cost + r.cost + BREAK * chosen.filter(c => overlaps(c.box, r.box)).length);
  };
  search(0, [], 0);
  best.forEach(take);
  for (const t of d.towns.filter(o => o.sees_it_high && !spots.has(o.city)).sort((a, b) => a.km - b.km)) {
    const free = tries(t, SPOTS).find(r => r.cost === 0);
    if (free) take(free);
  }
  spots.cost = least + BREAK * (d.towns.filter(t => wanted.has(t.city) && !spots.has(t.city)).length + !inView(glm) + !dotInView(flash.at));
  return spots;
}

// The view the data gives, unless a label that must show breaks a rule there, as happens where the map area beside the
// panel is narrow (a desktop window under about 1200 px). Then the flash, its label and the requested towns move to the
// middle of the free map area, or a little to either side, and the map steps back a tenth of a zoom level at a time. The
// first view where those labels break no rule and keep their margins wins; failing that, the one where they break fewest.
function fitView(d, view) {
  let best = {v: view, cost: placeTowns(d, view).cost};
  if (best.cost < BREAK) return view;
  for (let k = 0; k <= 15; k++) {
    const middle = centred(d, {...view, zoom: view.zoom - k / 10});
    for (const share of [0, -0.15, 0.15, -0.3, 0.3]) {
      const v = shifted(middle, share), cost = placeTowns(d, v).cost;
      if (!cost) return v;
      if (cost < best.cost) best = {v, cost};
    }
  }
  return best.v;
}

// The view moved so that what it shows moves sideways by a share of the free map area's width.
function shifted(view, share) {
  if (!share) return view;
  const vp = viewport(view), pad = view.padding, width = vp.width - pad.left - pad.right;
  return {...view, center: vp.unproject([(pad.left + vp.width - pad.right) / 2 - share * width, (pad.top + vp.height - pad.bottom) / 2])};
}

// The view moved so that the flash, its label and the requested towns, each with room for its label on either side, stand
// in the middle of the free map area (where the view's centre falls).
function centred(d, view) {
  const g = d.satellite.lonlat, towns = d.towns.filter(t => asked(d).has(t.city));
  for (let i = 0; i < 3; i++) {
    const vp = viewport(view), {xy, scale} = projector(vp), [x, y] = xy(g);
    const boxes = [labelBox(xy(g, COLUMN_TOP), scale(g, COLUMN_TOP), glmText(d), TAG()), [x, y, x, y]];
    for (const t of towns) {
      const at = xy(t.lonlat), b = labelBox(at, scale(t.lonlat), townLabel(d, t), {...TOWN_TAG(), offset: [LOOK.gap, 0]});
      boxes.push([2 * at[0] - b[2], b[1], b[2], b[3]]);  // its label right of its dot, or as far to the left
    }
    const mid = k => (Math.min(...boxes.map(b => b[k])) + Math.max(...boxes.map(b => b[k + 2]))) / 2;
    view = {...view, center: vp.unproject([mid(0), mid(1)])};
  }
  return view;
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
    const [h0, h1] = skyKm(state.data);
    html = `<b>${esc(object.city)}</b><br>${object.km} km from the flash; look ${dir(object.look_az_deg)} (${Math.round(object.look_az_deg)}°)`
      + `<br>${fmt(object.el_at_40km_deg, 0)}° up if it was ${h0} km high, ${fmt(object.el_at_80km_deg, 0)}° at ${h1} km`;
  } else if (layer.id === 'glm') {
    html = `<b>${esc(satellite(state.data))} GLM bolide</b><br>${esc(object.start_utc.replace('T', ' ').replace('Z', ' UTC'))}, ${fmt(object.duration_s, 2)} s`
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

const COUNT = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];
const count = n => COUNT[n] ?? String(n);

function leadSolved(d) {
  const s = d.solution, cat = d.catalogue;
  const [a, b] = s.clips.map(id => d.stations.find(x => x.id === id));
  const oriented = d.stations.filter(x => x.rays).length, dropped = d.stations.filter(x => x.status === 'dropped');
  const top = s.path[0][2] / 1000, low = s.path[s.path.length - 1][2] / 1000;
  return `<p class="when">Validation case: ${esc(d.when)}</p>
    <p>${d.stations.length} witness videos${cat ? `, chosen from the ${esc(cat.name)} of ${esc(d.title.split(' ')[0])} videos
    (${esc(cat.cite)}), which also gives each camera's position` : ''}. In ${oriented} of them, AI annotators measured street lines
    and poles and matched landmarks to OpenStreetMap during development, so those cameras could be oriented; SAM 3.1 tracked the
    fireball in each. The agent took it from there: it compared the cameras' planes of sight, ${d.tried.length === 1
      ? 'solved one combination' : `tried ${count(d.tried.length)} combinations`}${dropped.length ? `, left out
    ${esc(list(dropped.map(x => x.site)))} on a criterion the code measured` : ''},
    and chose <b>${esc(a.site)}</b> and <b>${esc(b.site)}</b>, ${Math.round(km(a.lonlat, b.lonlat))} km apart, whose planes cross at
    ${fmt(s.q_deg, 0)}°. The code re-solved that choice before accepting it.</p>
    <p class="big">Heading <span class="num">${fmt(s.azimuth_deg, 1)}°</span> (${dir(s.azimuth_deg)}), descending at
    <span class="num">${fmt(s.slope_deg, 1)}°</span>, from <span class="num">${fmt(top, 0)}</span> km down to
    <span class="num">${fmt(low, 0)}</span> km${s.seen_for_s ? `; one camera tracked it for <span class="num">${fmt(s.seen_for_s, 1)}</span> s` : ''}.</p>
    <p>${verdictText(d)}</p>
    ${everyday(d, top, low)}`;
}

// Escape speed in plain terms: what nothing that orbits the Earth can exceed when it enters the atmosphere.
const escapeText = e => `nothing that orbits the Earth can enter the atmosphere faster than ${e.escape_kms}&nbsp;km/s, Earth's escape speed
  (from a low orbit, satellites and rocket stages enter at about ${e.orbital_kms}&nbsp;km/s), and anything that orbits the Sun enters faster`;

// The solved case's figures in everyday terms: the stretch the cameras saw beside the distance between two cities, and how
// long the camera that followed it longest took; the flare's height on our fitted line beside a cruising airliner; and the
// speeds the verdict tells apart.
function everyday(d, top, low) {
  const e = d.everyday, s = d.solution, g = d.grade, band = s.speed_band_95_kms;
  if (!e) return '';
  const tracked = x => x.track[x.track.length - 1][0] - x.track[0][0];
  const cam = d.stations.filter(x => s.clips.includes(x.id) && x.track).sort((a, b) => tracked(b) - tracked(a))[0];
  const out = [`The stretch the ${count(s.clips.length)} cameras saw, from ${fmt(top, 0)}&nbsp;km down to ${fmt(low, 0)}&nbsp;km, is
    ${fmt(e.path_km, 0)}&nbsp;km long, about as far as ${esc(e.cities[0])} is from ${esc(e.cities[1])} in a straight line
    (${fmt(e.cities_km, 0)}&nbsp;km)${cam ? `; ${esc(cam.site)}'s camera followed the fireball from ${fmt(cam.track[0][1], 0)}&nbsp;km down to
    ${fmt(cam.track[cam.track.length - 1][1], 0)}&nbsp;km in ${fmt(tracked(cam), 1)}&nbsp;s` : ''}.`];
  if (g && g.our_height_near_flare_km) {
    const h = g.our_height_near_flare_km[0];
    out.push(`${esc(cbet(d))}'s major flare sits ${fmt(h, 0)}&nbsp;km up on our fitted line, about ${count(Math.round(h / e.cruise_km))}
      times as high as an airliner cruising at ${e.cruise_km}&nbsp;km.`);
  }
  const fast = band && band[0] > e.escape_kms;
  out.push(`${escapeText(e).replace(/^n/, 'N')}${fast ? `: even the low end of this fireball's 95% speed range
    (${esc(s.speed_band_source)}), ${fmt(band[0], 1)}&nbsp;km/s, is too fast for space junk` : ''}.`);
  return `<p><b>In everyday terms.</b> ${out.join(' ')}</p>`;
}

// The speed, then the verdict as the code's rule gave it (the rule and the 95% range are recorded with the run).
function verdictText(d) {
  const s = d.solution, mc = d.montecarlo && d.montecarlo.stats, r = s.rule, band = s.speed_band_95_kms;
  const fit = `Speed ${fmt(s.speed_kms, 2)} km/s by the fit${mc ? `; the Monte Carlo puts it at ${fmt(mc.speed.median, 1)} km/s
    (1 sigma ${between(...mc.speed['1sigma'])})` : ''}.`;
  if (!r || !band) return `${fit} The code's verdict: ${esc(s.verdict)}, ${esc(s.verdict_reason)}.`;
  const rule = `The code's rule: natural if the whole 95% speed range lies above ${r.natural_above_kms} km/s (Earth's escape speed
    is ${r.escape_kms} km/s); a re-entering satellite or rocket stage if it lies below ${r.reentry_below_kms} km/s and the passage is
    long (over ${r.long_s} s, or a slope under ${r.shallow_deg}°).`;
  const here = `Here the range runs from ${between(...band)} km/s (${esc(s.speed_band_source)})`;
  const verdict = {natural: `, all above ${r.natural_above_kms} km/s: <b>a natural meteor</b>.`,
    reentry: `, all below ${r.reentry_below_kms} km/s, and the passage is long: <b>a re-entering satellite or rocket stage</b>.`}[s.verdict]
    || `, which settles neither: <b>the verdict is inconclusive</b>.`;
  return `${fit} ${rule} ${here}${verdict}`;
}

// When the grade's criteria were fixed (from the repository's history) and how the run fared on each.
function gradeNote(d) {
  const g = d.grade, c = g.criteria || {}, geo = c.geometric, fit = c.first_camera_fit, speed = c.speed;
  const words = {azimuth: 'heading', slope: 'slope', flare_height: 'flare height', end_point: 'end point', speed: 'speed'};
  const say = keys => {
    const pass = keys.filter(k => g.gate[k]), fail = keys.filter(k => !g.gate[k]);
    if (keys.length === 1) return pass.length ? 'passes' : 'fails';
    if (!fail.length || !pass.length) return `all ${count(keys.length)} ${pass.length ? 'pass' : 'fail'}`;
    return `${list(pass.map(k => words[k]))} ${pass.length > 1 ? 'pass' : 'passes'}, ${list(fail.map(k => words[k]))}
      ${fail.length > 1 ? 'fail' : 'fails'}`;
  };
  const when = (x, after) => {  // 'on 26 October at 20:33', or only the time on the day just named
    const t = localTime(x.at);
    return after && localTime(after.at).day === t.day ? `at ${t.time}` : `on ${t.day} at ${t.time}`;
  };
  const out = [`The agent never saw these published values: a separate script graded the run afterwards, and it meets
    ${esc(g.passed)} criteria.`];
  if (d.calibration_history) {
    out.push(`The camera fits were made while comparing them with ${esc(cbet(d))} (${esc(d.calibration_history)} in the
      repository), so this check is blind for the agent but not for the calibration.`);
  }
  const w = d.montecarlo && d.montecarlo.widened;
  if (w && w.at) {
    out.push(`The Monte Carlo's range for ${esc(w.what)} was widened on ${localTime(w.at).day}, from ${esc(w.from)} to anywhere
      from ${esc(w.to)}, after ${esc(w.after)}.`);
  }
  if (geo && geo.at) {
    out.push(`The ${count(geo.gates.length)} geometric criteria (${list(geo.gates.map(k => words[k]))}) were committed
      ${when(geo)}${fit ? `, before the first camera was calibrated ${when(fit, geo)}` : ''}, and ${say(geo.gates)}.`);
  }
  if (speed && speed.at) {
    out.push(`The speed criterion was added on ${localTime(speed.at).day}, after the fit's ${fmt(d.solution.speed_kms, 2)} km/s was on
      record, and ${say(speed.gates)}.`);
  }
  return out.join(' ');
}

function compareSolved(d) {
  const s = d.solution, mc = d.montecarlo && d.montecarlo.stats, [first, zul] = d.published.values, name = esc(cbet(d));
  const cell = (v, unit = '') => (v === null || v === undefined ? 'not given' : `${fmt(v, 1)}${unit}`);
  // the fit's value, then the Monte Carlo's median and 1 sigma range, each named
  const range = (k, unit) => (mc ? `<span class="range">Monte Carlo ${fmt(mc[k].median, 1)}${unit}</span>
    <span class="range">1σ ${span(...mc[k]['1sigma'])}</span>` : '');
  const row = (label, k, ours, key, unit, d = 1) => `<tr><th scope="row">${label}</th>
    <td class="r ours"><span class="num">${fmt(ours, d)}${unit}</span> <span class="by">by the fit</span>${range(k, unit)}</td>
    <td class="r"><span class="num">${cell(first[key], unit)}</span></td><td class="r"><span class="num">${cell(zul[key], unit)}</span></td></tr>`;
  const notes = [];
  if (mc) {
    const sl = mc.slope, what = {azimuth: 'heading', slope: 'slope', speed: 'speed'}, keys = Object.keys(what);
    const say = (ks, where) => (ks.length ? `${name}'s ${list(ks.map(k => what[k]))} ${ks.length > 1 ? 'are' : 'is'}
      ${where.replace(/range/g, ks.length > 1 ? 'ranges' : 'range')}.` : '');
    notes.push([say(keys.filter(k => mc[k].cbet_within_1sigma), 'inside the Monte Carlo\'s 1 sigma range'),
      say(keys.filter(k => !mc[k].cbet_within_1sigma && mc[k].cbet_within_2sigma), 'inside the Monte Carlo\'s 2 sigma range, not its 1 sigma range'),
      say(keys.filter(k => !mc[k].cbet_within_2sigma), 'outside the Monte Carlo\'s 2 sigma range')].filter(Boolean).join(' '));
    if (!sl.cbet_within_2sigma) {
      notes.push(`Our slope is ${fmt(Math.abs(s.slope_deg - first.slope_deg), 1)}° ${s.slope_deg > first.slope_deg ? 'steeper' : 'shallower'}
        than theirs and outside our 2 sigma range: an error the Monte Carlo does not model.`);
    }
    const flare = d.published.points.find(p => /flare/.test(p.note)), g = d.grade;
    if (flare && g) {  // the fit's values (from the grade) beside the Monte Carlo's medians and ranges
      notes.push(`${name} puts its ${esc(flare.note)} at ${fmt(flare.h_km, 1)} km; on our fitted line that point sits at
        ${fmt(g.our_height_near_flare_km[0], 1)} km (Monte Carlo median ${fmt(mc.flare_h_km.median, 1)} km, 1 sigma
        ${between(...mc.flare_h_km['1sigma'])}). ${name}'s end point lies ${fmt(g.cbet_end_point_off_our_line_km, 1)} km from
        the fitted line (Monte Carlo median ${fmt(mc.end_off_km.median, 1)} km, 1 sigma ${between(...mc.end_off_km['1sigma'])}).`);
    }
    notes.push(`Our speed range is the Monte Carlo's (median ${fmt(mc.speed.median, 1)} km/s): it is the least certain number.`);
  }
  if (d.refereed) {
    const graded = d.grade && d.grade.first_graded_run;
    notes.push(`${name} was a preliminary telegram; refereed solutions published later give ${esc(list(d.refereed.map(r =>
      `${fmt(r.v_kms, 2)} km/s (${r.who})`)))}. That comparison was added after the first graded run${graded ? `
      (${esc(graded.split('-').pop())})` : ''} and does not change the grade.`);
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
    <table class="compare"><thead><tr><th></th><th class="r">This agent</th><th class="r">${name}</th>
    <th class="r">${esc(zul.who.split(',')[0])} et al.</th></tr></thead>
    <tbody>${row('Heading', 'azimuth', s.azimuth_deg, 'azimuth_deg', '°')}${row('Slope', 'slope', s.slope_deg, 'slope_deg', '°')}
    ${row('Speed, km/s', 'speed', s.speed_kms, 'speed_kms', '', 2)}
    <tr class="src"><th scope="row">From</th><td class="r">${s.clips.length} cameras${mc ? `, ${d.montecarlo.draws} Monte Carlo draws` : ''}</td>
    <td class="r">${esc(first.how)}</td><td class="r">${esc(zul.how)}</td></tr></tbody></table>
    <p class="note" style="margin-top:8px">${notes.join(' ')}</p>
    <p class="note">${d.grade ? gradeNote(d) : 'The agent never saw these published values.'}</p>
    <p class="note">${d.published.values.map(v => esc(v.who)).join('. ')}.</p>`;
}

// A re-entry's predicted window against the flash: 'OBJECT C's (07:54 UTC on 31 July, plus or minus 2 h) opens 2.1 h after
// the flash'. hours_between_window_and_flash counts from the window's edge.
function reentryWindow(d, r, flash = 'the flash') {
  const after = new Date(r.predicted_utc) > new Date(d.when_utc);
  return `${esc(r.object)}'s (${utcTime(r.predicted_utc)}, plus or minus ${r.window_h} h) ${after ? 'opens' : 'closed'}
    ${fmt(r.hours_between_window_and_flash, 1)} h ${after ? 'after' : 'before'} ${flash}`;
}

function leadOpen(d) {
  const g = d.satellite, nearest = [...d.towns].sort((a, b) => a.km - b.km)[0], req = d.run?.block?.request;
  const filmed = d.witness.find(w => w.video), town = filmed && d.towns.find(t => t.city === filmed.site);
  const [lo, hi] = d.sky.high_deg, later = d.not_analysed, re = d.reentries;
  const lightning = {isolated: 'no lightning nearby', 'not isolated': 'lightning nearby'}[g.lightning_nearby];
  return `<p class="when">Open case: ${esc(d.when)}</p>
    <p>A green fireball crossed the night sky over north-eastern Colombia. The lightning mapper on the ${esc(satellite(d))} weather
    satellite recorded a ${fmt(g.duration_s, 2)} s flash at <span class="num">${latlon(g.lonlat)}</span>, ${nearest.km} km from
    ${esc(nearest.city)}.</p>
    <p>NASA's analysts classified it as a ${esc(g.classification.toLowerCase())}${g.confidence ? `, with ${esc(g.confidence)} confidence` : ''}${lightning ? `
    and ${lightning}` : ''}.${filmed ? ` The one video analysed so far was filmed in ${esc(filmed.site)}${town ? `, ${town.km} km away` : ''}${filmed.post
    ? ` (${external(filmed.post.url, 'the post on X')})` : ''}: a
    handheld phone video that replays the moment in cuts. Muse judged it usable, but nothing in view can be located on a map and
    the filming spot is unknown, so the code cannot orient it.` : ''}${later ? ` ${esc(later.what)}, posted on ${esc(later.where)}
    by ${esc(later.by)} on ${isoDay(later.on)}, have not been analysed yet.` : ''} With fewer than two oriented cameras there is no
    trajectory, and the agent says so instead of guessing${req ? `: it asked for videos from ${esc(list(req.towns || []))}, and
    the run stays blocked until they arrive` : ''}.</p>
    ${re ? `<p>Was it space junk? ${re.containing_the_flash.length ? `In ${esc(re.database)}, the predicted window of
    ${esc(list(re.containing_the_flash))} includes the flash.` : `No satellite or rocket re-entry in ${esc(re.database)} has a
    predicted window that includes the flash.`}${re.nearest.length ? ` The ${count(re.nearest.length)} windows nearest the flash:
    ${list(re.nearest.map(r => reentryWindow(d, r, 'it')))}.` : ''} Only tracked objects are listed, so the speed still has to
    decide${d.everyday ? `: ${escapeText(d.everyday)}` : ''}.</p>` : ''}
    <p class="big">Phones in the towns marked in blue would have seen the flash ${lo}° to ${hi}° above the horizon. Two of those
    videos, from still cameras on different sides, could give its path and its speed.</p>`;
}

function compareOpen(d) {
  const rows = d.towns.filter(t => t.sees_it_high).slice(0, 9).map(t => `<tr><td>${esc(t.city)}</td><td class="r num">${t.km}</td>
    <td class="r">${abbr(t.look_az_deg)} <span class="num">${Math.round(t.look_az_deg)}°</span></td>
    <td class="r num">${span(t.el_at_40km_deg, t.el_at_80km_deg, 0)}°</td></tr>`).join('');
  const seen = d.witness.map(w => `<li><b>${esc(w.site)}</b>: ${esc(w.status)}${w.post ? `; ${external(w.post.url, esc(w.post.credit))}` : ''}</li>`).join('');
  return `<h2>Where a video would close the case</h2>
    <table><thead><tr><th>Town</th><th class="r">km away</th><th class="r">Look toward</th><th class="r">Up in the sky</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="note" style="margin-top:8px">Height above the horizon if the flash was ${between(...skyKm(d), 0)} km up; the satellite
    gives the place, not the height.</p>
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
    <p class="note" style="margin-top:8px">Each camera keeps its own clock; speeds use the first ${Math.round(d.solution.speed_window * 100)}%
    of its track, before the fireball slows. Miss is the RMS angle between its lines of sight and the plane through the camera and
    the final path.</p>`;
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
      ? `<b>Request recorded</b>; the run stops until a person supplies it (${esc(list(r.request.towns || []) || r.request.kind)}).`
      : `<b>Refused by the code</b>: ${esc((r.problems || []).join('; '))}`;
    case 'check_satellite': return (r.detections && r.detections.length
      ? r.detections.map(g => `${esc(g.class || 'Detection')} at ${esc(g.utc)}, ${esc(g.where || `${g.lat}, ${g.lon}`)}, ${fmt(g.duration_s, 2)} s`
        + (g.confidence ? `, ${esc(g.confidence)} confidence` : '')).join('; ')
      : `No detection. ${esc(r.note || '')}`)
      + (r.reentries ? `. Re-entries: ${r.reentries.containing_the_flash.length ? esc(list(r.reentries.containing_the_flash)) + ' could match'
        : `none whose window includes the flash; the nearest, ${reentryWindow(d, r.reentries.nearest[0])}`}` : '');
    case 'read_witness': return `${esc(String(r.clip_kind).replace(/_/g, ' '))}${r.camera_moves ? ', camera moving' : ''}${r.multiple_cuts ? ', several cuts' : ''};
      fireball from ${fmt(r.fireball_s[0], 1)} to ${fmt(r.fireball_s[1], 1)} s; ${r.landmarks.length} landmark guesses`;
    case 'calibration': return r.calibrated ? `Oriented (${esc(r.lens)}, ${fmt(r.hfov, 1)}° wide)` : `Not oriented: ${esc(r.why)}`;
    case 'missing_views': return `Best towns: ${esc(list(r.best_towns.slice(0, 5).map(t => t.split(' (')[0])))}`;
    case 'write_report': return r.accepted === false ? `<b>Refused by the code</b>: ${esc((r.problems || []).join('; '))}`
      : r.reports ? `Report written; every figure checked against the tool results: `
      + Object.entries(r.reports).filter(([, v]) => v && v.figures !== undefined).map(([lang, v]) => `${lang} ${v.traced} of ${v.figures}${v.passed ? '' : ' (refused)'}`
        + (v.refused_drafts ? `, after ${v.refused_drafts} refused draft${v.refused_drafts > 1 ? 's' : ''}` : '')).join(', ')
      : 'Wrote the report below.';
    default: return '';
  }
}

// Where a run stands, from its status and the last entry of its review history.
function runState(run) {
  const last = (run.history || []).slice(-1)[0], by = last && last.by ? ` by ${last.by}` : '';
  if (run.status === 'approved') return `report signed off${by}`;
  if (run.status === 'rejected') return last && last.withdraws === 'approval' ? `signature withdrawn${by}` : `report sent back with notes${by}`;
  if (run.status === 'blocked') return run.block && run.block.reason === 'missing_evidence' ? 'blocked, waiting for the evidence it asked for' : 'blocked for a person';
  return {awaiting_review: 'waiting for a person to sign the report off', failed: 'failed'}[run.status] || run.status;
}

// The run this one resumed, and the notes it was given (who wrote them is in the notes, or in the review they come from).
function resumedText(run) {
  if (!run.resumed_from) return '';
  const before = run.resumed && run.resumed.last_review, same = before && run.notes && before.notes === run.notes;
  const how = !before ? '' : before.withdraws === 'approval' ? `, whose signature ${before.by} withdrew`
    : before.review === 'rejected' ? `, which ${before.by} sent back` : '';
  return ` It resumed run <span class="num">${esc(run.resumed_from)}</span>${esc(how)}${run.notes ? `${same ? ' with these notes' : '. Its notes'}:
    “${esc(run.notes)}”` : '.'}`;
}

function drawLog(el, d) {
  const target = s => (s.clips && s.clips.length ? s.clips : s.clip ? [s.clip] : []).map(id => esc(name(d, id))).join(' + ');
  const run = d.run || {};
  el.innerHTML = `<h2>What the agent did</h2>
    <p class="note">${esc(modelName(run.planner_model))} chose each of these ${d.agent_log.length} steps by calling a tool and said why;
    the code ran the tool, checked what had to be checked and kept the record. ${d.tried ? 'Hover a solve step to see that solution on the map.' : ''}</p>
    ${run.run_id ? `<p class="note">Run <span class="num">${esc(run.run_id)}</span>: ${esc(runState(run))}.${resumedText(run)}
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
      ${toggle('published', 'dash" style="border-top-color:' + rgb(PUBLISHED), `Published path, ${esc(cbet(d))}`)}</details>`;
  } else {
    $('#legend').innerHTML = `<details ${narrow.matches ? '' : 'open'}><summary>Map key</summary>
      <div class="key"><span class="sw box"></span>${esc(glmText(d))} and its extent</div>
      <div class="key" data-stage="2"><span class="sw dash" style="border-top-color:${rgb(GRAY)}"></span>Witness video, camera not oriented</div>
      ${asked(d).size ? '<div class="key" data-stage="3"><span class="sw dot asked"></span>Towns requested by the agent</div>' : ''}
      <div class="key" data-stage="3"><span class="sw dot" style="background:${rgb(SERIES[0])}"></span>Towns that would see it ${span(...d.sky.high_deg, 0)}° up</div>
      <div class="key" data-stage="4"><span class="sw dot" style="background:${rgb(GRAY)}"></span>Other towns: too low in their sky</div></details>`;
    stageKey();
  }
  $('#legend').querySelectorAll('input').forEach(i => i.addEventListener('change', () => {
    state.show[i.dataset.key] = i.checked;
    redraw();
    namesUnderLabels();
  }));
  $('#legend details').addEventListener('toggle', placeHud);  // the replay bar may sit above the key
}

function stageKey() {  // the key lists only what the current stage shows
  $('#legend').querySelectorAll('[data-stage]').forEach(el => { el.hidden = !shows(Number(el.dataset.stage)); });
}

// ---- the witness video ------------------------------------------------------------------------------------------------
// One witness video can play beside the replay: its uploader's own YouTube video in YouTube's player (youtube-nocookie.com),
// which the uploader allows (the export reads credits.json). Nothing loads from YouTube until a reader presses play. The
// video's second is the replay's second plus start_s, both in real time; the replay follows the player when it starts,
// stalls, seeks or pauses, and the player follows the replay's Replay, Pause and Resume.

const clip = {player: null, ready: false, visible: true, observer: null, timer: 0};
const CLIP_ERRORS = {100: 'The video is no longer on YouTube, or it is private.', 101: 'Its uploader no longer allows it to play on other sites.',
  150: 'Its uploader no longer allows it to play on other sites.', 153: "YouTube's player needs this page's address, and the browser did not send it."};
const clock = (x, d = 0) => `${Math.floor(x / 60)}:${d ? (x % 60).toFixed(d).padStart(d + 3, '0') : String(Math.floor(x % 60)).padStart(2, '0')}`;  // 0:06, 0:18.8
const recall = () => { try { return localStorage.getItem('testigos.clip.open'); } catch (e) { return null; } };
const remember = open => { try { localStorage.setItem('testigos.clip.open', open ? '1' : '0'); } catch (e) { /* not kept */ } };
const external = (url, text) => `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${text}</a>`;

function drawClip(d) {
  dropClip();
  const el = $('#clip'), c = d.clip;
  if (!clipOn || !c || !c.youtube_id) { el.innerHTML = ''; return; }
  const st = d.stations.find(x => x.id === c.clip), out = c.left_out, pair = out && out.pairs[0];
  const kept = recall(), open = kept === null || kept === '1';
  const why = out ? `The agent left this camera out of the fit${pair ? ` (its planes cross ${esc(pair.site)}'s at ${fmt(pair.q_deg, 1)}°)` : ''},
    so it is the check: its lines of sight miss the fitted path by ${fmt(st.miss_deg, 2)}°.` : '';
  const others = (c.linked || []).map(l => `${esc(l.site)}'s uploader does not allow the video on other sites:
    ${external(l.url, `watch it on YouTube from ${clock(l.at_s)}`)}.`).join(' ');
  el.innerHTML = `<details${open ? ' open' : ''}><summary><span class="dot dashed"></span>A witness video · filmed in ${esc(c.site)}${out
    ? ', left out of the fit' : ''}</summary>
    <div class="clip-frame"><button type="button" class="clip-poster"><span class="clip-play" aria-hidden="true"></span>
      <span>Play the video with the replay</span>
      <small>The fireball crosses it from ${clock(c.fireball_s[0])} to ${clock(c.fireball_s[1])}. YouTube's player loads when you press
      play.</small></button></div>
    <p class="clip-hint" role="status"></p>
    <p class="note">Filmed from a ${esc(c.camera)} in ${esc(c.site)}. ${why} Play runs the replay from ${clock(c.start_s)}, the instant
    this camera's own clock puts at the top of the path; SAM 3.1 picks the fireball up at ${clock(c.fireball_s[0], 1)}. The fireball
    slowed and the replay flies the fitted line at one speed, so at the camera's last sight of it (${clock(c.fireball_s[1], 1)}) the
    replay's dot is ${fmt(c.ahead_at_last_s, 1)} s ahead.</p>
    <p class="clip-credit">${external(c.url, `“${esc(c.title)}”`)}, uploaded by ${esc(c.uploader)} (${esc(c.channel)}) on
    ${esc(c.uploaded)}, plays in YouTube's player; nothing of it is stored here. ${others}</p></details>`;
  const details = el.querySelector('details');
  details.addEventListener('toggle', () => { remember(details.open); if (!details.open) syncClip(false); });
  el.querySelector('.clip-poster').addEventListener('click', () => startClip(d));
  if ('IntersectionObserver' in window) {  // YouTube asks that scripted playback start only while half the player shows
    clip.observer = new IntersectionObserver(es => { clip.visible = es[0].intersectionRatio >= 0.5; }, {threshold: [0, 0.5, 1]});
    clip.observer.observe(el.querySelector('.clip-frame'));
  }
}

let youTube = null;
function loadYouTube() {  // YouTube's IFrame API, once, with a time limit
  if (window.YT && window.YT.Player) return Promise.resolve();
  if (!youTube) {
    youTube = new Promise((ok, fail) => {
      const s = document.createElement('script'), late = setTimeout(() => fail(new Error('timeout')), 15000);
      s.src = 'https://www.youtube.com/iframe_api';
      s.onerror = () => { clearTimeout(late); fail(new Error('blocked')); };
      window.onYouTubeIframeAPIReady = () => { clearTimeout(late); ok(); };
      document.head.append(s);
    }).catch(e => { youTube = null; throw e; });
  }
  return youTube;
}

async function startClip(d) {
  const c = d.clip, frame = $('#clip .clip-frame');
  if (!frame || clip.player) return;
  frame.innerHTML = '<p class="clip-wait">Loading YouTube\'s player…</p>';
  try { await loadYouTube(); } catch (e) { return clipFail(d, "YouTube's player could not load here."); }
  if (state.data !== d) return;
  const f = document.createElement('iframe');
  const q = new URLSearchParams({enablejsapi: 1, origin: location.origin, start: Math.floor(c.start_s), end: Math.ceil(c.end_s),
    mute: 1, playsinline: 1, rel: 0});
  f.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(c.youtube_id)}?${q}`;
  f.title = `${c.title}, by ${c.uploader}, in YouTube's player`;
  f.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
  f.referrerPolicy = 'strict-origin-when-cross-origin';  // YouTube refuses to play for a page that sends no address
  frame.replaceChildren(f);
  clip.timer = setTimeout(() => { if (!clip.ready) clipFail(d, "YouTube's player did not answer."); }, 15000);
  try {
    clip.player = new YT.Player(f, {events: {
      onReady: () => {
        if (state.data !== d) return;
        clearTimeout(clip.timer);
        clip.ready = true;
        // One press runs both, from the replay's paused instant or from the start. The video starts first; the replay
        // follows once the video actually plays (onClipState), so a slow start does not leave the replay ahead.
        const from = !state.playing && state.t !== null ? state.t : 0;
        if (state.playing) stop(false);
        state.t = null;
        readout();
        redraw();
        try { clip.player.mute(); clip.player.seekTo(c.start_s + from, true); clip.player.playVideo(); } catch (e) { /* the HUD still works */ }
      },
      onStateChange: e => onClipState(d, e),
      onError: e => clipFail(d, CLIP_ERRORS[e.data] || "YouTube's player could not play it here."),
      onAutoplayBlocked: () => hint('Press play in the video; the replay will follow.'),
    }});
  } catch (e) { clipFail(d, "YouTube's player could not load here."); }
}

// The replay drives the player: Replay and Resume seek the video to start_s + t and play it, Pause and the end pause it.
function syncClip(on, from = 0) {
  const p = clip.player, c = state.data && state.data.clip;
  if (!p || !clip.ready || !c) return;
  try {
    if (!on) { if (p.getPlayerState() === YT.PlayerState.PLAYING) p.pauseVideo(); return; }
    if (!clip.visible || !$('#clip details').open) return;
    const want = c.start_s + from;
    if (Math.abs(p.getCurrentTime() - want) > 0.3) p.seekTo(want, true);
    p.playVideo();
  } catch (e) { /* the replay never depends on the player */ }
}

// The player drives the replay: when it starts, stalls or seeks, the replay takes the video's time; when the reader plays
// or pauses inside the player, the replay follows; at the fragment's end the player goes back to its start.
function onClipState(d, e) {
  if (state.data !== d || !clip.ready) return;
  const p = clip.player, c = d.clip, S = YT.PlayerState, dur = d.solution.times[d.solution.times.length - 1];
  let t;
  try { t = p.getCurrentTime() - c.start_s; } catch (err) { return; }
  if (e.data === S.PLAYING) {
    hint('');
    if (state.playing) {
      if (t < -1 || t >= dur) stop(false);
      else if (Math.abs(t - state.t) > 0.4) started = performance.now() - Math.max(0, t) * 1000;
    } else if (t >= -1 && t < dur) { state.t = Math.max(0, t); play(); }
  } else if (e.data === S.PAUSED && state.playing) stop(false);
  else if (e.data === S.ENDED) {
    try { p.cueVideoById({videoId: c.youtube_id, startSeconds: c.start_s, endSeconds: c.end_s}); } catch (err) { /* stays ended */ }
  }
}

function clipFail(d, why) {
  if (state.data !== d) return;
  const c = d.clip, frame = $('#clip .clip-frame');
  dropClip();
  if (frame) frame.outerHTML = `<p class="clip-fail" role="status">${esc(why)} ${external(`${c.url}&t=${Math.floor(c.start_s)}s`,
    `Watch it on YouTube from ${clock(c.start_s)}`)}.</p>`;
}

function dropClip() {
  clearTimeout(clip.timer);
  if (clip.observer) clip.observer.disconnect();
  try { if (clip.player && clip.player.destroy) clip.player.destroy(); } catch (e) { /* already gone */ }
  Object.assign(clip, {player: null, ready: false, visible: true, observer: null, timer: 0});
}

function hint(text) {
  const el = $('#clip .clip-hint');
  if (el) el.textContent = text;
}

// ---- replay ----------------------------------------------------------------------------------------------------------

let raf = 0, started = 0;

function readout() {
  const d = state.data;
  if (!d || !d.solution) return;
  const dur = d.solution.times[d.solution.times.length - 1];
  // the replay flies the fitted line at the fitted speed: its seconds are not how long any camera saw the fireball
  $('#readout').textContent = state.t === null ? `${fmt(dur, 1)} s: the fitted line at the fitted speed, in real time`
    : `t ${fmt(state.t, 1)} s, ${fmt(headAt(d, state.t)[2] / 1000, 0)} km up`;
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
  syncClip(true, from);
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
  syncClip(false);
  if (finished) state.t = null;
  $('#play').textContent = state.t === null ? 'Replay' : 'Resume';
  readout();
  placeHud();
  redraw();
}

// On a desktop the replay bar sits at the foot of the map, in the middle of it or as near the middle as the map key allows,
// and its readout wraps to stay in the gap between the panel and the key; where that gap leaves the readout more than two
// lines, the bar rises above the key. On a phone and in ?panel=0 the style sheet places it.
function placeHud() {
  const hud = $('#hud'), s = hud.style, text = $('#readout');
  s.left = s.bottom = s.maxWidth = '';
  if (hud.hidden || narrow.matches || document.body.classList.contains('bare')) return;
  const from = $('#panel').getBoundingClientRect().right + 12, key = $('#legend').getBoundingClientRect();
  const to = key.width ? key.left - 12 : innerWidth - 12, middle = (from + innerWidth - 12) / 2;
  s.maxWidth = `${to - from}px`;
  s.left = `${Math.min(middle, to - hud.getBoundingClientRect().width / 2)}px`;
  const lines = text.getBoundingClientRect().height / parseFloat(getComputedStyle(text).lineHeight);
  if (!key.width || (lines < 2.5 && hud.scrollWidth <= hud.clientWidth + 1)) return;
  s.left = `${middle}px`;
  s.maxWidth = `${innerWidth - 12 - from}px`;
  s.bottom = `${innerHeight - key.top + 10}px`;
}
addEventListener('resize', placeHud);

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
  drawClip(d);
  $('#lead').innerHTML = d.solution ? leadSolved(d) : leadOpen(d);
  $('#compare').innerHTML = d.solution ? compareSolved(d) : compareOpen(d);
  if (d.solution) drawChart($('#chart'), d); else $('#chart').innerHTML = '';
  drawLog($('#log'), d);
  const wrote = `the verdict line is written by the code, the rest by ${esc(modelName(d.report_model))}`;
  $('#report').innerHTML = (d.report_en ? `<details><summary>The agent's report: ${wrote}</summary>
    <div class="report">${md(d.report_en)}</div></details>` : '') + `<details><summary>${d.report_en ? 'El mismo reporte en español'
    : `The agent's report, in Spanish: ${wrote}`}</summary>
    <div class="report">${md(d.report_es)}</div></details>`;
  $('#hud').hidden = !d.solution;
  $('#play').textContent = 'Replay';
  drawLegend(d);
  readout();
  placeHud();
  // A phone sees more of the solved case; the open case has a view of its own for a phone (view_narrow), closer to the flash
  // and less tilted, where the requested towns' labels have room beside their dots. In video mode the open case comes
  // closer to the flash, so its larger labels have room, and the solved case steps back beside the wider panel, so every
  // witness site stays in view. Where the map area left free is smaller, the open case's view fits itself to it (fitView).
  const closer = !video ? 0 : !d.solution ? 0.5 : document.body.classList.contains('bare') ? 0 : -0.2;
  const base = narrow.matches && d.view_narrow ? d.view_narrow : {...d.view, zoom: d.view.zoom - (narrow.matches ? 1.3 : 0)};
  const asGiven = {...base, zoom: base.zoom + closer, padding: padding()};
  const view = d.solution ? asGiven : fitView(d, asGiven);
  state.spots = d.solution ? new Map() : placeTowns(d, view);  // placed for where the camera is going
  under = [];  // the basemap names under the last case's labels; found again once the map has drawn this one
  quietNames();
  if (firstView) {
    map.jumpTo(view);
    // the replay runs once, when the map has drawn the case; a case switch before then cancels it
    if (autoplay && d.solution) map.once('idle', () => { if (state.data === d && state.t === null && !state.playing) play(); });
  } else map.flyTo({...view, duration: 2200, essential: true});
  firstView = false;
  redraw();
}

map.on('moveend', () => {  // after a pan, zoom, turn or resize the labels find their spots again
  const d = state.data;
  if (!d) return;
  if (d.solution) { if (!state.playing) redraw(); return; }  // CBET's label picks its side for the new view
  state.spots = placeTowns(d, currentView());
  quietNames();
  redraw();
});

addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (video && (/^[0-3]$/.test(e.key) || e.key === 'Escape')) {
    state.stage = e.key === 'Escape' ? 0 : Number(e.key);
    stageKey();
    redraw();
    namesUnderLabels();
    return;
  }
  if (e.target.closest('input, textarea, button, summary, a')) return;
  if (e.code === 'Space') { e.preventDefault(); play(); }
  if (e.key === 'h') {
    document.body.classList.toggle('bare');
    if (document.body.classList.contains('bare')) syncClip(false);  // the panel, and the player in it, are hidden
    placeHud();
    map.easeTo({padding: padding(), duration: 600});
  }
});

(async function init() {
  cases = await (await fetch('data/cases.json')).json();
  $('#cases').innerHTML = cases.map(c => `<button type="button" data-id="${c.id}" aria-pressed="false">${esc(c.title)}<small>${esc(c.role)}</small></button>`).join('');
  $('#cases').querySelectorAll('button').forEach(b => b.addEventListener('click', () => { location.hash = b.dataset.id; }));
  $('#play').addEventListener('click', play);
  addEventListener('hashchange', () => show(location.hash.slice(1)));
  try { await Promise.all([500, 600].map(w => document.fonts.load(`${w} 12px ${FONT}`))); } catch (e) { /* labels fall back to the system font */ }
  show(location.hash.slice(1));
})();
