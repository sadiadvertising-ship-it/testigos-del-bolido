"""Cuts the demo video from its pieces with ffmpeg, in one pass: the title cards and screen recordings in order, each
scene's narration laid at the scene's start, 1920x1080 at 30 frames a second.

The scenes come from a JSON list, for example:

  {"out": "demo-v1.mp4", "dir": "tomas",
   "scenes": [
     {"voice": "voz-1.m4a", "shots": [{"file": "title-a-before-and-during.png", "for": 12}]},
     {"voice": "voz-2.m4a", "shots": [{"file": "colombia.mov", "from": 3.5, "for": 10}, {"file": "title-b-meteor-cameras.png", "for": 7}]}]}

Paths are relative to the JSON's folder, then to "dir", then to out/demo/cards/. A shot is a still image held "for"
seconds, or a recording from "from" (seconds, default 0) for "for" seconds. Recordings keep no sound of their own: the
only sound is the narration, so no witness video's audio reaches the demo. The script stops before encoding if a file
is missing, if a narration runs past the end of its scene, or if the whole runs past 3:00, the hackathon's limit.
Usage: .venv/bin/python scripts/assemble_demo.py SCENES.json [--check]
"""
import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from track_cards import NIGHT, ROOT, H, W  # noqa: E402

CARDS = ROOT / 'out' / 'demo' / 'cards'
LIMIT_S, FPS = 180.0, 30
STILL = {'.png', '.jpg', '.jpeg'}


def length(path):
    """A media file's duration in seconds, as ffprobe reads it."""
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def plan(spec, here):
    """The shots and narrations with their files found and their times laid out, or SystemExit naming every problem."""
    roots = [here, here / spec.get('dir', '.'), CARDS]
    problems, shots, voices, t = [], [], [], 0.0

    def find(name):
        hit = next((r / name for r in roots if (r / name).is_file()), None)
        if hit is None:
            problems.append(f'not found: {name} (looked in {", ".join(str(r) for r in roots)})')
        return hit

    for k, scene in enumerate(spec['scenes'], 1):
        start = t
        for shot in scene['shots']:
            f, dur = find(shot['file']), float(shot['for'])
            if f is not None and f.suffix.lower() not in STILL and shot.get('from', 0) + dur > length(f) + 0.05:
                problems.append(f'scene {k}: {f.name} runs {length(f):.1f} s, short of {shot.get("from", 0)} + {dur} s')
            shots.append({'file': f, 'from': float(shot.get('from', 0)), 'for': dur})
            t += dur
        if scene.get('voice'):
            v = find(scene['voice'])
            if v is not None and length(v) > t - start + 0.05:
                problems.append(f'scene {k}: the narration runs {length(v):.1f} s, the scene {t - start:.1f} s')
            voices.append({'file': v, 'at': start})
    if t > LIMIT_S:
        problems.append(f'the whole runs {t:.1f} s, past the {LIMIT_S:.0f} s limit')
    if problems:
        raise SystemExit('\n'.join(problems))
    return shots, voices, t


def command(shots, voices, total, out):
    """One ffmpeg call: every shot scaled into the frame on the cards' background, joined, with the narrations mixed."""
    bg = '0x{:02x}{:02x}{:02x}'.format(*NIGHT)
    args, chains = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y'], []
    for i, s in enumerate(shots):
        if s['file'].suffix.lower() in STILL:
            args += ['-loop', '1', '-framerate', str(FPS), '-t', f"{s['for']:.3f}", '-i', str(s['file'])]
        else:
            args += ['-ss', f"{s['from']:.3f}", '-t', f"{s['for']:.3f}", '-i', str(s['file'])]
        chains.append(f'[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={bg},'
                      f"fps={FPS},setsar=1,format=yuv420p,trim=duration={s['for']:.3f},setpts=PTS-STARTPTS[v{i}]")
    chains.append(''.join(f'[v{i}]' for i in range(len(shots))) + f'concat=n={len(shots)}:v=1:a=0[v]')
    for j, v in enumerate(voices):
        ms = round(v['at'] * 1000)
        args += ['-i', str(v['file'])]
        chains.append(f'[{len(shots) + j}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{j}]')
    if voices:
        chains.append(''.join(f'[a{j}]' for j in range(len(voices))) + f'amix=inputs={len(voices)}:normalize=0,'
                      f'apad,atrim=duration={total:.3f}[a]')
    else:  # silence, so the file still has a sound track
        args += ['-f', 'lavfi', '-t', f'{total:.3f}', '-i', 'anullsrc=r=48000:cl=stereo']
        chains.append(f'[{len(shots)}:a]anull[a]')
    return args + ['-filter_complex', ';'.join(chains), '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium',
                   '-crf', '18', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-t', f'{total:.3f}', str(out)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('scenes', type=pathlib.Path)
    ap.add_argument('--check', action='store_true', help='lay out the scenes and stop before encoding')
    a = ap.parse_args()
    spec, here = json.loads(a.scenes.read_text()), a.scenes.resolve().parent
    shots, voices, total = plan(spec, here)
    t = 0.0
    for s in shots:
        print(f"{int(t // 60)}:{t % 60:05.2f}  {s['for']:5.1f} s  {s['file'].name}")
        t += s['for']
    print(f'{len(shots)} shots, {len(voices)} narrations, {int(total // 60)}:{total % 60:05.2f} in all')
    if a.check:
        return
    out = here / spec['out']
    subprocess.run(command(shots, voices, total, out), check=True)
    print(out, f'{length(out):.2f} s')


if __name__ == '__main__':
    main()
