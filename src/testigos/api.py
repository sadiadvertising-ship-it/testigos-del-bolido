"""Meta Model API client: file upload, /responses, and a cost ledger with a spending cap.

Every billable call is priced before it is sent and refused if today's spend would pass the cap
(TESTIGOS_BUDGET_USD, default 5). Prices are the public list prices at dev.meta.ai/docs/pricing-rate-limits.
"""
from __future__ import annotations

import datetime as dt
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


def upload(path, expires_days=7):
    path = pathlib.Path(path)
    boundary = uuid.uuid4().hex
    parts = [('purpose', 'user_data'), ('expires_after[anchor]', 'created_at'),
             ('expires_after[seconds]', str(expires_days * 86400))]
    body = b''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in parts)
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
             f'Content-Type: video/mp4\r\n\r\n').encode() + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    return _request('/files', body, {'Content-Type': f'multipart/form-data; boundary={boundary}'}, 300)['id']


def text_of(resp):
    return ''.join(c.get('text', '') for item in resp.get('output', []) for c in (item.get('content') or [])
                   if c.get('type') in ('output_text', 'text'))


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
    return json.loads(text) if schema else text


def sam_video(file_id, prompt, frames_guess, metadata=None, purpose=''):
    """Track a concept (short noun phrase) or box/point prompts through a video; returns the raw token text."""
    _guard(max(frames_guess, 50) * SAM_VIDEO_FRAME)
    body = {'model': 'sam-3.1', 'input': [{'type': 'message', 'role': 'user', 'content': [
        {'type': 'input_text', 'text': prompt}, {'type': 'input_video', 'file_id': file_id}]}]}
    if metadata:
        body['metadata'] = metadata
    t0 = time.time()
    resp = _request('/responses', json.dumps(body).encode(), {'Content-Type': 'application/json'}, 900)
    text = text_of(resp)
    frames = max(text.count('f>'), 0)
    _log('sam_video', max(frames, 50) * SAM_VIDEO_FRAME, prompt=prompt[:60], purpose=purpose,
         frames=frames, seconds=round(time.time() - t0, 1))
    return text
