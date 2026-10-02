import { test, expect } from "./fixture";
import type { Page } from "@playwright/test";
import type { LineString, MultiLineString } from "geojson";
import {
  candidateRoadGeometry,
  candidateRoads,
  filteredHex,
  roadBounds,
  styledPois,
} from "../src/safety/model";
import type { Bundle, FC, PoliceEvent } from "../src/safety/model";

const empty: FC = { type: "FeatureCollection", features: [] };
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4+fYlAAWCAsAGiqfBAAAAAElFTkSuQmCC",
  "base64",
);
const wide: LineString = {
  type: "LineString",
  coordinates: [
    [13.3, 52.508],
    [13.52, 52.508],
  ],
};
const disconnected: MultiLineString = {
  type: "MultiLineString",
  coordinates: [
    [
      [13.34, 52.508],
      [13.37, 52.508],
    ],
    [
      [13.45, 52.508],
      [13.482, 52.508],
    ],
  ],
};
function report(id: string, changes: Partial<PoliceEvent> = {}): PoliceEvent {
  return {
    id,
    title: id,
    category: "raub",
    month: "2026-09",
    event_date: null,
    coordinates: null,
    location_precision: "unknown",
    location_label: "Teststraße",
    location_scope: "Mitte",
    geocode_method: "long_or_ambiguous_street_review",
    candidate_road_geometry: wide,
    source_url: `https://www.berlin.de/polizei/${id}`,
    feed_url: "",
    poi_mentions: [],
    mention_basis: "",
    outcome: "unknown",
    ...changes,
  };
}
const rows = [
  report("Mapped report", {
    coordinates: [13.411, 52.508],
    location_precision: "point",
    geocode_method: "address",
    candidate_road_geometry: undefined,
  }),
  report("Wide road A"),
  report("Wide road B"),
  report("Disconnected road", {
    category: "sachbeschaedigung",
    geocode_method: "disconnected_street_review",
    candidate_road_geometry: disconnected,
  }),
  report("District only", {
    location_precision: "district",
    geocode_method: "district_only",
  }),
];
const hex: FC = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [13.37, 52.49],
            [13.45, 52.49],
            [13.45, 52.53],
            [13.37, 52.53],
            [13.37, 52.49],
          ],
        ],
      },
      properties: {
        id: "mapped-hex",
        edge_m: 1100,
        count: 1,
        event_ids: [rows[0].id],
      },
    },
  ],
};

test("review ranges preserve disconnected geometry and stay separate from statistical points", () => {
  expect(candidateRoads(rows).features.map((f) => f.properties.id)).toEqual([
    "Wide road A",
    "Wide road B",
    "Disconnected road",
  ]);
  expect(candidateRoadGeometry(rows[3])).toEqual(disconnected);
  expect(roadBounds(disconnected)).toEqual([13.34, 52.508, 13.482, 52.508]);
  expect(roadBounds(wide)).toEqual([13.3, 52.508, 13.52, 52.508]);
  expect(
    candidateRoadGeometry(report("mapped", { coordinates: [13.4, 52.5] })),
  ).toBeNull();
  expect(
    candidateRoadGeometry(
      report("missing", { candidate_road_geometry: undefined }),
    ),
  ).toBeNull();
  expect(
    candidateRoadGeometry(
      report("invalid", {
        candidate_road_geometry: {
          type: "LineString",
          coordinates: [[13.4, 52.5]],
        },
      }),
    ),
  ).toBeNull();
  expect(
    candidateRoadGeometry(
      report("nonfinite", {
        candidate_road_geometry: {
          type: "LineString",
          coordinates: [
            [NaN, 52.5],
            [13.4, 52.5],
          ],
        },
      }),
    ),
  ).toBeNull();
  const ids = new Set(rows.map((e) => e.id));
  expect(filteredHex(hex, ids).features[0].properties.count).toBe(1);
  const data: Bundle = {
    schema_version: 1,
    city: "Berlin",
    retrieved_at: "2026-09-27T12:00:00Z",
    expires_at: "",
    coverage: "test",
    events: rows,
    months: {},
    metadata: {},
    zones: { places: [], features: [], geometry_status: "pending" },
    pois: {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [13.4, 52.5] },
          properties: { id: "venue", kind: "bar" },
        },
      ],
    },
    catalog: {
      poi_types: { bar: { color: "#d97706", label: "酒吧" } },
      sources: [],
      coverage: [],
      exhaustive: false,
    },
  };
  expect(
    styledPois(data, [], ids, new Set(["bar"]), true).features[0].properties
      .association_count,
  ).toBe(0);
});

