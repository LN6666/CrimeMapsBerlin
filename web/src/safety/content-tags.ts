/** Content-label statistics. Coordinates are deliberately not an input. */
export const CONTENT_TAG_VERSION = "content-tags-v2";
export const CONTENT_TAG_CITIES = ["berlin", "bremen", "cologne", "dortmund", "dresden", "dusseldorf", "essen",
  "frankfurt", "hamburg", "hannover", "leipzig", "munich", "nuremberg", "stuttgart"] as const;
export const LEGACY_CONTENT_TAGS = [
  "violent_assault", "robbery", "threat", "sexual_offence", "property_offence",
  "possible_hate_crime",
] as const;
export const CONTENT_TAGS = [
  ...LEGACY_CONTENT_TAGS, "homicide", "theft", "burglary", "fraud", "arson",
  "drug_offence", "weapons_offence", "traffic_offence", "insult_or_incitement",
  "political_context_offence", "prohibited_symbol_or_organization_offence",
  "coercion_or_unlawful_detention", "public_order_offence", "animal_welfare_offence",
] as const;
export type ContentTag = typeof CONTENT_TAGS[number];
export type TagVerdict = "supported" | "no_support" | "uncertain" | "not_evaluated";
export type ContentTagCounts = Record<TagVerdict, number>;
/** Small count-only artifact derived from a checked overlay; no raw narrative or review notes. */
export interface ContentTagSummary {
  version: typeof CONTENT_TAG_VERSION;
  key: string; records: number; fully_evaluated_records: number;
  mapping_sha256: string; overlay_sha256: string;
  time_scope: "all_selected_months";
  text_scope: "full_official_text" | "accepted_upstream_summary" | "mixed";
  tags: readonly {tag: ContentTag; counts: ContentTagCounts}[];
}
export interface ContentRecord {
  city: string;
  id: string;
  source_url: string;
  source_sha256: string;
}
export interface TagDecision {
  tag: ContentTag;
  verdict: TagVerdict;
  evidence_quotes: readonly string[];
  basis?: "source_backed_offence" | "police_motive_suspected" | "reported_bias_language_or_behavior";
  /** Private export provenance; not rendered in the public panel. */
  review_provenance?: {
    batch: string; batch_sha256: string; annotation_input_sha256: string;
    version: "content-tags-v1" | "content-tags-v2"; reviewer: string;
  };
}
export interface ContentAssessment extends ContentRecord {
  version: typeof CONTENT_TAG_VERSION;
  /** Transport generations may change without changing the source version. */
  content_sha256: string | null;
  text_scope: "full_official_text" | "accepted_upstream_summary" | "unavailable";
  reviewer: string | null;
  /** Supplied by the validated source-bound annotation export, never inferred from empty tags. */
  evidence_checked: boolean;
  decisions: readonly TagDecision[];
}
export interface LegacyContentAssessment extends Omit<ContentAssessment, "version"> {
  version: "content-tags-v1";
}
/** Reuse the six actual v1 decisions; added types remain explicitly unreviewed. */
export function upgradeLegacyAssessment(review: LegacyContentAssessment): ContentAssessment {
  if (review.version !== "content-tags-v1" || review.decisions.length !== LEGACY_CONTENT_TAGS.length ||
      new Set(review.decisions.map(item => item.tag)).size !== LEGACY_CONTENT_TAGS.length ||
      review.decisions.some(item => !LEGACY_CONTENT_TAGS.includes(item.tag as typeof LEGACY_CONTENT_TAGS[number])))
    throw Error("Invalid legacy tag scope");
  return {...review, version: CONTENT_TAG_VERSION, decisions: CONTENT_TAGS.map(tag =>
    review.decisions.find(item => item.tag === tag) ?? {tag, verdict: "not_evaluated", evidence_quotes: []})};
}
/** Add only missing judgments for the exact same source text. Existing judgments are immutable. */
export function mergeContentAssessments(
  previous: ContentAssessment, supplement: ContentAssessment,
): ContentAssessment {
  if (previous.city !== supplement.city || previous.id !== supplement.id ||
      previous.source_url !== supplement.source_url || previous.source_sha256 !== supplement.source_sha256 ||
      previous.content_sha256 !== supplement.content_sha256 || previous.text_scope !== supplement.text_scope)
    throw Error("Supplement belongs to a different source text");
  contentTagStatistics([previous], [previous]);
  contentTagStatistics([previous], [supplement]);
  const decisions = CONTENT_TAGS.map(tag => {
    const old = previous.decisions.find(item => item.tag === tag)!;
    const added = supplement.decisions.find(item => item.tag === tag)!;
    if (old.verdict !== "not_evaluated" && added.verdict !== "not_evaluated")
      throw Error("Supplement would overwrite an evaluated judgment");
    return added.verdict === "not_evaluated" ? old : added;
  });
  return {...previous, reviewer: "Source-bound Codex supplements; see per-tag provenance", decisions};
}
const sha = (value: string) => /^[a-f0-9]{64}$/.test(value);
const key = (record: ContentRecord) => JSON.stringify([record.city, record.id]);
const ratio = (numerator: number, denominator: number) => ({
  numerator, denominator, value: denominator ? numerator / denominator : null,
});
const score = (numerator: number, denominator: number) =>
  denominator ? 100 * numerator / denominator : null;

