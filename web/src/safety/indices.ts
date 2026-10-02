/** Descriptive announcement statistics. No model calls, geocoding or risk scores. */
export const METRICS_METHOD_VERSION = "announcement-statistics-v1";
export const ALLOWED_TAGS = [
  "violent_assault", "robbery", "threat", "sexual_offence", "property_offence",
  "possible_hate_crime",
] as const;
const HATE_BASES = new Set([
  "police_motive_suspected", "reported_bias_language_or_behavior",
]);
export interface MetricAnnouncement {
  publisher_namespace?: string;
  id: string;
  source_url: string;
  category: string;
  month: string | null;
  event_date: string | null;
  reviewed_tags?: { tag: string; basis?: string; evidence_quote: string }[];
}
export interface MetricContext {
  city: string;
  publisher_namespace: string;
  data_basis: "official_announcements" | "polizeikarte_entries";
  time_basis: "publication_month" | "upstream_occurrence_month";
  generation: string;
  /** SHA-256 supplied by the current accepted artifact build, never a model. */
  artifact_sha256: string;
  scope: "loaded_months" | "full_artifact";
  category_filter?: string;
  selected_months: readonly string[];
  /** Collection time, not the date of the most recent offence. */
  data_as_of: string | null;
  coverage_note: string;
  missing_intervals: readonly { from: string; to: string; reason: string }[];
  /** IDs from the accepted map counting rule, before any category filter. */
  count_reference_ids: readonly string[];
  /** Empty/absent means full tag assessment is unknown, even when tags=[] . */
  complete_tag_assessments?: readonly { id: string; source_url: string }[];
}
export interface Fraction {
  numerator: number;
  denominator: number;
  value: number | null;
}
const fraction = (numerator: number, denominator: number): Fraction => ({
  numerator, denominator, value: denominator === 0 ? null : numerator / denominator,
});
function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) =>
    `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`
  ).join(",")}}`;
}
function requireHttps(value: string): void {
  if (new URL(value).protocol !== "https:") throw Error("Source URL must use HTTPS");
}
export function announcementStatistics(
  input: readonly MetricAnnouncement[], context: MetricContext,
) {
  if (!context.city || !context.publisher_namespace || !context.generation || !/^[a-f0-9]{64}$/.test(context.artifact_sha256))
    throw Error("Current city/generation/artifact binding is required");
  if (!context.coverage_note.trim()) throw Error("Coverage disclosure is required");
  if (!["official_announcements", "polizeikarte_entries"].includes(context.data_basis))
    throw Error("Unknown data basis");
  if ((context.city === "munich") !== (context.data_basis === "polizeikarte_entries") ||
      (context.data_basis === "official_announcements" && context.time_basis !== "publication_month") ||
      (context.data_basis === "polizeikarte_entries" && context.time_basis !== "upstream_occurrence_month"))
    throw Error("City/source/time basis does not match the accepted Munich exception");
  if (context.data_as_of !== null && !Number.isFinite(Date.parse(context.data_as_of)))
    throw Error("Invalid collection timestamp");
  const months = new Set(context.selected_months);
  if (months.size !== context.selected_months.length ||
      [...months].some((month) => !/^\d{4}-(0[1-9]|1[0-2])$/.test(month)))
    throw Error("Invalid or duplicate publication months");
  const rows = new Map<string, MetricAnnouncement>();
  const urls = new Map<string, string>();
  let duplicateRows = 0;
  for (const row of input) {
    if (!row.id || !row.source_url) throw Error("Announcement identity is required");
    requireHttps(row.source_url);
    if (row.month !== null && !/^\d{4}-(0[1-9]|1[0-2])$/.test(row.month))
      throw Error("Invalid publication month");
    if (row.month !== null && !months.has(row.month))
      throw Error("Rows outside declared publication months");
    // Native IDs are already unique in each city artifact; keep publisher identity explicit.
    const namespace = row.publisher_namespace ?? context.publisher_namespace;
    if (!namespace.trim()) throw Error("Publisher namespace is required");
    const existing = rows.get(row.id);
    if (existing) {
      if ((existing.publisher_namespace ?? context.publisher_namespace) !== namespace ||
          canonical(existing) !== canonical(row))
        throw Error(`Conflicting current announcement: ${row.id}`);
      duplicateRows += 1;
      continue;
    }
    if (context.data_basis === "official_announcements" && urls.has(row.source_url))
      throw Error("One source URL has conflicting IDs");
    rows.set(row.id, row);
    urls.set(row.source_url, row.id);
  }
  const assessed = new Set<string>();
  for (const assessment of context.complete_tag_assessments ?? []) {
    if (rows.get(assessment.id)?.source_url !== assessment.source_url || assessed.has(assessment.id))
      throw Error("Stale, duplicate or out-of-scope tag assessment");
    assessed.add(assessment.id);
  }
  const countReferences = new Set(context.count_reference_ids);
  for (const id of countReferences)
    if (!rows.has(id)) throw Error("Count reference outside loaded announcement set");
  const categories = new Map<string, number>();
  const tagCounts = new Map<string, number>(ALLOWED_TAGS.map((tag) => [tag, 0]));
  const assessedTagCounts = new Map<string, number>(ALLOWED_TAGS.map((tag) => [tag, 0]));
  let unclassified = 0, summaryDateMissing = 0, publicationMonthUnknown = 0;
  for (const row of rows.values()) {
    const category = row.category.trim();
    if (!category || category === "Unklassifiziert") unclassified += 1;
    else categories.set(category, (categories.get(category) ?? 0) + 1);
    if (!row.event_date) summaryDateMissing += 1;
    if (row.month === null) publicationMonthUnknown += 1;
    const tags = new Set<string>();
    for (const tag of row.reviewed_tags ?? []) {
      if (!tagCounts.has(tag.tag) || tags.has(tag.tag) ||
          tag.evidence_quote.trim().length < 15 || tag.evidence_quote.trim().length > 240)
        throw Error("Invalid, repeated or unsupported reviewed tag");
      if (tag.tag === "possible_hate_crime" && !HATE_BASES.has(tag.basis ?? ""))
        throw Error("Hate lead requires explicit source-backed bias evidence");
      tags.add(tag.tag);
      tagCounts.set(tag.tag, tagCounts.get(tag.tag)! + 1);
      if (assessed.has(row.id)) assessedTagCounts.set(tag.tag, assessedTagCounts.get(tag.tag)! + 1);
    }
  }
  const total = rows.size;
  return {
    method_version: METRICS_METHOD_VERSION,
    context: { ...context, selected_months: [...months].sort(),
      count_reference_ids: undefined, complete_tag_assessments: undefined },
    time_basis: context.time_basis,
    unit: context.data_basis === "official_announcements" ? "unique_announcement" : "upstream_entry",
    identity_rule: "city_publisher_namespace_native_source_id" as const,
    loaded_announcements: total,
    duplicate_rows_removed: duplicateRows,
    map_count_references: countReferences.size,
    unclassified: fraction(unclassified, total),
    summary_event_date_missing: fraction(summaryDateMissing, total),
    publication_month_unknown: fraction(publicationMonthUnknown, total),
    categories: [...categories].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
      .map(([category, count]) => ({ category, ...fraction(count, total) })),
    tag_assessment: { complete: assessed.size, unknown: total - assessed.size },
    tags: ALLOWED_TAGS.map((tag) => ({ tag,
      // Observed documented leads divided by all included announcements, not prevalence.
      observed_in_included_announcements: fraction(tagCounts.get(tag)!, total),
      // Available only for explicitly complete source-version-bound tag assessments.
      in_completely_assessed_announcements: fraction(assessedTagCounts.get(tag)!, assessed.size),
    })),
    uncertainty: "selection_and_missingness_not_population_confidence_interval" as const,
    risk_score: null,
    city_comparison_supported: false,
  };
}
export type AnnouncementStatistics = ReturnType<typeof announcementStatistics>;