async function mockData(page: Page) {
  for (const pattern of [
    "https://tile.openstreetmap.org/**",
    "https://gdi.berlin.de/**",
  ])
    await page.route(pattern, (route) =>
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
          coverage: { discovered: 5, fetched: 5, pending: 0, failed: 0 },
          months: { "2026-09": { count: 5 } },
          categories: ["raub", "sachbeschaedigung"],
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
          event_ids: rows.map((e) => e.id),
          events: rows,
          hex: { overview: hex, detail: hex },
          links: [],
        },
      });
    return route.fulfill({ json: empty });
  });
}

/** Inspect the rendered canvas rather than adding a production-only map test API. */
async function roadPixels(page: Page) {
  const screenshot = await page.locator(".maplibregl-canvas").screenshot();
  return page.evaluate(async (base64) => {
    const image = new Image();
    image.src = `data:image/png;base64,${base64}`;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.width;
    canvas.height = image.height;
    const context = canvas.getContext("2d")!;
    context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, image.width, image.height).data;
    let count = 0,
      minX = Infinity,
      maxX = -Infinity,
      left = 0,
      middle = 0,
      right = 0;
    for (let i = 0; i < pixels.length; i += 4)
      if (
        pixels[i] > 210 &&
        pixels[i + 1] > 75 &&
        pixels[i + 1] < 160 &&
        pixels[i + 2] < 75
      ) {
        count++;
        const x = (i / 4) % image.width;
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        if (x < image.width * 0.35) left++;
        if (x > image.width * 0.4 && x < image.width * 0.6) middle++;
        if (x > image.width * 0.65) right++;
      }
    return { count, minX, maxX, left, middle, right, width: image.width };
  }, screenshot.toString("base64"));
}
async function orangePixels(page: Page) {
  return (await roadPixels(page)).count;
}

/** Center clicks exercise real WebGL hit geometry, including a wide hit area. */
async function clickCenter(page: Page, offsetY = 0) {
  const box = await page.locator(".maplibregl-canvas").boundingBox();
  await page.locator(".maplibregl-canvas").click({
    position: { x: box!.width / 2, y: box!.height / 2 + offsetY },
  });
}

