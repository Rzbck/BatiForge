# 0003 — Facade evidence and geometric detail

Status: active / IMPLEMENTED_NOT_VALIDATED
Issue: #9
Branch: `feat/facade-evidence-20260923`

## Goal
Recover facade detail such as doors, windows, recesses and secondary volumes from real image evidence while keeping RNB + IGN LiDAR as the metric authority.

## Sequence
1. Prepare a gitignored photo intake workspace and preserve original user-captured images/metadata.
2. Use Blender only as the 3D inspection host; import BatiForge local XYZ numerically without OBJ axis reinterpretation.
3. Run image quality/coverage gates before photogrammetry.
4. Run deterministic COLMAP 4.2 CUDA sparse reconstruction; stop if registration/coverage is weak.
5. Register/re-scale the photogrammetric model to the BatiForge RNB/LiDAR frame and report residuals.
6. Recover facade planes/openings from registered evidence. Doors/windows become geometry only when supported by multiple views / reconstructed depth; otherwise remain unresolved.
7. Export a fused Blender-inspectable model with provenance/confidence per added facade component where practical.

## Guardrails
- no scraping restricted imagery;
- no AI-generated architectural geometry treated as truth;
- semantic/AI models may classify openings or surfaces, but metric placement and dimensions must be tied back to registered image/LiDAR evidence;
- do not deform the authoritative building footprint or global scale to fit imagery;
- keep current Roofer/LiDAR building core as a separate recoverable asset.

## First host validation
Create the facade workspace, launch the existing c070 building in Blender through the exact-XYZ loader, then ingest the first real facade photo session.
