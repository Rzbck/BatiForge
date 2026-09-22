# ADR 0002 — Large geospatial data stays outside Git

Status: accepted

Raw or generated large data is not stored in the source repository.

This includes LiDAR, COPC/LAZ, downloaded image collections, COLMAP databases, dense reconstruction results, native tool distributions, caches and large generated meshes.

The repository stores reproducible acquisition/reconstruction recipes, identifiers, provenance, checksums when useful, compact metadata and tests.

Small deliberate fixtures may be added later under `tests/fixtures/` when required.
