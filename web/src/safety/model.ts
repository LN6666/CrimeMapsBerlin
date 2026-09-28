import type {
  FeatureCollection,
  Geometry,
  LineString,
  MultiLineString,
} from "geojson";
export type Properties = Record<string, any>;
export type FC = FeatureCollection<Geometry, Properties>;
export type SceneRole =
  | "incident"
  | "accident"
  | "discovery"
  | "operation"
  | "arrest"
  | "search"
  | "background"
  | "unknown";
export type SceneCaseRelation =
  | "independent_case"
  | "same_case_phase"
  | "search_arrest_operation"
  | "background_reference"
  | "unresolved_relation";
export interface SceneLocation {
  label: string;
  role: SceneRole;
  location_precision: string;
  geocode_method: string;
  coordinates?: [number, number] | null;
  geometry?: Geometry | null;
  candidate_road_geometry?: LineString | MultiLineString | null;
  primary_for_count: boolean;
  case_relation?: SceneCaseRelation;
  minimum_incidents?: number;
}
export interface PoliceEvent {
  id: string;
  title: string;
  source_status?: string;
  category: string;
  month: string | null;
  event_date: string | null;
  coordinates: [number, number] | null;
  location_precision: string;
  location_label: string;
  location_extent_m?: number;
  location_scope?: string;
  location_selection?: string;
  geocode_method?: string;
  other_scene_candidates?: { name: string; sentence_index: number }[];
  scene_locations?: SceneLocation[];
  reported_location_geometry?: Geometry;
  candidate_road_geometry?: LineString | MultiLineString;
  source_url: string;
  feed_url: string;
  poi_mentions: string[];
  mention_basis: string;
  outcome: string;
  reviewed_tags?: {
    tag: string;
    basis?: string;
    evidence_quote: string;
  }[];
}
export interface Link {
  event_id: string;
  poi_id: string;
  status: string;
  source_url: string;
  mention_basis: string;
}
export interface Month {
  event_ids: string[];
  hex: { overview: FC; detail: FC };
  links: Link[];
}
export interface Bundle {
  schema_version: number;
  city: string;
  retrieved_at: string;
  expires_at: string;
  coverage: string;
  events: PoliceEvent[];
  months: Record<string, Month>;
  pois: FC;
  metadata: Properties;
  catalog: {
    sources: Properties[];
    coverage: Properties[];
    poi_types: Record<string, { color: string; label: string }>;
    exhaustive: boolean;
  };
  zones: {
    places: Properties[];
    features: FC["features"];
    geometry_status: string;
  };
}
export const empty = (): FC => ({ type: "FeatureCollection", features: [] });
export function sceneRoleGroup(role: SceneRole): string {
  if (role === "incident" || role === "accident") return "incident";
  if (role === "discovery") return "discovery";
  if (["operation", "arrest", "search"].includes(role)) return "operation";
  return "context";
}
export function sceneRoleLabel(role: SceneRole): string {
  return {
    incident: "案发地点",
    accident: "事故地点",
    discovery: "发现地点",
    operation: "警方行动地点",
    arrest: "抓捕地点",
    search: "搜查地点",
    background: "背景地点",
    unknown: "地点角色待核",
  }[role] ?? "地点角色待核";
}
const validPoint = (point: number[]): boolean =>
  point.length >= 2 &&
  Number.isFinite(point[0]) &&
  Number.isFinite(point[1]) &&
  Math.abs(point[0]) <= 180 &&
  Math.abs(point[1]) <= 90;
const validLine = (line: number[][]): boolean =>
  line.length >= 2 && line.every(validPoint);
const countablePrecision = (precision: string): boolean =>
  ["street", "point", "place", "address"].includes(precision);
