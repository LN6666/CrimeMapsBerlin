import { test, expect } from "./fixture";
import type {
  ErrorEvent,
  LayerSpecification,
  Map as MapLibreMap,
  SourceSpecification,
} from "maplibre-gl";
import { Basemaps, rasterSource } from "../src/safety/basemaps";

const empty = { type: "FeatureCollection", features: [] };
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4+fYlAAWCAsAGiqfBAAAAAElFTkSuQmCC",
  "base64",
);

class TestMap {
  sources = new Map<string, SourceSpecification>(
    ["roads", "hex", "pois", "kbo", "reported-sections"].map((id) => [
      id,
      { type: "geojson", data: empty as GeoJSON.FeatureCollection },
    ]),
  );
  layers: LayerSpecification[] = [
    { id: "background", type: "background" },
    { id: "roads-line", type: "line", source: "roads" },
    { id: "hex-fill", type: "fill", source: "hex" },
    { id: "poi-fill", type: "fill", source: "pois" },
    { id: "reported-sections-line", type: "line", source: "reported-sections" },
  ];
  layout = new Map<string, unknown>();
  camera = { center: [13.411, 52.508], zoom: 12.1, bearing: 15 };
  error?: (event: ErrorEvent) => void;
  on(_event: string, listener: (event: ErrorEvent) => void) {
    this.error = listener;
  }
  off() {
    this.error = undefined;
  }
  getLayer(id: string) {
    return this.layers.find((layer) => layer.id === id);
  }
  getSource(id: string) {
    return this.sources.get(id);
  }
  addSource(id: string, source: SourceSpecification) {
    this.sources.set(id, source);
  }
  removeSource(id: string) {
    this.sources.delete(id);
  }
  addLayer(layer: LayerSpecification, before: string) {
    this.layers.splice(
      this.layers.findIndex((value) => value.id === before),
      0,
      layer,
    );
  }
  removeLayer(id: string) {
    this.layers = this.layers.filter((layer) => layer.id !== id);
  }
  setLayoutProperty(id: string, _property: string, value: unknown) {
    this.layout.set(id, value);
  }
  fail(sourceId: string) {
    this.error?.({
      type: "error",
      sourceId,
      error: new Error("tile unavailable"),
    } as ErrorEvent);
  }
}

test("basemap switches retain data sources, overlays and camera with one raster", () => {
  const map = new TestMap();
  const originalSources = new Map(map.sources);
  const originalLayers = [...map.layers];
  const camera = JSON.stringify(map.camera);
  const basemaps = new Basemaps(
    map as unknown as MapLibreMap,
    () => {},
    () => {},
  );
  for (const id of ["street", "aerial", "local", "street"] as const) {
    basemaps.select(id);
    expect(
      [...map.sources.values()].filter((source) => source.type === "raster"),
    ).toHaveLength(id === "local" ? 0 : 1);
    for (const [key, source] of originalSources)
      expect(map.sources.get(key)).toBe(source);
    expect(
      map.layers.filter((layer) => !layer.id.startsWith("basemap-")),
    ).toEqual(originalLayers);
    expect(map.layout.get("roads-line")).toBe(
      id === "local" ? "visible" : "none",
    );
    expect(JSON.stringify(map.camera)).toBe(camera);
    if (id !== "local") expect(map.layers[1].id).toBe(`basemap-${id}`);
  }
  basemaps.dispose();
  expect(map.error).toBeUndefined();
});

test("failed raster is removed once and an explicit local switch clears failure", () => {
  const map = new TestMap();
  const failures: string[] = [];
  const basemaps = new Basemaps(
    map as unknown as MapLibreMap,
    () => {},
    (id) => failures.push(id),
  );
  basemaps.select("street");
  map.fail("basemap-aerial");
  expect(basemaps.rendered).toBe("street");
  map.fail("basemap-street");
  map.fail("basemap-street");
  expect(failures).toEqual(["street"]);
  expect(basemaps.rendered).toBe("local");
  expect(map.sources.size).toBe(5);
  expect(map.layout.get("roads-line")).toBe("visible");
  basemaps.select("local");
  basemaps.select("aerial");
  expect(basemaps.rendered).toBe("aerial");
  expect(map.sources.size).toBe(6);
});

