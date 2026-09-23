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
- Diagnostic grids may measure support/topology but are never emitted as production stair-step roof geometry.
- LiDAR/raw/derived heavy assets remain outside Git.
- Every host validation is tied to an exact code SHA.
- The compact high structure is preserved as independent evidence until explicitly modelled.

## Milestone A — roof-surface evidence

HOST_VALIDATED on exact SHA `4e12ae8b3a659db233bdca30262923cb42beb20a`:
- deterministic seeded RANSAC plane extraction;
- least-squares refinement;
- near-vertical rejection;
- metric/georeferenced JSON report;
- diagnostic local Z-up OBJ;
- synthetic tests;
- real Espace des Forges validation: 7 planes, 17,819 / 19,271 roof candidates assigned, coverage 0.924654, 4–7 cm plane RMSE.

Important interpretation: convex XY support hulls overlap and are diagnostic only. They are not final roof patch boundaries.

## Milestone B — authoritative footprint alignment

HOST_VALIDATED on exact SHA `748a624a955108641add2cc91c5c41b22cdd9ebb`:
- fetch RNB building by ID from the public RNB OGC API Features item endpoint;
- project EPSG:4326 to EPSG:2154;
- express absolute and local XY using the exact roof-analysis origin;
- deterministic JSON output;
- local diagnostic OBJ footprint outline;
- synthetic projection/alignment tests;
- live RNB `1A6BNQQ3VXGZ` result: one polygon, 428.075 m², bbox 27.5 x 30.4 m;
- isolated class-6 LiDAR alignment: 19,404 / 19,404 points inside, 0 outside, ratio 1.000000;
- Git remained CLEAN.

The 100% containment validates consistency of the already isolated building cloud with the authoritative footprint. It does not remove the need to filter arbitrary raw LiDAR against that footprint.

## Milestone C — topology-constrained roof evidence

IMPLEMENTED_NOT_VALIDATED on the active branch:
- re-evaluate point support against the fitted roof-plane equations inside the authoritative footprint;
- exclude the >=22 m compact high structure from the main-roof topology pass;
- use a metric occupancy grid only to measure local support, never as final mesh geometry;
- label cells only when point count and purity gates pass;
- preserve sparse, mixed-support and residual-unassigned cells explicitly;
- measure plane-to-plane adjacency boundaries;
- compute median/p95 plane height gaps at observed boundaries;
- compare observed boundaries with the analytic plane-equality line;
- classify continuous intersection candidates separately from height-step/overlap candidates;
- output deterministic JSON plus a line-only diagnostic OBJ.

Acceptance for the reference case:
- exact branch SHA host validation on the real isolated LAZ + validated footprint JSON;
- high main-roof point assignment ratio without absorbing the >=22 m high structure;
- meaningful support for the dominant fitted planes;
- adjacency graph consistent with measured plane families;
- unresolved regions reported rather than silently filled;
- diagnostic outputs remain gitignored and Git stays CLEAN.

Only after these evidence gates pass should accepted relationships be converted into vector roof regions.

## Milestone D — bounded shell

- convert accepted roof relationships into vector regions clipped to the authoritative footprint;
- derive eaves/walls from footprint + validated roof topology;
- assemble a clean bounded shell;
- verify manifold/boundary status explicitly;
- keep the compact high structure as separate geometry until supported by its own segmentation;
- export local and georeferenced metadata together.

## Later enrichment

- orthophoto/top appearance after geometry is stable;
- facade/public imagery only if an automatic viability gate passes;
- photogrammetry only when useful overlapping views actually exist.
