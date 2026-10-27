"""Meta Model API client: file upload, /responses, and a cost ledger with a spending cap.

Every billable call is priced before it is sent and refused if today's spend would pass the cap
(TESTIGOS_BUDGET_USD, default 5). Prices are the public list prices at dev.meta.ai/docs/pricing-rate-limits.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import time
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = 'https://api.meta.ai/v1'
LEDGER = ROOT / 'out' / 'costs.jsonl'
CACHE = ROOT / 'out' / 'cache'

SPARK_IN, SPARK_OUT = 1.25 / 1e6, 4.25 / 1e6  # USD per token
SAM_VIDEO_FRAME = 0.0002  # USD per tracked frame, 50-frame minimum per request
SAM_IMAGE = 2.50 / 1000


class BudgetExceeded(RuntimeError):
    pass


def key():
    for line in (ROOT / '.env').read_text().splitlines():
        if line.startswith('MODEL_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"')
    raise RuntimeError('MODEL_API_KEY missing in .env')


def budget():
    return float(os.environ.get('TESTIGOS_BUDGET_USD', '5'))


def spent_today():
    if not LEDGER.exists():
        return 0.0
    today = dt.date.today().isoformat()
    return sum(r['usd'] for r in map(json.loads, LEDGER.read_text().splitlines()) if r['ts'].startswith(today))


def _guard(estimate):
    if spent_today() + estimate > budget():
        raise BudgetExceeded(f'today: US$ {spent_today():.2f} spent, this call ~US$ {estimate:.2f}, cap US$ {budget():.2f}')


def _log(kind, usd, **extra):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    row = {'ts': dt.datetime.now().isoformat(timespec='seconds'), 'kind': kind, 'usd': round(usd, 5), **extra}
    with LEDGER.open('a') as f:
        f.write(json.dumps(row) + '\n')


def _request(path, data, headers, timeout):
    req = urllib.request.Request(BASE + path, data=data, headers={'Authorization': 'Bearer ' + key(), **headers})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors='replace')[:800]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f'{path} HTTP {e.code}: {body}') from None


def file_sha(path):
    return hashlib.sha1(pathlib.Path(path).read_bytes()).hexdigest()[:16]


def upload(path):
    """Upload once per file content; later calls reuse the file id."""
    path = pathlib.Path(path)
    index = CACHE / 'uploads.json'
    known = json.loads(index.read_text()) if index.exists() else {}
    sha = file_sha(path)
    if sha in known:
        return known[sha]
    file_id = _upload(path)
    CACHE.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({**known, sha: file_id}, indent=1))
    return file_id


def _upload(path):
    boundary = uuid.uuid4().hex
    body = f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nuser_data\r\n'.encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
             f'Content-Type: video/mp4\r\n\r\n').encode() + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    return _request('/files', body, {'Content-Type': f'multipart/form-data; boundary={boundary}'}, 300)['id']


def text_of(resp):
    return ''.join(c.get('text', '') for item in resp.get('output', []) for c in (item.get('content') or [])
                   if c.get('type') in ('output_text', 'text'))


def _json_in(text):
    """The JSON object in a structured answer. Muse sometimes puts a sentence of commentary before it."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == '{':
            try:
                obj, _ = dec.raw_decode(text[i:])
                return obj
            except json.JSONDecodeError:
                continue
    return None


def spark(content, schema=None, model='muse-spark-1.2', max_output_tokens=8000, effort='medium',
          input_tokens_guess=60000, purpose=''):
    _guard(input_tokens_guess * SPARK_IN + max_output_tokens * SPARK_OUT)
    body = {'model': model, 'max_output_tokens': max_output_tokens, 'reasoning': {'effort': effort},
            'input': [{'role': 'user', 'content': content}]}
    if schema:
        body['text'] = {'format': {'type': 'json_schema', 'name': 'out', 'schema': schema, 'strict': True}}
    t0 = time.time()
    resp = _request('/responses', json.dumps(body).encode(), {'Content-Type': 'application/json'}, 600)
    u = resp.get('usage') or {}
    usd = u.get('input_tokens', 0) * SPARK_IN + u.get('output_tokens', 0) * SPARK_OUT
    _log('spark', usd, model=model, purpose=purpose, seconds=round(time.time() - t0, 1),
         input_tokens=u.get('input_tokens'), output_tokens=u.get('output_tokens'))
    text = text_of(resp)
    if not schema:
        return text
    parsed = _json_in(text)
    if parsed is not None:
        return parsed
    bad = CACHE / f"spark-unparsed-{dt.datetime.now().strftime('%H%M%S')}.txt"
    CACHE.mkdir(parents=True, exist_ok=True)
    bad.write_text(text)
    raise RuntimeError(f'Muse Spark returned {len(text)} chars that are not valid JSON '
                       f'(status {resp.get("status")}, output tokens {u.get("output_tokens")}); saved to {bad}')


def sam_video(file_id, prompt, frames_guess, metadata=None, purpose='', cache_key=None):
    """Track a concept (short noun phrase) or box/point prompts through a video; returns the raw token text.

    With a cache_key the raw answer is kept in out/cache, so the same clip and prompt are never paid twice.
    """
    cached = CACHE / f'sam-{cache_key}.txt' if cache_key else None
    if cached and cached.exists():
        return cached.read_text()
    _guard(max(frames_guess, 50) * SAM_VIDEO_FRAME)
    body = {'model': 'sam-3.1', 'input': [{'type': 'message', 'role': 'user', 'content': [
        {'type': 'input_text', 'text': prompt}, {'type': 'input_video', 'file_id': file_id}]}]}
    if metadata:
        body['metadata'] = metadata
    t0 = time.time()
    resp = _request('/responses', json.dumps(body).encode(), {'Content-Type': 'application/json'}, 900)
    text = text_of(resp)
    billed = max(frames_guess, 50)  # billed per frame processed, not per frame with a detection
    _log('sam_video', billed * SAM_VIDEO_FRAME, prompt=prompt[:60], purpose=purpose, frames_billed=billed,
         frames_with_output=text.count('f>'), seconds=round(time.time() - t0, 1))
    if cached:
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(text)
    return text
