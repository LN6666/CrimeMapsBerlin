# GitHub country chart integration

The real dynamic image URL is `https://<connected-worker>/v1/chart/berlin.svg?lang=en`, with the fixed city slug substituted for each repository. This is the wide world-map and ranking card. Add `&layout=stacked` for the narrow image; layout is an allowlisted enum and a separate cache key. The map and ranking consume the same published/suppressed/rounded country rows. GET never creates a page-view event. The image contains localized country labels, accessible SVG title/description, cumulative rounded counts and its UTC generation time. A frontend script is not needed in the README. Gray means no published group, not zero visits. These are approximate connection origins, not nationality or residence.

GitHub uses Camo to proxy external images. The Worker sets five-minute caching, but GitHub may show an older cached copy; that is not a promise that README images update every five minutes. Check the generation time in the image. Country figures are map page views, not visits to the repository or its README. [GitHub's Camo and cache explanation](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-anonymized-urls), [Camo supported MIME types](https://raw.githubusercontent.com/atmos/camo/master/mime-types.json).

Until a real Worker is connected, show the localized “statistics not connected” text with the local gray-map placeholder and empty ranking. Generate it with `node services/analytics/src/placeholders.mjs CITY` from the repository root. Its sidecar has `source_kind=not_connected`, null source/metric/time and no counts. The generator refuses to replace an existing live image or an unverified image. Do not embed `.invalid` examples or local test fixtures in a public README.

A saved snapshot is also supported:

```sh
node services/analytics/src/snapshot.mjs https://CONNECTED-WORKER berlin de docs/assets/visitors-by-country.de.svg
node services/analytics/src/snapshot.mjs https://CONNECTED-WORKER berlin en docs/assets/visitors-by-country.en.svg
node services/analytics/src/snapshot.mjs https://CONNECTED-WORKER berlin zh docs/assets/visitors-by-country.zh.svg
```

Run those commands from the city repository root. The CLI writes a JSON sidecar with `city`, `locale`, repository-relative `path`, SHA-256, `generated_at_utc`, `source_kind=live_aggregate`, public source URL, metric and privacy parameters. README integration must verify that digest and reject a partial image/sidecar update.

The CLI requires a current live HTTPS response for the selected city and refuses to write on errors, mismatched city, invalid schema or stale data. It writes only the safe SVG and logs its public aggregate source/time. Keep the previous good snapshot when a later update fails. A scheduled GitHub job may update only these reviewed public snapshots after the real backend is connected; no schedule or automation was created by this window. Do not export raw storage or logs to a repository.

Use this text beside either image, with a descriptive image alt and a link to the live stats endpoint as an accessible alternative:

| Language | Caption |
|---|---|
| Deutsch | Freiwillig erfasste Kartenaufrufe nach Ländern. Einzelne Besucher werden nicht gezählt. Gruppen unter 20 Aufrufen werden verborgen oder zusammengefasst, Zahlen auf Zehner abgerundet. GitHub kann eine ältere Bildfassung anzeigen; beachten Sie die Zeit im Bild. |
| English | Optional map page views by country. Individual visitors are not counted. Groups below 20 are hidden or combined, and values are rounded down to 10. GitHub may show an older image; check the time in the image. |
| 中文 | 按国家累计的自愿地图页面浏览，不统计独立访客。少于20次的分组合并或隐藏，数字按10次向下取整。GitHub可能显示较早的缓存图片，请看图中时间。 |

The SVG's description includes text for every displayed group, including labels that are shortened visually. The adjacent caption states what the chart counts. A README screenshot or SVG fetched by GitHub reveals the proxy request's network details to the image host, not the reader's map country. This is why image requests never enter the collector.


Use responsive local images on all three README languages (substitute the language code):

```html
<picture>
  <source media="(max-width: 640px)" srcset="docs/assets/visitors-by-country.en.mobile.svg">
  <img src="docs/assets/visitors-by-country.en.svg" alt="Countries and regions of optional map page views; statistics not connected">
</picture>
```

For a current connected aggregate, the original snapshot command writes the wide image. The matching narrow snapshot is:

```sh
node services/analytics/src/snapshot.mjs https://CONNECTED-WORKER berlin en docs/assets/visitors-by-country.en.mobile.svg stacked
```

Both layouts use the same model and preserve city/locale/source/time/SHA metadata. Replace placeholder assets only with reviewed live-aggregate snapshots whose digest matches their sidecar. A later failed fetch preserves the last good image. `WORLD-MAP-SOURCES.md` records the public-domain vector source, deterministic simplification and exact country/region code mapping; no map library, tiles or tracking script is fetched to draw this card.