test("official aerial tiles use metric WMS bounding boxes and Berlin bounds", () => {
  const source = rasterSource("aerial");
  const url = new URL(source.tiles![0]);
  expect(url.origin).toBe("https://gdi.berlin.de");
  expect(url.searchParams.get("VERSION")).toBe("1.3.0");
  expect(url.searchParams.get("LAYERS")).toBe("truedop_2026");
  expect(url.searchParams.get("CRS")).toBe("EPSG:3857");
  expect(url.searchParams.get("BBOX")).toBe("{bbox-epsg-3857}");
  expect(url.searchParams.get("WIDTH")).toBe("256");
  expect(url.searchParams.get("HEIGHT")).toBe("256");
  expect(url.searchParams.get("FORMAT")).toBe("image/jpeg");
  expect(source.bounds).toEqual([13.04758, 52.31644, 13.76742, 52.6854]);
  expect(source.attribution).toContain("dl-de/zero-2.0");
  expect(rasterSource("street").tiles).toEqual([
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  ]);
});

test.describe("basemap browser", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("https://tile.openstreetmap.org/**", (route) =>
      route.fulfill({
        contentType: "image/png",
        body: png,
        headers: {
          "cache-control": "public, max-age=3600",
          "access-control-allow-origin": "*",
        },
      }),
    );
    await page.route(
      "https://gdi.berlin.de/services/wms/truedop_2026?**",
      (route) =>
        route.fulfill({
          contentType: "image/png",
          body: png,
          headers: { "access-control-allow-origin": "*" },
        }),
    );
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
            categories: ["raub"],
            tile_index: { pois: ["bar/335_2100"], roads: [] },
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
      if (url.includes("/months/")) {
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
                count: 1,
                event_ids: ["1"],
              },
            },
          ],
        };
        return route.fulfill({
          json: {
            event_ids: ["1"],
            events: [
              {
                id: "1",
                title: "Scene retained",
                category: "raub",
                month: "2026-09",
                coordinates: [13.411, 52.508],
                location_precision: "place",
                location_label: "Testpark",
                location_selection: "first_explicit_incident_scene",
                poi_mentions: [],
                reported_location_geometry: {
                  type: "LineString",
                  coordinates: [
                    [13.411, 52.508],
                    [13.413, 52.509],
                  ],
                },
                source_url: "https://www.berlin.de/",
              },
            ],
            hex: { overview: hex, detail: hex },
            links: [],
          },
        });
      }
      if (url.includes("/pois/"))
        return route.fulfill({
          json: {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: { type: "Point", coordinates: [13.411, 52.508] },
                properties: {
                  id: "venue",
                  kind: "bar",
                  name: "Test venue",
                  geometry_mode: "footprint_missing",
                  source_url: "https://www.openstreetmap.org/node/1",
                },
              },
            ],
          },
        });
      return route.fulfill({ json: empty });
    });
  });

  test("street, aerial and local choices preserve the month and selected scene", async ({
    page,
  }) => {
    const requests: string[] = [];
    const errors: string[] = [];
    page.on("request", (request) => requests.push(request.url()));
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    await page.goto("/?lang=zh");
    await expect(page.locator("#stats .big")).toHaveText("1");
    await expect(page.locator("#basemap")).toHaveValue("vector");
    await page.locator("#basemap").selectOption("street");
    await expect
      .poll(
        () =>
          requests.filter((url) =>
            url.startsWith("https://tile.openstreetmap.org/"),
          ).length,
      )
      .toBeGreaterThan(0);
    expect(
      requests.some((url) => url.startsWith("https://gdi.berlin.de/")),
    ).toBe(false);
    await expect
      .poll(async () => {
        await page.locator(".maplibregl-canvas").click();
        return page.locator("#selection").innerText();
      })
      .toContain("Scene retained");
    const selection = await page.locator("#selection").innerText();
    const scale = await page.locator(".maplibregl-ctrl-scale").innerText();
    for (const id of ["aerial", "local", "street"]) {
      await page.locator("#basemap").selectOption(id);
      await expect(page.locator("#selection")).toHaveText(selection, {
        useInnerText: true,
      });
      await expect(page.locator("#month")).toHaveValue("09");
      await expect(page.locator("#year")).toHaveValue("2026");
      await expect(page.locator(".maplibregl-ctrl-scale")).toHaveText(scale);
      if (id === "aerial") {
        await expect
          .poll(
            () =>
              requests.filter((url) => url.startsWith("https://gdi.berlin.de/"))
                .length,
          )
          .toBeGreaterThan(0);
        await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText(
          "DOP 2026",
        );
        await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText(
          "dl-de/zero-2.0",
        );
        const request = new URL(
          requests.find((url) => url.startsWith("https://gdi.berlin.de/"))!,
        );
        const bbox = request.searchParams.get("BBOX")!.split(",").map(Number);
        expect(bbox).toHaveLength(4);
        expect(bbox.every(Number.isFinite)).toBe(true);
        expect(bbox[0]).toBeGreaterThan(1_000_000);
        expect(bbox[1]).toBeGreaterThan(5_000_000);
      } else {
        await expect(page.locator(".maplibregl-ctrl-attrib")).not.toContainText(
          "DOP 2026",
        );
      }
    }
    await expect(page.locator(".maplibregl-ctrl-attrib")).toBeVisible();
    await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText(
      "OpenStreetMap",
    );
    await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText(
      "Polizei Berlin",
    );
    expect(requests.filter((url) => url.includes("/months/"))).toHaveLength(1);
    expect(requests.filter((url) => url.includes("/pois/"))).toHaveLength(0);
    expect(errors).toEqual([]);
  });

  test("an unavailable raster stops loading and offers the local fallback", async ({
    page,
  }) => {
    let failedTiles = 0;
    await page.route(
      "https://gdi.berlin.de/services/wms/truedop_2026?**",
      (route) => {
        failedTiles++;
        return route.fulfill({
          status: 503,
          body: "Unavailable",
          headers: { "access-control-allow-origin": "*" },
        });
      },
    );
    await page.goto("/?lang=zh");
    await expect(page.locator("#stats .big")).toHaveText("1");
    await page.locator("#basemap").selectOption("aerial");
    await expect(page.locator("#basemap-error")).toContainText("加载失败");
    const failedCount = failedTiles;
    await page.locator("#basemap-fallback").click();
    await expect(page.locator("#basemap")).toHaveValue("local");
    await expect(page.locator("#basemap-error")).toBeHidden();
    const scale = await page.locator(".maplibregl-ctrl-scale").innerText();
    await page.locator("#overview").click();
    await expect(page.locator(".maplibregl-ctrl-scale")).not.toHaveText(scale);
    expect(failedTiles).toBe(failedCount);
    await expect(page.locator("#stats .big")).toHaveText("1");
  });

  test("basemap switching preserves a selected POI without extra viewport downloads", async ({
    page,
  }) => {
    const requests: string[] = [];
    page.on("request", (request) => requests.push(request.url()));
    await page.goto("/?lang=zh");
    await expect(page.locator("#stats .big")).toHaveText("1");
    await page.locator(".maplibregl-ctrl-zoom-in").click();
    await expect
      .poll(() => requests.filter((url) => url.includes("/pois/")).length)
      .toBe(1);
    await expect
      .poll(async () => {
        await page.locator(".maplibregl-canvas").click();
        return page.locator("#selection").innerText();
      })
      .toContain("Test venue");
    const selection = await page.locator("#selection").innerText();
    const scale = await page.locator(".maplibregl-ctrl-scale").innerText();
    for (const id of ["aerial", "local", "street"]) {
      await page.locator("#basemap").selectOption(id);
      await expect(page.locator("#selection")).toHaveText(selection, {
        useInnerText: true,
      });
      await expect(page.locator(".maplibregl-ctrl-scale")).toHaveText(scale);
    }
    await page.locator(".maplibregl-canvas").click();
    await expect(page.locator("#selection")).toHaveText(selection, {
      useInnerText: true,
    });
    expect(requests.filter((url) => url.includes("/pois/"))).toHaveLength(1);
    expect(requests.filter((url) => url.includes("/months/"))).toHaveLength(1);
  });

  test("basemap controls and credits fit a narrow screen", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 760 });
    await page.goto("/?lang=zh");
    await expect(page.locator("#stats .big")).toHaveText("1");
    await page.locator(".mobile-basemap-settings > summary").click();
    await page.locator("#basemap").selectOption("aerial");
    const attributionSummary = page.locator(".maplibregl-ctrl-attrib > summary");
    if (await attributionSummary.isVisible()) await attributionSummary.click();
    await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText(
      "DOP 2026",
    );
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(320);
    const bounds = await page.locator(".map-wrap").boundingBox();
    for (const selector of [
      ".basemap-picker",
      ".maplibregl-ctrl-attrib",
      ".maplibregl-ctrl-scale",
    ]) {
      const control = await page.locator(selector).boundingBox();
      expect(control!.x).toBeGreaterThanOrEqual(bounds!.x);
      expect(control!.x + control!.width).toBeLessThanOrEqual(
        bounds!.x + bounds!.width,
      );
    }
  });
});