test.describe("candidate roads browser", () => {
  test.beforeEach(async ({ page }) => {
    await mockData(page);
    await page.goto("/?lang=zh");
    await expect(page.locator("#stats .big")).toHaveText("5");
  });

  test("clicking overlapping roads shows every source and preserves basemap state", async ({
    page,
  }) => {
    const requests: string[] = [];
    const errors: string[] = [];
    page.on("request", (request) => requests.push(request.url()));
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(page.locator("#candidate-roads-toggle")).toBeChecked();
    await expect(page.locator("#stats")).toContainText(
      "1条已定位；4条未定位，其中3条可查看道路参照范围",
    );
    await expect.poll(() => orangePixels(page)).toBeGreaterThan(100);
    await expect
      .poll(async () => {
        // Five pixels off the visual line still hits its continuous 14 px area.
        await clickCenter(page, 5);
        return page.locator("#selection").innerText();
      })
      .toContain("2条具体道路位置未知的公告");
    await expect(page.locator("#selection")).toContainText("Wide road A");
    await expect(page.locator("#selection")).toContainText("Wide road B");
    await expect(page.locator("#selection")).toContainText("具体事件位置未知");
    await expect(page.locator("#selection")).toContainText(
      "不计入六边形，也不用于关联具体场所",
    );
    const sources = page.locator("#selection a");
    await expect(sources).toHaveCount(2);
    await expect(sources.first()).toHaveAttribute(
      "href",
      new URL(rows[1].source_url).href,
    );
    const selection = await page.locator("#selection").innerText();
    const scale = await page.locator(".maplibregl-ctrl-scale").innerText();
    for (const basemap of ["aerial", "local", "street"]) {
      await page.locator("#basemap").selectOption(basemap);
      await expect(page.locator("#selection")).toHaveText(selection, {
        useInnerText: true,
      });
      await expect(page.locator("#candidate-roads-toggle")).toBeChecked();
      await expect(page.locator("#month")).toHaveValue("09");
      await expect(page.locator(".maplibregl-ctrl-scale")).toHaveText(scale);
      await clickCenter(page);
      await expect(page.locator("#selection h2")).toHaveText(
        "2条具体道路位置未知的公告",
      );
    }
    await page.locator("#candidate-roads-toggle").uncheck();
    await expect(page.locator("#selection")).toHaveText(selection, {
      useInnerText: true,
    });
    await expect.poll(() => orangePixels(page)).toBe(0);
    await expect
      .poll(async () => {
        await clickCenter(page);
        return page.locator("#selection").innerText();
      })
      .toContain("1条公告");
    await expect(page.locator("#selection")).not.toContainText("Wide road A");
    await expect(page.locator("#stats .big")).toHaveText("5");
    await page.locator("#basemap").selectOption("local");
    await expect(page.locator("#candidate-roads-toggle")).not.toBeChecked();
    await clickCenter(page);
    await expect(page.locator("#selection h2")).toHaveText("1条公告");
    await page.locator("#candidate-roads-toggle").check();
    await expect
      .poll(async () => {
        await clickCenter(page);
        return page.locator("#selection").innerText();
      })
      .toContain("2条具体道路位置未知的公告");
    expect(requests.filter((url) => url.includes("/months/"))).toHaveLength(0);
    expect(requests.filter((url) => url.includes("/pois/"))).toHaveLength(0);
    expect(errors).toEqual([]);
    await expect(page.locator(".maplibregl-marker")).toHaveCount(0);
  });

  test("category and month filters replace the batched road ranges", async ({
    page,
  }) => {
    await page.locator("#category").selectOption("raub");
    await expect(page.locator("#stats .big")).toHaveText("4");
    await expect(page.locator("#stats")).toContainText(
      "其中2条可查看道路参照范围",
    );
    await expect
      .poll(async () => {
        await clickCenter(page);
        return page.locator("#selection").innerText();
      })
      .toContain("2条具体道路位置未知的公告");
    const widePixels = await orangePixels(page);
    await page.locator("#category").selectOption("sachbeschaedigung");
    await expect(page.locator("#stats .big")).toHaveText("1");
    await expect(page.locator("#stats")).toContainText(
      "0条已定位；1条未定位，其中1条可查看道路参照范围",
    );
    await expect.poll(() => orangePixels(page)).toBeLessThan(widePixels);
    await expect.poll(() => orangePixels(page)).toBeGreaterThan(100);
    await clickCenter(page);
    await expect(page.locator("#selection")).not.toContainText("Wide road");
    await expect(page.locator("#selection")).not.toContainText(
      "具体道路位置未知的公告",
    );
    await page.locator("#month").selectOption("08");
    await expect(page.locator("#stats .big")).toHaveText("—");
    await expect.poll(() => orangePixels(page)).toBe(0);
    await clickCenter(page);
    await expect(page.locator("#selection")).not.toContainText(
      "具体道路位置未知的公告",
    );
    await page.locator("#month").selectOption("09");
    await expect(page.locator("#stats .big")).toHaveText("1");
    await page.locator("#category").selectOption("all");
    await expect(page.locator("#stats .big")).toHaveText("5");
    await expect
      .poll(async () => {
        await clickCenter(page);
        return page.locator("#selection").innerText();
      })
      .toContain("2条具体道路位置未知的公告");
  });

  test("unmapped drawer focuses the entire disconnected range and retains unknown scene wording", async ({
    page,
  }) => {
    await page.locator("#candidate-roads-toggle").uncheck();
    await page.locator("#stats button").click();
    await expect(page.locator("#drawer")).toBeVisible();
    await expect(page.locator("#drawer .report")).toHaveCount(4);
    await expect(page.locator("#drawer .road-focus")).toHaveCount(3);
    const district = page
      .locator("#drawer .report")
      .filter({ hasText: "District only" });
    await expect(district.locator(".road-focus")).toHaveCount(0);
    const card = page
      .locator("#drawer .report")
      .filter({ hasText: "Disconnected road" });
    await expect(card).toContainText("本地道路数据包含不连续的路段");
    await expect(card).toContainText("匹配的地点范围：Mitte");
    await card.locator(".road-focus").click();
    await expect(page.locator("#drawer")).not.toBeVisible();
    await expect(page.locator("#candidate-roads-toggle")).toBeChecked();
    await expect(page.locator("#selection")).toContainText("Disconnected road");
    await expect(page.locator("#selection h2")).toHaveText(
      "1条具体道路位置未知的公告",
    );
    await expect(page.locator("#selection")).toContainText("具体事件位置未知");
    await expect(page.locator("#stats")).toContainText(
      "1条已定位；4条未定位",
    );
    // Both separated pieces fit; the gap does not invent a connecting road.
    await page.locator("#category").selectOption("sachbeschaedigung");
    await expect(page.locator("#stats .big")).toHaveText("1");
    await expect
      .poll(async () => {
        const pixels = await roadPixels(page);
        return (
          pixels.left > 50 &&
          pixels.right > 50 &&
          pixels.middle === 0 &&
          pixels.minX >= 40 &&
          pixels.maxX <= pixels.width - 40
        );
      })
      .toBe(true);
    await expect(page.locator(".maplibregl-ctrl-scale")).not.toHaveText("50 m");
    await clickCenter(page);
    await expect(page.locator("#selection")).not.toContainText(
      "具体道路位置未知的公告",
    );
  });
});
