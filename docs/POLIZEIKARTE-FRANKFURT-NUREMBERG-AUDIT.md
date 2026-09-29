# POLIZEIKARTE acceleration audit: Frankfurt and Nuremberg

Checked on 2026-09-30. This audit distinguishes three separate claims:

1. a city has a POLIZEIKARTE page;
2. POLIZEIKARTE has structured the entries it currently carries; and
3. that structured set is complete and clean enough to replace the project's
   official-corpus LLM review.

The first two claims are true for both cities. The third is false for Frankfurt
and is a viable, but not yet approved, fast path for Nuremberg.

All counts below come from local ignored snapshots. The ten exclusive category
pages were checked against one common total, non-overlapping entry IDs and their
map payloads. Official overlap used only canonical URLs or exact Presseportal
article IDs. Titles, dates, districts and coordinates were not used to declare
an automatic match. Neither audit accepts upstream semantics or grants
publication authority.

## Measured comparison

| Measure | Munich accepted baseline | Frankfurt | Nuremberg |
| --- | ---: | ---: | ---: |
| POLIZEIKARTE entries | 1,814 | 209 | 654 |
| Distinct linked official URLs | 342 | 209 | 654 |
| Entries per linked URL | 5.30 | 1.00 | 1.00 |
| Entries with upstream coordinates | 1,355 | 52 | 547 |
| Street-precision entries | 994 | 28 | 398 |
| Full official reports in the project's current corpus | not used for the accepted path | 1,230 | 849 |
| Exact upstream-to-corpus URL matches | not applicable | 186 | 13 |
| Exact matched share of official reports | not applicable | 15.1% | 1.5% |
| Approximate current official-body input | bypassed by owner decision | 377k tokens | 328k tokens |
| Approximate structured map-metadata input | accepted upstream database | 19k tokens | 63k tokens |

Token figures use a transparent 3.5-character approximation and are for
relative workload comparison, not billing. They exclude structured decision
output and later geometry checks.

## Frankfurt

The snapshot ranges from 2025-12-02 through 2026-09-27, but 199 of its 209
entries fall in August or September 2026. It is therefore not a continuous
365-day replacement for the 1,230-report 2026 official corpus.

All 209 POLIZEIKARTE entries link to Presseportal. Of those, 186 match a current
Frankfurt official report exactly; 23 do not occur in the selected local corpus.
The 186 matched bodies contain about 203,349 of the official corpus's 1,320,335
characters, or 15.4% of the original-text input.

Only 28 entries have street precision. The other structured locations are 149
district and 32 city labels. Twenty-four of the 52 supplied coordinates belong
to city or district precision and cannot be used as incident points.

A representative exact match shows the limitation. POLIZEIKARTE entry 135454
classifies Presseportal article 6360452 as `gewalt`, summarizes one assault and
retains only district precision (`Gallus`). The 1,638-character official body
separately names the pickup road, the actual assault intersection, the escape
direction and later hospital transport. The upstream row helps with the class
lead, but it does not replace the project's location-role review.

### Frankfurt speed effect

- **Hint mode, with the LLM still reading every official body:** original input
  remains essentially unchanged. The upstream fields can shorten reasoning for
  186 reports, so the expected whole-corpus gain is only about 0–5%.
- **Bounded inheritance for the 186 exact matches:** the article queue falls
  from 1,230 to 1,044. Ignoring metadata overhead gives an upper bound of
  1.18× throughput. Including the 65,631-character structured snapshot gives
  about 1.12× input throughput, or roughly an 11% practical reduction.
- **Replacing the corpus with POLIZEIKARTE:** rejected by the evidence because
  the older months are largely absent.

Frankfurt should therefore retain the official corpus as the primary input.
POLIZEIKARTE can be attached to the 186 exact matches as a review lead, while
the original narrative remains decisive.

## Nuremberg

The snapshot is continuous from 2025-09-29 through 2026-09-28 and contains
entries in every intervening month. It is a city-specific set, while the 849
selected Polizeipräsidium Mittelfranken reports cover the wider region.

