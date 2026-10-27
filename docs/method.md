# Method

How a set of witness videos becomes a trajectory, a speed and a verdict, and how the agent and its checks sit on top.
Every step names the file that does it.

## 1. Frames and directions (`src/testigos/geo.py`)

Positions are WGS84 latitude, longitude and height, converted to Earth-centred Earth-fixed (ECEF) coordinates for all
geometry. At each camera a local east-north-up (ENU) frame turns a direction into azimuth (clockwise from north) and
elevation. A line of sight is a unit vector in ENU, and in ECEF once rotated by the camera site's ENU basis.

## 2. Camera model (`src/testigos/camera.py`)

A camera has a yaw, pitch and roll (its orientation in the local frame), a horizontal field of view `hfov` and a radial
distortion `k1`, on an image `width × height`.

- Pinhole: the focal length in pixels is `f = (width/2) / tan(hfov/2)`. A direction with normalised image coordinates
  `(x, y)` lands at pixel `(width/2 + f·x·s, height/2 + f·y·s)` with `s = 1 + k1·(x² + y²)`; `k1 < 0` is barrel
  distortion, usual in dashcams.
- Equidistant fisheye: the radius on the image is `r = f·θ·(1 + k1·θ²)` for an angle `θ` from the optical axis, with
  `f = (width/2) / (hfov/2)`.

`unproject` inverts both by fixed-point iteration, so every pixel becomes a direction.

## 3. Orienting a camera (`camera.fit`, `scripts/stations.py`)

Evidence is marked in one frame of the video, and the fit finds the camera parameters that explain it, by least squares
with a soft-L1 loss (scale 3 px), all residuals in pixels. This step is not automated in the product yet. During
development an AI coding assistant (Claude Code, not a Meta model) did it: two independent annotation passes measured
the lines from intensity profiles, and the assistant matched the landmarks and street bearings to OpenStreetMap. No
person checked the points by hand; every point file and every fit residual is in `events/chelyabinsk-2013/`.



| Evidence | What it pins | Residual |
|---|---|---|
| Landmark with known coordinates (OpenStreetMap, a church or a tower) | orientation and field of view | pixel distance between the projected landmark and the marked pixel |
| Object of unknown height (only its x counts) | yaw | horizontal pixel difference |
| Plumb line (a pole, a building corner) | roll and distortion | spread of azimuths along the line |
| Straight edge (a roof, a kerb) | distortion | distance of its rays from one common plane |
| Edge parallel to a known direction (a street, with its bearing from OSM) | yaw and pitch through the vanishing point | distance of its rays from the plane they share with that direction |
| Distant flat horizon | pitch and roll | elevation difference |

Parallel edges alone leave the rotation about the vanishing point free; vertical lines close it. Korkino's 480×360 frame
cannot pin its field of view or its distortion, so `k1` is fixed at −0.15 (a typical wide dashcam) and the field of view
at 79.5°, the value where Korkino's speed agrees with Kamensk's; CBET is not used. The fits leave 0.03 to 0.07° of
residual (`events/chelyabinsk-2013/calibration.json`). Measured against the plane that CBET's published path makes with
each camera, the cameras are off by 0.62° (Kamensk-Uralskiy), 0.98° (Tyumen) and 3.39° (Korkino); that check uses the
published answer, so it lives in `validation/chelyabinsk-2013/calibration-vs-cbet.json`. The OSM extracts were fetched
from Overpass with curl; the annotators' notes are in `events/chelyabinsk-2013/lines-*.json` and `plumb-48.json`. The
superseded fits and solutions, each graded against CBET as the work went, are in `validation/chelyabinsk-2013/history/`.

## 4. The fireball in the image (`src/testigos/track.py`, `scripts/sam_probe.py`)

Each clip is trimmed to the fireball's window and sent to SAM 3.1 in video mode with the phrase "bright light" (the only
phrase that found it; "fireball", "meteor" and "light streak" returned nothing). SAM returns a box per frame for every
bright object, headlights included; the fireball is the object that travels farthest across the frame. Its point is
the leading edge for a streak and the centroid for a round glow; a ring-contrast test drops frames where it is not
brighter than its surroundings, a smooth cubic path drops jumps, and frames whose bytes repeat the previous frame
(md5) are flagged as duplicates and left out. Frame times are ffprobe's timestamps, not a nominal frame rate.

