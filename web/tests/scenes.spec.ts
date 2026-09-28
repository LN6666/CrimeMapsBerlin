import { expect, test } from "@playwright/test";
import type { Bundle, FC, PoliceEvent } from "../src/safety/model";
import {
  countableEventIds,
  filteredHex,
  monthEvents,
  sceneEventIds,
  sceneFeatures,
  sceneRoleGroup,
  sceneRoleLabel,
} from "../src/safety/model";

function report(id: string, changes: Partial<PoliceEvent> = {}): PoliceEvent {
  return {
    id,
    title: id,
    category: "Gewalt",
    month: "2026-09",
    event_date: null,
    coordinates: null,
    location_precision: "unknown",
    location_label: "",
    source_url: `https://www.berlin.de/polizei/${id}`,
    feed_url: "",
    poi_mentions: [],
    mention_basis: "",
    outcome: "unknown",
    ...changes,
  };
}

const sharedReport = report("A", {
  scene_locations: [
    {
      label: "案发处",
      role: "incident",
      location_precision: "street",
      geocode_method: "named_street_intersection",
      coordinates: [13.4, 52.5],
      primary_for_count: true,
    },
    {
      label: "伤者发现处",
      role: "discovery",
      location_precision: "point",
      geocode_method: "named_place",
      coordinates: [13.402, 52.502],
      primary_for_count: false,
    },
    {
      label: "搜查路径",
      role: "search",
      location_precision: "unknown",
      geocode_method: "route_review",
      geometry: {
        type: "LineString",
        coordinates: [[13.397, 52.498], [13.405, 52.498]],
      },
      candidate_road_geometry: {
        type: "MultiLineString",
        coordinates: [
          [[13.395, 52.497], [13.398, 52.497]],
          [[13.403, 52.497], [13.408, 52.497]],
        ],
      },
      primary_for_count: false,
    },
    {
      label: "背景区域",
      role: "background",
      location_precision: "district",
      geocode_method: "named_area_geometry_review",
      geometry: {
        type: "Polygon",
        coordinates: [[
          [13.395, 52.495], [13.405, 52.495], [13.405, 52.505],
          [13.395, 52.505], [13.395, 52.495],
        ]],
      },
      primary_for_count: false,
    },
  ],
});
const rows = [
  sharedReport,
  report("B", {
    category: "Raub",
    scene_locations: [{
      label: "抓捕地点",
      role: "arrest",
      location_precision: "point",
      geocode_method: "address",
      coordinates: [13.41, 52.51],
      primary_for_count: false,
    }],
  }),
  report("C", {
    month: "2026-08",
    scene_locations: [{
      label: "事故地点",
      role: "accident",
      location_precision: "point",
      geocode_method: "address",
      coordinates: [13.42, 52.52],
      primary_for_count: true,
    }],
  }),
];
const data = { events: rows } as Bundle;
const hex: FC = {
  type: "FeatureCollection",
  features: [{
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[
      [13.39, 52.49], [13.41, 52.49], [13.41, 52.51],
      [13.39, 52.51], [13.39, 52.49],
    ]] },
    properties: { id: "hex", event_ids: ["A", "A", "B", "C"], count: 4 },
  }],
};

test("scene source retains every visible role and geometry under the month and category filter", () => {
  const september = monthEvents(data, "2026-09", "all");
  expect(september.map((event) => event.id)).toEqual(["A", "B"]);
  const features = sceneFeatures(september).features;
  expect(features).toHaveLength(6);
  expect(features.map((feature) => feature.geometry.type)).toEqual([
    "Point", "Point", "LineString", "MultiLineString", "Polygon", "Point",
  ]);
  expect(features.map((feature) => feature.properties.role_group)).toEqual([
    "incident", "discovery", "operation", "operation", "context", "operation",
  ]);
  expect(features.map((feature) => feature.properties.scene_id)).toEqual([
    "A/0", "A/1", "A/2", "A/2", "A/3", "B/0",
  ]);
  expect(sceneEventIds(features)).toEqual(["A", "B"]);
  expect(sceneFeatures(monthEvents(data, "2026-09", "Raub")).features)
    .toHaveLength(1);
  expect(sceneFeatures(monthEvents(data, "2026-08", "all")).features)
    .toHaveLength(1);
  expect(sceneRoleGroup("accident")).toBe("incident");
  expect(sceneRoleGroup("discovery")).toBe("discovery");
  for (const role of ["operation", "arrest", "search"] as const)
    expect(sceneRoleGroup(role)).toBe("operation");
  for (const role of ["background", "unknown"] as const)
    expect(sceneRoleGroup(role)).toBe("context");
  expect(sceneRoleLabel("arrest")).toBe("抓捕地点");
});

test("only a countable primary scene enters the hex once", () => {
  const ids = countableEventIds(monthEvents(data, "2026-09", "all"));
  expect([...ids]).toEqual(["A"]);
  const filtered = filteredHex(hex, ids);
  expect(filtered.features[0].properties).toMatchObject({
    event_ids: ["A"], count: 1,
  });
  const duplicateCell = {
    ...hex.features[0],
    properties: { ...hex.features[0].properties, id: "second", event_ids: ["A"] },
  };
  expect(filteredHex({ ...hex, features: [...hex.features, duplicateCell] }, ids).features)
    .toHaveLength(1);
  expect(countableEventIds([report("legacy")])).toEqual(new Set(["legacy"]));
  expect(countableEventIds([report("empty", { scene_locations: [] })])).toEqual(new Set());
  expect(countableEventIds([report("uncertain", {
    scene_locations: [{
      label: "不确定",
      role: "unknown",
      location_precision: "unknown",
      geocode_method: "review",
      coordinates: [13.4, 52.5],
      primary_for_count: true,
    }],
  })])).toEqual(new Set());
});

