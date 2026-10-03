import {t} from "./i18n";
import type {
  FeatureCollection,
  Geometry,
  LineString,
  MultiLineString,
} from "geojson";
export type Properties = Record<string, any>;
export type FC = FeatureCollection<Geometry, Properties>;
export const SCENE_CLICK_LAYERS = [
  "scene-point", "scene-candidate-road-hit", "scene-line", "scene-line-hit", "scene-transit-route",
  "scene-transit-line-reference", "scene-transit-line-reference-hit",
  "scene-area-fill", "scene-area-outline",
];
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
export interface EventTime {
  display: string;
  date: string | null;
  precision: "exact" | "approximate" | "date" | "range" | "unknown";
  evidence_quote: string;
}
export interface TransitRoute {
  mode: "bus" | "tram" | "subway" | "train" | "ferry" | "other";
  line: string;
  extent: "full_line" | "source_segment";
  evidence_quote: string;
}
export interface PoiContext {
  kind: string;
  scope: "along_geometry" | "near_geometry" | "named_object";
  radius_m: number;
  evidence_quote: string;
}
export interface SceneLocation {
  public_display_fields?:string[];
  public_reference_note?:string;
  location_object_ids?:string[];
  poi_review?: {status:string;note:string};
  transit_review?: {status:string;note:string};
  source_relations?: {decision:{review_note:string}}[];
  native_platform_count?:number;
  actual_platform_side_known?:boolean;
  source_platform_side_known?:boolean;
  source_attachment_url?:string;
  height_known?:false;
  full_legal_definition_verified?:false;
  static_scene_reference?:boolean;
  label: string;
  role: SceneRole;
  location_precision: string;
  geocode_method: string;
  coordinates?: [number, number] | null;
  geometry?: Geometry | null;
  candidate_road_geometry?: LineString | MultiLineString | null;
  geometry_usage?: "source_road_reference_only" | "carrier_line_reference_only" | "source_footprint_reference_only" | "source_transit_corridor_reference_only" | "source_junction_reference_only" | "source_native_collection_reference_only" | "official_attachment_horizontal_reference_only" | "source_native_platform_points_reference_only" | "source_station_platform_footprint_reference_only";
  actual_event_position_known?: boolean;
  actual_event_extent_known?: boolean;
  actual_non_transit_extent_known?: boolean;
  service_identity_known?: false;
  source_road_extent?: "native_endpoint_bounded" | "native_bridge_outline_bounded";
  actual_transit_extent_known?: false;
  complete_transit_line?: false;
  primary_for_count: boolean;
  case_relation?: SceneCaseRelation;
  minimum_incidents?: number;
  details?: string;
  geometry_review?: {
    verdict: "resolved" | "unresolved" | "needs_correction";
    method: string;
    review_note: string;
  };
  event_time?: EventTime;
  incidents?: {
    incident_id: string;
    category?: string;
    event_time?: EventTime;
    details?: string;
  }[];
  transit_route?: TransitRoute;
  poi_contexts?: PoiContext[];
}
export interface SourceStage {
  incident_id:string;details?:string;event_time?:EventTime;category?:string;formal_location_ids?:string[];
}
export interface PoliceEvent {
  public_display_fields?:string[];
  public_uncertainty?:string[];
  status_update?:string;
  historical_source_reviews?: {
    source_id: string;
    title: string;
    source_url: string;
    published_at_source_literal: string;
    review_note: string;
    source_incidents: {
      incident_id: string;
      event_time: EventTime;
      details: string;
      formal_location_ids: string[];
    }[];
    formal_locations: {
      location_id: string;
      label: string;
      role: SceneRole;
      precision: string;
      poi_review: { status: string; note: string };
      transit_review: { status: string; note: string };
    }[];
  }[];
  source_reference_comparisons?: { review_note: string }[];
  current_claim_overlays?: { display_note: string }[];
  source_attachments?: { source_url: string; source_sha256: string; read: boolean; page_count: number; note: string }[];
  source_supporting_materials?: { source_url: string; source_sha256: string; label: string; note: string }[];
  map_review_note?: string;
  source_incidents?:SourceStage[];
  published_at_source_literal?:string;
  published_at_timezone_basis?:string;
  month_basis?:string;
  id: string;
  title: string;
  published_at?:string;
  publication_month?:string;
  time_basis?:string;
  source_status?: string;
  source_scope_verdict?: "in_city" | "mixed" | "uncertain" | "out_of_city";
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
  incidents?:SourceStage[];
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
  scene_id?: string;
  evidence_quote?: string;
}
export interface Month {
  source_poi_reference_features?:FC;
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
export function poiGeometryLabel(mode: string): string {
  if (mode === "50m_circle") return t("geometry.circle");
  if (mode === "footprint_missing") return t("geometry.footprintMissing");
  if (mode === "native_line_reference") return t("geometry.nativeLine");
  if (mode === "native_named_reference_area") return t("geometry.namedArea");
  return t("geometry.osmArea");
}
export function sceneRoleGroup(role: SceneRole): string {
  if (role === "incident" || role === "accident") return "incident";
  if (role === "discovery") return "discovery";
  if (["operation", "arrest", "search"].includes(role)) return "operation";
  return "context";
}
export function sceneRoleLabel(role: SceneRole): string {
  return t(`role.${role}`,{},t("role.unknown"));
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
/** Road anchors must not be labelled as checked operational lines or precise segments. */
export function transitGeometryLabel(scene: SceneLocation): string {
  if (isUnderpassReference(scene)) return t("transit.underpass");
  if (scene.geometry_usage === "source_transit_corridor_reference_only")
    return t("transit.trackInterval");
  if (scene.geometry_usage === "carrier_line_reference_only")
    return t("transit.carrierLine");
  if (scene.geometry_usage === "source_road_reference_only")
    if (scene.actual_non_transit_extent_known === false)
      return t("transit.roadExtent");
  if (scene.geometry_usage === "source_road_reference_only")
    return scene.source_road_extent === "native_endpoint_bounded"
      ? t("transit.partialRoad")
      : t("transit.unknownRoad");
  return scene.transit_route?.extent === "full_line" ? t("transit.fullLine") : t("transit.sourceSection");
}
function isUnderpassReference(scene: SceneLocation): boolean {
  return scene.geocode_method === "osm_road_under_bridge_reference";
}
function isFootprintReference(scene: SceneLocation): boolean {
  return scene.geometry_usage === "source_footprint_reference_only" || [
    "osm_named_footprint_reference", "osm_place_footprint_reference",
    "osm_non_transit_footprint_reference", "osm_station_footprint_reference",
    "osm_water_footprint_reference", "official_district_footprint_reference",
  ].includes(scene.geocode_method);
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
          primary_for_count: scene.geometry_usage?.endsWith("reference_only") || isUnderpassReference(scene) || isFootprintReference(scene) || scene.geometry_usage === "source_junction_reference_only" ||
            ["osm_junction_reference", "osm_rail_crossing_area_reference"].includes(scene.geocode_method) ? false : scene.primary_for_count,
          location_precision: scene.location_precision,
          geocode_method: scene.geocode_method,
          transit_line: scene.transit_route?.line,
          geometry_usage: scene.geometry_usage,
          actual_event_position_known: scene.actual_event_position_known,
          actual_event_extent_known: scene.actual_event_extent_known,
          actual_non_transit_extent_known: scene.actual_non_transit_extent_known,
          source_road_extent: scene.source_road_extent,
          actual_transit_extent_known: scene.actual_transit_extent_known,
          service_identity_known: scene.service_identity_known,
        };
        const features: FC["features"] = [];
        if (scene.geometry && validGeometry(scene.geometry))
          for (const [part, geometry] of sceneGeometries(scene.geometry).entries())
            features.push({
              type: "Feature",
              geometry,
              properties: {
                ...properties,
                geometry_kind:
                  scene.geometry_usage === "source_native_platform_points_reference_only"
                    ? "native_platform_reference"
                    : scene.geocode_method === "osm_station_footprint_reference"
                    ? "station_footprint_reference"
                    : scene.geocode_method === "official_district_footprint_reference"
                    ? "official_district_reference"
                    : scene.geocode_method === "osm_water_footprint_reference"
                    ? "water_reference"
                    : scene.geometry_usage === "source_native_collection_reference_only"
                    ? "native_collection_reference"
                    : scene.geometry_usage === "source_junction_reference_only" ||
                      ["osm_junction_reference", "osm_rail_crossing_area_reference"].includes(scene.geocode_method)
                    ? "junction_reference"
                    : scene.geometry_usage === "source_road_reference_only"
                    ? (scene.actual_non_transit_extent_known === false ? "road_reference" : "transit_road_reference")
                    : scene.geometry_usage === "carrier_line_reference_only"
                      ? "transit_line_reference"
                    : scene.location_precision === "route" && scene.transit_route
                      ? "transit_route" : "reported",
                part,
              },
            });
        if (
          !scene.geometry_usage?.endsWith("reference_only") && !isUnderpassReference(scene) && !isFootprintReference(scene) &&
          scene.geometry_usage !== "source_native_collection_reference_only" &&
          scene.geometry_usage !== "source_junction_reference_only" &&
          scene.coordinates &&
          !["osm_junction_reference", "osm_rail_crossing_area_reference"].includes(scene.geocode_method) &&
          scene.geocode_method !== "osm_water_footprint_reference" &&
          scene.geocode_method !== "osm_station_footprint_reference" &&
          scene.geocode_method !== "official_district_footprint_reference" &&
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
            !scene.geometry_usage?.endsWith("reference_only") && !isUnderpassReference(scene) && !isFootprintReference(scene) &&
            scene.geometry_usage !== "source_native_collection_reference_only" &&
            scene.geometry_usage !== "source_junction_reference_only" &&
            scene.primary_for_count &&
            !["osm_junction_reference", "osm_rail_crossing_area_reference"].includes(scene.geocode_method) &&
            scene.geocode_method !== "osm_water_footprint_reference" &&
            scene.geocode_method !== "osm_station_footprint_reference" &&
            scene.geocode_method !== "official_district_footprint_reference" &&
            countablePrecision(scene.location_precision) &&
            (Boolean(scene.coordinates && validPoint(scene.coordinates)) ||
              Boolean(scene.geometry?.type === "Point" && validPoint(scene.geometry.coordinates))),
        ),
      )
      .map((event) => event.id),
  );
}
/** A displayed road/area/discovery reference is not a countable incident point. */
export function locationCoverage(rows: PoliceEvent[], displayedScenes = sceneFeatures(rows)) {
  const countable = countableEventIds(rows);
  const withoutCountPoint = rows.filter((event) =>
    event.scene_locations !== undefined
      ? !countable.has(event.id)
      : !event.coordinates || !countablePrecision(event.location_precision),
  );
  const displayedIds = new Set([
    ...sceneEventIds(displayedScenes.features),
    ...candidateRoads(rows).features.map((feature) => String(feature.properties.id)),
  ]);
  return {
    countableAnnouncements: rows.length - withoutCountPoint.length,
    withoutCountPointIds: withoutCountPoint.map((event) => event.id),
    withoutCountPointWithDisplayGeometry: withoutCountPoint.filter((event) =>
      displayedIds.has(event.id)).length,
  };
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
  const context = new Map<string, Set<string>>();
  for (const link of links) {
    if (!ids.has(link.event_id)) continue;
    const target = link.status.startsWith("context_")
      ? context
      : ["approximate_candidate", "named_place_candidate"].includes(link.status)
        ? candidate
        : counts;
    if (!target.has(link.poi_id)) target.set(link.poi_id, new Set());
    target.get(link.poi_id)!.add(link.event_id);
  }
  return {
    ...data.pois,
    features: data.pois.features
      .filter((f) => f.properties.scope_category ? kinds.has(f.properties.scope_category)
        : (f.properties.context_kinds ?? [f.properties.kind]).some((kind:string) => kinds.has(kind)))
      .map((f) => {
        const id = f.properties.id,
          n = counts.get(id)?.size ?? 0,
          c = candidate.get(id)?.size ?? 0,
          x = context.get(id)?.size ?? 0;
        const displayKind = f.properties.scope_category ? f.properties.kind
          : (f.properties.context_kinds ?? [f.properties.kind]).find((kind:string) => kinds.has(kind)) ?? f.properties.kind;
        return {
          ...f,
          properties: {
            ...f.properties,
            display_kind: displayKind,
            color:
              data.catalog.poi_types[displayKind]?.color ?? "#64748b",
            count: n,
            candidate_count: c,
            context_count: x,
            association_count: n + c + x,
            opacity: highlight
              ? Math.min(0.78, 0.12 + 0.16 * Math.log2(1 + n + c + x))
              : 0.12,
            event_ids: [
              ...(counts.get(id) ?? []),
              ...(candidate.get(id) ?? []),
              ...(context.get(id) ?? []),
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

/** Metre radius for a reviewed display-only circle in MapLibre's 512px Mercator world.
 * Native geometry/scene/count/context matching never consume this display copy.
 */
export function radiusPixelsAtZoomZero(latitude: number, radius: number): number {
  if (!Number.isFinite(latitude) || Math.abs(latitude) >= 85 || radius !== 50)
    throw Error("Invalid reviewed display circle");
  return radius * 512 / (40075016.68557849 * Math.cos(latitude * Math.PI / 180));
}
export function renderPois(fc: FC): FC {
  return { ...fc, features: fc.features.map((feature) => {
    const p = feature.properties;
    if (p.compact_geometry_version !== 1) return feature;
    if (feature.geometry.type !== "Point" || p.geometry_mode !== "50m_circle" ||
        p.boundary_clipped !== false || p.display_radius_m !== 50 ||
        !validPoint(feature.geometry.coordinates) ||
        !Array.isArray(p.center) || p.center[0] !== feature.geometry.coordinates[0] ||
        p.center[1] !== feature.geometry.coordinates[1])
      throw Error("Invalid compact reviewed circle");
    return { ...feature, properties: { ...p,
      radius_px_z0: radiusPixelsAtZoomZero(feature.geometry.coordinates[1], p.display_radius_m) } };
  }) };
}

/** Preserve stages that have no displayed scene; they never supply coordinates or counts. */
export function unplacedStages(event:PoliceEvent):SourceStage[] {
 const displayed=new Set(event.scene_locations?.flatMap(scene=>scene.incidents?.map(stage=>stage.incident_id)??[])??[]);
 return (event.incidents??event.source_incidents??[]).filter(stage=>!displayed.has(stage.incident_id));
}

export const SOURCE_POI_CLICK_LAYERS=["source-poi-reference-fill","source-poi-reference-line","source-poi-reference-point"];
/** Display already reviewed native context geometry; never replace it with a display circle. */
export function sourcePoiReferences(rows:PoliceEvent[],references:FC|undefined):FC {
 const sources=new Map(rows.map(e=>[String((e as PoliceEvent&{source_id?:string}).source_id??e.id.split(":").at(-1)),e.id]));
 return {type:"FeatureCollection",features:(references?.features??[]).flatMap(f=>{const id=sources.get(String(f.properties.source_id));if(!id)return [];if(f.properties.context_only!==true||f.properties.counts_as_crime_point!==false||f.properties.event_count_point!==false||f.properties.association_radius_m!==0||!validGeometry(f.geometry))throw Error("Invalid reviewed source POI reference");return [{...f,properties:{...f.properties,id,source_reference_id:f.id??f.properties.native_object_id}}];})};
}
