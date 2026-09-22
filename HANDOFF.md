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
- PR `#5` — Panoramax imagery survey core.

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

First metadata-only survey validation:
- code SHA `049978e533a35d05675003bf4ef4bbd5c1251e2d`;
- 2 unit tests PASS;
- live Panoramax survey at 500 m PASS;
- 340 candidates;
- nearest metadata candidate 232.24 m;
- no imagery downloaded;
- worktree CLEAN.

Target-orientation validation:
- exact code SHA `f457ac0fe0af5d75179ac55708db8ac3902af02f`;
- `uv sync --frozen --python 3.12.11`: PASS;
- 4 unit tests: PASS;
- live Panoramax survey: PASS;
- 340 candidates across 13 sequences;
- view classes: 32 panoramic, 32 front, 174 lateral, 102 rear, 0 unknown;
- target-in-FOV: 55 true, 78 false, 207 unknown;
- nearest non-360 front candidate: 281.03 m;
- nearest non-360 candidate with target_in_fov=True: 291.30 m;
- nearest panorama in the orientation report: 233.94 m;
- no full-resolution imagery downloaded;
- Git worktree remained CLEAN.

Preview validation:
- exact code SHA `d4e0bb8a64b5d9db72f55f82db95d26a76083207`;
- 7 unit tests: PASS;
- deterministic shortlist: 24 candidates;
- explicit thumbnail derivatives downloaded: 24/24;
- failures: 0;
- worktree remained CLEAN;
- human visual inspection showed motorway views, noise barriers, vegetation and unrelated distant structures rather than useful views of the Espace des Forges.

Decision for this reference building: **Panoramax is rejected as a reconstruction-image source**. The provider implementation remains useful as a generic survey provider and as evidence that target bearing/FOV geometry alone cannot establish line of sight or facade usefulness.

Do not spend more time extracting Panoramax full-resolution imagery for the Espace des Forges.

## Local migration

Migration is complete:
- `E:\_Project\_ProjectPython\GeoReconstruction` is absent;
- active root is `E:\_Project\_ProjectPython\BatiForge`;
- local LiDAR/workspaces were preserved under BatiForge;
- local COLMAP 4.2.0 was preserved under BatiForge;
- large local data/tools remain gitignored;
- local `main` was verified synchronized and CLEAN after migration.

## NEXT

1. Keep the validated Panoramax provider, but stop Panoramax acquisition for this building.
2. Add KartaView as the next street-level provider: public nearby-photo API, metadata first, no bulk download.
3. Visually verify whether KartaView has actual close facade coverage before selecting originals.
4. If street-level coverage is still insufficient, survey Mapillary and Wikimedia/official municipal imagery with explicit per-source licensing/provenance.
5. Use IGN aerial/orthophoto imagery for roof/planimetric evidence, not as a substitute for facade coverage.
6. Only run controlled COLMAP when a useful overlapping facade image set exists.
7. Align/fuse photogrammetry with metric LiDAR/RNB evidence.

Active plan: `docs/exec-plans/active/0001-imagery-survey.md`.
