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

This proves that some Panoramax candidates are geometrically compatible with looking toward the target, but they are still hundreds of metres away. Geometry does not prove that the building is visible, unoccluded or detailed enough for reconstruction.

## Current next step

Generate a small deterministic shortlist, fetch only explicit Panoramax thumbnail derivatives for visual inspection, reject bad/occluded candidates, then compare against additional legal/open imagery providers before selecting any full-resolution image set for COLMAP.