test("invalid scene coordinates and road ranges are not rendered or counted", () => {
  const invalid = report("invalid", {
    scene_locations: [{
      label: "无效地理对象",
      role: "unknown",
      location_precision: "street",
      geocode_method: "review",
      coordinates: [Infinity, 52.5],
      geometry: { type: "LineString", coordinates: [[13.4, 52.5]] },
      candidate_road_geometry: {
        type: "LineString", coordinates: [[13.4, 52.5]],
      },
      primary_for_count: true,
    }],
  });
  expect(sceneFeatures([invalid]).features).toEqual([]);
  expect(countableEventIds([invalid])).toEqual(new Set());
});

test("clicking overlapping scene shapes opens one report card with every scene", async ({ page }) => {
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4+fYlAAWCAsAGiqfBAAAAAElFTkSuQmCC",
    "base64",
  );
  for (const pattern of ["https://tile.openstreetmap.org/**", "https://gdi.berlin.de/**"])
    await page.route(pattern, (route) => route.fulfill({
      contentType: "image/png",
      body: png,
      headers: { "access-control-allow-origin": "*" },
    }));
  const browserRows = [
    report("shared", {
      title: "多地点公告",
      scene_locations: [
        {
          label: "主案发处", role: "incident", location_precision: "street",
          geocode_method: "named_street_intersection",
          coordinates: [13.411, 52.508], primary_for_count: true,
        },
        {
          label: "发现处", role: "discovery", location_precision: "point",
          geocode_method: "named_place",
          coordinates: [13.412, 52.508], primary_for_count: false,
        },
        {
          label: "行动路段", role: "operation", location_precision: "unknown",
          geocode_method: "route_review",
          geometry: { type: "LineString", coordinates: [[13.409, 52.508], [13.413, 52.508]] },
          primary_for_count: false,
        },
        {
          label: "背景区域", role: "background", location_precision: "district",
          geocode_method: "named_area_geometry_review",
          geometry: { type: "Polygon", coordinates: [[
            [13.409, 52.506], [13.413, 52.506], [13.413, 52.510],
            [13.409, 52.510], [13.409, 52.506],
          ]] },
          primary_for_count: false,
        },
      ],
    }),
    report("other", {
      title: "其他类别公告",
      category: "Raub",
      scene_locations: [{
        label: "抓捕处", role: "arrest", location_precision: "point",
        geocode_method: "address", coordinates: [13.42, 52.52],
        primary_for_count: false,
      }],
    }),
  ];
  const browserHex: FC = {
    ...hex,
    features: hex.features.map((feature) => ({
      ...feature,
      properties: { ...feature.properties, event_ids: ["shared", "shared", "other"] },
    })),
  };
  await page.route("http://127.0.0.1:4173/safety/**", (route) => {
    const url = route.request().url();
    if (url.endsWith("manifest.json")) return route.fulfill({ json: {
      schema_version: 2, city: "Berlin",
      generation: "0123456789abcdef-20260927T120000",
      retrieved_at: "2026-09-27T12:00:00Z",
      coverage: { discovered: 2, fetched: 2, pending: 0, failed: 0 },
      months: { "2026-09": { count: 2 } },
      categories: ["Gewalt", "Raub"],
      tile_index: { pois: [], roads: [] }, tile_size: [0.04, 0.025],
      catalog: { poi_types: {}, sources: [], coverage: [], exhaustive: false },
      zones: { places: [], features: [], geometry_status: "pending" },
      metadata: { zoom_threshold: 13 },
    } });
    if (url.includes("/months/")) return route.fulfill({ json: {
      event_ids: browserRows.map((event) => event.id),
      events: browserRows,
      hex: { overview: browserHex, detail: browserHex }, links: [],
    } });
    return route.fulfill({ json: { type: "FeatureCollection", features: [] } });
  });
  await page.goto("/");
  await expect(page.locator("#stats .big")).toHaveText("2");
  const canvas = page.locator(".maplibregl-canvas");
  await expect.poll(async () => {
    const box = await canvas.boundingBox();
    await canvas.click({ position: { x: box!.width / 2, y: box!.height / 2 } });
    return page.locator("#selection").innerText();
  }).toContain("多地点公告");
  await expect(page.locator("#selection .report")).toHaveCount(1);
  await expect(page.locator("#selection .scene-list li")).toHaveCount(4);
  await expect(page.locator("#selection")).toContainText("主场景");
  await expect(page.locator("#selection")).toContainText("同一公告最多计一次");
  await page.locator("#category").selectOption("Raub");
  await expect(page.locator("#selection")).not.toContainText("多地点公告");
  await expect(page.locator("#stats")).toContainText("已定位 0 条 · 未定位 1 条");
  await page.locator("#month").selectOption("08");
  await expect(page.locator("#stats .big")).toHaveText("—");
});
