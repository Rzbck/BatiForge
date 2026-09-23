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
- PR `#8` — deterministic LiDAR roof-plane core + authoritative RNB footprint alignment;
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

## HOST_VALIDATED — building roof-plane core

Exact host-validated code SHA: `4e12ae8b3a659db233bdca30262923cb42beb20a`.

Windows / Python 3.12.11 validation on the real isolated Espace des Forges LAZ:
- 10 unit tests PASS;
- source building points: 19,404;
- roof candidates >=2 m above local ground: 19,271;
- detected roof-like planes: 7;
- assigned points: 17,819;
- unassigned roof candidates: 1,452;
- coverage ratio: 0.924654;
- high-structure counts exactly reproduced: 306 >=22 m, 26 >=24 m, 13 >=26 m, 5 >=28 m;
- maximum observed height above local ground: 29.17 m;
- georeference preserved: EPSG:2154 / IGN69, origin X 940125.09, Y 6539039.03, ground Z 427.77 m;
- worktree remained CLEAN.

Detected plane evidence:
- P1: 6,221 pts, RMSE 0.05 m, projected convex support area 245.65 m², slope 37.38°, downslope aspect 116.93°;
- P2: 5,303 pts, RMSE 0.06 m, area 174.57 m², slope 38.02°, aspect 297.67°;
- P3: 3,086 pts, RMSE 0.04 m, area 326.27 m², slope 13.89°, aspect 297.10°;
- P4: 1,913 pts, RMSE 0.04 m, area 360.79 m², slope 12.76°, aspect 116.21°;
- P5: 563 pts, RMSE 0.07 m, area 50.05 m², slope 36.53°, aspect 346.18°;
- P6: 408 pts, RMSE 0.06 m, area 40.76 m², slope 35.98°, aspect 69.17°;
- P7: 325 pts, RMSE 0.07 m, area 307.72 m², slope 8.40°, aspect 19.66°.

Interpretation constraints:
- the very low 4–7 cm plane RMSE and paired near-opposite aspects are strong evidence for real roof systems;
- convex support hull areas overlap and must **not** be summed as building area or treated as final roof boundaries;
- the authoritative footprint/topology stage is required before shell construction;
- the compact high structure remains separate evidence and must not be erased by roof simplification.

## IMPLEMENTED_NOT_VALIDATED — authoritative footprint alignment

Current branch HEAD includes:
- fetch by RNB ID from the public RNB building API in GeoJSON;
- project EPSG:4326 footprint geometry to EPSG:2154;
- reuse the exact roof-analysis local origin so footprint and roof diagnostics share one metric frame;
- deterministic JSON plus local Z-up diagnostic OBJ outline;
- synthetic projection tests;
- fix for the `python -m ...roof_planes` eager-import RuntimeWarning seen during host validation.

This footprint stage is not HOST_VALIDATED on the real RNB feature yet.

## Local migration

Migration is complete:
- `E:\_Project\_ProjectPython\GeoReconstruction` is absent;
- active root is `E:\_Project\_ProjectPython\BatiForge`;
- local LiDAR/workspaces were preserved under BatiForge;
- local COLMAP 4.2.0 was preserved under BatiForge;
- large local data/tools remain gitignored.

## NEXT

1. Host-validate the RNB footprint fetch/projection against `1A6BNQQ3VXGZ` using the exact roof-analysis origin.
2. Compare returned planimetric area/bounds with the already validated ~428.06 m² / ~27.5 x 30.4 m evidence.
3. Inspect roof-plane diagnostic OBJ and authoritative footprint OBJ together in Blender to verify metric alignment.
4. Replace unconstrained convex roof hulls with footprint/topology-constrained patches.
5. Derive eaves/walls and assemble a bounded clean shell.
6. Preserve/model the compact high structure separately if the main roof segmentation does not capture it.
7. Add orthophoto/top appearance only after metric geometry is stable.

Active plan: `docs/exec-plans/active/0002-building-core.md`.
