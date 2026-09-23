# Exec plan 0002 — Building-centric reconstruction core

Status: active.

## Goal

Build the first production-oriented BatiForge path around authoritative building identity, footprint and LiDAR evidence instead of relying on public street imagery.

Reference building: Espace des Forges / Théâtre des collines, RNB `1A6BNQQ3VXGZ`, BD TOPO `BATIMENT0000000298370002`.

## Invariants

- Horizontal CRS, vertical datum, units, source IDs and provenance stay explicit.
- The authoritative building footprint is a hard planimetric constraint.
- Missing geometry is not invented silently.
- The rejected regular-grid proxy is not reused as production geometry.
- LiDAR/raw/derived heavy assets remain outside Git.
- Every host validation is tied to an exact code SHA.
- The compact high structure is preserved as independent evidence until explicitly modelled.

## Milestone A — roof-surface evidence

IMPLEMENTED and HOST_VALIDATED on exact SHA `4e12ae8b3a659db233bdca30262923cb42beb20a`:
- deterministic seeded RANSAC plane extraction;
- least-squares refinement;
- near-vertical rejection;
- metric/georeferenced JSON report;
- diagnostic local Z-up OBJ;
- synthetic tests;
- real Espace des Forges validation: 7 planes, 17,819 / 19,271 roof candidates assigned, coverage 0.924654, 4–7 cm plane RMSE.

Important interpretation: convex XY support hulls overlap and are diagnostic only. They are not final roof patch boundaries.

## Milestone B — authoritative footprint alignment

IMPLEMENTED_NOT_VALIDATED:
- fetch RNB building by ID through the public building API in GeoJSON;
- project EPSG:4326 to EPSG:2154;
- express absolute and local XY using the exact roof-analysis origin;
- deterministic JSON output;
- local diagnostic OBJ footprint outline;
- synthetic projection tests.

Acceptance for the reference case:
- RNB `1A6BNQQ3VXGZ` fetch succeeds;
- projected area/bounds are coherent with the previously measured ~428.06 m² and ~27.5 x 30.4 m footprint;
- footprint diagnostic and roof-plane diagnostic align in one local metric frame;
- Git remains CLEAN.

## Milestone C — topology-constrained roof patches

NEXT after Milestone B validation:
- replace unconstrained convex support hulls with footprint-constrained roof regions;
- infer adjacency/ridge/eave candidates from accepted plane intersections and LiDAR support;
- reject impossible overlaps explicitly;
- preserve unresolved regions rather than filling them by guesswork;
- generate a topology report before creating a shell.

## Milestone D — bounded shell

- derive eaves/walls from footprint + validated roof topology;
- assemble a clean bounded shell;
- verify manifold/boundary status explicitly;
- keep the compact high structure as separate geometry until supported by its own segmentation;
- export local and georeferenced metadata together.

## Later enrichment

- orthophoto/top appearance after geometry is stable;
- facade/public imagery only if an automatic viability gate passes;
- photogrammetry only when useful overlapping views actually exist.
