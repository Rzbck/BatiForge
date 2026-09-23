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
- Core reconstruction coordinates stay X east / Y north / Z up; presentation-axis transforms must not corrupt georeferencing.

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

## Milestone C1 — support-aware topology evidence

HOST_VALIDATED on exact SHA `7fea565a578f0b8601327fe38f46c430c2f1bb1f`:
- 18,964 main-roof candidates after excluding >=22 m compact high structure;
- 17,794 assigned, ratio 0.938304;
- 1,518 / 1,710 support cells resolved, ratio 0.887719;
- unresolved cells remain explicit;
- 8 measured adjacencies;
- continuous candidates identified separately from ~4.9–5.5 m height-step/overlap boundaries;
- Git remained CLEAN.

## Milestone C2 — conservative analytic roof vectors

HOST_VALIDATED on exact SHA `8d7b1bf1c0c73701b2e6ad3c115e2958a570df31`:
- 23 unit tests PASS;
- 5 continuous candidates detected, 4 promoted and 1 short candidate rejected;
- accepted vectors: P1↔P2, P1↔P6, P2↔P5, P4↔P7;
- P1↔P2 vector length 21.30 m;
- P1↔P6 6.00 m;
- P2↔P5 7.19 m;
- P4↔P7 2.35 m;
- P5↔P6 rejected by minimum support length;
- P1↔P4, P1↔P7 and P2↔P3 remain explicit height-step/overlap candidates;
- 306 >=22 m high-structure points preserved separately;
- Git remained CLEAN.

Blender inspection confirmed a coherent but intentionally incomplete vector skeleton. OBJ importer defaults may remap axes; source data remains X east / Y north / Z up.

## Milestone C3 — support-resolved vector roof regions

IMPLEMENTED_NOT_VALIDATED on the active branch:
- use the authoritative footprint as the outer constraint;
- use validated continuous equality lines as exact analytic dividers;
- fit straight PCA divider lines to measured height-step boundary evidence instead of tracing grid staircases;
- triangulate the footprint only internally to robustly partition concave geometry;
- assign each resulting vector polygon to a fitted roof plane only when real LiDAR support inside it passes count/purity gates;
- leave unsupported or mixed polygons unresolved;
- lift region vertices exactly onto the assigned fitted plane;
- emit deterministic JSON, source-frame OBJ, and Blender-friendly PLY roof faces;
- keep the >=22 m high structure separate.

Acceptance for the reference case:
- exact branch SHA host validation on the real LiDAR + validated roof/footprint/topology/vector outputs;
- high resolved footprint-area ratio without silently filling unsupported pieces;
- per-plane area distribution coherent with measured support;
- PLY roof faces visually coherent in Blender and not staircase/grid geometry;
- no accidental absorption of the compact high structure;
- Git remains CLEAN.

## Milestone D — bounded shell

NEXT after roof-region validation:
- derive explicit vertical step faces where validated height-step regions meet;
- derive eaves/walls from footprint + validated roof regions;
- model the compact high structure separately;
- assemble a clean bounded shell;
- verify manifold/boundary status explicitly;
- export local and georeferenced metadata together.

## Later enrichment

- orthophoto/top appearance after geometry is stable;
- facade/public imagery only if an automatic viability gate passes;
- photogrammetry only when useful overlapping views actually exist.
