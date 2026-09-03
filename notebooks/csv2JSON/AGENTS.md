# CSV-to-Aardvark project context

## Purpose

This directory is developing a reproducible metadata-ingest workflow for the American Geographical Society Library (AGSL) implementation of the OpenGeoMetadata (OGM) Aardvark schema.

The workflow must remain source-agnostic and reusable across many kinds of geospatial metadata. The Milwaukee Open Data Portal is one useful example and test case, not the pipeline's defining or preferred source.

The intended pipeline is:

1. Acquire metadata for geospatial resources from a range of portals, APIs, metadata endpoints, exports, and other sources.
2. Transform source metadata, often with OpenRefine, or manually enter metadata into the human-editable CSV template.
3. Validate and normalize each CSV record.
4. Convert each valid record to an individual OGM Aardvark JSON document suitable for GeoBlacklight/Solr ingest.

The AGSL implementation notes are the primary local-domain reference:

- https://uwm-libraries.github.io/GeoDiscovery-Documentation/docs/agsl-ogm-aardvark.html

Use the upstream OGM Aardvark documentation for the full schema and controlled vocabularies:

- https://opengeometadata.org/ogm-aardvark/

## Current development stage

`01_csv-2-json.ipynb` is the current development workspace. Use it to explore behavior and develop the main transformations, validation rules, and error messages.

Keep reusable logic in small, focused, testable functions even while it lives in the notebook. The planned destination is a Python module and command-line script; do not make core conversion behavior depend on notebook state, cell execution order, or hard-coded working directories.

The notebook TODO list records known correctness and validation work. Preserve it and update checkboxes only when the corresponding behavior has been implemented and verified.

## Relevant files

- `01_csv-2-json.ipynb`: exploratory implementation and current TODO list.
- `01_template.csv`: blank, human-editable input template.
- `template-filled.csv`: example populated template.
- `OpenIndexMaps_Aardvark_workshop.csv`: larger example input dataset.
- `../aardvark-profile/aardvark.csv`: mapping from CSV labels to Aardvark field names, types, obligations, and guidance.
- `../aardvark-profile/referenceURIs.csv`: mapping from human-readable reference columns to reference URIs.
- `../../schema/geoblacklight-schema-aardvark.json`: local JSON Schema used to validate generated records; from the repository root this is `schema/geoblacklight-schema-aardvark.json`.

Treat input CSVs as source data. Do not rewrite or reformat them merely as a side effect of conversion. Avoid changing template column names without also reviewing the profile mappings, examples, converter, tests, and student instructions.

## AGSL and Aardvark conventions

Preserve the distinction between the generic OGM Aardvark schema and AGSL's implementation choices. In particular:

- Generate JSON objects keyed by Aardvark field names, not by the friendly CSV headings.
- Enforce fields required by the schema and report missing or invalid values with the CSV row and column/field name.
- Use `Aardvark` for `gbl_mdVersion_s`.
- Use `American Geographical Society Library – UWM Libraries` for `schema_provider_s` when producing AGSL records, unless an explicit workflow requirement says otherwise.
- Treat `Public` and `Restricted` as the allowed access-rights values.
- Preserve genuine multivalued fields as JSON arrays. The CSV convention currently separates multiple values with `|`.
- Serialize `dct_references_s` as a JSON-encoded string inside the outer JSON record, using the mappings in `referenceURIs.csv`.
- Preserve Unicode in output.
- Validate spatial values and retain the documented `ENVELOPE(W,E,N,S)` coordinate order for geometry and bounding boxes.
- Treat identifiers, ARKs, dates, booleans, numeric arrays, controlled vocabularies, and output filenames as validation concerns rather than relying on pandas' implicit coercion.
- Never silently truncate numeric values, overwrite duplicate output filenames, or generate a filename from a missing identifier.

When the AGSL documentation, upstream schema documentation, profile CSV, and local JSON Schema disagree, do not silently choose one. Describe the conflict and ask which source should govern before making a compatibility-breaking decision.

## Source acquisition and transformation

Keep source acquisition separate from schema conversion. Source-specific adapters may fetch and reshape metadata, but the CSV-to-Aardvark converter should accept the documented CSV contract without requiring network access. The Milwaukee Open Data Portal may be used to develop one adapter and representative fixtures, but the architecture and terminology must not assume that all inputs come from Milwaukee or even from an open data portal.

