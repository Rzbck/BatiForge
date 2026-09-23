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
- PR `#8` — roof-plane core + authoritative footprint + support-aware topology + analytic roof vectors + first vector roof regions;
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

Source reconstruction coordinates are X east / Y north / Z up. OBJ does not carry authoritative axis metadata, so Blender OBJ import defaults can rotate an otherwise correct model. Preserve the georeferenced frame in core outputs; use explicit importer axes or the Blender-friendly PLY diagnostic for inspection.

## HOST_VALIDATED — imagery survey core

Panoramax metadata/orientation/preview survey is implemented and merged. The provider is useful generically, but Panoramax is rejected as a reconstruction-image source for the Espace des Forges after thumbnail inspection showed motorway/noise-barrier/vegetation coverage rather than useful building views.

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
- convex support hull areas overlap and must not be summed as building area or treated as final roof boundaries;
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

## HOST_VALIDATED — support-aware roof topology evidence

Exact host-validated code SHA: `7fea565a578f0b8601327fe38f46c430c2f1bb1f`.

Real isolated LAZ + validated footprint result:
- 19 unit tests PASS;
- 19,404 source points;
- 18,964 main-roof candidates after excluding the >=22 m high structure;
- 17,794 assigned to fitted planes; assignment ratio 0.938304;
- 1,518 / 1,710 observed support cells resolved; ratio 0.887719;
- unresolved cells: 42 sparse, 115 mixed-support, 35 with no plane inside residual threshold;
- compact high structure preserved separately: 306 points >=22 m;
- 8 measured plane adjacencies;
- Git remained CLEAN.

Key measured adjacencies:
- P1↔P2: ~24.0 m boundary, median gap 0.13 m, p95 gap 0.31 m, median equality-line distance 0.09 m — strong continuous-intersection candidate;
- P2↔P5: ~5.5 m, gap 0.10 m, equality-line distance 0.16 m — continuous candidate;
- P1↔P6: ~4.0 m, gap 0.06 m, equality-line distance 0.10 m — continuous candidate;
- P4↔P7: ~1.5 m, gap 0.05 m, equality-line distance 0.17 m — continuous candidate;
- P5↔P6: ~0.5 m, gap 0.11 m, equality-line distance 0.11 m — continuous but too short to promote by default;
- P1↔P4, P2↔P3 and P1↔P7 show ~4.9–5.5 m height gaps and are treated as height-step/overlap candidates, not ridges.

One point is reported outside the footprint in the topology pass although the authoritative alignment audit reported 19,404/19,404 inside. This is a boundary-classification/serialized-coordinate edge case and does not materially affect the roof support result; keep it visible until boundary semantics are unified.

## HOST_VALIDATED — conservative analytic roof vectors

Exact host-validated code SHA: `8d7b1bf1c0c73701b2e6ad3c115e2958a570df31`.

Real topology/roof/footprint validation:
- 23 unit tests PASS;
- 5 continuous candidates detected;
- 4 analytic vectors accepted and 1 short continuous relationship rejected;
- accepted: P1↔P2, P1↔P6, P2↔P5, P4↔P7;
- P1↔P2 vector length 21.30 m from ~24.0 m measured support;
- P1↔P6 vector length 6.00 m;
- P2↔P5 vector length 7.19 m;
- P4↔P7 vector length 2.35 m;
- P5↔P6 remains rejected by the default minimum-support-length gate;
- three height-step/overlap relationships remain separate: P1↔P4, P1↔P7, P2↔P3;
- compact high structure remains separate: 306 points >=22 m;
- Git remained CLEAN.

Human Blender inspection confirmed that the vector skeleton is coherent but intentionally incomplete because it contains only validated intersection/step evidence and no roof faces yet. The footprint lies in the XY plane and roof vectors carry Z height. Apparent OBJ orientation issues are importer-axis behavior; the core frame stays X east / Y north / Z up.

## IMPLEMENTED_NOT_VALIDATED — support-resolved vector roof regions

Current branch adds `batiforge.reconstruction.roof_regions`.

It creates the first actual roof faces while remaining conservative:
- authoritative footprint remains the outer planimetric constraint;
- accepted continuous relationships are used as exact analytic divider lines;
- measured height-step boundaries are straightened by PCA into vector divider lines rather than traced as staircase grid edges;
- footprint triangulation is only an internal partition aid, not the visible roof topology;
- each resulting vector polygon is assigned to a fitted plane only when real LiDAR support inside that polygon passes point-count and purity gates;
- unresolved pieces remain explicit instead of being silently filled;
- vertices are lifted exactly onto the assigned fitted plane;
- outputs include JSON, source-frame OBJ, and a Blender-friendly PLY preserving stored XYZ coordinates directly;
- the >=22 m compact high structure remains excluded from the main roof face pass.

This stage must now be host-validated on the real Espace des Forges evidence before walls or shell closure.

## Local migration

Migration is complete:
- `E:\_Project\_ProjectPython\GeoReconstruction` is absent;
- active root is `E:\_Project\_ProjectPython\BatiForge`;
- local LiDAR/workspaces were preserved under BatiForge;
- local COLMAP 4.2.0 was preserved under BatiForge;
- large local data/tools remain gitignored.

## NEXT

1. Host-validate `roof_regions` on the exact real LiDAR + roof + footprint + topology + vector outputs.
2. Inspect resolved footprint-area ratio, unresolved pieces, per-plane area and the PLY roof faces in Blender.
3. Do not fill unresolved areas unless supported by continuity/topology evidence.
4. Add explicit vertical step faces and eaves/walls only after the roof-region assignment is credible.
5. Model the compact high structure separately from the main roof.
6. Assemble and validate a bounded clean shell.
7. Add orthophoto/top appearance only after metric geometry is stable.

Active plan: `docs/exec-plans/active/0002-building-core.md`.
