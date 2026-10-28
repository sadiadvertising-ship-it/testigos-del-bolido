# Testigos del Bólido

**Colombia has no fireball camera network. Its phones can be one.**

When a fireball crosses the sky, people film it with phones, dashcams and security cameras. Testigos del Bólido ("fireball
witnesses") is an agent that turns those witness videos into a trajectory with error bars, a speed and a verdict: a
natural meteor, a re-entering satellite, or not enough evidence to tell. It was checked against the published solutions
for the Chelyabinsk fireball of 2013 and pointed at a green fireball seen over Colombia on 30 July 2025, which has no
published trajectory. Today it needs cameras that stood still (a dashcam, a security camera, a phone resting on
something), and it has only been tested by day.

The Global Meteor Network's 2025 report lists 36 meteor cameras in Brazil, 11 in Mexico, 2 in Chile and none in
Colombia (Roggemans et al. 2026). When a fireball crosses Colombia, the videos people post are the only record from the
ground.

Built during the Meta Global AI Developer Hackathon (26 October to 4 November 2026) with Muse Spark and SAM 3.1.
The 3D viewer runs from this repository: `python3 -m http.server -d web 8000`, then open http://localhost:8000.

## How it works

1. **Muse Spark reads each video**: camera type, edits, on-screen clock, when the fireball shows, and landmarks a map
   could locate (`src/testigos/witness.py`).
2. **SAM 3.1 tracks the fireball** frame by frame from the phrase "bright light", the only phrase that found it
   ("fireball" and "meteor" returned nothing) (`track.py`). The agent runs it itself on any clip nobody has tracked yet.
3. **Each camera is oriented** from lines and landmarks in one frame: a camera model (pinhole with radial distortion) is
   fitted to them and to OpenStreetMap, so every pixel becomes a direction in the sky (`camera.py`). This step is not
   automated in the product yet. During development an AI coding assistant (Claude Code, not a Meta model) did it: two
   independent annotation passes measured street lines and poles from intensity profiles, and the assistant matched the
   landmarks and street bearings to OpenStreetMap. No person checked the points by hand.
4. **Planes of sight.** One camera's lines of sight to the fireball lie in a plane. Two cameras on different sides give
   two planes that cross in the trajectory, refined by least squares over every ray (`solve.py`; Ceplecha 1987,
   Borovička 1990). The speed comes from each video's own frame times.
5. **Verdict.** Natural if the speed's 95% range lies above 11 km/s (Earth's escape speed is 11.2 km/s); re-entry if it
   lies below 8.5 km/s and the passage is long; inconclusive otherwise (`verdict.py`). The range is the Monte Carlo's.

## The agent

Meta's agent workshop for this hackathon puts it as "an agent is a model that uses tools in a loop": the model decides
which tool to call, the code carries the call out and keeps the record, and checks outside the model decide whether the
work may move on. That is how the case agent works (`src/testigos/agent.py`):

- **Planner.** Muse Spark 1.3 calls the tools natively on `/v1/responses`, one call per turn, with the whole
  conversation sent each turn. It is told the rules of the case, not an order of steps.
