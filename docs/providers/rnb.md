# RNB building footprint provider

Status: authoritative building-identity and footprint acquisition for the building-centric reconstruction core.

BatiForge uses the Référentiel National des Bâtiments (RNB) as the building identity pivot. For a known RNB ID, the public OGC API - Features endpoint returns one building directly as a GeoJSON Feature.

Current read endpoint:

`https://rnb-api.beta.gouv.fr/api/alpha/ogc/collections/buildings/items/{rnb_id}`

Official documentation:
- https://rnb-fr.gitbook.io/documentation/api-et-outils/api-batiments/consulter-un-batiment
- https://rnb-fr.gitbook.io/documentation/api-et-outils/api-batiments/standard-ogc-api-features

The generic `/api/alpha/buildings/{rnb_id}/?format=geojson` route is not used by BatiForge for footprint acquisition. Although it supports a `format=geojson` parameter, its documented response media type is `application/json`; requesting that route with `Accept: application/geo+json` produced HTTP 406 during host validation. The OGC item endpoint explicitly serves `application/geo+json` and is therefore the unambiguous footprint source.

The RNB data is published as open data. BatiForge records the source URL and RNB ID with derived geometry.

## Coordinate handling

The API GeoJSON is treated as WGS84 / EPSG:4326. BatiForge projects the authoritative footprint to the reconstruction CRS, currently EPSG:2154 for the Espace des Forges reference case.

The projected footprint is then expressed both:
- in absolute Lambert-93 coordinates; and
- in the exact same local metric XY frame used by the LiDAR roof analysis.

This keeps authoritative planimetry and LiDAR roof evidence aligned without discarding their georeference.

## Geometry policy

At this stage BatiForge preserves outer Polygon / MultiPolygon rings and refuses to silently discard interior rings/holes.

The footprint is a hard planimetric constraint for later roof clipping, eaves/walls and shell generation. Roof-plane convex support hulls remain diagnostic evidence until they are reconciled with this authoritative boundary.
