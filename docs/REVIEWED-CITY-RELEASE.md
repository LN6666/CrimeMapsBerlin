# Reviewed city release gate

`reviewed_city_release.py` closes the gap between a reviewed local candidate and
an owner-approved static data generation. It currently accepts this repository's
official-source review contract: Berlin, Hamburg, Cologne and Frankfurt. Munich
uses the separately authorized upstream workflow. Other repositories must retain
their own source contracts before adopting this gate.

## Prepare the inspection packet

Save the following JSON under the Git-ignored `.runtime/` directory, using
absolute paths to the **current** inputs:

```json
{
  "city": "hamburg",
  "source_db": "/absolute/runtime/police.sqlite",
  "source_pbf_path": "/absolute/downloads/hamburg.osm.pbf",
  "inventory_path": "/absolute/runtime/reviewed-scene-inventory.json",
  "geometry_index_path": "/absolute/runtime/osm-geometry-index.json",
  "geometry_ledger_path": "/absolute/runtime/geometry-ledger-current.json",
  "map_ledger_path": "/absolute/runtime/map-ledger-current.json",
  "poi_root": "/absolute/runtime/poi-product",
  "catalog_path": "/absolute/repository/catalog.json",
  "reviewed_poi_binding_path": null,
  "reviewed_display_path": null,
  "acceptance_path": null,
  "publication_timezone": null,
  "month_basis": "reviewed_incident_time"
}
```

Provide the optional display and POI bindings when they were used to build the
candidate. Preserve the original timezone and month basis. Preparation rechecks
every current source body, stored review and evidence quote; validates the native
index against the actual PBF hash and municipal boundary; recompiles the explicit
geometry and map choices; then reproduces every candidate file, including tiles.
It cannot infer semantic decisions or grant approval.

```sh
PYTHONPATH=src uv run python -m crimemapsberlin.reviewed_city_release packet \
  --inputs .runtime/release-inputs.json \
  --candidate /absolute/runtime/current-candidate \
  --out .runtime/current-owner-release-packet.json
```

The packet records exact input and payload hashes, coverage, unlocated scenes,
counting limits and every remaining publication block. A completed source scan
describes the selected channel and frozen range, not all crimes or all history.
An explicit unresolved geometry can remain unknown; proximity to a POI does not
prove an offence at that business.

## Current technical acceptance

The optional acceptance file must have `schema_version: 1`, the city ID,
`generation`, `candidate_digest`, and `candidate_file_hashes` equal to this exact
candidate. Its `input_bindings` must equal `ReleaseInputs.bindings()` with
`acceptance_path` omitted. Eight `checks` must be explicitly true:

- `source_acquisition`
- `source_semantics`
- `geometry_dispositions`
- `map_semantics`
- `poi_product`
- `data_assembly`
- `browser_behaviour`
- `gap_disclosure`

For each check, `evidence` must contain a nonempty list of
`{"path": "/absolute/current/check-result.json", "sha256": "actual file SHA-256"}`.
These are saved inspection results, not automatically generated assertions of
accuracy. Changed or missing evidence, changed inputs or changed candidate bytes
invalidate acceptance. Missing acceptance remains visible as a publication block.
Acceptance does not remove source/display blocks or grant owner permission.

## Explicit owner approval and local promotion

After the owner inspects and questions **this packet and map**, an approval record
must name its `city`, `packet_digest`, `candidate_digest`, `approved: true`,
`approved_by`, `inspection_note`, and `approved_at` (ISO time with timezone).
`accepted_scope` must equal the packet's full `scope` object, including incomplete
coverage and unknown positions. Codex may record a human instruction within its
authorized scope; a scheduler or LLM verdict cannot supply that approval.

The owner's October 2, 2026 project instruction grants standing authorization
for the routine batch approval step after required checks pass. For that scope,
record `authorization_type: "standing_routine_batch_authorization"`, the exact
current packet/candidate hashes, the instruction evidence and accepted limits.
Do not ask for the same routine approval again or claim a new personal owner
inspection. Source and technical checks remain mandatory. Promoted manifests
record `OWNER_APPROVED` and the authorization type; this metadata does not
generate approval or authorize a new hosting service.

```sh
PYTHONPATH=src uv run python -m crimemapsberlin.reviewed_city_release publish \
  --inputs .runtime/release-inputs.json \
  --candidate /absolute/runtime/current-candidate \
  --owner-approval .runtime/explicit-owner-approval.json \
  --out /absolute/local/static-city-data-root
```

Promotion repeats preparation and rejects stale approvals or any remaining
technical/source block. Only the two explicit owner-missing blocks may be cleared.
It copies verified payloads into an immutable generation, retains prior
generations, writes a receipt with the owner signoff and file hashes, then switches
the manifest atomically as the final commit point. Copy failures preserve the old
manifest. Conflicting generations, symlinks, another city's output and concurrent
promotion are rejected. Published browser labels require both owner approval and
publication readiness.

This command installs local static data. It does not deploy a site, upload source
bodies, commit generated data, merge a PR, or provide hosting authorization.
All source bodies, review ledgers, candidate data, packets, acceptance evidence,
approval records and local static output must remain excluded from Git. Deployment
of the approved artifacts remains a separate owner-authorized step.