Of 654 entries, 641 link to `polizei.bayern.de` and 13 link directly to the
selected Presseportal newsroom. Exact URL matching therefore finds only 13 of
849 local reports. That low number measures incompatible source URLs, not an
absence of upstream structuring.

POLIZEIKARTE supplies 398 street-precision entries and 547 coordinates. The
remaining 200 city and 56 district entries must stay non-point geometry; the
149 coordinates attached to those coarse precision levels are representatives
and must be withheld from incident counts.

A representative row is entry 135621. It supplies category `gewalt`, street
precision, a coordinate and a detailed summary for the Spittlertorzwinger /
Ottostraße assault. The selected newsroom contains the same incident as article
6360414. POLIZEIKARTE also contains entry 135771 for that incident through the
Presseportal URL. This is a semantic duplicate with different source URLs and
titles, so URL/hash deduplication alone cannot remove it. Manual inspection of
the thirteen recent Presseportal-linked rows found at least four clear pairs of
this kind; a full LLM duplicate pass is required before counting.

### Nuremberg speed effect

- **Hint mode limited to exact URLs:** only 13 reports are connected, so the
  whole-corpus gain is below 2%.
- **Cross-source hints while retaining all official-body rereads:** linking 641
  Bayern URLs to the newsroom narratives becomes an extra task. This does not
  provide a reliable speed gain.
- **Munich-style upstream-primary path:** the 654-entry structured metadata is
  220,021 characters, approximately 63k tokens, compared with about 328k tokens
  for the 849 official bodies. Metadata alone is 5.2× smaller. Including
  summaries, duplicate review and targeted source checks gives a realistic
  **2.5–4× faster LLM pass**. The result still needs semantic deduplication,
  municipality boundary checks, coarse-coordinate withholding, hashes, map
  assembly and owner approval.

Nuremberg is therefore a strong candidate for the same owner-accepted upstream
policy used for Munich. It should not reuse the current 849-report review queue
and also count all 654 upstream entries, because that would double-count some
incidents.

## Why Munich is already further ahead

Munich is not faster merely because its page exists. Its accepted checkpoint
has several additional properties:

- the owner explicitly accepted POLIZEIKARTE classifications and locations as
  the semantic basis;
- all ten categories form one verified rolling 365-day partition;
- 1,814 entries link to only 342 official URLs, showing that upstream work has
  already split many aggregate police pages into separate incidents;
- 994 entries have street precision and 992 of those have coordinates;
- municipal-boundary checks already retained 884 in-city street points and
  withheld outside-city or coarse representative coordinates;
- a deterministic local map candidate and owner-review package already exist.

Frankfurt lacks the historical coverage and detailed geometry needed for this
path. Nuremberg has strong temporal coverage and geometry, but still lacks the
deduplicated, boundary-checked, owner-accepted checkpoint.

## Reproducible local audit

The audit command writes structured upstream data only under ignored
`.runtime/`; it never writes report bodies, semantic decisions or public map
data to Git:

```sh
PYTHONPATH=src uv run python -m crimemapsberlin.polizeikarte_coverage \
  --city frankfurt \
  --official-db .runtime/safety/cities/frankfurt/police.sqlite \
  --out .runtime/safety/polizeikarte-coverage/frankfurt.json

PYTHONPATH=src uv run python -m crimemapsberlin.polizeikarte_coverage \
  --city nuernberg \
  --official-db /absolute/path/to/CrimeMapsDE-Cities-11-14/.runtime/safety/cities/nuremberg/newsroom.sqlite \
  --out .runtime/safety/polizeikarte-coverage/nuernberg.json
```

The local snapshots used for this audit had SHA-256 digests
`edf6e3beafcf8d781fce680d8bdf885e8cf7d113e77ffabddeb03c84b798004a`
for Frankfurt and
`bc42569b0a46de7e63d75bc759d86ad44a6016af9236b2d9149b87cc5c506ae1`
for Nuremberg. The corresponding official-overlap audit digests were
`bdea82aeff31965c52b7aae4a91dda7dc7b573f0965f85c9d0f945dcf14483c6`
and `150a4b0753584d3526873fd0c40f1b2ef4ecce011aa066d8e7591baf04fecfb1`.
