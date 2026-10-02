import {t} from "../src/safety/i18n";
import { expect, test } from "./fixture";
import type { Bundle, FC, PoliceEvent, SceneLocation } from "../src/safety/model";
import {
  countableEventIds,
  filteredHex,
  locationCoverage,
  monthEvents,
  poiGeometryLabel,
  sceneEventIds,
  sceneFeatures,
  sceneRoleGroup,
  sceneRoleLabel,
  SCENE_CLICK_LAYERS,
  styledPois,
  transitGeometryLabel,
} from "../src/safety/model";

test("carrier-line references are clickable without becoming count points", () => {
  expect(SCENE_CLICK_LAYERS).toContain("scene-transit-line-reference");
  expect(SCENE_CLICK_LAYERS).toContain("scene-transit-line-reference-hit");
  expect(new Set(SCENE_CLICK_LAYERS).size).toBe(SCENE_CLICK_LAYERS.length);
});

function report(id: string, changes: Partial<PoliceEvent> = {}): PoliceEvent {
  return {
    id,
    title: id,
    category: "gewalt",
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

test("source-road-only moving transit stays distinct from a checked line or segment", () => {
  const event = report("moving-bus", {
    scene_locations: [{
      label: "source road", role: "incident", location_precision: "route",
      geocode_method: "osm_transit_road_reference", primary_for_count: false,
      geometry_usage: "source_road_reference_only", complete_transit_line: false,
      geometry: {type: "LineString", coordinates: [[13.4, 52.5], [13.41, 52.51]]},
      transit_route: {mode: "bus", line: "unknown", extent: "source_segment", evidence_quote: "source road"},
    }],
  });
  const scene = event.scene_locations![0];
  expect(transitGeometryLabel(scene)).toBe(t("transit.unknownRoad"));
  const feature = sceneFeatures([event]).features[0];
  expect(feature.properties.geometry_kind).toBe("transit_road_reference");
  expect(feature.properties.geometry_usage).toBe("source_road_reference_only");
  expect(feature.properties.primary_for_count).toBe(false);
  expect(countableEventIds([event])).toEqual(new Set());
  const checked = {...scene, geometry_usage: undefined};
  expect(transitGeometryLabel(checked)).toBe(t("transit.sourceSection"));
  checked.transit_route = {...checked.transit_route!, extent: "full_line"};
  expect(transitGeometryLabel(checked)).toBe(t("transit.fullLine"));
  expect(sceneFeatures([report("full-line", {scene_locations: [checked]})]).features[0]
    .properties.geometry_kind).toBe("transit_route");
});

test("native junction candidates do not become inferred scene coordinates or counts", () => {
  const event = report("junction", {scene_locations: [{
    label: "van search near bridge", role: "search", location_precision: "point",
    geocode_method: "osm_junction_reference", primary_for_count: false,
    geometry_usage: "source_junction_reference_only", actual_event_position_known: false,
    geometry: {type: "MultiPoint", coordinates: [[13.4, 52.5], [13.4002, 52.5002]]},
  }]});
  const feature = sceneFeatures([event]).features[0];
  expect(feature.geometry.type).toBe("MultiPoint");
  expect(feature.properties.geometry_kind).toBe("junction_reference");
  expect(feature.properties.actual_event_position_known).toBe(false);
  expect(feature.properties.primary_for_count).toBe(false);
  expect(countableEventIds([event])).toEqual(new Set());
});

for (const method of ["osm_place_footprint_reference", "osm_named_footprint_reference",
  "osm_non_transit_footprint_reference", "osm_station_footprint_reference",
  "osm_water_footprint_reference", "official_district_footprint_reference"]) {
  for (const missing of [null, "geometry_usage", "geocode_method"] as const) {
    test(`footprint references reject injected count points: ${method}, missing ${missing}`, () => {
      const scene: SceneLocation = {
        label: "source venue surroundings", role: "background", location_precision: "place",
        geocode_method: method, geometry_usage: "source_footprint_reference_only",
        geometry: {type: "Polygon", coordinates: [[[13.4, 52.5], [13.401, 52.5],
          [13.401, 52.501], [13.4, 52.5]]]},
        coordinates: [13.4005, 52.5005], primary_for_count: true,
      };
      if (missing === "geometry_usage") delete scene.geometry_usage;
      if (missing === "geocode_method") scene.geocode_method = "";
      const event = report("footprint-reference", {scene_locations: [scene]});
      const features = sceneFeatures([event]).features;
      expect(features).toHaveLength(1);
      expect(features[0].geometry).toEqual(scene.geometry);
      expect(features[0].properties.primary_for_count).toBe(false);
      expect(countableEventIds([event])).toEqual(new Set());
    });
  }
}

test("non-transit road references keep actual driving and work extent unknown", () => {
  const event = report("motorway", {scene_locations: [{
    label: "A115 source corridor", role: "accident", location_precision: "route",
    geocode_method: "osm_non_transit_road_reference_segment", primary_for_count: false,
    geometry_usage: "source_road_reference_only", source_road_extent: "native_endpoint_bounded",
    actual_non_transit_extent_known: false,
    geometry: {type: "LineString", coordinates: [[13.2, 52.44], [13.23, 52.46]]},
  }]});
  const scene = event.scene_locations![0];
  expect(transitGeometryLabel(scene)).toBe(t("transit.roadExtent"));
  const feature = sceneFeatures([event]).features[0];
  expect(feature.properties.geometry_kind).toBe("road_reference");
  expect(feature.properties.actual_non_transit_extent_known).toBe(false);
  expect(feature.properties.source_road_extent).toBe("native_endpoint_bounded");
  expect(feature.properties.transit_line).toBeUndefined();
  expect(countableEventIds([event])).toEqual(new Set());
});

test("bounded road and carrier-line references retain their different uncertainty", () => {
  const base = sharedReport.scene_locations![2];
  const bounded: SceneLocation = {...base, location_precision: "route", geometry_usage: "source_road_reference_only",
    source_road_extent: "native_endpoint_bounded" as const, complete_transit_line: false as const,
    candidate_road_geometry: undefined,
    transit_route: {mode: "bus", line: "unknown", extent: "source_segment" as const, evidence_quote: "bounded road"}};
  expect(transitGeometryLabel(bounded)).toBe(t("transit.partialRoad"));
  const carrier: SceneLocation = {...bounded, geometry_usage: "carrier_line_reference_only",
    source_road_extent: undefined, actual_transit_extent_known: false as const,
    transit_route: {...bounded.transit_route!, mode: "tram", line: "M1"}};
  expect(transitGeometryLabel(carrier)).toBe(t("transit.carrierLine"));
  const events = [report("bounded", {scene_locations: [bounded]}), report("carrier", {scene_locations: [carrier]})];
  const features = sceneFeatures(events).features;
  expect(features[0].properties.source_road_extent).toBe("native_endpoint_bounded");
  expect(features[1].properties.geometry_kind).toBe("transit_line_reference");
  expect(features[1].properties.actual_transit_extent_known).toBe(false);
  expect(countableEventIds(events)).toEqual(new Set());
});

test("native unidentified-service corridor does not infer a historical line", () => {
  const scene: SceneLocation = {...sharedReport.scene_locations![2], location_precision: "route",
    candidate_road_geometry: undefined, geometry_usage: "source_transit_corridor_reference_only",
    service_identity_known: false, complete_transit_line: false,
    transit_route: {mode: "subway", line: "unidentified U-Bahn line", extent: "source_segment", evidence_quote: "between two stations"}};
  expect(transitGeometryLabel(scene)).toBe(t("transit.trackInterval"));
  const event = report("unidentified", {scene_locations: [scene]});
  const feature = sceneFeatures([event]).features[0];
  expect(feature.properties.transit_line).toBe("unidentified U-Bahn line");
  expect(feature.properties.service_identity_known).toBe(false);
  expect(countableEventIds([event])).toEqual(new Set());
});

test("full-line carrier reference does not become an actual train trip or count", () => {
  const scene: SceneLocation = {...sharedReport.scene_locations![2], role: "incident",
    label: "U8 train interior; motion and position unknown", location_precision: "route",
    candidate_road_geometry: undefined, primary_for_count: false,
    geometry_usage: "carrier_line_reference_only", complete_transit_line: false,
    actual_transit_extent_known: false,
    transit_route: {mode: "subway", line: "U8", extent: "full_line", evidence_quote: "inside U8"}};
  const event = report("unknown-motion-U8", {scene_locations: [scene]});
  expect(transitGeometryLabel(scene)).toBe(t("transit.carrierLine"));
  const feature = sceneFeatures([event]).features[0];
  expect(feature.properties.geometry_kind).toBe("transit_line_reference");
  expect(feature.properties.actual_transit_extent_known).toBe(false);
  expect(scene.complete_transit_line).toBe(false);
  expect(feature.properties.primary_for_count).toBe(false);
  expect(countableEventIds([event])).toEqual(new Set());
});

test("native water footprint is context, not an actual boat trajectory or count", () => {
  const scene: SceneLocation = {...sharedReport.scene_locations![2], location_precision: "route",
    candidate_road_geometry: undefined, transit_route: undefined,
    geometry_usage: "source_footprint_reference_only", actual_non_transit_extent_known: false,
    geometry: {type: "Polygon", coordinates: [[[13.4, 52.5], [13.41, 52.5], [13.41, 52.51], [13.4, 52.5]]]},
    coordinates: null, primary_for_count: false};
  const event = report("water-reference", {scene_locations: [scene]});
  const feature = sceneFeatures([event]).features[0];
  expect(feature.geometry).toEqual(scene.geometry);
  expect(feature.properties.actual_non_transit_extent_known).toBe(false);
  expect(feature.properties.geometry_usage).toBe("source_footprint_reference_only");
  expect(feature.properties.transit_line).toBeUndefined();
  expect(countableEventIds([event])).toEqual(new Set());
});
const rows = [
  sharedReport,
  report("B", {
    category: "raub",
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
  expect(sceneFeatures(monthEvents(data, "2026-09", "raub")).features)
    .toHaveLength(1);
  expect(sceneFeatures(monthEvents(data, "2026-08", "all")).features)
    .toHaveLength(1);
  expect(sceneRoleGroup("accident")).toBe("incident");
  expect(sceneRoleGroup("discovery")).toBe("discovery");
  for (const role of ["operation", "arrest", "search"] as const)
    expect(sceneRoleGroup(role)).toBe("operation");
  for (const role of ["background", "unknown"] as const)
    expect(sceneRoleGroup(role)).toBe("context");
  expect(sceneRoleLabel("arrest")).toBe(t("role.arrest"));
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

test("location coverage separates no count point from retained scene references", () => {
  const rows = [sharedReport, report("line-reference", {
    scene_locations: [{
      label: "Reviewed road reference", role: "incident", location_precision: "street",
      geocode_method: "osm_line", primary_for_count: false,
      geometry: { type: "LineString", coordinates: [[13.4, 52.5], [13.41, 52.5]] },
    }],
  }), report("discovery-reference", {
    scene_locations: [{
      label: "Discovery, not offence", role: "discovery", location_precision: "point",
      geocode_method: "source_named_point", primary_for_count: false,
      geometry: { type: "Point", coordinates: [13.4, 52.5] },
    }],
  }), report("unlocated", {
    scene_locations: [{
      label: "Unspecified location", role: "unknown", location_precision: "unknown",
      geocode_method: "none", primary_for_count: false,
    }],
  })];
  expect(locationCoverage(rows)).toEqual({
    countableAnnouncements: 1,
    withoutCountPointIds: ["line-reference", "discovery-reference", "unlocated"],
    withoutCountPointWithDisplayGeometry: 2,
  });
  expect(locationCoverage([]).countableAnnouncements).toBe(0);
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

test("reviewed demonstration routes stay road ranges instead of transit lines", () => {
  const demonstration = report("demonstration", {
    scene_locations: [{
      label: "Straße des 17. Juni / Großer Stern",
      role: "background",
      location_precision: "route",
      geocode_method: "osm_non_transit_route",
      geometry: {
        type: "LineString",
        coordinates: [[13.34, 52.51], [13.35, 52.52]],
      },
      primary_for_count: false,
    }],
  });
  const features = sceneFeatures([demonstration]).features;
  expect(features).toHaveLength(1);
  expect(features[0].properties).toMatchObject({
    geometry_kind: "reported",
    geocode_method: "osm_non_transit_route",
  });
  expect(features[0].properties?.transit_line).toBeUndefined();
  expect(countableEventIds([demonstration])).toEqual(new Set());
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

test("native platform lines remain lines with context-only intensity and explicit missing-area wording", () => {
  const data = {
    pois: { type: "FeatureCollection", features: [{
      type: "Feature", geometry: { type: "LineString", coordinates: [[13.4, 52.5], [13.401, 52.501]] },
      properties: { id: "platform-1", kind: "station", geometry_mode: "native_line_reference" },
    }] },
    catalog: { poi_types: { station: { color: "#2563eb", label: "车站" } } },
  } as unknown as Bundle;
  const link = {
    event_id: "A", poi_id: "platform-1", status: "context_named_object",
    source_url: "https://example.test/source", mention_basis: "source_reviewed_context_only",
  };
  const styled = styledPois(data, [link, link], new Set(["A"]), new Set(["station"]), true);
  expect(styled.features[0].geometry.type).toBe("LineString");
  expect(styled.features[0].properties).toMatchObject({ count: 0, candidate_count: 0, context_count: 1 });
  expect(styled.features[0].properties.opacity).toBeGreaterThan(0.12);
  expect(poiGeometryLabel("native_line_reference")).toBe(t("geometry.nativeLine"));
  expect(poiGeometryLabel("native_named_reference_area")).toBe(t("geometry.namedArea"));
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
        {
          label: "移动公交道路参考", role: "background", location_precision: "route",
          geocode_method: "osm_transit_road_reference", primary_for_count: false,
          geometry_usage: "source_road_reference_only", complete_transit_line: false,
          geometry: {type: "LineString", coordinates: [[13.409, 52.508], [13.413, 52.508]]},
          transit_route: {mode: "bus", line: "unknown", extent: "source_segment", evidence_quote: "source road"},
        },
      ],
    }),
    report("other", {
      title: "其他类别公告",
      category: "raub",
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
      categories: ["gewalt", "raub"],
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
  await page.goto("/?lang=zh");
  await expect(page.locator("#stats .big")).toHaveText("2");
  const canvas = page.locator(".maplibregl-canvas");
  await expect.poll(async () => {
    const box = await canvas.boundingBox();
    await canvas.click({ position: { x: box!.width / 2, y: box!.height / 2 } });
    return page.locator("#selection").innerText();
  }).toContain("多地点公告");
  await expect(page.locator("#selection .report")).toHaveCount(1);
  await expect(page.locator("#selection .scene-list li")).toHaveCount(5);
  await expect(page.locator("#selection")).toContainText("仅作道路参照，不是完整线路；精确路段未知");
  await expect(page.locator("#selection")).toContainText("用于公告统计的代表地点");
  await expect(page.locator("#selection")).toContainText("每篇公告最多计一次");
  await page.locator("#category").selectOption("raub");
  await expect(page.locator("#selection")).not.toContainText("多地点公告");
  await expect(page.locator("#stats")).toContainText("0条可计入六边形；1条没有可用于统计的代表地点");
  await page.locator("#month").selectOption("08");
  await expect(page.locator("#stats .big")).toHaveText("—");
});
