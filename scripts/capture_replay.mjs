// The Chelyabinsk replay from the 3D viewer as the README's looping GIF, docs/replay.gif. It shows the map only: the
// side panel is hidden (the viewer's ?panel=0 mode), and no witness frame is in it, since the viewer draws directions
// and times, not video.
//
// Serve web/ first, then run from anywhere:
//   python3 -m http.server -d web 8000
//   node scripts/capture_replay.mjs [--url=http://127.0.0.1:8000/] [--out=docs/replay.gif] [--beat=1.5] [--keep] [--only=0,60,140]
// Needs Node 22 or later, Google Chrome (or CHROME=/path/to/chrome) and ffmpeg. --only saves just those frames as PNG,
// to check the framing; --keep keeps the frames. Temporary files go to $SCRATCH, else the system's temp folder.
//
// A headless renderer is too slow to film the replay as it plays, so each frame sets the replay clock itself and waits
// until the map has drawn it. The frames are what the Replay button shows at those instants (web/app.js, play()): the
// clock runs from 0 to the end of the flight in real time (the fitted line flown at the fitted speed), the last instant
// holds 0.9 s, then the still view returns in two beats of --beat seconds (1.5 by default): first without the Monte Carlo
// lines, so the agent's white path shows beside CBET 3423's dashed path, then with them. The GIF then starts over. The
// viewer also turns the map by 16° during a replay; a turning map changes every pixel of every frame and makes the GIF
// many times larger, so the map stays still here (--turn=16 gives the viewer's motion).
import {spawn, spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, rmSync, statSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const opt = Object.fromEntries(process.argv.slice(2).map(a => {
  const [k, ...v] = a.replace(/^--/, '').split('=');
  return [k, v.length ? v.join('=') : true];
}));
// replay=0: the viewer would otherwise start its own replay on load, whose clock would override the one set here
const url = new URL('?panel=0&replay=0#chelyabinsk-2013', opt.url || 'http://127.0.0.1:8000/').href;
const out = resolve(opt.out || join(ROOT, 'docs', 'replay.gif'));
// 880 CSS pixels is about the width GitHub gives a README image; twice the pixels keeps the lines sharp on dense screens.
const W = +(opt.width || 880), H = +(opt.height || 495), SCALE = +(opt.scale || 2), FPS = +(opt.fps || 10);
const ZOOM = +(opt.zoom || 6.4), CENTER = String(opt.center || '62.75,55.45').split(',').map(Number);  // lon,lat
const TURN = +(opt.turn || 0), BEAT_S = +(opt.beat || 1.5);
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const work = mkdtempSync(join(process.env.SCRATCH || tmpdir(), 'replay-'));
const frames = join(work, 'frames');
mkdirSync(frames);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn(CHROME, ['--headless=new', `--user-data-dir=${join(work, 'profile')}`, '--disable-extensions',
  '--no-first-run', '--no-default-browser-check', `--window-size=${W},${H}`, '--use-angle=swiftshader',
  '--enable-unsafe-swiftshader', '--hide-scrollbars', `--remote-debugging-port=${port}`, 'about:blank'], {stdio: 'ignore'});

let ws;
try {
  let targets;
  for (let i = 0; i < 75 && !targets; i++) {
    await sleep(200);
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); } catch { /* not up yet */ }
  }
  if (!targets) throw new Error('Chrome did not start');
  ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((ok, fail) => { ws.addEventListener('open', ok); ws.addEventListener('error', fail); });
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === 'Runtime.exceptionThrown') {
      console.log('page exception:', (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).slice(0, 300));
    }
  });
  const send = (method, params = {}) => new Promise(r => { const n = ++id; pending.set(n, r); ws.send(JSON.stringify({id: n, method, params})); });
  const run = async expression => {
    const r = await send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text);
    return r.result?.result?.value;
  };

  await send('Runtime.enable');
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', {width: W, height: H, deviceScaleFactor: SCALE, mobile: false});
  await send('Page.navigate', {url});

  // The viewer's own globals (state, map, redraw and readout in web/app.js) draw each frame.
  const info = await run(`(async () => {
    const t0 = performance.now();
    while (!(typeof state !== 'undefined' && state.data && state.data.solution && map.loaded())) {
      if (performance.now() - t0 > 60000) throw new Error('the viewer did not load the case');
      await new Promise(r => setTimeout(r, 100));
    }
    const css = document.createElement('style');  // the HUD keeps its readout, centred; no buttons to press in a GIF
    css.textContent = '.maplibregl-ctrl-top-right, #play { display: none; } #hud { left: 50%; padding: 7px 16px; }'
      + ' #readout { min-width: 11em; text-align: center; }';
    document.head.append(css);
    map.jumpTo({zoom: ${ZOOM}, center: ${JSON.stringify(CENTER)}});
    window.__drawn = async () => {
      await new Promise(r => { map.once('idle', r); map.triggerRepaint(); setTimeout(r, 20000); });  // tiles and label fades
      for (let i = 0; i < 4; i++) await new Promise(r => requestAnimationFrame(r));  // deck.gl draws on its own frame
    };
    window.__frame = async (t, bearing, mc) => {
      state.t = t; state.show.mc = mc; readout(); redraw(); map.jumpTo({bearing}); await window.__drawn();
    };
    await window.__drawn();
    const times = state.data.solution.times;
    return {dur: times[times.length - 1], bearing: map.getBearing()};
  })()`);

  // play(): t is the elapsed time up to the end of the flight; the bearing eases linearly by the turn over that time
  // plus 1.2 s; 0.9 s after the end, stop(true) halts the map and shows the still view (t = null), here first without
  // the Monte Carlo lines (mc false), then with them.
  const span = info.dur * 1000 + 1200, stopAt = info.dur * 1000 + 900;
  const shots = [];
  for (let ms = 0; ms < stopAt; ms += 1000 / FPS) shots.push({t: Math.min(ms / 1000, info.dur), mc: true, bearing: info.bearing + TURN * ms / span});
  for (const mc of [false, true]) {
    for (let k = 0; k < Math.round(BEAT_S * FPS); k++) shots.push({t: null, mc, bearing: info.bearing + TURN * stopAt / span});
  }
  const only = opt.only ? new Set(String(opt.only).split(',').map(Number)) : null;
  let n = 0;
  for (const [i, s] of shots.entries()) {
    if (only && !only.has(i)) continue;
    await run(`window.__frame(${s.t}, ${s.bearing}, ${s.mc})`);
    const shot = await send('Page.captureScreenshot', {format: 'png'});
    writeFileSync(join(frames, `${String(i).padStart(4, '0')}.png`), Buffer.from(shot.result.data, 'base64'));
    if (++n % 20 === 0) console.log(`frame ${n} of ${only ? only.size : shots.length}`);
  }
  console.log(`${shots.length} frames at ${FPS} fps: ${info.dur} s of flight, ${W}×${H} CSS pixels at ${SCALE}×`);

  if (!only) {
    // One palette for the whole loop; ordered dithering leaves the still map identical from frame to frame, so each
    // frame stores only the rectangle that changed.
    mkdirSync(dirname(out), {recursive: true});
    const ff = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(FPS), '-i', join(frames, '%04d.png'),
      '-vf', 'split[a][b];[a]palettegen=max_colors=256:stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle',
      '-loop', '0', out], {stdio: 'inherit'});
    if (ff.status !== 0) throw new Error('ffmpeg failed');
    console.log(`${out}: ${(statSync(out).size / 1e6).toFixed(2)} MB`);
  }
} finally {
  ws?.close();
  chrome.kill();
  if (opt.keep || opt.only) console.log('frames in', frames);
  else { await sleep(500); rmSync(work, {recursive: true, force: true}); }
}
