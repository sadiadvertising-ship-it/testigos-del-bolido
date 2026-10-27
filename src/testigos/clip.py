"""Video plumbing with ffmpeg and ffprobe: metadata, per-frame timestamps, trimming and grayscale frames.

Frame times come from the container (best_effort_timestamp_time), never from an assumed frame rate:
social-media re-encodes drop and duplicate frames, and phones record at variable rates.
"""
from __future__ import annotations

import hashlib
import json
import subprocess

import numpy as np


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def probe(path):
    """Displayed width and height (rotation applied), average fps and duration."""
    info = json.loads(_run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                            'stream=width,height,avg_frame_rate,duration:stream_side_data=rotation:format=duration',
                            '-of', 'json', str(path)]))
    s = info['streams'][0]
    rot = next((int(d['rotation']) for d in s.get('side_data_list', []) if 'rotation' in d), 0)
    w, h = (s['height'], s['width']) if abs(rot) % 180 == 90 else (s['width'], s['height'])
    num, den = (int(x) for x in s.get('avg_frame_rate', '0/1').split('/'))
    duration = float(s.get('duration') or info.get('format', {}).get('duration') or 0)
    return {'width': w, 'height': h, 'fps': num / den if den else 0.0, 'duration': duration, 'rotation': rot}


def frame_times(path):
    out = _run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                'frame=best_effort_timestamp_time', '-of', 'csv=p=0', str(path)])
    return np.array([float(x) for x in out.split() if x.strip() not in ('', 'N/A')])


def normalize(src, dst, start=None, end=None, max_height=720):
    """Trim, apply rotation, cap the height and re-encode as H.264 with faststart; the frame rate is kept."""
    args = ['ffmpeg', '-v', 'error', '-y']
    if start is not None:
        args += ['-ss', f'{start:.3f}']
    if end is not None:
        args += ['-to', f'{end:.3f}']
    args += ['-i', str(src), '-vf', f"scale=-2:'min({max_height},ih)'", '-c:v', 'libx264', '-preset', 'veryfast',
             '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(dst)]
    subprocess.run(args, check=True)
    return dst


def gray_frames(path):
    """Yield every decoded frame as a uint8 grayscale array."""
    meta = probe(path)
    w, h = meta['width'], meta['height']
    proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'gray', '-'],
                            stdout=subprocess.PIPE)
    try:
        while True:
            buf = proc.stdout.read(w * h)
            if len(buf) < w * h:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w)
    finally:
        proc.stdout.close()
        proc.wait()


def duplicate_flags(frames):
    """True where a frame is byte-identical to the previous one (re-encode padding)."""
    flags, last = [], None
    for f in frames:
        digest = hashlib.md5(f.tobytes()).digest()
        flags.append(digest == last)
        last = digest
    return np.array(flags, bool)
