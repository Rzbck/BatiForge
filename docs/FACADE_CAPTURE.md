# Facade capture for geometric reconstruction

Goal: recover facade geometry such as doors, windows, recesses and secondary volumes. Photos are evidence for geometry, not a texture-only deliverable.

## Capture pattern

- Prefer the phone's normal/main `1x` camera. Keep the same lens for one capture sequence; avoid digital zoom.
- Keep original files and metadata. Do not resize, screenshot, re-encode or strip EXIF before ingestion.
- Walk continuously around every accessible facade. Aim for roughly 60-80% overlap between neighbouring frames.
- For each facade, capture both near-frontal views and 30-45 degree oblique views from each side. Corners are especially valuable because they tie adjacent facade planes together.
- Include the whole wall in many frames. Add closer frames for doors, windows, deep recesses or architectural details, but do not replace the wider overlapping sequence with close-ups.
- Keep the camera moving sideways as well as changing angle; a pile of photos from one position does not provide useful parallax.
- Use landscape orientation when practical, keep the camera reasonably level, and avoid extreme ultrawide distortion.
- Avoid motion blur. Prefer daylight and reasonably even exposure. Moving people/cars can be present, but avoid having them cover the same architectural area in many consecutive frames.

## Minimum useful first session

For one test building, target about 30-60 useful photos across the accessible facades. More is useful only when it adds overlap or viewpoints, not duplicates.

## BatiForge provenance rule

User-captured originals live under the gitignored workspace and are never committed. The pipeline must preserve source filename, capture metadata when available, and quality/rejection reasons. Photogrammetry may refine facade/detail geometry only after registration back to the authoritative RNB/LiDAR metric frame.