export function contentTagStatistics(
  records: readonly ContentRecord[], assessments: readonly ContentAssessment[],
  weights?: Readonly<Partial<Record<ContentTag, number>>>,
) {
  const identities = new Map<string, ContentRecord>();
  for (const record of records) {
    if (!record.city || !record.id || !sha(record.source_sha256) ||
        new URL(record.source_url).protocol !== "https:") throw Error("Invalid source identity");
    const existing = identities.get(key(record));
    if (existing && (existing.source_sha256 !== record.source_sha256 ||
        existing.source_url !== record.source_url)) throw Error("Conflicting source version");
    identities.set(key(record), record);
  }
  const reviews = new Map<string, ContentAssessment>();
  for (const review of assessments) {
    const record = identities.get(key(review));
    if (!record || record.source_sha256 !== review.source_sha256 ||
        record.source_url !== review.source_url || reviews.has(key(review)) ||
        review.version !== CONTENT_TAG_VERSION) throw Error("Stale, duplicate or foreign assessment");
    if (!["full_official_text", "accepted_upstream_summary", "unavailable"].includes(review.text_scope))
      throw Error("Unknown text scope");
    const seen = new Set<ContentTag>();
    for (const decision of review.decisions) {
      if (!CONTENT_TAGS.includes(decision.tag) || seen.has(decision.tag) ||
          !["supported", "no_support", "uncertain", "not_evaluated"].includes(decision.verdict))
        throw Error("Invalid tag decision");
      seen.add(decision.tag);
      if (decision.verdict !== "not_evaluated" && (!review.reviewer?.trim() ||
          !review.content_sha256 || !sha(review.content_sha256) || !review.evidence_checked ||
          review.text_scope === "unavailable")) throw Error("Source-bound review required");
      if (decision.verdict === "supported") {
        if (!decision.evidence_quotes.length || decision.evidence_quotes.some(q => q.trim().length < 15 || q.trim().length > 240))
          throw Error("Supported tag needs checked literal evidence");
        if (decision.tag === "possible_hate_crime") {
          if (!["police_motive_suspected", "reported_bias_language_or_behavior"].includes(decision.basis ?? ""))
            throw Error("Explicit source-backed bias evidence required");
        } else if (decision.basis !== "source_backed_offence") throw Error("Offence evidence basis required");
      }
    }
    if (seen.size !== CONTENT_TAGS.length) throw Error("All tag states must be explicit");
    reviews.set(key(review), review);
  }
  const total = identities.size;
  const countsByTag = CONTENT_TAGS.map(tag => {
    const counts = {supported: 0, no_support: 0, uncertain: 0, not_evaluated: 0};
    for (const record of identities.values()) {
      const verdict = reviews.get(key(record))?.decisions.find(d => d.tag === tag)?.verdict ?? "not_evaluated";
      counts[verdict]++;
    }
    return {tag, counts};
  });
  return statisticsFromCounts(total, countsByTag, weights);
}

