# Architecture

## Goal

BatiForge separates authoritative geospatial evidence, source acquisition, reconstruction and final asset generation.

Target flow:

```text
selection
  -> building identity
  -> survey
  -> fetch
  -> normalize
  -> reconstruct
  -> align / fuse
  -> validate
  -> export
```

## Building identity

Resolve a selected real-world building into stable identifiers and geometry. Current reference sources include RNB and BD TOPO.

## Survey

Query providers without bulk downloading. Record provider, source identifier, coordinates, distance, date, resolution, view/orientation metadata, license/provenance and availability.

## Fetch

Download only selected source data while preserving original provenance and source metadata.

## Geometry evidence

Metric sources such as LiDAR constrain position, scale, terrain, envelope, roof geometry and height. They must not be assumed to contain facade detail they never measured.

## Photogrammetry

Image reconstruction is handled independently from the metric source layer. COLMAP is the current validated reconstruction engine.

## Fusion

Photogrammetry is aligned against authoritative metric/geospatial evidence rather than replacing it blindly.

## Export

Generated assets may use a local DCC-friendly coordinate system, but enough metadata must remain to restore source georeferencing.

## Core invariants

- CRS and units are explicit.
- Raw evidence is preserved.
- Derived geometry stays distinguishable from source measurements.
- Provider provenance is never discarded.
- Failed experiments do not overwrite validated sources.
- Large datasets stay outside Git.
