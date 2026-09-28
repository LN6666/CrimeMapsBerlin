import { test, expect } from "@playwright/test";
import { LRU, tileKeys } from "../src/safety/data";
import { styledPois } from "../src/safety/model";

test("tile enumeration is bounded and LRU evicts oldest", () => {
  const cache = new LRU<number>(2);
  cache.set("a", 1);
  cache.set("b", 2);
  cache.get("a");
  cache.set("c", 3);
  expect(cache.get("b")).toBeUndefined();
  expect(cache.size).toBe(2);
  expect(tileKeys([-180, -80, 180, 80], [0.04, 0.025], new Set())).toEqual([]);
  expect(
    tileKeys([13.4, 52.5, 13.41, 52.51], [0.04, 0.025], new Set(["335_2100"])),
  ).toEqual(["335_2100"]);
});

test("named place links remain candidates and do not affect other POIs", () => {
  const data = {
    pois: {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [13.4, 52.5] },
          properties: { id: "named", kind: "park" },
        },
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [13.4, 52.5] },
          properties: { id: "other", kind: "park" },
        },
      ],
    },
    catalog: { poi_types: { park: { color: "#059669" } } },
  };
  const links = [
    {
      event_id: "p",
      poi_id: "named",
      status: "named_place_candidate",
      source_url: "https://example.org",
      mention_basis: "keyword",
    },
  ];
  const fc = styledPois(
    data as any,
    links,
    new Set(["p"]),
    new Set(["park"]),
    true,
  );
  expect(fc.features[0].properties.candidate_count).toBe(1);
  expect(fc.features[0].properties.count).toBe(0);
  expect(fc.features[1].properties.association_count).toBe(0);
});

test("overview loads no POI geometry, month switching clears missing months", async ({
  page,
}) => {
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.fulfill({
      contentType: "image/png",
      headers: { "access-control-allow-origin": "*" },
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4+fYlAAWCAsAGiqfBAAAAAElFTkSuQmCC",
        "base64",
      ),
    }),
  );
  const empty = { type: "FeatureCollection", features: [] };
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  const hex = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [13.4, 52.5],
              [13.42, 52.5],
              [13.42, 52.52],
              [13.4, 52.52],
              [13.4, 52.5],
            ],
          ],
        },
        properties: {
          id: "test",
          edge_m: 1100,
          count: 2,
          event_ids: ["1", "2"],
        },
      },
    ],
  };
  page.on("request", (r) => requests.push(r.url()));
  await page.route("http://127.0.0.1:4173/safety/**", (route) => {
    const url = route.request().url();
    if (url.endsWith("manifest.json"))
      return route.fulfill({
        json: {
          schema_version: 2,
          city: "Berlin",
          generation: "0123456789abcdef-20260927T120000",
          retrieved_at: "2026-09-27T12:00:00Z",
          coverage: { discovered: 2, fetched: 2, pending: 0, failed: 0 },
          months: { "2026-09": { count: 2 } },
          categories: ["Raub"],
          tile_index: { pois: [], roads: [] },
          tile_size: [0.04, 0.025],
          catalog: {
            poi_types: { bar: { color: "#d97706", label: "酒吧" } },
            sources: [],
            coverage: [],
            exhaustive: false,
          },
          zones: { places: [], features: [], geometry_status: "pending" },
          metadata: { zoom_threshold: 13 },
        },
      });
    if (url.includes("/months/"))
      return route.fulfill({
        json: {
          event_ids: ["1", "2"],
          events: [
            {
              id: "1",
              title: "Test",
              category: "Raub",
              month: "2026-09",
              coordinates: null,
              location_precision: "unknown",
              poi_mentions: [],
              source_url: "https://www.berlin.de/",
            },
            {
              id: "2",
              title: "Named park",
              category: "Raub",
              month: "2026-09",
              coordinates: [13.41, 52.51],
              location_precision: "place",
              location_label: "Testpark",
              location_extent_m: 110,
              location_selection: "first_explicit_incident_scene",
              other_scene_candidates: [
                { name: "Anderstraße", sentence_index: 4 },
              ],
              reported_location_geometry: {
                type: "LineString",
                coordinates: [
                  [13.41, 52.51],
                  [13.412, 52.51],
                ],
              },
              poi_mentions: ["park"],
              source_url: "https://www.berlin.de/",
              reviewed_tags: [{
                tag: "property_offence",
                evidence_quote: "Das Fahrzeug wurde beschädigt.",
              }],
            },
          ],
          hex: { overview: hex, detail: hex },
          links: [],
        },
      });
    return route.fulfill({ json: empty });
  });
  await page.goto("/");
  await expect(page.locator("#city-switch optgroup")).toHaveCount(3);
  await expect(page.locator("#city-switch option")).toHaveCount(14);
  await expect(page.locator("#city-switch")).toHaveValue("berlin");
  await expect(page.locator("#city-switch option[value='hamburg']")).toHaveAttribute("disabled", "");
  await expect(page.locator("#stats .big")).toHaveText("2");
  await expect(page.locator("#stats button")).toContainText("1 条位置不足");
  expect(requests.filter((url) => url.includes("/pois/"))).toHaveLength(0);
  await expect
    .poll(async () => {
      await page.locator(".maplibregl-canvas").click();
      return page.locator("#selection").innerText();
    })
    .toContain("2 条已收录警情");
  await expect(page.locator("#selection")).toContainText("场所近似位置");
  await expect(page.locator("#selection")).toContainText(
    "匹配对象跨度约 110 米",
  );
  await expect(page.locator("#selection")).toContainText("案发地优先");
  await expect(page.locator("#selection")).toContainText(
    "其他案发地点候选：Anderstraße",
  );
  await expect(page.locator("#selection")).toContainText(
    "本公告在网格中只计一条",
  );
  await expect(page.locator("#selection")).toContainText("财产相关事件线索");
  await expect(page.locator("#selection")).toContainText("Das Fahrzeug wurde beschädigt.");
  expect(errors).toEqual([]);
  expect(requests.filter((url) => url.includes("/months/"))).toHaveLength(1);
  await page.locator("#month").selectOption("08");
  await expect(page.locator("#stats .big")).toHaveText("—");
  await page.locator("#month").selectOption("09");
  await expect(page.locator("#stats .big")).toHaveText("2");
  expect(requests.filter((url) => url.includes("/months/"))).toHaveLength(1);
});
