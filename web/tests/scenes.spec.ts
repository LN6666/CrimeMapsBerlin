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
  styledPois,
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

test("moving transit incidents retain their reviewed full route without becoming count points", () => {
  const moving = report("moving", {
    scene_locations: [{
      label: "U8 列车内",
      role: "incident",
      location_precision: "route",
      geocode_method: "osm_transit_route",
      geometry: {
        type: "MultiLineString",
        coordinates: [
          [[13.40, 52.49], [13.41, 52.50]],
          [[13.41, 52.50], [13.42, 52.51]],
        ],
      },
      primary_for_count: false,
      transit_route: {
        mode: "subway",
        line: "U8",
        extent: "full_line",
        evidence_quote: "in einem Zug der Linie U8",
      },
      event_time: {
        display: "21. September 2026 gegen 23.30 Uhr",
        date: "2026-09-21",
        precision: "approximate",
        evidence_quote: "gegen 23.30 Uhr",
      },
      details: "威胁发生在行驶中的 U8 列车内。",
    }],
  });
  const features = sceneFeatures([moving]).features;
  expect(features).toHaveLength(1);
  expect(features[0].properties).toMatchObject({
    geometry_kind: "transit_route",
    transit_line: "U8",
  });
  expect(countableEventIds([moving])).toEqual(new Set());
});

test("reviewed POI context deepens display without becoming a venue incident", () => {
  const poiData = {
    pois: {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        geometry: { type: "Point", coordinates: [13.4, 52.5] },
        properties: { id: "bar-1", kind: "bar", name: "Bar" },
      }],
    },
    catalog: { poi_types: { bar: { color: "#123456", label: "酒吧" } } },
  } as unknown as Bundle;
  const pois = styledPois(
    poiData,
    [{
      event_id: "A",
      poi_id: "bar-1",
      status: "context_along_geometry",
      source_url: "https://example.test/source",
      mention_basis: "source_reviewed_context_only",
    }],
    new Set(["A"]),
    new Set(["bar"]),
    true,
  );
  expect(pois.features[0].properties).toMatchObject({
    count: 0,
    candidate_count: 0,
    context_count: 1,
    association_count: 1,
  });
});

test("native platform references keep all original nodes and reject any count representative", () => {
  const points: [number, number][] = [[10, 53.55], [10.001, 53.55], [10.002, 53.55]];
  const row = report("platforms", { scene_locations: [{
    label: "Three reviewed platforms", role: "incident", location_precision: "place",
    geocode_method: "osm_native_platform_points", primary_for_count: true,
    geometry_usage: "source_native_platform_points_reference_only",
    coordinates: [10.001, 53.55], geometry: { type: "MultiPoint", coordinates: points },
  }] });
  const features = sceneFeatures([row]).features;
  expect(features).toHaveLength(1);
  expect(features[0].geometry).toEqual({ type: "MultiPoint", coordinates: points });
  expect(features[0].properties.primary_for_count).toBe(false);
  expect([...countableEventIds([row])]).toEqual([]);
});

test("junction reference points cannot bypass the count gate through a malformed primary flag", () => {
  const row = report("junction", { scene_locations: [{
    label: "Native junction reference", role: "incident", location_precision: "point",
    geocode_method: "osm_junction_reference", primary_for_count: true,
    geometry_usage: "source_junction_reference_only",
    geometry: { type: "Point", coordinates: [10, 53.55] },
  }] });
  expect([...countableEventIds([row])]).toEqual([]);
  expect(sceneFeatures([row]).features[0].properties.primary_for_count).toBe(false);
});

test("multiple POI memberships show a selected subtype and one announcement context", () => {
  const feature = { type: "Feature" as const, geometry: { type: "Point" as const, coordinates: [10, 53.55] as [number, number] },
    properties: { id: "osm/node/1", kind: "park", context_kinds: ["park", "school"] } };
  const bundle = { pois: { type: "FeatureCollection", features: [feature] },
    catalog: { poi_types: { park: { color: "green" }, school: { color: "blue" } } } } as unknown as Bundle;
  const links = [1, 2].map(() => ({ event_id: "A", poi_id: "osm/node/1", status: "context_named_object",
    source_url: "https://example.invalid/source", mention_basis: "source_reviewed_context_only" }));
  const result = styledPois(bundle, links, new Set(["A"]), new Set(["school"]), true);
  expect(result.features).toHaveLength(1);
  expect(result.features[0].properties.display_kind).toBe("school");
  expect(result.features[0].properties.context_count).toBe(1);
  expect(result.features[0].properties.count).toBe(0);
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
