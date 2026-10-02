import { expect, test } from "@playwright/test";
import { announcementStatistics, type MetricAnnouncement, type MetricContext } from "../src/safety/indices";
const context: MetricContext = {
  city: "berlin", publisher_namespace: "berlin-official", generation: "test-current-artifact", artifact_sha256: "a".repeat(64),
  data_basis: "official_announcements", time_basis: "publication_month",
  scope: "loaded_months", selected_months: ["2026-09"], data_as_of: "2026-10-02T00:00:00Z",
  coverage_note: "Selected reviewed announcements; archive coverage incomplete.",
  missing_intervals: [], count_reference_ids: [],
};
const row = (id: string, changes: Partial<MetricAnnouncement> = {}): MetricAnnouncement => ({
  id, source_url: `https://example.org/official/${id}`, category: "Gewalt", month: "2026-09",
  event_date: null, ...changes,
});
const hate = {tag: "possible_hate_crime", basis: "reported_bias_language_or_behavior",
  evidence_quote: "Explicit source-backed bias evidence in the accepted review."};
test("announcements remain the unit across duplicates, follow-ups and map references", () => {
  const a = row("A"), followup = row("followup");
  const stats = announcementStatistics([a, a, followup], {...context, count_reference_ids: ["A", "A"]});
  expect(stats.loaded_announcements).toBe(2);
  expect(stats.duplicate_rows_removed).toBe(1);
  expect(stats.map_count_references).toBe(1);
  expect(stats.categories[0]).toMatchObject({numerator: 2, denominator: 2, value: 1});
  expect(stats.risk_score).toBeNull();
});
test("empty tags never imply completed negative assessment; zero denominator is null", () => {
  const stats = announcementStatistics([row("A", {reviewed_tags: [hate]}), row("B", {reviewed_tags: []})], context);
  expect(stats.tag_assessment).toEqual({complete: 0, unknown: 2});
  const lead = stats.tags.find(t => t.tag === hate.tag)!;
  expect(lead.observed_in_included_announcements).toEqual({numerator: 1, denominator: 2, value: 0.5});
  expect(lead.in_completely_assessed_announcements.value).toBeNull();
  expect(announcementStatistics([], context).unclassified.value).toBeNull();
});
test("denominators retain unclassified and unknown dates without invented certainty", () => {
  const stats = announcementStatistics([row("A", {reviewed_tags: [hate]}), row("B", {category: "Unklassifiziert", month: null})],
    {...context, complete_tag_assessments: [{id: "A", source_url: row("A").source_url}]});
  expect(stats.categories[0].denominator).toBe(2);
  expect(stats.unclassified.numerator).toBe(1);
  expect(stats.summary_event_date_missing.numerator).toBe(2);
  expect(stats.publication_month_unknown.numerator).toBe(1);
  expect(stats.tag_assessment).toEqual({complete: 1, unknown: 1});
  expect(stats.tags.at(-1)!.in_completely_assessed_announcements).toEqual({numerator: 1, denominator: 1, value: 1});
});
test("identity, motive and current binding errors fail closed", () => {
  expect(() => announcementStatistics([row("A"), row("A", {category: "Raub"})], context)).toThrow(/Conflicting/);
  expect(() => announcementStatistics([row("A"), row("B", {source_url: row("A").source_url})], context)).toThrow(/conflicting IDs/);
  expect(() => announcementStatistics([row("A", {reviewed_tags: [{...hate, basis: "nationality"}]})], context)).toThrow(/bias/);
  expect(() => announcementStatistics([row("A")], {...context, artifact_sha256: ""})).toThrow(/binding/);
  expect(() => announcementStatistics([row("A")], {...context, complete_tag_assessments: [{id: "A", source_url: "https://wrong.example"}]})).toThrow(/Stale/);
  expect(() => announcementStatistics([row("A")], {...context, count_reference_ids: ["unknown"]})).toThrow(/outside/);
});
test("period and valid source links are explicit, input is not mutated, order is deterministic", () => {
  const records = [row("B", {category: "Raub"}), row("A")];
  const before = JSON.stringify(records);
  expect(announcementStatistics(records, context)).toEqual(announcementStatistics([...records].reverse(), context));
  expect(JSON.stringify(records)).toBe(before);
  expect(() => announcementStatistics([row("A", {month: "2026-08"})], context)).toThrow(/outside/);
  expect(() => announcementStatistics([row("A", {source_url: "javascript:alert(1)"})], context)).toThrow(/HTTPS/);
});
test("Munich keeps upstream entries and their occurrence-month basis separate", () => {
  const munich: MetricContext = {...context, city: "munich", publisher_namespace: "POLIZEIKARTE",
    data_basis: "polizeikarte_entries", time_basis: "upstream_occurrence_month"};
  const stats = announcementStatistics([row("1"), row("2", {source_url: row("1").source_url})], munich);
  expect(stats.loaded_announcements).toBe(2);
  expect(stats.unit).toBe("upstream_entry");
  expect(stats.time_basis).toBe("upstream_occurrence_month");
  expect(() => announcementStatistics([], {...context, city: "munich"})).toThrow(/exception/);
});
