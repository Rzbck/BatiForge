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
- PR `#8` — deterministic LiDAR roof-plane core + authoritative RNB footprint alignment + topology evidence;
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
- footprint bbox: 27.5 x 30.4 m
- footprint area: 428.075 m² from the live RNB OGC feature

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

## HOST_VALIDATED — authoritative footprint alignment

Exact host-validated code SHA: `748a624a955108641add2cc91c5c41b22cdd9ebb`.

Live RNB OGC validation for `1A6BNQQ3VXGZ` using the exact roof-analysis local origin:
- 15 unit tests PASS;
- source endpoint: `https://rnb-api.beta.gouv.fr/api/alpha/ogc/collections/buildings/items/1A6BNQQ3VXGZ`;
- one authoritative polygon;
- projected area: 428.075 m²;
- projected bbox: 27.5 x 30.4 m;
- 19,404 / 19,404 isolated class-6 LiDAR points inside the authoritative footprint;
- 0 outside;
- inside ratio: 1.000000;
- output remained under gitignored workspace paths;
- worktree remained CLEAN.

This validates the RNB and isolated LiDAR planimetry in the same EPSG:2154 local metric frame. The 100% containment is a consistency result for the already isolated building cloud, not evidence that arbitrary raw LiDAR can be accepted without footprint filtering.

## IMPLEMENTED_NOT_VALIDATED — support-aware roof topology evidence

Current branch adds `batiforge.reconstruction.roof_topology`.

It deliberately does **not** create final mesh geometry. It:
- re-evaluates real LiDAR support against the fitted plane equations inside the authoritative footprint;
- excludes the >=22 m compact high structure from the main-roof topology pass;
- uses a metric occupancy grid only as diagnostic support evidence, never as production stair-step geometry;
- labels cells only when point support is sufficient and pure enough;
- measures plane-to-plane adjacency;
- reports boundary length, median/p95 height gap and distance to the analytic plane-equality line;
- distinguishes continuous intersection candidates from height-step/overlap candidates;
- preserves sparse/mixed/unresolved regions explicitly;
- writes JSON plus a line-only diagnostic OBJ, not roof faces.

The next host validation must be tied to the exact branch SHA and the real Espace des Forges LAZ.

## Local migration

Migration is complete:
- `E:\_Project\_ProjectPython\GeoReconstruction` is absent;
- active root is `E:\_Project\_ProjectPython\BatiForge`;
- local LiDAR/workspaces were preserved under BatiForge;
- local COLMAP 4.2.0 was preserved under BatiForge;
- large local data/tools remain gitignored.

## NEXT

1. Host-validate the support-aware roof-topology evidence on the exact isolated Espace des Forges LAZ + validated RNB footprint.
2. Inspect assignment ratio, resolved-cell ratio, per-plane support and measured adjacencies; do not tune from appearance alone.
3. Accept only adjacency/intersection relationships supported by LiDAR and plane-height continuity; preserve unresolved areas explicitly.
4. Convert accepted topology into vector roof regions constrained by the authoritative footprint.
5. Derive eaves/walls and assemble a bounded clean shell.
6. Preserve/model the compact high structure separately from the main roof.
7. Add orthophoto/top appearance only after metric geometry is stable.

Active plan: `docs/exec-plans/active/0002-building-core.md`.