- **Tools.** `read_witness` (Muse reads a video), `track` (SAM 3.1, run on any clip nobody has tracked), `calibration`,
  `planes`, `solve`, `check_satellite` (NASA's GLM bolide catalogue), `missing_views`, `drop_clip`, `finalize`,
  `write_report`, `request_evidence`.
- **Checks inside the tools, which the model cannot skip:**
  - `drop_clip` leaves a camera out only on a criterion the code measures: the weaker of a near-parallel pair (its
    planes cross a kept camera's under 10°, and that camera crosses the rest more widely), planes that cross every kept
    camera's under 10°, or a rise of every other camera's residual by more than 25% and 0.1°.
  - `finalize` re-solves the chosen cameras and refuses them when an oriented camera was left out without an accepted
    drop, when a much wider pair was left aside, or when an added camera raises every other camera's residual.
  - `write_report` writes the report in English and Spanish. Every figure must match a tool result of the run, as the
    same kind of quantity: a convergence angle cannot pass as a speed (`verify.py`). Hemisphere letters must agree, and
    the text must not state a verdict other than the code's, which the code writes at the top. An open case's report
    waits until the satellite detections and the towns were checked. Refused drafts stay in the run record.
  - `request_evidence` stops the run until a person supplies videos, a camera position or a landmark confirmation, and
    is refused while the evidence at hand is enough.
  - Three refusals of the same check stop the run for a person.
- **A person at the end.** A run ends waiting for review (`python -m testigos review … --approve`) or for the evidence it
  asked for. A blocked run does not call the model again until one of its inputs changes or a reviewer sends notes
  (`python -m testigos resume`).
- **Records.** Every run is kept in `events/<id>/runs/<run_id>.json`, never overwritten: code version, hashes of every
  input, model, each step with its reason and result, the checks, refused drafts and the API cost.
  `python -m testigos replay <event> <run_id> --echo` re-runs a recorded run's tools offline and lists any difference.
- **The answer is out of reach.** The published solutions and every comparison with them live in `validation/`; a test
  fails if anything in `src/` reads them, and no agent input holds a value derived from them. `scripts/grade.py` grades a
  run afterwards.

What the agent did on Chelyabinsk (run `20261027T185758-cee8`, 9 steps, US$ 0.07):

```
01  calibration   2         oriented        (02: 48 oriented, 03: 10 oriented)
04  planes                  Q: 2-10 66.3°, 48-10 58.9°, 2-48 7.5°
05  solve         2+48+10   278.5° heading, 16.8° slope, 19.49 km/s
06  solve         2+10      282.1° heading, 17.5° slope, 19.65 km/s
07  drop_clip     48        near_parallel_pair, confirmed by the code: its planes cross Kamensk's at 7.5°,
                            and Kamensk crosses Korkino at 66.3° against Tyumen's 58.9°
08  finalize      2+10      accepted by the code
09  write_report            figures traced: es 29 of 29, en 22 of 22 -> awaiting review
```

This is the case's second run. The first (`20261027T132419-a996`) chose the same cameras, but it dropped Tyumen citing a
rise in residuals that was below the code's own threshold, and the code then checked only that the reason quoted numbers
from the tools. Its report quoted the fit's formal speed error, ±0.29 km/s, and called the geometry solid. Diego Burbano
signed it off. A review that evening caught both. Drops now need a criterion the code measures, the verdict and the report
read the Monte Carlo's range, and the run went back with the reviewer's notes (`python -m testigos resume … --notes`).
Replayed with today's code, the first run's drop of Tyumen no longer goes through and its `finalize` is refused.

The second run (`20261027T183453-9c57`) passed every check, and its Spanish report still said the uncertainty came from
a short baseline. That is false: the two cameras are 173 km apart and their planes cross at 66°. No figure was wrong,
so no check could catch it; Diego Burbano did, and sent the report back (`review --reject --notes`). The third run is
the one above, waiting for his signature. Each review is kept in the run record's history.

## Validation: Chelyabinsk, 15 February 2013

The case holds eight witness videos chosen from the Ondřejov catalogue of Chelyabinsk videos (Borovička et al. 2016):
cameras that stood still, with buildings or streets in view. Two more were no longer online. Three of the cameras could
be oriented: Kamensk-Uralskiy (a stopped car), Korkino (a standing car) and Tyumen (a car at a traffic light). The agent
kept Kamensk-Uralskiy and Korkino, 173 km apart, whose planes cross at 66°, and left Tyumen out as the weaker of a
near-parallel pair: its planes cross Kamensk-Uralskiy's at 7.5°.

| | This agent | CBET 3423 | Refereed, 2013 | Zuluaga, Ferrín & Geens |
|---|---|---|---|---|
| Heading (azimuth of motion) | 282.1° (Monte Carlo 1σ 275.8–282.6°) | 279.5° | | 285° |
| Slope below the horizontal | 17.5° (1σ 16.4–17.6°) | 16.5° | 17.0° at the end | 15.8° |
| Speed | 19.65 km/s by the fit; Monte Carlo median 17.6 km/s (1σ 14.9–20.3) | 17.5 ± 0.5 km/s | 19.03 ± 0.13 and 19.16 ± 0.15 km/s | |
| Height where CBET puts the main flare | 29.2 km on our line (1σ 24.9–34.0 km) | 31.7 km | brightest at 29.7 km | |
| Distance from CBET's end point to our line | 3.7 km | | | |

The refereed values are Borovička et al. (2013, Nature) and Popova et al. (2013, Science); CBET 3423 was the same team's
preliminary telegram. The Monte Carlo (`scripts/montecarlo.py`, 500 draws) re-fits both cameras from perturbed evidence
on every draw: line and landmark pixels, street bearings, camera positions (8 m), Korkino's field of view (anywhere from
76 to 95°) and distortion, the SAM points, and each camera's clock. Its median heading sits 2.8° from the fit's because
the field of view it draws is wider on average than the fit's 79.5°.

`scripts/grade.py` graded the run afterwards with the criteria written before the work (committed on 26 October, 20:33,
before the first camera was calibrated at 21:25): heading within 3°, slope within 3°, flare height within 5 km and end
point within 15 km pass; speed within 1.5 km/s of CBET's 17.5 does not (4 of 5). Against the refereed speeds, a
comparison added after the run, the fit's 19.65 km/s is within 0.62 km/s.

Three checks that do not use any published value:

- **Tyumen, held out.** Its 223 lines of sight miss the Kamensk-Uralskiy and Korkino path by 0.45° (median; 90% within
  0.54°), and its own clock gives 19.17 ± 0.08 km/s along it (`scripts/holdout.py`).
- **Why Tyumen is out.** With all three cameras, 62 of 200 Monte Carlo draws slide more than 10° off the heading or below
  a 12° slope, because Kamensk-Uralskiy's and Tyumen's nearly parallel planes pull the fit along their shared plane;
  with Kamensk-Uralskiy and Korkino, 4 of 500 do.
- **SAM against a brightness threshold.** The numpy baseline that runs beside SAM, fed to the same solver on the same
  frames, gives a heading of 303.7° and a speed of 0.01 km/s for the same two cameras: it follows the glare
  (`scripts/sam_vs_threshold.py`). With SAM's points, 282.1° and 19.65 km/s.

What these numbers do not say:

- **The validation is blind for the agent, not for the calibration.** The camera fits were curated with CBET in view:
  Tyumen was recalibrated after missing CBET's plane by 3.4°, and Plast was left without a camera after missing by 9.3°
  (`validation/chelyabinsk-2013/history/`).
- **Korkino's field of view is the dominant systematic.** Its 480×360 frame cannot pin it. The fit uses 79.5°, where
  Korkino's speed agrees with Kamensk-Uralskiy's; an earlier fit gave 91.9°, which turns the heading to about 276°.
- **The head point changes definition mid-track.** It is the leading end of a streak and the centre of a round glow.
  Kamensk-Uralskiy's frames before the change give a 16.2° slope and 16.8 km/s; after it, 20.3° and 19.1 km/s. The
  Monte Carlo does not draw this choice.
- **One validated case.** Iberia 2024, a night fireball planned as a second check, was not attempted.

## Open case: Colombia, 30 July 2025

At 10:50 pm Colombian time a green fireball crossed the sky. The Geostationary Lightning Mapper on GOES-19 recorded a
1.05 s flash at 6.46° N, 72.21° W, which NASA's analysts classified as a bolide, with medium confidence and lightning
nearby. The only video analysed so far was filmed in Medellín, 373 km away: a handheld phone video that replays the
moment in cuts. The agent ran SAM 3.1 on it, which found the flash in 79 of 132 frames, but nothing in view can be located
on a map and the filming spot is unknown, so the camera cannot be oriented. Security-camera and dashcam clips from
Bogotá and Medellín, reposted on 1 August 2025, have not been analysed yet.

Was it space junk? No satellite or rocket re-entry in the Aerospace Corporation's CORDS database has a predicted window
that includes the flash: the nearest, OBJECT C, was due 2.1 hours after it, and STARLINK-2038 8.1 hours before
(`events/colombia-2025-07-30/reentries.json`). The database lists tracked objects only, so the speed still has to
decide, and the speed needs a trajectory.

With fewer than two oriented cameras the agent reports insufficient geometry and asks for what would close it: videos
from Málaga, Saravena and San Gil, where the flash would have stood 20° to 50° above the horizon. Run
`20261027T184659-28c2` (6 steps, US$ 0.05) is blocked waiting for them (`events/colombia-2025-07-30/requests.json`). It
resumed the run before it, `20261027T183335-867d`, when the re-entry listing was added; that earlier run is where the
agent tracked the Medellín clip with SAM 3.1 itself:

```
01  track            medellin   SAM 3.1: the flash in 79 of 132 frames, window 1.2-4.2 s     (run 867d)
02  calibration      medellin   not oriented
03  finalize                    accepted: insufficient geometry
04  check_satellite             1 GOES-19 detection; no re-entry window includes it           (run 28c2)
05  missing_views               towns: Málaga, Saravena, San Gil, Pamplona
06  write_report                figures traced: es 24 of 24, en 42 of 42                      (run 28c2)
07  request_evidence            blocked: waiting for videos from Málaga, Saravena and San Gil
```

The case's first run wrote its report before checking the satellite, and that report claimed two videos that do not
exist. An open case's report now waits for both checks, and its facts say which clips have a video.

Separately, on 27 October the author asked Colombian astronomers to review these results and for videos of the
fireball; none has reviewed them yet. A Colombian team studied the fireballs of 31 May 2024 (Araujo-Salcedo et al.
2024, a poster at the VIII Colombian Congress of Astronomy).

## Built during the hackathon, and what came before

Everything in this repository was written during the event: the first commit is from 26 October 2026, 20:25 Colombian
time, after the kickoff, and the code was written with an AI coding assistant (Claude Code). What came before: the method
(Ceplecha 1987; Borovička 1990), the published solutions used to grade (CBET 3423; Borovička et al. 2013; Popova et al.
2013; Zuluaga, Ferrín & Geens 2013), the Ondřejov catalogue of camera sites (Borovička et al. 2016), OpenStreetMap,
NASA's GLM bolide catalogue, and the witness videos, which belong to their authors.

## Meta models

| Model | Used for |
|---|---|
| `muse-spark-1.3` | the agent's planner, with native tool calling; the reports; retries when 1.2 loops |
| `muse-spark-1.2` | reading the witness videos under a strict JSON schema |
| `sam-3.1` | tracking the fireball through each video, inside the agent's loop when a clip is new |

What Muse saw, against what was measured later: in Kamensk-Uralskiy it named the chapel the orientation depends on and
put it at 0.89 of the frame's width, where the point matched to OpenStreetMap sits at 0.884, about 8 pixels away; it read
the dashcam clock as 09:20:18, two seconds before CBET's time in local hours; in Korkino it read a clock 22 minutes off,
which is why the method uses each video's frame times and never its clock; in Tyumen it missed the power tower the
orientation uses. Muse Spark 1.2 ran to its token cap on 4 of its 11 video reads; the retries recovered all of them.

API spending is capped in code (`TESTIGOS_BUDGET_USD` a day, `TESTIGOS_TOTAL_BUDGET_USD` in total) and logged per call in
`out/costs.jsonl`: US$ 2.60 for the whole project so far.

## Run it

```
python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e '.[test]'
.venv/bin/python -m pytest                          # offline: geometry, report check, agent checks, replay
.venv/bin/python -m testigos replay chelyabinsk-2013 20261027T185758-cee8 --echo   # the agent's tools again, no API key
.venv/bin/python scripts/grade.py chelyabinsk-2013  # grades the newest run against validation/
.venv/bin/python scripts/triangulate.py 2 10        # the two-camera solution and the CBET gate
.venv/bin/python scripts/holdout.py                 # Tyumen as a held-out witness
.venv/bin/python scripts/sam_vs_threshold.py        # SAM 3.1 against a brightness threshold
.venv/bin/python scripts/montecarlo.py 500 2 10     # the uncertainty (about half an hour)
.venv/bin/python scripts/export_web.py && python3 -m http.server -d web 8000
```

Running the agent itself needs a Meta Model API key: copy `.env.example` to `.env`, fill in `MODEL_API_KEY`, then
`.venv/bin/python -m testigos run chelyabinsk-2013` (about US$ 0.10 to 0.20 a run).

## Data, credits and privacy

The witness videos are not in this repository, and neither are their frames. `events/<id>/credits.json` names each
video's source, uploader, permission status and where its camera position comes from. Only SAM pixel tracks and numbers
derived from them are published. Muse's readings keep no transcript of what the witnesses say (three short ones were in
earlier commits). The Chelyabinsk camera positions are the Ondřejov catalogue's as published (cars on public roads and
security cameras), and the viewer rounds them to about 100 m. No witness's home location is published.

