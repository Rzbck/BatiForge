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

## Imagery

The first versioned Panoramax survey implementation was host-validated at code SHA `049978e533a35d05675003bf4ef4bbd5c1251e2d`.

For a 500 m radius around the reference coordinate it returned:
- 340 metadata candidates;
- nearest candidate at 232.24 m;
- API-reported object license CC-BY-SA-4.0;
- metadata-only output under the gitignored workspace;
- no image downloads.

The earlier manual inspection identified visually relevant 360° sequences at roughly 234 m. This remains too distant to assume useful high-detail facade coverage, so candidate visibility still needs to be inspected before any image set is selected.

## Current next step

Inspect/score Panoramax candidates for actual target visibility, survey additional legal/open imagery sources without bulk downloading them, compare coverage, then run a controlled COLMAP reconstruction only if a useful overlapping image set exists.