A plain numpy tracker runs alongside: the largest saturated blob per frame, kept only if it moves smoothly. Fed to the
same solver on the same frames, it gives a heading of 303.7° and a speed of 0.01 km/s for Kamensk-Uralskiy and Korkino,
against 282.1° and 19.65 km/s with SAM's points; on Korkino its rays sit 16.75° (median) from CBET's plane, SAM's 3.39°.
The threshold locks onto the glare, SAM onto the object (`scripts/sam_vs_threshold.py`,
`validation/chelyabinsk-2013/sam-vs-threshold.json`). The baseline is a plain threshold, not a tuned classical tracker.

The agent's `track` tool runs SAM 3.1 itself on a clip nobody has tracked yet (`track.track_video`), within the fireball
window that Muse's reading gives plus one second each side, and refuses a clip that would cost more than US$ 0.10.

## 5. Trajectory (`src/testigos/solve.py`)

Ceplecha (1987) and Borovička (1990): the lines of sight from one camera to a straight trajectory all lie in one plane
through the camera.

1. **Plane per camera.** The plane's normal is the right singular vector of the ray matrix with the smallest singular
   value. Rays farther from the plane than three robust sigmas (1.4826 × the median distance) or 0.2°, whichever is
   larger, are dropped and the plane refitted, up to three times: in flare frames the glow's centre sits off the head.
2. **Convergence angle Q.** The angle between two planes. Under 10° a pair triangulates poorly and solve() warns; under
   5° a two-camera solution is refused. Distant cameras on the same side give small Q (Kamensk and Tyumen: 7.5°); a
   camera near the path gives large Q (Kamensk and Korkino: 66°).
3. **Line.** The two planes of the widest pair intersect in a first line. Least squares then adjusts its direction and
   position over every ray of every camera, each residual being the ray's angular miss of the line, with a soft-L1 loss
   (scale 0.3°) so that outlying rays lose their pull.
4. **Along-track position and speed.** Each ray's point on the line is its closest approach. Each camera's speed is the
   slope of position against its own frame times over the first 60% of its track, before the fireball slows. Speeds
   combine by inverse variance (each error floored at 0.05 km/s). The solver reports that formal error and the spread
   between cameras over √n separately; both are far smaller than the Monte Carlo's range, which is the one the verdict
   reads. With three or more cameras, one whose speed sits more than 3σ from the median of the others (σ at least 5% of
   that median) is left out of the speed and named: its clock, not the path, is the likely fault.
5. **Nearly parallel planes.** Two cameras whose planes cross under 10° add little convergence to each other, and in a
   joint least-squares fit their many rays can pull the line along their shared plane. In Chelyabinsk's Monte Carlo the
   Kamensk-Uralskiy and Tyumen planes, 7.5° apart, come as close as 3.7°, and with all three cameras some draws slide to
   headings near 245° while Kamensk-Uralskiy and Korkino stay put. So the weaker camera of such a pair, the one that
   crosses the rest less widely, may leave the fit; it stays a check (`scripts/holdout.py`).

## 6. Uncertainty (`scripts/montecarlo.py`)

Every draw re-fits each camera from perturbed evidence and solves again: annotated line points (0.7 px), landmark pixels
(3 px), street bearings (0.7 to 1.0°), camera positions (8 m), Korkino's field of view drawn uniformly from 76 to 95°
(every value tried while calibrating it, 79.5° and 91.9°, lies inside) and its `k1` N(−0.15, 0.07), the SAM points
(1.5 px), each camera's clock scale N(1, 0.01) and every timestamp (± half a frame). The results quote the 2.5, 16, 50,
84 and 97.5 percentiles; `events/<id>/montecarlo-<cameras>.json` holds them and the agent's `solve` reads them, and the
comparison with CBET goes to `validation/`. Systematic errors outside these draws do not show up in them: a
misidentified landmark, a lens model that does not fit, or the head point's definition, which is the leading end of a
streak and the centre of a round glow, so the point jumps when the fireball's look changes mid-track.

## 7. Verdict (`src/testigos/verdict.py`)

Anything bound to the Sun hits the atmosphere faster than Earth's escape speed, 11.2 km/s; satellites and rocket stages
re-enter below orbital speed, about 7.8 km/s, slowly and for long. The rule reads a 95% speed range: the Monte Carlo's
2.5 and 97.5 percentiles when there is one, else the speed ± 2σ with σ at least 10% of the speed. Natural if the range
lies above 11 km/s; re-entry if it lies below 8.5 km/s and the passage is long (more than 20 s, or a slope under 10°);
inconclusive otherwise. The code writes the verdict sentence at the top of each report. What a solution marks is a
search strip along the ground track, not a fall zone: dark flight after the light ends is not modelled.

## 8. Satellites and missing views

