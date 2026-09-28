import type {
  FeatureCollection,
  Geometry,
  LineString,
  MultiLineString,
} from "geojson";
export type Properties = Record<string, any>;
export type FC = FeatureCollection<Geometry, Properties>;
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
        line.every(
          (point) =>
            point.length >= 2 &&
            Number.isFinite(point[0]) &&
            Number.isFinite(point[1]) &&
            Math.abs(point[0]) <= 180 &&
            Math.abs(point[1]) <= 90,
        ),
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
  return {
    ...source,
    features: source.features.flatMap((f) => {
      const eventIds = (f.properties.event_ids as string[]).filter((id) =>
        ids.has(id),
      );
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
