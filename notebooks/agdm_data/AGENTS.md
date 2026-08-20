# AGDM / Allmaps Context

`examples.md` is a hand-curated table of AGDM example records for testing catalog bounding boxes, IIIF manifests, and Allmaps georeference annotations.

The table intentionally includes spatial edge cases: antimeridian crossing, polar, quadrant examples, prime-meridian crossing, equator/inset-map cases, and Mexico City.

Preserve the distinction between Allmaps `map`, `image`, and `manifest` annotation URLs:

- Use `maps/{hash}` for single map objects when one map annotation is the relevant unit.
- Use `images/{hash}` when one IIIF image contains multiple Allmaps map objects, such as inset maps.
- Use `manifests/{hash}` when a compound object has multiple image-level annotations, such as the six-sheet Ghana example.

`annotations/` stores downloaded JSON representations of individual Allmaps georeference `Annotation` objects, named by the Allmaps map hash: `{hash}.json`.

The polar example, `Polus Antarcticus`, is currently marked blocked because Allmaps transformations do not appear to support the needed antimeridian/polar behavior. See https://github.com/allmaps/allmaps/issues/613.

When updating Allmaps links, verify the annotation endpoint first and only record links that resolve. For `images/` or `manifests/` endpoints, inspect `items[]` to understand how many individual map annotations are represented.
