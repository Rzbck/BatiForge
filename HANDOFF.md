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

Current active work:
- issue `#4` — Implement imagery survey core;
- branch `feat/imagery-survey-20260922`;
- draft PR `#5` — Panoramax imagery survey core.

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

## HOST_VALIDATED — imagery survey core

Exact validated code SHA: `049978e533a35d05675003bf4ef4bbd5c1251e2d`.

Local Windows validation on the Espace des Forges reference config:
- `uv sync --frozen --python 3.12.11`: PASS;
- 2 unit tests: PASS;
- live Panoramax metadata-only survey, radius 500 m: PASS;
- candidates returned: 340;
- nearest metadata candidate: 232.24 m from the target;
- API-reported object license: CC-BY-SA-4.0;
- output written under the gitignored workspace;
- no imagery downloaded;
- Git worktree remained CLEAN.

This independently reproduces the earlier manual result that Panoramax coverage exists but is too far away to assume high-detail facade usefulness. The previously identified visually relevant 360° sequences were around 234 m away.

Do not bulk-download imagery before source/license/use constraints and actual facade usefulness are audited.

## Removed / not part of BatiForge

The earlier VGGT experiment was removed after testing. Do not restore it merely because it appears in old conversation history.

## Local migration

Migration is complete:
- `E:\_Project\_ProjectPython\GeoReconstruction` is absent;
- active root is `E:\_Project\_ProjectPython\BatiForge`;
- local LiDAR/workspaces were preserved under BatiForge;
- local COLMAP 4.2.0 was preserved under BatiForge;
- large local data/tools remain gitignored;
- local `main` was verified synchronized and CLEAN after migration.

## NEXT

1. Inspect and score Panoramax candidates for actual target visibility, not distance alone.
2. Preserve only metadata until a source is deliberately selected.
3. Add the next legal/open imagery provider(s) to the same provider-neutral survey model.
4. Compare coverage from all providers for facade/detail usefulness.
5. Only then fetch a selected image set.
6. Run the first controlled COLMAP reconstruction.
7. Align/fuse photogrammetry with metric LiDAR/RNB evidence.

Active plan: `docs/exec-plans/active/0001-imagery-survey.md`.