function validGeometry(geometry: Geometry): boolean {
  switch (geometry.type) {
    case "Point":
      return validPoint(geometry.coordinates);
    case "MultiPoint":
      return geometry.coordinates.length > 0 && geometry.coordinates.every(validPoint);
    case "LineString":
      return validLine(geometry.coordinates);
    case "MultiLineString":
      return geometry.coordinates.length > 0 && geometry.coordinates.every(validLine);
    case "Polygon":
      return geometry.coordinates.length > 0 &&
        geometry.coordinates.every((ring) => ring.length >= 4 && ring.every(validPoint));
    case "MultiPolygon":
      return geometry.coordinates.length > 0 &&
        geometry.coordinates.every((polygon) =>
          polygon.length > 0 &&
          polygon.every((ring) => ring.length >= 4 && ring.every(validPoint))
        );
    case "GeometryCollection":
      return geometry.geometries.length > 0 && geometry.geometries.every(validGeometry);
  }
}
function sceneGeometries(geometry: Geometry): Geometry[] {
  return geometry.type === "GeometryCollection"
    ? geometry.geometries.flatMap(sceneGeometries)
    : [geometry];
}
/** All displayable scenes share one source; point representatives never replace source geometry. */
export function sceneFeatures(rows: PoliceEvent[]): FC {
  return {
    type: "FeatureCollection",
    features: rows.flatMap((event) =>
      (event.scene_locations ?? []).flatMap((scene, index) => {
        const properties = {
          id: event.id,
          scene_id: `${event.id}/${index}`,
          scene_index: index,
          label: scene.label,
          role: scene.role,
          role_group: sceneRoleGroup(scene.role),
          primary_for_count: scene.primary_for_count,
          location_precision: scene.location_precision,
          geocode_method: scene.geocode_method,
        };
        const features: FC["features"] = [];
        if (scene.geometry && validGeometry(scene.geometry))
          for (const [part, geometry] of sceneGeometries(scene.geometry).entries())
            features.push({
              type: "Feature",
              geometry,
              properties: { ...properties, geometry_kind: "reported", part },
            });
        if (
          scene.coordinates &&
          validPoint(scene.coordinates) &&
          !(scene.geometry?.type === "Point" &&
            scene.geometry.coordinates[0] === scene.coordinates[0] &&
            scene.geometry.coordinates[1] === scene.coordinates[1])
        )
          features.push({
            type: "Feature",
            geometry: { type: "Point", coordinates: scene.coordinates },
            properties: { ...properties, geometry_kind: "representative_point" },
          });
        if (
          scene.candidate_road_geometry &&
          validGeometry(scene.candidate_road_geometry)
        )
          features.push({
            type: "Feature",
            geometry: scene.candidate_road_geometry,
            properties: { ...properties, geometry_kind: "candidate_road" },
          });
        return features;
      }),
    ),
  };
}
export function sceneEventIds(features: FC["features"]): string[] {
  return [...new Set(features.map((feature) => String(feature.properties.id)))];
}
/** Existing snapshots have no scene array; new snapshots count only an explicit primary point. */
export function countableEventIds(rows: PoliceEvent[]): Set<string> {
  return new Set(
    rows
      .filter((event) =>
        event.scene_locations === undefined ||
        event.scene_locations.some(
          (scene) =>
            scene.primary_for_count &&
            countablePrecision(scene.location_precision) &&
            (Boolean(scene.coordinates && validPoint(scene.coordinates)) ||
              Boolean(scene.geometry?.type === "Point" && validPoint(scene.geometry.coordinates))),
        ),
      )
      .map((event) => event.id),
  );
}
/** A review range identifies a road, never an incident point. */
export function candidateRoadGeometry(
  event: PoliceEvent,
): LineString | MultiLineString | null {
  if (
    event.coordinates !== null ||
    !["long_or_ambiguous_street_review", "disconnected_street_review"].includes(
      event.geocode_method ?? "",
    )
  )
    return null;
  const geometry = event.candidate_road_geometry;
  if (!geometry || !["LineString", "MultiLineString"].includes(geometry.type))
    return null;
  const lines =
    geometry.type === "LineString"
      ? [geometry.coordinates]
      : geometry.coordinates;
  if (
    !lines.length ||
    !lines.every(
      (line) =>
        line.length >= 2 &&
        line.every(validPoint),
    )
  )
    return null;
  return geometry;
}
export function candidateRoads(rows: PoliceEvent[]): FC {
  return {
    type: "FeatureCollection",
    features: rows.flatMap((event) => {
      const geometry = candidateRoadGeometry(event);
      return geometry
        ? [{ type: "Feature" as const, geometry, properties: { id: event.id } }]
        : [];
    }),
  };
}
export function roadBounds(
  geometry: LineString | MultiLineString,
): [number, number, number, number] {
  const lines =
    geometry.type === "LineString"
      ? [geometry.coordinates]
      : geometry.coordinates;
  let west = Infinity,
    south = Infinity,
    east = -Infinity,
    north = -Infinity;
  for (const line of lines)
    for (const [lon, lat] of line) {
      west = Math.min(west, lon);
      south = Math.min(south, lat);
      east = Math.max(east, lon);
      north = Math.max(north, lat);
    }
  return [west, south, east, north];
}
export function monthEvents(
  data: Bundle,
  month: string,
  category: string,
): PoliceEvent[] {
  return data.events.filter(
    (e) => e.month === month && (category === "all" || e.category === category),
  );
}
export function filteredHex(source: FC, ids: Set<string>): FC {
  // One announcement contributes to at most one cell, including malformed duplicate bundles.
  const seen = new Set<string>();
  return {
    ...source,
    features: source.features.flatMap((f) => {
      const eventIds = (f.properties.event_ids as string[]).filter((id) => {
        if (!ids.has(id) || seen.has(id)) return false;
        seen.add(id);
        return true;
      });
      return eventIds.length
        ? [
            {
              ...f,
              properties: {
                ...f.properties,
                event_ids: eventIds,
                count: eventIds.length,
              },
            },
          ]
        : [];
    }),
  };
}
export function styledPois(
  data: Bundle,
  links: Link[],
  ids: Set<string>,
  kinds: Set<string>,
  highlight: boolean,
): FC {
  const counts = new Map<string, Set<string>>();
  const candidate = new Map<string, Set<string>>();
  for (const link of links) {
    if (!ids.has(link.event_id)) continue;
    const target = ["approximate_candidate", "named_place_candidate"].includes(
      link.status,
    )
      ? candidate
      : counts;
    if (!target.has(link.poi_id)) target.set(link.poi_id, new Set());
    target.get(link.poi_id)!.add(link.event_id);
  }
  return {
    ...data.pois,
    features: data.pois.features
      .filter((f) => kinds.has(f.properties.kind))
      .map((f) => {
        const id = f.properties.id,
          n = counts.get(id)?.size ?? 0,
          c = candidate.get(id)?.size ?? 0;
        return {
          ...f,
          properties: {
            ...f.properties,
            color:
              data.catalog.poi_types[f.properties.kind]?.color ?? "#64748b",
            count: n,
            candidate_count: c,
            association_count: n + c,
            opacity: highlight
              ? Math.min(0.78, 0.12 + 0.16 * Math.log2(1 + n + c))
              : 0.12,
            event_ids: [
              ...(counts.get(id) ?? []),
              ...(candidate.get(id) ?? []),
            ],
          },
        };
      }),
  };
}
export function safeURL(value: string): string | null {
  try {
    const u = new URL(value);
    return u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}
