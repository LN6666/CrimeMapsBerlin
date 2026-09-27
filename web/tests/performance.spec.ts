import { test, expect } from "@playwright/test";
import { LRU, tileKeys } from "../src/safety/data";

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

test("overview loads no POI geometry, month switching clears missing months", async ({
  page,
}) => {
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
        properties: { id: "test", edge_m: 1100, count: 1, event_ids: ["1"] },
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
          coverage: { discovered: 1, fetched: 1, pending: 0, failed: 0 },
          months: { "2026-09": { count: 1 } },
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
          event_ids: ["1"],
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
          ],
          hex: { overview: hex, detail: hex },
          links: [],
        },
      });
    return route.fulfill({ json: empty });
  });
  await page.goto("/");
  await expect(page.locator("#stats .big")).toHaveText("1");
  expect(requests.filter((url) => url.includes("/pois/"))).toHaveLength(0);
  await expect
    .poll(async () => {
      await page.locator(".maplibregl-canvas").click();
      return page.locator("#selection").innerText();
    })
    .toContain("1 条已收录警情");
  expect(errors).toEqual([]);
  expect(requests.filter((url) => url.includes("/months/"))).toHaveLength(1);
  await page.locator("#month").selectOption("08");
  await expect(page.locator("#stats .big")).toHaveText("—");
  await page.locator("#month").selectOption("09");
  await expect(page.locator("#stats .big")).toHaveText("1");
  expect(requests.filter((url) => url.includes("/months/"))).toHaveLength(1);
});
