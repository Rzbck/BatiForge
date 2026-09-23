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

HOST_VALIDATED on exact SHA `7fea565a578f0b8601327fe38f46c430c2f1bb1f`:
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

Reference-case validation:
- 19 unit tests PASS;
- 18,964 main-roof candidates after excluding >=22 m high structure;
- 17,794 assigned; ratio 0.938304;
- 1,518 / 1,710 observed support cells resolved; ratio 0.887719;
- unresolved: 42 sparse, 115 mixed-support, 35 no compatible plane;
- 306 high-structure points preserved separately;
- 8 measured plane adjacencies;
- P1↔P2 is the dominant continuous intersection candidate (~24 m, 0.13 m median gap, 0.09 m equality-line distance);
- P2↔P5, P1↔P6 and P4↔P7 are shorter continuous candidates;
- P5↔P6 is only ~0.5 m and should not be promoted by default;
- P1↔P4, P2↔P3 and P1↔P7 are height-step/overlap candidates with ~4.9–5.5 m height gaps;
- Git remained CLEAN.

One boundary-classification edge case reports 19,403 points inside during the topology pass while the authoritative footprint audit reports 19,404/19,404. Keep this discrepancy visible until boundary semantics are unified; it does not materially affect the topology metrics.

## Milestone D — conservative analytic roof vectors

IMPLEMENTED_NOT_VALIDATED on the active branch:
- promote only measured `continuous_intersection_candidate` relationships;
- default minimum measured boundary support: 1.0 m;
- derive exact roof-vector geometry from the analytic equality line of each fitted plane pair;
- use occupancy-grid boundary segments only to bound the supported span, never as final geometry;
- add a conservative support margin before clipping;
- clip vector segments to the authoritative footprint;
- preserve height-step/overlap relationships separately;
- emit deterministic JSON and line-only local-metric OBJ skeleton;
- synthetic tests cover equality-line vectorization, authoritative footprint clipping, short-support rejection and no-face OBJ output.

Acceptance for the reference case:
- exact branch SHA host validation on the already validated roof/topology/footprint JSON outputs;
- dominant P1↔P2 vector survives and remains close to the measured ~24 m support;
- P2↔P5, P1↔P6 and P4↔P7 are evaluated conservatively;
- the ~0.5 m P5↔P6 relation is rejected by the default 1.0 m support gate;
- height-step pairs are not promoted to ridge vectors;
- all vector endpoints remain inside/on the authoritative footprint;
- Git remains CLEAN.

Only after these vector gates pass should roof-region faces be constructed.

## Milestone E — bounded shell

- use validated vector edges + authoritative footprint to construct vector roof regions;
- derive eaves/walls from footprint + validated roof topology;
- assemble a clean bounded shell;
- verify manifold/boundary status explicitly;
- keep the compact high structure as separate geometry until supported by its own segmentation;
- export local and georeferenced metadata together.

## Later enrichment

- orthophoto/top appearance after geometry is stable;
- facade/public imagery only if an automatic viability gate passes;
- photogrammetry only when useful overlapping views actually exist.
