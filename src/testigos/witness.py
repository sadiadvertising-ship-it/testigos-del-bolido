"""Muse Spark reads one witness video and says what the geometry needs from it.

Muse proposes; it never measures. Its pixel positions and times are seeds for SAM and for the
landmark picker, and every number in a trajectory comes from SAM tracks and the camera model.
"""
from __future__ import annotations

from . import api

LANDMARK_KINDS = ['church', 'tower', 'chimney', 'antenna', 'building', 'bridge', 'ridge', 'peak', 'moon', 'sun',
                  'street_lamp', 'traffic_light', 'pylon', 'road', 'other']

SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'clip_kind': {'type': 'string', 'enum': ['phone_handheld', 'phone_tripod', 'dashcam_moving', 'dashcam_parked',
                                                 'security_fixed', 'compilation', 'screen_recording', 'other']},
        'camera_moves': {'type': 'boolean'},
        'edits': {'type': 'object', 'additionalProperties': False,
                  'properties': {'slow_motion': {'type': 'boolean'}, 'mirrored': {'type': 'boolean'},
                                 'cropped_or_zoomed': {'type': 'boolean'}, 'music_overlay': {'type': 'boolean'},
                                 'multiple_cuts': {'type': 'boolean'}},
                  'required': ['slow_motion', 'mirrored', 'cropped_or_zoomed', 'music_overlay', 'multiple_cuts']},
        'onscreen_clock': {'type': ['object', 'null'], 'additionalProperties': False,
                           'properties': {'text': {'type': 'string'}, 'at_video_s': {'type': 'number'}},
                           'required': ['text', 'at_video_s']},
        'fireball': {'type': 'object', 'additionalProperties': False,
                     'properties': {'first_s': {'type': 'number'}, 'last_s': {'type': 'number'},
                                    'enters_from': {'type': 'string'}, 'exits_to': {'type': 'string'},
                                    'flare_times_s': {'type': 'array', 'items': {'type': 'number'}},
                                    'fragments': {'type': 'boolean'}, 'color': {'type': 'string'}},
                     'required': ['first_s', 'last_s', 'enters_from', 'exits_to', 'flare_times_s', 'fragments', 'color']},
        'landmarks': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'name_guess': {'type': 'string'}, 'kind': {'type': 'string', 'enum': LANDMARK_KINDS},
                           'frame_s': {'type': 'number'}, 'x_frac': {'type': 'number'}, 'y_frac': {'type': 'number'},
                           'distance_guess_m': {'type': ['number', 'null']}, 'osm_hint': {'type': 'string'},
                           'confidence': {'type': 'number'}},
            'required': ['name_guess', 'kind', 'frame_s', 'x_frac', 'y_frac', 'distance_guess_m', 'osm_hint', 'confidence']}},
        'location_hints': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'text': {'type': 'string'}, 'source': {'type': 'string', 'enum': ['sign', 'language', 'skyline', 'speech', 'overlay', 'other']}},
            'required': ['text', 'source']}},
        'sound': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'t_s': {'type': 'number'}, 'kind': {'type': 'string', 'enum': ['boom', 'rumble', 'shout', 'speech', 'music', 'engine', 'none']},
                           'confidence': {'type': 'number'}},
            'required': ['t_s', 'kind', 'confidence']}},
        'transcript': {'type': 'string'},
        'usable_for_geometry': {'type': 'boolean'},
        'reason': {'type': 'string'},
    },
    'required': ['clip_kind', 'camera_moves', 'edits', 'onscreen_clock', 'fireball', 'landmarks', 'location_hints',
                 'sound', 'transcript', 'usable_for_geometry', 'reason'],
}

PROMPT = """You are reading one witness video of a fireball (a very bright meteor) for a scientific trajectory
reconstruction. Report only what you can see or hear; do not guess the trajectory.
- clip_kind and camera_moves: is the camera fixed, parked, handheld or driving, and does it move during the fireball?
- edits: slow motion, mirroring, cropping or zoom, music, cuts.
- onscreen_clock: copy any clock or date overlay exactly, with the video second where you read it; null if none.
- fireball: the video seconds when it is first and last visible, where it enters and leaves the frame
  (for example "top left", "right edge"), flare times, whether it fragments, its colour.
- landmarks: distinct, fixed, surveyable objects that a map could locate (church domes, towers, chimneys, antennas,
  tall buildings, bridges, mountain peaks or ridges, the Sun or Moon). For each give the video second of a clear frame,
  its position as a fraction of the frame width (x_frac, 0 = left) and height (y_frac, 0 = top) at its top point,
  a distance guess in metres if you can, a short OpenStreetMap search hint (for example "orthodox church with a bell tower"),
  and your confidence from 0 to 1. Street lamps and traffic lights are allowed but rank last.
- location_hints: signs, language, skyline or speech that hint where the camera is.
- sound: times of a boom, rumble, shouts or speech; "none" if the video is silent.
- transcript: what people say, in the original language.
- usable_for_geometry: false if the fireball is never clearly visible or the camera moves throughout; say why in reason."""


def read(file_id, video_s, purpose=''):
    content = [{'type': 'input_text', 'text': PROMPT}, {'type': 'input_video', 'file_id': file_id}]
    return api.spark(content, schema=SCHEMA, max_output_tokens=6000, input_tokens_guess=int(4000 + 1500 * video_s),
                     purpose=purpose or 'witness read')
