import numpy as np

from testigos.track import blob_track, bright_centroid, dominant, parse

# The example line from dev.meta.ai/docs/sam/segmenting, with mask payloads shortened.
DOC_LINE = ('<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,~abc|>,'
            '1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,48,~def|>')


def test_parse_documented_line():
    frames = parse(DOC_LINE)
    assert list(frames) == [0]
    a, b = frames[0]
    assert (a['id'], a['x1'], a['y2'], a['w'], a['h']) == (0, 211, 254, 320, 334)
    assert b['id'] == 1 and b['x1'] == 155


def test_parse_frames_out_of_order_with_confidence():
    text = ('<12f>0<|box;x1=10;y1=10;x2=20;y2=20;w=100;h=50;c=0.96|><|mask;x=0;y=0;data=1,!z;c=0.9|>\n'
            '<3f>0<|box;x1=1;y1=2;x2=3;y2=4;w=100;h=50;c=0.5|><|mask;x=0;y=0;data=1,!z|>\n<4f>\n')
    frames = parse(text)
    assert sorted(frames) == [3, 4, 12]
    assert frames[12][0]['c'] == 0.96 and frames[4] == []


def test_dominant_keeps_the_most_persistent_object():
    frames = parse('<0f>0<|box;x1=1;y1=1;x2=2;y2=2;w=9;h=9|>,1<|box;x1=5;y1=5;x2=6;y2=6;w=9;h=9|>'
                   '<1f>1<|box;x1=5;y1=5;x2=7;y2=7;w=9;h=9|><2f>1<|box;x1=6;y1=6;x2=8;y2=8;w=9;h=9|>')
    kept = dominant(frames)
    assert sorted(kept) == [0, 1, 2] and all(b['id'] == 1 for b in kept.values())


def _image(shape, cx, cy, sigma=2.0, peak=215.0, background=40.0):
    ys, xs = np.indices(shape)
    blob = peak * np.exp(-((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma ** 2))
    return np.clip(background + blob, 0, 255).astype(np.uint8)


def test_bright_centroid_finds_the_core_and_rescales_boxes():
    img = _image((360, 640), 300.4, 120.7)
    c = bright_centroid(img, {'x1': 140, 'y1': 50, 'x2': 160, 'y2': 70, 'w': 320, 'h': 180})
    assert np.hypot(c[0] - 300.4, c[1] - 120.7) < 0.5


def test_blob_track_follows_a_moving_saturated_blob():
    frames = [_image((120, 200), 20 + 10 * i, 30 + 3 * i, sigma=3, peak=400, background=0) for i in range(8)]
    pts = blob_track(frames)
    for i, p in enumerate(pts):
        assert np.hypot(p[0] - (20 + 10 * i), p[1] - (30 + 3 * i)) < 0.6
