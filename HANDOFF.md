# HANDOFF — BatiForge

Canonical restart point for a new AI or human contributor.

Do not reconstruct current state from a previous chat. Re-fetch Git, inspect branch/HEAD/status, then reconcile this snapshot with newer repository activity.

## Product

BatiForge aims to become a map-driven building reconstruction system:

map/building selection -> authoritative building identity -> footprints + geospatial metadata -> LiDAR/point clouds -> legal/open imagery -> photogrammetry -> metric/georeferenced fusion -> clean 3D asset export.

Current phase: technical core / research pipeline.

## Repository

Repository: `Rzbck/BatiForge`
Default branch: `main`

## HOST_VALIDATED — local environment

- Windows 11 / PowerShell 7.6.6.
- NVIDIA RTX 5080.
- CUDA toolkit 12.8.
- uv-managed Python 3.12.11.
- COLMAP 4.2.0 Windows CUDA build.
- COLMAP GPU SIFT feature extraction successfully executed on RTX 5080.

## HOST_VALIDATED — Espace des Forges reference case

Target:
- Espace des Forges / Théâtre des collines
- 72 avenue de la République, Annecy
- latitude: 45.9086611
- longitude: 6.0984374

Building authority:
- RNB: `1A6BNQQ3VXGZ`
- BD TOPO: `BATIMENT0000000298370002`
- footprint bbox approximately 27.5 x 30.4 m
- footprint area approximately 428.06 m²

IGN point cloud:
- primary tile `LHD_FXX_0940_6540_PTS_LAMB93_IGN69.copc.laz`
- building extraction uses the authoritative RNB footprint
- isolated building cloud: 19,404 class-6 points
- density: approximately 45.3 building points/m²
- local ground median: approximately 427.77 m IGN69

Height evidence:
- main roof mass strongly represented around 5–16 m above local ground
- 306 points at >=22 m in a compact ~6.76 x 5.13 m region
- 26 points at >=24 m
- 13 points at >=26 m
- 5 points at >=28 m
- highest observed return: approximately 29.17 m above local ground

The high structure is real enough to preserve, although the exact extreme tip is not millimetric truth.

## EXPERIMENTAL / rejected as production geometry

A 0.25 m grid-based LiDAR proxy OBJ was generated and inspected in Blender. It preserved scale/rough volume but produced terrace/step artifacts from grid interpolation and vertical extrusion.

Do not use that OBJ as final architectural geometry. The isolated raw LiDAR is stronger evidence.

The source mesh is Z-up. Future Blender imports must explicitly preserve intended axes rather than relying on importer defaults.

## Imagery survey status

Panoramax coverage exists, including 360° panoramas, but the closest useful panoramas found were about 234 m from the target. They are context candidates, not accepted as sufficient primary facade coverage.

No bulk imagery download before current API/license/use constraints and actual facade usefulness are audited.

## Removed / not part of BatiForge

The earlier VGGT experiment was removed after testing. Do not restore it merely because it appears in old conversation history.

## NEXT

1. Implement an imagery survey stage.
2. Query legal/open candidate sources around the selected building.
3. Produce metadata only first: source, position, distance, date, resolution, viewing information and license/provenance.
4. Rank/inspect facade usefulness.
5. Only then fetch a selected image set.
6. Run the first controlled COLMAP reconstruction.
7. Align/fuse photogrammetry with metric LiDAR/RNB evidence.

Active plan: `docs/exec-plans/active/0001-imagery-survey.md`.

## Local migration note

The existing local `GeoReconstruction` prototype contains the validated raw/workspace data and tool install. During migration it should be moved into the BatiForge local root while large assets remain gitignored. Delete the old path only after the new local BatiForge checkout is verified and synchronized with GitHub.
