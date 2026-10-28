"""Title cards for the demo video: four 1920x1080 cards of text, in the background, font and colours of
scripts/track_cards.py.

  title-a-before-and-during.png    what came before the hackathon and what was built during it
  title-b-meteor-cameras.png       the Global Meteor Network's camera counts (GMN_CAMERAS below, with their source)
  title-c-sam-vs-threshold.png     SAM 3.1 against a brightness threshold, on the same two cameras and frames
  title-d-filmed-it.png            the call for videos, with the address of the witness page (web/enviar.html)
The script reads validation/chelyabinsk-2013/sam-vs-threshold.json for every number on the third card, and stops if a
field is missing. It also reads the font: /System/Library/Fonts/Helvetica.ttc, which macOS ships, or the files named
with --font and --bold. The cards go to out/demo/cards/, which git ignores.
Usage: .venv/bin/python scripts/title_cards.py [--out DIR] [--font PATH] [--bold PATH]
"""
import argparse
import json
import pathlib
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from track_cards import HELVETICA, INK, INK2, NIGHT, ROOT, SS, TRACK, H, W, font, use_fonts  # noqa: E402

# Cameras per country that produced meteor orbits in 2025: Table 5 of the Global Meteor Network's report, which
# counts only cameras with meteors paired with another camera (GMN_SOURCE)
GMN_REPORT = 'Global Meteor Network, 2025 report: cameras that produced meteor orbits'
GMN_SOURCE = 'Roggemans et al. 2026, eMeteorNews 2026-2, Table 5'
GMN_CAMERAS = {'Brazil': 36, 'Mexico': 11, 'Chile': 2, 'Colombia': 0}

COMPARISON = ROOT / 'validation' / 'chelyabinsk-2013' / 'sam-vs-threshold.json'
PAIR = '2+10'  # the solution from two cameras, Kamensk-Uralskiy (2) and Korkino (10)
# web/ is published at the site's root (.github/workflows/pages.yml), so web/enviar.html is served here
WITNESS_PAGE = 'sadiadvertising-ship-it.github.io/testigos-del-bolido/enviar.html'
MARGIN = 160  # left and right margin of the text
NAME = pathlib.Path(__file__).name
KEEP = '\u00a0'  # a no-break space: drawn as a space, but a line never breaks there (a number and its unit)


def words(runs):
    """Runs of (text, font, colour) as words, each a list of (text, font, colour) pieces. Words break at spaces; a run
    that starts without a space continues the word before it."""
    out, glued = [], False
    for text, f, fill in runs:
        for i, part in enumerate(text.split(' ')):
            if i:
                glued = False
            if part:
                if glued:
                    out[-1].append((part, f, fill))
                else:
                    out.append([(part, f, fill)])
                glued = True
    return out


def wrap(runs, width):
    """The runs broken into lines of words no wider than `width` (1920x1080 pixels)."""
    lines, line, x = [], [], 0.0
    for word in words(runs):
        wide = sum(f.getlength(t) for t, f, _ in word) / SS
        space = word[0][1].getlength(' ') / SS if line else 0.0
        if line and x + space + wide > width:
            lines.append(line)
            line, x, space = [], 0.0, 0.0
        line.append(word)
        x += space + wide
    return lines + [line] if line else lines


def para(runs, size, before=0, leading=1.25, indent=0.0):
    """A paragraph: runs of (text, bold, colour) at `size` px, `before` px below the one above it, its lines starting
    `indent` px right of the margin."""
    return {'runs': [(t, font(size, bold), fill) for t, bold, fill in runs], 'size': size, 'before': before,
            'leading': leading, 'indent': indent}


def width(text, size, bold=False):
    """The width of one line of text, in 1920x1080 pixels."""
    return font(size, bold).getlength(text) / SS


def card(paragraphs, path, foot=None, centre=0.47):
    """Draw the paragraphs left-aligned at MARGIN, the block's middle at `centre` of the height, and an optional foot
    line (text, size, colour) at the bottom; save the card to path."""
    img = Image.new('RGB', (W * SS, H * SS), NIGHT)
    d = ImageDraw.Draw(img)
    laid = [(p, wrap(p['runs'], W - 2 * MARGIN - p['indent'])) for p in paragraphs]
    # each line is leading x size tall, its baseline at 0.8 of the size below the line's top
    tall = sum(p['before'] + len(lines) * p['leading'] * p['size'] for p, lines in laid) - laid[0][0]['before']
    y = centre * H - tall / 2
    for i, (p, lines) in enumerate(laid):
        y += p['before'] if i else 0
        for line in lines:
            x, base = MARGIN + p['indent'], y + 0.8 * p['size'] + (p['leading'] - 1) * p['size'] / 2
            for j, word in enumerate(line):
                if j:
                    x += word[0][1].getlength(' ') / SS
                for t, f, fill in word:
                    d.text((x * SS, base * SS), t, font=f, fill=fill, anchor='ls')
                    x += f.getlength(t) / SS
            y += p['leading'] * p['size']
    if foot:
        text, size, fill = foot
        d.text((MARGIN * SS, (H - 72) * SS), text, font=font(size), fill=fill, anchor='ls')
    path.parent.mkdir(parents=True, exist_ok=True)
    img.resize((W, H), Image.LANCZOS).save(path)
    return path