/** Recompute percentages deterministically from verified exported counts. */
export function contentTagStatisticsForSummary(
  summary: ContentTagSummary, weights?: Readonly<Partial<Record<ContentTag, number>>>,
) {
  if (summary.version !== CONTENT_TAG_VERSION || !summary.key ||
      !Number.isSafeInteger(summary.records) || summary.records < 0 ||
      !Number.isSafeInteger(summary.fully_evaluated_records) || summary.fully_evaluated_records < 0 ||
      summary.fully_evaluated_records > summary.records ||
      !sha(summary.mapping_sha256) || !sha(summary.overlay_sha256) ||
      summary.time_scope !== "all_selected_months" ||
      !["full_official_text", "accepted_upstream_summary", "mixed"].includes(summary.text_scope) ||
      summary.tags.length !== CONTENT_TAGS.length ||
      new Set(summary.tags.map(item => item.tag)).size !== CONTENT_TAGS.length)
    throw Error("Invalid count-summary contract");
  for (const item of summary.tags) {
    if (!CONTENT_TAGS.includes(item.tag) || Object.keys(item.counts).length !== 4 ||
        ["supported", "no_support", "uncertain", "not_evaluated"].some(verdict => {
          const count=item.counts[verdict as TagVerdict];
          return !Number.isSafeInteger(count) || count < 0;
        }) || Object.values(item.counts).reduce((a,b)=>a+b,0) !== summary.records ||
        summary.fully_evaluated_records > summary.records-item.counts.not_evaluated)
      throw Error("Invalid exported tag counts");
  }
  return statisticsFromCounts(summary.records, summary.tags, weights);
}

function statisticsFromCounts(
  total: number, countsByTag: readonly {tag: ContentTag; counts: ContentTagCounts}[],
  weights?: Readonly<Partial<Record<ContentTag, number>>>,
) {
  const tags = CONTENT_TAGS.map(tag => {
    const counts=countsByTag.find(item=>item.tag===tag)!.counts;
    const resolved = counts.supported + counts.no_support;
    const evaluated = resolved + counts.uncertain;
    return {
      tag, counts,
      evaluation_coverage: ratio(evaluated, total),
      documented_share: ratio(counts.supported, total),
      share_in_resolved_records: ratio(counts.supported, resolved),
      /** Public content-label index: supported announcements divided by all selected announcements. */
      documented_share_points: score(counts.supported, total),
      /** Uncertain and not-evaluated states stay visible in counts; neither removes a record from the denominator. */
      content_index: score(counts.supported, total),
      /** Arithmetic missing-label bounds, not a statistical confidence interval. */
      possible_index_range: total ? [
        score(counts.supported, total),
        score(counts.supported + counts.uncertain + counts.not_evaluated, total),
      ] : null,
    };
  });
  let composite: {value: number | null; weights: Partial<Record<ContentTag, number>>; formula: string} | null = null;
  if (weights !== undefined) {
    let weightSum = 0, weightedPoints = 0, ready = total > 0;
    const declared: Partial<Record<ContentTag, number>> = {};
    for (const [tagName, weight] of Object.entries(weights)) {
      if (!CONTENT_TAGS.includes(tagName as ContentTag) || typeof weight !== "number" ||
          !Number.isFinite(weight) || weight < 0) throw Error("Invalid declared weights");
      declared[tagName as ContentTag] = weight;
      if (!weight) continue;
      const index = tags.find(item => item.tag === tagName)!.content_index;
      weightSum += weight;
      if (index === null) ready = false;
      else weightedPoints += weight * index;
    }
    if (!weightSum) throw Error("At least one positive weight required");
    composite = {value: ready ? weightedPoints / weightSum : null, weights: declared,
      formula: "sum(weight * content_index) / sum(weight); overlapping labels remain explicit"};
  }
  return {version: CONTENT_TAG_VERSION, records: total, tags, composite,
    basis: "selected_record_content_labels", index_range: [0, 100] as const,
    crime_rate: null, city_risk_score: null,
    formula: "100 * supported_records / all_selected_records; uncertain and not_evaluated counts remain separately visible",
  };
}
