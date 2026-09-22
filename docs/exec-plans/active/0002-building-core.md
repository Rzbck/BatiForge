# Exec plan 0002 — Building-centric reconstruction core

Status: ACTIVE

## Objective

Build the first production-oriented BatiForge reconstruction path from authoritative building geometry and LiDAR, with street imagery treated as optional enrichment rather than the primary dependency.

Primary flow:

selected building -> RNB/BD TOPO identity + footprint -> LiDAR HD subcrop -> metric roof/structure surface extraction -> footprint-constrained shell -> orthophoto-assisted top appearance -> georeferenced export.

## Reference case

Espace des Forges / Théâtre des collines, Annecy.

Validated evidence already available locally:
- RNB `1A6BNQQ3VXGZ`;
- BD TOPO `BATIMENT0000000298370002`;
- isolated class-6 building cloud: 19,404 points;
- density approximately 45.3 pts/m²;
- local ground median approximately 427.77 m IGN69;
- compact high structure with returns up to approximately 29.17 m above local ground.

## First implementation slice

Fit deterministic roof-like planes directly from the isolated building point cloud.

Requirements:
- retain explicit horizontal CRS, vertical datum, units and local georeference origin;
- use local XY coordinates for numerical conditioning while preserving absolute georeference in metadata;
- use seeded RANSAC followed by least-squares refinement;
- reject near-vertical/facade-like planes from the roof stage;
- report support count, RMSE, area, slope, downslope aspect and convex XY support hull;
- preserve high-structure height counts independently of plane fitting;
- emit deterministic JSON plus a local-metric diagnostic OBJ;
- do not claim the diagnostic OBJ is final geometry;
- add synthetic tests for a known gabled roof before host validation.

## Acceptance for this slice

1. Synthetic gabled roof recovers its two known planes within bounded coefficient/slope error.
2. Repeated runs with the same seed serialize identically.
3. Output records EPSG/datum/origin/ground reference explicitly.
4. Espace des Forges host run completes on the real isolated LAZ without modifying tracked files.
5. Real-run report exposes plane count, coverage, RMSE/area/slope per plane and the already-known high-structure evidence.
6. Diagnostic OBJ opens in Blender with Z up and local metric coordinates.

## Next slices

- inspect and tune real roof segmentation without overfitting;
- intersect roof patches with the authoritative footprint;
- derive eaves/walls and build a bounded shell;
- preserve or separately model the compact high structure;
- validate manifold/watertightness and metric/georeferenced export;
- add orthophoto support only after geometry is stable.

## Explicit non-goals

- regular-grid vertical extrusion as final geometry;
- inventing facade detail not supported by evidence;
- using rejected Panoramax/KartaView imagery for this reference building;
- full texture baking in this slice.