Chelyabinsk videos, by YouTube uploader: Aleksandr Ivanov (Kamensk-Uralskiy), Никита Зенкович (Korkino), Alexander
Voronov (Tyumen), MrKuzaman (Beloretsk), 🫐 голубика🫐 (Chebarkul), Мясников Сергей (Yekaterinburg), Сергей Давлеткулов
(Magnitogorsk), Максим Речинский (Plast). Colombia: the Medellín video posted by Santiago Garces (@GarcesUwu), who
credits it to Håskę Bräyãn.

## Limits

- Orienting a camera is not automated: the lines and landmarks were marked offline during development, and the agent
  cannot yet do it from OpenStreetMap alone.
- Handheld videos are not supported: the camera must stay still while the fireball crosses. Night videos are untested.
- The verifier checks every figure, its kind of quantity, the hemispheres and the verdict; it cannot judge other
  qualitative claims, and a bare small integer can still match an unrelated result.
- GLM gives where a flash projects onto a reference altitude, not the fireball's height.

## References

- Ceplecha, Z. (1987). Geometric, dynamic, orbital and photometric data on meteoroids from photographic fireball
  networks. Bull. Astron. Inst. Czechosl. 38, 222.
- Borovička, J. (1990). The comparison of two methods of determining meteor trajectories from photographs. Bull. Astron.
  Inst. Czechosl. 41, 391.