def camera_counts(cameras):
    """['36 in Brazil', '11 in Mexico', '2 in Chile', 'none in Colombia'] from GMN_CAMERAS."""
    return [f"{n if n else 'none'} in {country}" for country, n in cameras.items()]


def comparison(path=COMPARISON, pair=PAIR):
    """{'sam': (heading, speed), 'threshold': (heading, speed)} of the two-camera solution, read from the file now;
    stops with one line naming the field when one is missing or is not a number."""
    where = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        sys.exit(f'{NAME}: cannot read {where} ({e.strerror if isinstance(e, OSError) else e})')
    out = {}
    for method in ('sam', 'threshold'):
        values = []
        for field in ('azimuth_deg', 'speed_kms'):
            keys, node = ('solutions', pair, method, field), data
            for depth, key in enumerate(keys):
                if not isinstance(node, dict) or key not in node:
                    sys.exit(f"{NAME}: {where} has no field {' > '.join(keys[:depth + 1])}")
                node = node[key]
            if isinstance(node, bool) or not isinstance(node, (int, float)):
                sys.exit(f"{NAME}: in {where}, {' > '.join(keys)} is {json.dumps(node)}, not a number")
            values.append(node)
        out[method] = tuple(values)
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', type=pathlib.Path, default=ROOT / 'out' / 'demo' / 'cards')
    ap.add_argument('--font', type=pathlib.Path, metavar='PATH',
                    help=f'font file for the text (default {HELVETICA}, which macOS ships)')
    ap.add_argument('--bold', type=pathlib.Path, metavar='PATH',
                    help='font file for the bold text (default face 1 of Helvetica.ttc; with --font alone, that font)')
    args = ap.parse_args(argv)
    use_fonts(args.font, args.bold)
    numbers = comparison()  # before any card is drawn, so a missing field stops the script with no card half made
    if not (ROOT / 'web' / 'enviar.html').is_file():
        sys.exit(f'{NAME}: web/enviar.html is missing, so the address on the last card would lead nowhere')
    out = args.out

    made = [card([
        para([('Before this hackathon:', True, INK2),
              (" a 1987 method, published data, OpenStreetMap, NASA's satellite catalogue and strangers' videos.",
               False, INK2)], 54),
        para([(f'Built during it, from 26{KEEP}October, with an AI coding assistant:', True, TRACK),
              (' the agent, its checks and this viewer.', False, INK)], 54, before=64),
    ], out / 'title-a-before-and-during.png')]

    counts = camera_counts(GMN_CAMERAS)
    made.append(card([
        para([(f'{GMN_REPORT}:', False, INK2)], 44),
        para([(', '.join(counts[:-1]) + ',', False, INK)], 64, before=28),
        para([(f'{counts[-1]}.', True, TRACK)], 64),
    ], out / 'title-b-meteor-cameras.png', foot=(GMN_SOURCE, 32, INK2)))

    (sam_heading, sam_speed), (thr_heading, thr_speed) = numbers['sam'], numbers['threshold']
    sam, thr = 'SAM 3.1:', 'A brightness threshold:'
    made.append(card([
        para([('Same two cameras, same frames.', False, INK2)], 44),
        # the two colons line up, so the headings and the speeds sit one above the other
        para([(sam, True, TRACK), (f' heading {sam_heading:.1f}°, speed {sam_speed:.2f}{KEEP}km/s.', False, INK)],
             58, before=40, indent=width(thr, 58, True) - width(sam, 58, True)),
        para([(thr, True, INK2), (f' heading {thr_heading:.1f}°, speed {thr_speed:.2f}{KEEP}km/s.', False, INK)],
             58, before=8),
    ], out / 'title-c-sam-vs-threshold.png'))

    made.append(card([
        para([('¿Lo grabaste?', True, INK), (' Filmed it?', False, INK2)], 96),
        para([(WITNESS_PAGE, False, TRACK)], 56, before=36),
        para([('Colombia has no fireball camera network. Its phones can be one.', False, INK2)], 44, before=72),
    ], out / 'title-d-filmed-it.png'))
    for path in made:
        print(path)


if __name__ == '__main__':
    main(sys.argv[1:])