OpenRefine is an established part of the human-in-the-loop workflow: metadata endpoints or exports may be opened in OpenRefine, cleaned and reshaped there, and exported into the CSV template contract. Treat an OpenRefine-produced CSV exactly like a manually populated or programmatically generated CSV. When practical, preserve and document reusable OpenRefine operation histories or project exports so the preparation step can be repeated and audited.

For source transformations:

- Retain the source record identifier and source URL so transformations are traceable.
- Make source-to-template mappings explicit and reviewable; do not hide substantive cataloging choices in generic cleanup code.
- Preserve the original source value when a mapping is uncertain, and report values that need human review.
- Prefer deterministic transformations that produce the same output from the same input.
- Do not invent missing descriptive metadata.
- Isolate provider-specific field names and API behavior in an adapter so additional portals can be supported later.

The manually populated template and harvested/transformed metadata should converge on the same validation and conversion path.

## Identifier minting and binding

The OGM Aardvark `id` is intended to be a persistent AGSL identifier. The current workflow manually supplies NOID-based ARKs, but a future high-value integration should wrap the NOID service so the pipeline can mint and bind identifiers as part of ingest. Starter Python wrapper code is known to exist, although it is not currently located in this repository; locate and evaluate that code before designing a replacement.

Keep NOID access behind a small interface separate from CSV parsing and Aardvark serialization. The converter should be testable with a fake identifier service and usable in an offline mode when IDs are already present. The eventual CLI should make identifier behavior explicit, for example validating supplied IDs by default and minting missing IDs only when the operator deliberately enables a minting mode.

Minting and binding are state-changing operations. Design this stage to:

- preserve and validate an existing `ID` rather than minting a replacement;
- associate each minted ID with a stable source identifier or other provenance needed to recognize the record on a rerun;
- avoid minting a second ID for the same source record when a run is retried;
- bind the identifier using the AGSL NOID conventions and report partial failures clearly;
- record enough information to reconcile a minted ID if later validation or file writing fails;
- keep service configuration and credentials outside source data, notebooks, container images, fixtures, and committed files.

Do not simulate successful minting, silently fall back to a fabricated ID, or call the live NOID service from ordinary unit tests. Resolve the precise NOID API, binding fields, ARK normalization rules, and transaction/retry behavior from the starter wrapper and service documentation before implementation.

## Target student workflow

The end product should be approachable for students who populate a CSV and run one documented command. Favor:

- clear input and output paths;
- actionable validation messages that identify the affected row and field;
- a validation-only or dry-run mode before files are written;
- a nonzero exit status when any record fails;
- a concise conversion summary with counts for read, written, skipped, and invalid records;
- deterministic output and explicit behavior for existing or stale files;
- examples and fixtures that are small enough to understand.

Do not require students to edit Python source, notebook cells, absolute paths, or container internals for routine conversion.

## Script and container direction

Design the eventual script as a thin CLI around importable conversion and validation functions. Configuration such as input CSV, schema/profile paths, and output directory should be command-line options with sensible repository-relative or container-relative defaults.

The eventual container should:

- run the same tested Python code as local development;
- pin dependencies reproducibly;
- accept input and expose output through documented bind-mounted directories;
- run without Jupyter for routine conversion;
- avoid requiring credentials for CSV-to-JSON conversion;
- keep any portal credentials out of images, notebooks, fixtures, and committed files.

Do not containerize the exploratory notebook as a substitute for extracting a script. Notebook support may remain available for teaching and development.

## Verification expectations

Add focused automated tests as reusable functions are extracted. Cover at least the cases listed in the notebook TODO, including booleans, integer-like arrays, decimals, Unicode, multivalues, ARKs, missing IDs, malformed identifiers, missing reference mappings, duplicate filenames, absent files, and stale output behavior.

Validate generated records against `../../schema/geoblacklight-schema-aardvark.json` in addition to testing expected values. Use small temporary output directories in tests; do not overwrite example CSVs or committed outputs.

For notebook changes, run the relevant cells from a clean kernel or exercise the extracted functions independently. For the future CLI, test both successful conversion and failure exit behavior.

## Working style

- Prefer `pathlib.Path` and paths resolved relative to an explicit project/input location, not the process's accidental current directory.
- Keep harvesting, mapping, normalization, validation, serialization, and file writing separable.
- Prefer explicit types and validation over broad exception handling or pandas inference.
- Preserve useful notebook narrative and avoid unrelated notebook reformatting or output churn.
- Document cataloging-policy assumptions close to the mapping that implements them.
