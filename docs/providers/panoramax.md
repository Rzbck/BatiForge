# Panoramax provider

Status: metadata survey plus bounded thumbnail-preview inspection.

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

## Survey stage

The provider currently:
- searches a radius-derived WGS84 bounding box;
- follows STAC pagination links;
- filters candidates by true great-circle distance;
- records stable picture and sequence identifiers;
- records capture date, image dimensions and view metadata when present;
- records source and license references;
- calculates target bearing, heading error and target-in-FOV when metadata allows;
- emits deterministically sorted metadata JSON.

Orientation scoring is geometry only. It does not prove line of sight,
occlusion state, actual facade visibility or sufficient photogrammetric detail.

## Preview inspection stage

Panoramax/STAC items may advertise an explicit thumbnail derivative through:
- `properties.geovisio:thumbnail`; or
- an asset with the `thumbnail` role.

BatiForge's preview stage deliberately requests the item metadata first and then
fetches only an explicitly advertised thumbnail derivative. It does not fall
back to `visual`, `data`, tiled or original/high-definition assets.

The shortlist is deterministic and sequence-capped. Priority is:
1. non-panoramic candidates with `target_in_fov=true`;
2. non-panoramic `front` candidates whose FOV is unknown;
3. panoramas.

A candidate with known `target_in_fov=false` is not promoted merely because its
heading is inside the broader `front` class.

Preview files, manifest and HTML gallery belong under a gitignored workspace and
are for human visual rejection/selection only. They are not COLMAP inputs.

Full-resolution image selection/download remains a later deliberate stage.
