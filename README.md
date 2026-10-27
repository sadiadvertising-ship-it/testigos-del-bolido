# Testigos del Bólido

**Colombia has no fireball camera network. Its phones can be one.**

When a fireball crosses the sky, people film it with phones, dashcams and security cameras. Testigos del Bólido ("fireball
witnesses") is an agent that turns those witness videos into a trajectory with error bars, a speed and a verdict: a
natural meteor, a re-entering satellite, or not enough evidence to tell. It was checked against the published solution
for the Chelyabinsk fireball of 2013 and pointed at a green fireball seen over Colombia on 30 July 2025, which has no
published trajectory.

Built during the Meta Global AI Developer Hackathon (26 October to 4 November 2026) with Muse Spark and SAM 3.1.
The 3D viewer runs from this repository: `python3 -m http.server -d web 8000`, then open http://localhost:8000.

## How it works

1. **Muse Spark reads each video**: camera type, edits, on-screen clock, when the fireball shows, and landmarks a map
   could locate (`src/testigos/witness.py`).
2. **SAM 3.1 tracks the fireball** frame by frame from the phrase "bright light", the only phrase that found it
   ("fireball" and "meteor" returned nothing) (`track.py`, run by `scripts/sam_probe.py`).
3. **Each camera is oriented.** A person marks street lines and landmarks in a frame; the code fits a camera model
   (pinhole with radial distortion) to them and to OpenStreetMap, so every pixel becomes a direction in the sky
   (`camera.py`). This step is still human work.
4. **Planes of sight.** One camera's lines of sight to the fireball lie in a plane. Two cameras on different sides give
   two planes that cross in the trajectory, refined by least squares over every ray (`solve.py`; Ceplecha 1987,
   Borovička 1990). The speed comes from each video's own frame times.
5. **Verdict.** Natural if v − 2σ > 11 km/s (Earth's escape speed is 11.2 km/s); re-entry if v + 2σ < 8.5 km/s and the
   passage is long; inconclusive otherwise (`verdict.py`).

## The agent

Meta's agent workshop for this hackathon puts it as "an agent is a model that uses tools in a loop": the model decides
which tool to call, the code carries the call out and keeps the record, and checks outside the model decide whether the
work may move on. That is how the case agent works (`src/testigos/agent.py`):

- **Planner.** Muse Spark 1.3 calls the tools natively on `/v1/responses`, one call per turn, with the whole
  conversation sent each turn. It is told the rules of the case, not an order of steps.
- **Tools.** `read_witness` (Muse reads a video), `track`, `calibration`, `planes`, `solve`, `check_satellite` (NASA's
  GLM bolide catalogue), `missing_views`, `drop_clip`, `finalize`, `write_report`, `request_evidence`.
- **Checks inside the tools, which the model cannot skip:**
  - `finalize` re-solves the chosen cameras and refuses them when an oriented camera was left out without a reason that
    cites a measured number, when a much wider pair was left aside, or when an added camera raises every other camera's
    residual. Three refusals stop the run for a person.
  - `write_report` writes the report in English and Spanish. Every figure and hemisphere letter in it must match a tool
    result of the run (`verify.py`), or the report is refused.
  - `request_evidence` stops the run until a person supplies videos, a camera position or a landmark confirmation, and
    is refused while the evidence at hand is enough.
- **A person at the end.** A run ends waiting for review (`python -m testigos review … --approve`) or for the evidence it
  asked for. A blocked run does not call the model again until one of its inputs changes (`python -m testigos resume`).
- **Records.** Every run is kept in `events/<id>/runs/<run_id>.json`, never overwritten: code version, hashes of every
  input, model, each step with its reason and result, the checks and the API cost. `python -m testigos replay` re-runs a
  recorded run's tools offline and lists any difference.
- **The answer is out of reach.** The published solutions live in `validation/`, a test fails if anything in `src/`
  reads them, and `scripts/grade.py` grades a run afterwards.

What the agent did on Chelyabinsk (run `20261027T132419-a996`, 11 steps, US$ 0.13):

```
01  read_witness  10        dashcam parked; fireball from 0.8 to 7.7 s
02  calibration   2         oriented        (03: 48 oriented, 04: 10 oriented)
05  planes                  Q: 2-10 66.3°, 48-10 58.9°, 2-48 7.5°
06  solve         2+10+48   278.5° heading, 16.8° slope, 19.49 km/s
07  solve         2+10      282.1° heading, 17.5° slope, 19.65 km/s
08  solve         48+10     282.4° heading, 17.2° slope, 19.10 km/s
09  drop_clip     48        "Pair Q 7.5 deg with clip 2 is under 10 deg and adding it raises residuals
                             from 0.687 to 0.715 deg (clip 2) and 0.824 to 0.931 deg (clip 10)"
10  finalize      2+10      accepted by the code
11  write_report            figures traced: en 16 of 16, es 17 of 17 -> awaiting review
```

Diego Burbano signed the report off on 27 October 2026.

## Validation: Chelyabinsk, 15 February 2013

The case holds eight witness videos chosen from the Ondřejov catalogue of Chelyabinsk videos (Borovička et al. 2016):
cameras that stood still, with buildings or streets in view. Two more were no longer online. Three of the cameras could
be oriented: Kamensk-Uralskiy (a stopped car), Korkino (a standing car) and Tyumen (a car at a traffic light). The agent kept Kamensk-Uralskiy and Korkino, 173 km apart, whose planes cross at 66°.

| | This agent | CBET 3423 | Zuluaga, Ferrín & Geens |
|---|---|---|---|
| Heading (azimuth of motion) | 282.1° (Monte Carlo 1σ 280.0–283.6°) | 279.5° | 285° |
| Slope below the horizontal | 17.5° (1σ 17.1–17.7°) | 16.5° | 15.8° |
| Speed | 19.65 km/s by the fit; Monte Carlo median 18.7 km/s (1σ 15.6–21.6) | 17.5 ± 0.5 km/s | |
| Height where CBET puts the main flare | 29.2 km on our line (1σ 25.3–34.1 km) | 31.7 km | |
| Distance from CBET's end point to our line | 3.7 km | | |

The Monte Carlo (`scripts/montecarlo.py`, 500 draws) re-fits both cameras from perturbed evidence on every draw: line
and landmark pixels, street bearings, camera positions (8 m), Korkino's field of view and distortion, the SAM points,
and each camera's clock. `scripts/grade.py` graded the run afterwards with criteria fixed before it: heading within 3°,
slope within 3°, flare height within 5 km and end point within 15 km pass; speed within 1.5 km/s of 17.5 does not
(4 of 5).

What these numbers do not say:

- **The slope sits outside our 2σ.** There is a systematic error the draws do not model. The likely source is
  Korkino's field of view, which its 480×360 frame cannot pin. We set it to 79.5° from speed agreement with Kamensk
  (both saw the fireball before it slowed), without using CBET. With it, Korkino's lines of sight sit 3.4° (median) from
  the plane that CBET's path makes with Korkino; the field of view that matches that plane (91.9°) turns our heading to
  about 276°.
- **Calibration residuals are internal.** The fits leave 0.03 to 0.07° (the evidence agrees with itself). Measured
  against CBET's plane, Kamensk is off by 0.62°, Tyumen by 0.98° and Korkino by 3.39°
  (`events/chelyabinsk-2013/calibration.json`).
- **The speed is the least certain number.** Kamensk's orientation hangs on a chapel 129 m away: moving the car 10 m
  changes the speed by up to 3 km/s while heading and slope barely move. The agent's own σ (0.29 km/s) is the fit's
  formal error and is far too small; the Monte Carlo is the honest one.
- **The validation is blind for the agent, not for the people.** The camera calibrations were curated with CBET in view:
  Tyumen was recalibrated after missing CBET's plane by 3.4°, and Plast was left without a camera after missing by 9.3°.
- **Iberia 2024**, a night fireball planned as a second check, was not attempted.

## Open case: Colombia, 30 July 2025

At 10:50 pm Colombian time a green fireball crossed the sky. The Geostationary Lightning Mapper on GOES-19 recorded a
1.05 s flash at 6.46° N, 72.21° W, which NASA's catalogue classifies as a bolide. The only witness video still online,
filmed in Medellín 373 km away, shows nothing a map could locate and replays the moment in cuts, so it cannot be
oriented. With fewer than two oriented cameras the agent reports insufficient geometry and asks for what would close it:
videos from Málaga, Saravena and San Gil, where the flash would have stood 20° to 50° above the horizon. Run
`20261027T132811-1934` is blocked waiting for them, and the request went to Colombian astronomers on 27 October 2026.

## Built during the hackathon, and what came before

Everything in this repository was written during the event: the first commit is from 26 October 2026, 20:25 Colombian
time, after the kickoff. What came before: the method (Ceplecha 1987; Borovička 1990), the published solutions used to
grade (CBET 3423; Zuluaga, Ferrín & Geens 2013), the Ondřejov catalogue of camera sites (Borovička et al. 2016),
OpenStreetMap, NASA's GLM bolide catalogue, and the witness videos, which belong to their authors.

## Meta models

| Model | Used for |
|---|---|
| `muse-spark-1.3` | the agent's planner, with native tool calling; retries when 1.2 loops |
| `muse-spark-1.2` | reading the witness videos under a strict JSON schema; writing the reports |
| `sam-3.1` | tracking the fireball through each video |

API spending is capped in code (`TESTIGOS_BUDGET_USD` a day, `TESTIGOS_TOTAL_BUDGET_USD` in total) and logged per call in
`out/costs.jsonl`: US$ 2.34 for the whole project so far.

## Run it

```
python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e '.[test]'
.venv/bin/python -m pytest                          # offline: geometry, report check, agent checks, replay
.venv/bin/python -m testigos replay chelyabinsk-2013 20261027T132419-a996   # the agent's tools again, no API key
.venv/bin/python scripts/grade.py chelyabinsk-2013  # grades the newest run against validation/
.venv/bin/python scripts/triangulate.py 2 10        # the two-camera solution and the CBET gate
.venv/bin/python scripts/montecarlo.py 500 2 10     # the uncertainty (several minutes)
.venv/bin/python scripts/export_web.py && python3 -m http.server -d web 8000
```

Running the agent itself needs a Meta Model API key: copy `.env.example` to `.env`, fill in `MODEL_API_KEY`, then
`.venv/bin/python -m testigos run chelyabinsk-2013` (about US$ 0.05 to 0.15 a run).

## Data, credits and privacy

The witness videos are not in this repository. `events/<id>/credits.json` names each video's source, uploader,
permission status and where its camera position comes from. Only SAM pixel tracks and numbers derived from them are
published, never a frame. The Chelyabinsk camera positions are the Ondřejov catalogue's as published (cars on public
roads and security cameras), and the viewer rounds them to about 100 m. No witness's home location is published.

Chelyabinsk videos, by YouTube uploader: Aleksandr Ivanov (Kamensk-Uralskiy), Никита Зенкович (Korkino), Alexander
Voronov (Tyumen), MrKuzaman (Beloretsk), 🫐 голубика🫐 (Chebarkul), Мясников Сергей (Yekaterinburg), Сергей Давлеткулов
(Magnitogorsk), Максим Речинский (Plast). Colombia: the Medellín video posted by Santiago Garces (@GarcesUwu), who
credits it to Håskę Bräyãn.

## Limits

- Orienting a camera needs a person to mark lines and landmarks; the agent cannot yet do it from OpenStreetMap alone.
- Handheld videos are not supported: the camera must stay still while the fireball crosses.
- The agent works from tracks that a script made with SAM 3.1; it does not run SAM itself yet.
- Muse Spark 1.2 sometimes loops when reading a video until it hits its token cap; a retry on 1.3 recovers.
- GLM gives where a flash projects onto a reference altitude, not the fireball's height.

## References

- Ceplecha, Z. (1987). Geometric, dynamic, orbital and photometric data on meteoroids from photographic fireball
  networks. Bull. Astron. Inst. Czechosl. 38, 222.
- Borovička, J. (1990). The comparison of two methods of determining meteor trajectories from photographs. Bull. Astron.
  Inst. Czechosl. 41, 391.
- Borovička, J., Spurný, P., Shrbený, L. (2013). CBET 3423.
- Borovička, J. et al. (2016). A&A, doi:10.1051/0004-6361/201526680 (the catalogue of Chelyabinsk video sites).
- Zuluaga, J. I., Ferrín, I., Geens, S. (2013). The orbit of the Chelyabinsk event impactor as reconstructed from
  amateur and public footage. arXiv:1303.1796.
- NASA neo-bolide catalogue (GOES GLM): https://neo-bolide.ndc.nasa.gov

## License

MIT (see `LICENSE`).
