# Exec plan 0001 — Imagery survey

Status: ACTIVE

## Objective

Determine whether enough legally usable imagery exists to reconstruct useful facade/detail geometry for the Espace des Forges before starting a full COLMAP run.

## Scope

Implement a survey stage that accepts a target building/location and returns candidate image metadata without bulk downloading source imagery.

Each provider is evaluated independently and only enabled when its current API/licensing constraints are understood.

## Required candidate metadata

For each candidate image/view:
- provider;
- stable source identifier;
- source URL/API reference;
- capture position;
- distance from target;
- date when available;
- dimensions/resolution when available;
- heading/FOV/orientation when available;
- license/provenance;
- sequence/panorama membership;
- estimated usefulness for the target.

## Acceptance

1. Survey runs on the Espace des Forges reference config.
2. No bulk imagery download is required for discovery.
3. Provider failures/rate limits are explicit.
4. Output is deterministic enough to compare between runs.
5. Selected candidates can be traced back to source/license.
6. The result supports a decision between public imagery and user-captured imagery.

## Out of scope

- final mesh generation;
- texture baking;
- GUI/map application;
- automatic downloading of every discovered image;
- replacing validated LiDAR/RNB evidence.
