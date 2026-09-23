# Case study — Espace des Forges

First BatiForge reference building.

## Identity

- Name: Espace des Forges / Théâtre des collines
- Address: 72 avenue de la République, Annecy, France
- Latitude: 45.9086611
- Longitude: 6.0984374
- RNB: `1A6BNQQ3VXGZ`
- BD TOPO: `BATIMENT0000000298370002`

## Validated metric evidence

RNB footprint:
- bbox approximately 27.5 x 30.4 m;
- area approximately 428.06 m².

Isolated LiDAR:
- 19,404 building-class points;
- approximately 45.3 pts/m²;
- ground median approximately 427.77 m IGN69.

Height distribution shows a compact high structure:
- >=22 m: 306 points;
- >=24 m: 26 points;
- >=26 m: 13 points;
- >=28 m: 5 points;
- maximum observed return approximately 29.17 m above local ground.

## LiDAR source

Primary source tile:
`LHD_FXX_0940_6540_PTS_LAMB93_IGN69.copc.laz`

COPC subsetting was used instead of downloading complete kilometre tiles.

## Reconstruction experiments

COLMAP 4.2.0 CUDA feature extraction has been validated locally on an RTX 5080.

A regular-grid LiDAR proxy mesh preserved scale and rough volume but produced terrace artifacts and is not accepted as production geometry.

### Roof-plane core

The deterministic roof-plane core was host-validated on exact code SHA `4e12ae8b3a659db233bdca30262923cb42beb20a` using the real isolated LAZ:
- 10 unit tests PASS;
- 19,404 source points;
- 19,271 roof candidates >=2 m above ground;
- 7 roof-like planes detected;
- 17,819 points assigned;
- 1,452 candidates unassigned;
- coverage ratio 0.924654;
- EPSG:2154 / IGN69 preserved;
- local origin X 940125.09, Y 6539039.03, ground Z 427.77 m;
- Git remained CLEAN.

Planes:
- P1: 6,221 points, RMSE 0.05 m, convex XY support area 245.65 m², slope 37.38°, aspect 116.93°;
- P2: 5,303 points, RMSE 0.06 m, area 174.57 m², slope 38.02°, aspect 297.67°;
- P3: 3,086 points, RMSE 0.04 m, area 326.27 m², slope 13.89°, aspect 297.10°;
- P4: 1,913 points, RMSE 0.04 m, area 360.79 m², slope 12.76°, aspect 116.21°;
- P5: 563 points, RMSE 0.07 m, area 50.05 m², slope 36.53°, aspect 346.18°;
- P6: 408 points, RMSE 0.06 m, area 40.76 m², slope 35.98°, aspect 69.17°;
- P7: 325 points, RMSE 0.07 m, area 307.72 m², slope 8.40°, aspect 19.66°.

The 37–38° pair has near-opposite aspects (~116.9° / ~297.7°), as does the 12.8–13.9° pair (~116.2° / ~297.1°). Together with 4–7 cm RMSE, this is strong evidence for coherent real roof systems rather than random planar fits.

The convex support hulls are only diagnostic envelopes. Their projected areas overlap and must not be summed or used as final roof boundaries. The next geometry stage must use the authoritative RNB footprint/topology.

The high-structure evidence was independently reproduced by the new implementation: 306 points >=22 m, 26 >=24 m, 13 >=26 m, 5 >=28 m and max 29.17 m above ground.

## Imagery

The metadata-only Panoramax survey was first host-validated at code SHA `049978e533a35d05675003bf4ef4bbd5c1251e2d`.

For a 500 m radius around the reference coordinate it returned 340 metadata candidates and no image downloads.

Target-orientation scoring was then host-validated at exact code SHA `f457ac0fe0af5d75179ac55708db8ac3902af02f`:
- 340 candidates across 13 sequences;
- 32 panoramic;
- 32 front;
- 174 lateral;
- 102 rear;
- 0 unknown orientation;
- 55 candidates with target_in_fov=True;
- 78 with target_in_fov=False;
- 207 with unknown FOV;
- nearest non-360 front candidate: 281.03 m;
- nearest non-360 target-in-FOV candidate: 291.30 m;
- nearest panorama in the report: 233.94 m.

A bounded preview stage was then host-validated at exact code SHA `d4e0bb8a64b5d9db72f55f82db95d26a76083207`:
- 7 unit tests PASS;
- 24 deterministic shortlist entries;
- 24 explicit Panoramax thumbnail derivatives downloaded;
- 0 failures;
- no full-resolution/original imagery used;
- Git remained CLEAN.

Human inspection of the generated gallery showed motorway carriageways, noise barriers, vegetation and unrelated distant buildings. The Espace des Forges is not usefully visible in the shortlisted frames. The geometric `front` / `target_in_fov` signals were therefore not sufficient to establish real facade visibility.

KartaView was then probed as a second negative case: five API candidates clustered roughly 232–255 m from the target and available thumbnails again showed unrelated road imagery. No provider implementation was continued for this target.

### Decision

Panoramax and KartaView are rejected as reconstruction imagery for Espace des Forges. Street/public imagery remains optional enrichment behind an automatic viability gate, not the primary reconstruction path.

## Current next step

Fetch the authoritative RNB footprint for `1A6BNQQ3VXGZ`, project it to EPSG:2154 using the exact roof-analysis local origin, verify metric alignment against the roof-plane diagnostic, then constrain roof topology to that footprint before deriving walls/eaves and a clean bounded shell.
