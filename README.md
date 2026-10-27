# Testigos del Bólido

Colombia has no fireball camera network. Its phones can be one.

When a fireball crosses the sky, people film it with phones, security cameras and dashcams. Testigos del Bólido turns those witness videos into a trajectory with error bars, a speed, and a verdict: natural meteoroid, re-entering spacecraft, or inconclusive.

- **Muse Spark** reads each video: on-screen clock, landmarks, location hints, the sonic boom.
- **SAM 3.1** tracks the fireball frame by frame.
- A small geometry core calibrates each camera from landmarks with known coordinates (OpenStreetMap, elevation models) and intersects the cameras' planes of sight (Ceplecha 1987; Borovička 1990), with Monte Carlo uncertainty.

## Status (built during the Meta Global AI Developer Hackathon, Oct 26 – Nov 4, 2026)

- [x] Geometry core with synthetic tests: frames, camera calibration, plane triangulation, speed, verdict.
- [x] Meta API client with a daily spending cap; SAM 3.1 token parser; bright-core centroid.
- [ ] Validation against the published Chelyabinsk solution (CBET 3423).
- [ ] Night and speed check on the Iberian superbolide of 18 May 2024.
- [ ] The Colombian fireball of 30 July 2025.

## Prior work this builds on

Reconstructing fireballs from casual videos is not new: Borovička, Spurný and Shrbený did it for Chelyabinsk from seven videos calibrated with Google Maps (CBET 3423, 2013), and Zuluaga and Ferrín of Universidad de Antioquia published one of the first reconstructions from witness videos (arXiv:1302.5377). What is new here is an agent that does the work in minutes, for anyone, with honest uncertainty.

## Data

Witness videos are not stored in this repository. `events/<id>/event.json` lists each clip's public source, the camera position and what is visible; `truth.json` holds the published solution used for validation.

## Run the tests

```
python3 -m venv --system-site-packages .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest
```
