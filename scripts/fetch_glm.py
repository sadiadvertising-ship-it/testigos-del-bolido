"""Download NASA's GLM bolide catalog and keep, for each event, the detections within 30 minutes of it.

The catalog (neo-bolide.ndc.nasa.gov, about 30 MB) goes to out/cache/glm-bolides.json and is not committed; the
small excerpt events/<id>/glm-window.json is, so the agent's satellite check works in a fresh clone without a network.
GLM watches the Americas from GOES orbit since 2017, so older or other-region events get an empty excerpt.
Usage: .venv/bin/python scripts/fetch_glm.py [--refresh]
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
URL = 'https://neo-bolide.ndc.nasa.gov/service/event/public'
CATALOG = ROOT / 'out' / 'cache' / 'glm-bolides.json'
WINDOW_S = 1800


def download():
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(URL, timeout=300) as r:
            CATALOG.write_bytes(r.read())
    except OSError as exc:  # the macOS system Python's TLS has failed on some hosts; curl is the fallback
        print('urllib failed:', exc, '- trying curl')
        subprocess.run(['curl', '-sSf', '--retry', '3', '-o', str(CATALOG), URL], check=True)


def main(refresh):
    if refresh or not CATALOG.exists():
        download()
    catalog = json.loads(CATALOG.read_text())['data']
    downloaded = dt.datetime.fromtimestamp(CATALOG.stat().st_mtime, dt.timezone.utc).strftime('%Y-%m-%d')
    for event_file in sorted((ROOT / 'events').glob('*/event.json')):
        utc = json.loads(event_file.read_text()).get('utc')
        if not utc:
            continue
        t0 = dt.datetime.fromisoformat(utc.replace('Z', '+00:00')).timestamp()
        hits = [e for e in catalog if abs(e['datetime'] / 1000 - t0) < WINDOW_S]
        excerpt = {'source': URL, 'catalog_downloaded': downloaded, 'catalog_events': len(catalog), 'event_utc': utc,
                   'window_s': WINDOW_S, 'events': hits}
        (event_file.parent / 'glm-window.json').write_text(json.dumps(excerpt, indent=1, ensure_ascii=False) + '\n')
        print(f'{event_file.parent.name}: {len(hits)} detections within {WINDOW_S // 60} min')


if __name__ == '__main__':
    main('--refresh' in sys.argv[1:])
