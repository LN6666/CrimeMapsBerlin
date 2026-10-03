# 14-city, three-language README integration

Keep the current world-map/blue-ranking layout and responsive picture structure. Each city repository must use the SVGs generated with its own fixed city ID; never copy a Berlin live aggregate into the other thirteen repositories. There are 42 localized READMEs and 84 image layouts. The existing image paths remain unchanged:

```html
<picture>
  <source media="(max-width: 520px)" srcset="docs/assets/visitors-by-country.en.mobile.svg">
  <img src="docs/assets/visitors-by-country.en.svg" alt="Country distribution of this city website’s published page views">
</picture>
```

Replace `en` with `de` or `zh` in the corresponding README. Use a real local aggregate only after a valid GoatCounter JSON export; otherwise retain the reviewed gray no-data SVGs. The snapshot CLI makes the site data and six pictures from one identical city aggregate and preserves newer/previous-good outputs on invalid inputs. Source, time, metric and aggregate digest are recorded in sidecars. Reuse the existing manual/release process; do not add trackers to the SVG or schedule independent city exports.

EN: This map and ranking show this city website’s country/region page views from GoatCounter, including ordinary reloads; language changes and map operations do not add a count. These are not unique people or README readers. Small groups are hidden/combined and values round down to ten. Gray means no published count, not zero. The snapshot date is shown; GitHub may cache images.

DE: Karte und Rangliste zeigen die Länder-/Regionen-Seitenaufrufe dieser Stadt-Website aus GoatCounter, einschließlich Neuladen; Sprachwechsel und Kartenaktionen zählen nicht zusätzlich. Das sind weder eindeutige Personen noch README-Leser. Kleine Gruppen werden verborgen/zusammengefasst und Werte auf Zehner abgerundet. Grau bedeutet keine veröffentlichte Zahl, nicht null. Das Snapshot-Datum wird angezeigt; GitHub kann Bilder zwischenspeichern.

ZH: 地图和排行显示此城市网站的 GoatCounter 国家／地区页面浏览，包括普通刷新；语言切换和地图操作不另计。这不是独立人数或 README 读者统计。小样本合并或隐藏，数值按10向下取整；灰色表示没有公布的次数，不表示零。图中标注快照日期，GitHub 图片可能有缓存。

The shared README writer integrates these paragraphs into each city's three language files. Analytics does not overwrite their repository homes, GitHub feedback links, footer icons or city map content.