- Borovička, J., Spurný, P., Shrbený, L. (2013). CBET 3423.
- Borovička, J. et al. (2013). The trajectory, structure and origin of the Chelyabinsk asteroidal impactor. Nature 503,
  235. doi:10.1038/nature12671
- Popova, O. P. et al. (2013). Chelyabinsk airburst, damage assessment, meteorite recovery, and characterization.
  Science 342, 1069. doi:10.1126/science.1242642
- Borovička, J. et al. (2016). A&A, doi:10.1051/0004-6361/201526680 (the catalogue of Chelyabinsk video sites).
- Zuluaga, J. I., Ferrín, I., Geens, S. (2013). The orbit of the Chelyabinsk event impactor as reconstructed from
  amateur and public footage. arXiv:1303.1796.
- Araujo-Salcedo, A. V. et al. (2024). Bólidos en el cielo colombiano: estudio y documentación del fenómeno del 31 de
  mayo de 2024. Poster, VIII Congreso Colombiano de Astronomía (CoCoA), Universidad Industrial de Santander.
- Roggemans, P. et al. (2026). Global Meteor Network report 2025. eMeteorNews 2026-2.
- NASA neo-bolide catalogue (GOES GLM): https://neo-bolide.ndc.nasa.gov

## License

MIT (see `LICENSE`).
