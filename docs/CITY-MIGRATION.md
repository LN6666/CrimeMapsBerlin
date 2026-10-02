# City data for local development

This repository contains the application and source-processing tools. Police report databases, downloaded articles, review archives and generated city bundles are kept outside Git. The new public map is still being prepared.

The repository's `city-config.json` selects its city and production URL prefix. The development server runs at `http://127.0.0.1:5173/`. Changing a query parameter cannot turn this repository into another city's map.

To inspect an existing checked bundle locally, use its schema-2 city directory as the source. Obtain the exact manifest hash and a provenance JSON containing the city, manifest hash and every declared file hash from the bundle's review handoff. Those values must come from the checked delivery, rather than being generated to approve an unknown download.

```sh
uv sync --locked
uv run python scripts/migration/city_artifact.py \
  --city dresden \
  --source /path/to/checked-city-directory \
  --manifest-sha256 CHECKED_MANIFEST_SHA256 \
  --provenance /path/to/checked-provenance.json \
  --provenance-sha256 CHECKED_PROVENANCE_SHA256 \
  --output .runtime/local-city-import \
  --receipt .runtime/local-city-import-receipt.json
```

Use the lowercase city ID from `city-config.json` in place of `dresden`. The output directory must not already exist. The command checks the declared file set, city identity, hashes, announcement IDs and size limit before copying files. It does not repeat the source review or grant publication approval.

After a successful local import, copy the resulting `safety/` directory into `web/public/safety/`, which Git ignores. Do not replace a usable bundle until the import has passed. Start the frontend with `npm --prefix web run dev`. Without the bundle, the application reports unavailable data.

Public deployment uses a separately accepted release artifact and the guarded Pages workflow. A successful build or local import does not enable Pages, connect visit collection or activate private feedback. Keep those services disabled until their actual configuration and checks are complete.
