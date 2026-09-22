# ADR 0003 — Preserve georeferencing and metric evidence

Status: accepted

Real-world source coordinates remain authoritative evidence.

DCC-friendly exports may be recentered near a local origin, but the transform back to the source CRS must remain explicit and reproducible.

No stage may silently change CRS, axis order, datum or units.

Photogrammetry is aligned/fused with metric evidence; it does not implicitly replace authoritative scale and georeferencing.
