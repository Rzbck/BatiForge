# Panoramax provider

Status: metadata-only survey with target-orientation analysis.

BatiForge uses Panoramax as an imagery-discovery provider, not as an implicit
license grant for arbitrary downstream use.

## API model

Panoramax exposes a STAC-compatible HTTP API. Collections represent sequences
and items represent pictures. Picture discovery is available through
`GET`/`POST /api/search`.

Official documentation:
- https://docs.panoramax.fr/backend/api/api/
- https://docs.panoramax.fr/web-viewer/05_Compatibility/
- https://docs.panoramax.fr/federated-catalog/data_export/

The default endpoint is:

`https://panoramax.openstreetmap.fr/api`

It remains configurable because BatiForge must be able to query other Panoramax
instances.

## License handling

Panoramax documents the picture license as an instance-level setting. The
license can be exposed through `/api/configuration` and through a STAC landing
page link with `rel=license`.

BatiForge records this license/provenance metadata in survey output. It does not
bulk-download imagery during discovery.

Official license-setting documentation:
- https://docs.panoramax.fr/backend/install/settings/#pictures-license

## View metadata

Panoramax/STAC exposes `view:azimuth` for picture heading. Perspective metadata
can expose horizontal field of view under
`pers:interior_orientation.field_of_view`. Panoramax metadata also distinguishes
360/equirectangular imagery from flat imagery when that information is known.

For every candidate BatiForge now computes:
- bearing from camera position to the target;
- smallest heading error relative to the target;
- coarse horizontal class: `front`, `lateral`, `rear`, `panoramic`, or `unknown`;
- whether the target coordinate falls inside the reported horizontal field of
  view when enough metadata exists;
- deterministic per-sequence summary counts.

This classification is deliberately geometric only. `target_in_fov=true` does
not prove that the building is visible: terrain, vegetation, other buildings,
image framing, capture height, blur and resolution can still make a picture
useless. Visual preview remains a separate selection stage.

## Current stage

The provider currently:
- searches a radius-derived WGS84 bounding box;
- follows STAC pagination links;
- filters candidates by true great-circle distance;
- records stable picture and sequence identifiers;
- records capture date, image dimensions and view metadata when present;
- records source and license references;
- computes target-facing geometry without downloading image pixels;
- groups candidates by sequence in the survey output;
- emits deterministically sorted metadata JSON.

Full-resolution image download and photogrammetric selection remain separate
later stages.
