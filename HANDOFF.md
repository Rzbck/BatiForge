# HANDOFF — BatiForge

Canonical restart point for a new AI or human contributor.

Do not reconstruct current state from a previous chat. Re-fetch Git, inspect branch/HEAD/status, then reconcile this snapshot with newer repository activity.

## Product

BatiForge aims to become a map-driven building reconstruction system:

map/building selection -> authoritative building identity -> footprints + geospatial metadata -> LiDAR/point clouds -> optional legal/open imagery -> metric/georeferenced reconstruction -> clean 3D asset export.

Current phase: building-centric technical core / research pipeline.

## Repository

Repository: `Rzbck/BatiForge`
Default branch: `main`

Current active work:
- issue `#7` — Implement building-centric reconstruction core;
- branch `feat/building-core-20260922`;
- active plan `docs/exec-plans/active/0002-building-core.md`.

Imagery survey core was merged to `main` through PR `#5` at merge commit `9d7261c219c76aaa4cabd3db7e41e58c33919a63`.

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

A 0.25 m regular-grid LiDAR proxy OBJ was generated and inspected in Blender. It preserved scale/rough volume but produced terrace/step artifacts from grid interpolation and vertical extrusion.

Do not use that OBJ as final architectural geometry. The isolated raw LiDAR is stronger evidence.

The source mesh is Z-up. Future Blender imports must explicitly preserve intended axes rather than relying on importer defaults.

## HOST_VALIDATED — imagery survey core

Panoramax metadata/orientation/preview survey is implemented and merged. The provider is useful generically, but **Panoramax is rejected as a reconstruction-image source for the Espace des Forges** after thumbnail inspection showed motorway/noise-barrier/vegetation coverage rather than useful building views.

KartaView was then probed metadata-first. Five nearby API results were returned, but their actual camera positions were still roughly 232–255 m from the target and thumbnail inspection again showed road imagery unrelated to the building. KartaView provider implementation was therefore stopped for this reference case; issue `#6` was closed as not planned.

Do not continue provider-by-provider street-image probing as the primary path for this building. Public/street imagery is optional enrichment and must pass an automatic viability gate before preview/original download.

## IMPLEMENTED_NOT_VALIDATED — building roof-plane core

Branch `feat/building-core-20260922` now contains the first building-centric reconstruction slice:
- deterministic seeded RANSAC roof-plane fitting from LAS/LAZ XYZ;
- least-squares refinement;
- rejection of near-vertical/facade-like planes;
- explicit EPSG/datum/origin/ground metadata;
- per-plane support count, RMSE, area, slope, downslope aspect and convex support hull;
- independent high-structure height counts;
- deterministic JSON output;
- local-metric diagnostic OBJ with Z up;
- synthetic gabled-roof tests.

This code is not HOST_VALIDATED on the real Espace des Forges LAZ yet. Do not present its real-building results as established until the exact branch SHA has been run locally and inspected.

## Local migration

Migration is complete:
- `E:\_Project\_ProjectPython\GeoReconstruction` is absent;
- active root is `E:\_Project\_ProjectPython\BatiForge`;
- local LiDAR/workspaces were preserved under BatiForge;
- local COLMAP 4.2.0 was preserved under BatiForge;
- large local data/tools remain gitignored.

## NEXT

1. Host-validate the roof-plane core on the exact isolated Espace des Forges LAZ.
2. Inspect plane count, coverage, RMSE, support area and slope distribution; tune only from measured evidence.
3. Verify the diagnostic OBJ in Blender as local metric/Z-up geometry.
4. Intersect accepted roof patches with the authoritative footprint rather than their unconstrained convex hulls.
5. Derive eaves/walls and assemble a bounded clean shell.
6. Preserve/model the compact high structure separately if the main roof segmentation does not capture it.
7. Add orthophoto/top appearance only after metric geometry is stable.

Active plan: `docs/exec-plans/active/0002-building-core.md`.
