# Panoramax provider

Status: initial metadata-only implementation.

BatiForge uses Panoramax as an imagery-discovery provider, not as an implicit
license grant for arbitrary downstream use.

## API model

Panoramax exposes a STAC-compatible HTTP API. Collections represent sequences
and items represent pictures. Picture discovery is available through
`GET`/`POST /api/search`.

Official documentation:
- https://docs.panoramax.fr/backend/api/api/
- https://docs.panoramax.fr/backend/dev/STAC_compatibility/

The initial default endpoint is:

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

## Current stage

The provider currently:
- searches a radius-derived WGS84 bounding box;
- follows STAC pagination links;
- filters candidates by true great-circle distance;
- records stable picture and sequence identifiers;
- records capture date, image dimensions and view metadata when present;
- records source and license references;
- emits deterministically sorted metadata JSON.

Image download, facade-visibility scoring and photogrammetric selection remain
separate later stages.