`scripts/fetch_glm.py` downloads NASA's GLM bolide catalogue and keeps, per event, the detections within 30 minutes
(`events/<id>/glm-window.json`). GLM places a flash where it projects onto a reference altitude, so it gives a place,
not a height. For an open case, `events/<id>/city-geometry.json` lists towns with their distance to the GLM point, the
direction to look and the flash's elevation if it was 40 or 80 km up; towns that would see it 10° to 60° up are the
ones whose videos would close the geometry.

## 9. The agent and its checks (`src/testigos/agent.py`, `verify.py`)

Muse Spark 1.3 chooses each tool call (native tool calling on `/v1/responses`, the whole conversation resent each
turn, one call per turn, at most 16 turns); the code runs it and records it. The checks sit inside the tools:

- `drop_clip(clip, criterion)` leaves a camera out only when the code measures and confirms the criterion:
  `near_parallel_pair` (its planes cross a kept camera's under 10°, and that camera crosses the rest more widely),
  `narrow_planes` (its planes cross every kept camera's under 10°), `raises_residuals` (with three or more cameras, it
  raises every other camera's residual by more than 25% and 0.1°), or `not_oriented`. Three refusals block the run.
- `finalize(clips)` re-solves the chosen cameras. It refuses when an oriented camera is left out without an accepted
  drop, when the chosen pair's Q is more than 15° below the widest pair available, or when an added camera raises every
  other camera's residual by more than 25% and 0.1°. Three refusals block the run for a person. With fewer than two
  oriented cameras it records insufficient geometry, and the report then waits until the satellite detections and the
  towns that would close the geometry have been checked.
- `write_report` asks Muse Spark 1.3 for the report in English and Spanish and checks each with `verify.check_report`:
  every number in the text (decimal comma or point, ranges, dates, times, scientific notation; list numbers and the 1 in
  "1σ" excepted) must equal a number in the run's tool results within half a unit of its last printed digit, and a
  number printed with a unit (km/s, km, degrees, seconds, percent) must equal a result of that kind, so a convergence
  angle cannot pass as a speed. Every hemisphere letter next to a coordinate must agree with the results, and the text
  must not state a verdict other than the code's, which the code writes at the top. One retry names what was wrong; a
  second failure keeps the plain record and blocks the run. Every refused draft is kept in the run record. The check
  cannot judge other qualitative claims, and a bare small integer can still match an unrelated result.
- `request_evidence` asks a person for videos from given towns, a camera position or a landmark confirmation. It is
  refused while two cameras are oriented, before the satellite check, or while a clip with a video is unread; when
  accepted it appends the request to `events/<id>/requests.json` and blocks the run.

A run ends waiting for review or for the evidence it asked for. Each run is recorded with the code version, the hashes
of every input and every step; `resume` refuses to call the model while no input changed, and `replay` re-runs the
recorded tool calls with today's code and no model (`--echo` prints every step). The published answers live in
`validation/`, which no file in `src/` reads, and no agent input holds a value derived from them. `scripts/grade.py`
applies, after the run, the criteria written before the work: heading and slope within 3°, height at CBET's main flare
within 5 km and CBET's end point within 15 km of the line (committed on 26 October at 20:33, before the first camera was
calibrated at 21:25), and speed within 1.5 km/s (in the plan that day, committed on 27 October). A fifth criterion in
`truth.json`, a calibration residual under 0.3°, was written for landmark fits: the internal fits pass it, and
Korkino's 3.39° from CBET's plane would not. The refereed solutions that followed CBET are compared separately
(`validation/chelyabinsk-2013/refereed.json`), and that comparison never changes the pre-registered grade.

## References

- Ceplecha, Z. (1987). Bull. Astron. Inst. Czechosl. 38, 222.
- Borovička, J. (1990). Bull. Astron. Inst. Czechosl. 41, 391.
- Borovička, J., Spurný, P., Shrbený, L. (2013). CBET 3423.
- Borovička, J. et al. (2013). The trajectory, structure and origin of the Chelyabinsk asteroidal impactor. Nature 503,
  235. doi:10.1038/nature12671
- Popova, O. P. et al. (2013). Chelyabinsk airburst, damage assessment, meteorite recovery, and characterization.
  Science 342, 1069. doi:10.1126/science.1242642
- Borovička, J. et al. (2016). A&A, doi:10.1051/0004-6361/201526680.
- Zuluaga, J. I., Ferrín, I., Geens, S. (2013). arXiv:1303.1796.
- NASA neo-bolide catalogue (GOES GLM): https://neo-bolide.ndc.nasa.gov
- Roggemans, P. et al. (2026). Global Meteor Network report 2025. eMeteorNews 2026-2.
