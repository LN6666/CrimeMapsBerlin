import type { EventTime, PoliceEvent, SceneLocation, SceneRole } from "./model";

export const UNCERTAINTY_KINDS = ["district", "street", "area", "venue_reference", "no_location"] as const;
export type UncertaintyKind = (typeof UNCERTAINTY_KINDS)[number];
export interface UncertaintyRow {
  key: string;
  sourceId: string;
  title: string;
  sourceURL: string | null;
  category: string;
  kind: UncertaintyKind;
  label: string;
  role: SceneRole;
  // Source-native time only; the publication month is never substituted.
  eventTime: EventTime | null;
  // A legacy summary date is separate from reviewed scene-native time.
  summaryEventDate: string | null;
  publicationMonth: string | null;
  referenceAvailable: boolean;
  status: "unresolved" | "reference_only" | "insufficient_precision";
}
const POINT_PRECISIONS = new Set(["point", "address", "exact"]);
function precise(scene: SceneLocation): boolean {
  if (!POINT_PRECISIONS.has(scene.location_precision) || scene.geometry_usage ||
      scene.actual_event_position_known === false ||
      scene.geometry_review?.verdict === "unresolved" || scene.geometry_review?.verdict === "needs_correction") return false;
  const p = scene.geometry?.type === "Point" ? scene.geometry.coordinates : scene.coordinates;
  return !!p && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]) &&
    Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90;
}
function kind(scene: SceneLocation): UncertaintyKind {
  const p = scene.location_precision;
  if (["district", "borough", "city", "city_only"].includes(p)) return "district";
  if (["street", "route", "road", "line", "street_only"].includes(p)) return "street";
  if (["area", "region", "neighbourhood", "neighborhood", "area_only"].includes(p)) return "area";
  if (["point", "address", "exact", "place", "venue", "poi"].includes(p)) return "venue_reference";
  // Do not infer a location class from words in a source label.
  if (scene.geometry_usage === "source_road_reference_only" ||
      scene.geometry_usage === "carrier_line_reference_only" ||
      scene.geometry_usage === "source_transit_corridor_reference_only") return "street";
  return "no_location";
}
export function sourceURL(value: string): string | null {
  try {
    const u = new URL(value);
    return u.protocol === "https:" && !u.username && !u.password ? u.href : null;
  } catch { return null; }
}
function publicationMonth(event: PoliceEvent): string | null {
  // month is the selected data month and can represent an occurrence month.
  // Read the source's publication fields without timezone conversion.
  const record = event as PoliceEvent & { publication_month?: string; published_at?: string };
  if (typeof record.publication_month === "string" && /^\d{4}-(0[1-9]|1[0-2])$/.test(record.publication_month)) return record.publication_month;
  if (typeof record.published_at === "string" && /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?:T|\s|$)/.test(record.published_at)) return record.published_at.slice(0, 7);
  return null;
}
export function uncertaintyRows(events: readonly PoliceEvent[]): UncertaintyRow[] {
  const rows: UncertaintyRow[] = [];
  const seen = new Set<string>();
  for (const event of events) {
    // Scope inclusion remains the source-reviewer's decision.
    if (event.source_scope_verdict === "out_of_city") continue;
    const hasScenes = !!event.scene_locations?.length;
    const scenes: SceneLocation[] = hasScenes ? event.scene_locations! : [{
      label: event.location_label, role: "unknown", location_precision: event.location_precision,
      geocode_method: event.geocode_method ?? "", primary_for_count: false,
      coordinates: event.coordinates, geometry: event.reported_location_geometry,
      candidate_road_geometry: event.candidate_road_geometry,
    }];
    scenes.forEach((scene, index) => {
      if (precise(scene)) return;
      const key = `${event.id}/${index}`;
      if (seen.has(key)) return;
      seen.add(key);
      const referenceAvailable = scene.geometry_review?.verdict !== "unresolved" &&
        scene.geometry_review?.verdict !== "needs_correction" &&
        !!(scene.geometry || scene.candidate_road_geometry) &&
        (scene.geometry?.type !== "Point" || !!scene.geometry_usage);
      rows.push({key, sourceId: event.id, title: event.title, sourceURL: sourceURL(event.source_url),
        category: event.category, kind: kind(scene), label: scene.label ?? "", role: scene.role,
        eventTime: scene.event_time ?? null,
        summaryEventDate: !hasScenes && typeof event.event_date === "string" && /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(event.event_date) ? event.event_date : null,
        publicationMonth: publicationMonth(event),
        referenceAvailable, status: scene.geometry_review?.verdict === "unresolved" ? "unresolved" :
          referenceAvailable ? "reference_only" : "insufficient_precision"});
    });
  }
  return rows;
}
export function uncertaintyStats(rows: readonly UncertaintyRow[]) {
  const announcements = new Set(rows.map(r => r.sourceId)).size;
  const byKind = Object.fromEntries(UNCERTAINTY_KINDS.map(k => [k,
    new Set(rows.filter(r => r.kind === k).map(r => r.sourceId)).size])) as Record<UncertaintyKind, number>;
  return {announcements, scenes: rows.length, byKind};
}
export function uncertaintyPage(rows: readonly UncertaintyRow[], filter: UncertaintyKind | "all", page: number, size = 20) {
  const selected = filter === "all" ? rows : rows.filter(r => r.kind === filter);
  const pageSize = Math.max(1, Math.min(50, Math.floor(size) || 20));
  const pages = Math.max(1, Math.ceil(selected.length / pageSize));
  const current = Math.max(0, Math.min(pages - 1, Math.floor(page) || 0));
  return {items: selected.slice(current * pageSize, (current + 1) * pageSize), page: current, pages, total: selected.length};
}
