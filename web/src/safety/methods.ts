import {
  announcementStatistics, type MetricAnnouncement, type MetricContext, type Fraction,
} from "./indices";

export type Translate = (key: string, params?: Record<string, string | number>, fallback?: string) => string;
export interface MethodOptions {
  t: Translate;
  locale: "de" | "en" | "zh";
  categoryLabel?: (category: string) => string;
}
export interface MethodUpdate {
  month: string;
  city: string;
  category?: string;
  category_label?: string;
  /** Pass the manifest generation, so stale method metadata cannot be used. */
  generation?: string;
  metadata: Record<string, unknown>;
  countReferenceIds?: readonly string[];
}
export interface MethodMetadata extends Omit<MetricContext,
  "city" | "selected_months" | "scope" | "count_reference_ids" | "category_filter"> {
  schema_version: 1;
  city: string;
}

/** Native details/table elements; no network request and no innerHTML. */
export function mountAnnouncementMethods(parent: HTMLElement, options: MethodOptions) {
  const container = document.createElement("section"), introduction = document.createElement("div");
  container.className = "announcement-methods";
  const root = document.createElement("details");
  const summary = document.createElement("summary"), body = document.createElement("div");
  root.append(summary, body);
  container.append(introduction, root);
  parent.append(container);
  const {t} = options;
  const line = (key: string, params?: Record<string, string | number>) => {
    const element = document.createElement("p");
    element.textContent = t(key, params);
    body.append(element);
  };
  const format = (f: Fraction) => f.value === null ? t("methods.unknown") :
    t("methods.fraction", {n: f.numerator, total: f.denominator,
      percent: new Intl.NumberFormat(options.locale, {style: "percent", maximumFractionDigits: 1}).format(f.value)});
  const table = (caption: string, items: {label: string; fraction: Fraction}[]) => {
    const element = document.createElement("table"), heading = document.createElement("caption");
    heading.textContent = t(caption);
    element.append(heading);
    for (const item of items) {
      const row = document.createElement("tr"), label = document.createElement("th"), value = document.createElement("td");
      label.scope = "row";
      label.textContent = item.label;
      value.textContent = format(item.fraction);
      row.append(label, value);
      element.append(row);
    }
    body.append(element);
  };
  return {
    element: container,
    update(rows: readonly MetricAnnouncement[], current: MethodUpdate) {
      introduction.replaceChildren();
      for (const key of ["project.initial", "project.contribute"]) {
        const paragraph = document.createElement("p");
        paragraph.textContent = t(key);
        introduction.append(paragraph);
      }
      const contributionUrl = current.metadata.project_contribution_url;
      if (typeof contributionUrl === "string") {
        try {
          const url = new URL(contributionUrl);
          if (url.protocol === "https:" && url.hostname === "github.com" && !url.username && !url.password) {
            const link = document.createElement("a");
            link.href = url.href;
            link.textContent = t("project.guide");
            link.rel = "noopener noreferrer";
            introduction.append(link);
          }
        } catch { /* Missing/invalid contribution links are not advertised as available. */ }
      }
      const privacy = document.createElement("p");
      const privacyFallback = {
        en: "Issues and pull requests are public. Leave personal or sensitive information out; use the private feedback option when it is available.",
        de: "Issues und Pull Requests sind öffentlich. Bitte keine persönlichen oder vertraulichen Angaben veröffentlichen. Nutze für solche Anliegen die private Rückmeldung, falls sie angeboten wird.",
        zh: "项目讨论和代码贡献是公开的，请勿提交个人信息或敏感资料。如页面提供私密反馈入口，请在那里反映敏感问题。",
      }[options.locale];
      privacy.textContent = t("project.contributionPrivacy", {}, privacyFallback);
      introduction.append(privacy);
      body.replaceChildren();
      summary.textContent = t("methods.title");
      line("methods.independent");
      const munich = current.city === "munich";
      line(munich ? "methods.munichSource" : "methods.officialSource");
      line("methods.selection");
      line("methods.geometry");
      line("methods.tools");
      line(munich ? "methods.munichValidation" : "methods.validation");
      line("methods.hate");
      line("methods.translation");
      line("methods.updates");
      line("methods.noComparison");
      const metadata = current.metadata.announcement_statistics as MethodMetadata | undefined;
      if (!metadata || metadata.schema_version !== 1 || metadata.city !== current.city ||
          !current.generation || metadata.generation !== current.generation ||
          current.countReferenceIds === undefined) {
        line("methods.statisticsUnavailable");
        return;
      }
      try {
        const wantedIds = new Set(rows.map(row => row.id));
        const stats = announcementStatistics(rows, {...metadata,
          scope: "loaded_months", selected_months: [current.month],
          category_filter: current.category ?? "all", count_reference_ids: current.countReferenceIds,
          complete_tag_assessments: metadata.complete_tag_assessments?.filter(item => wantedIds.has(item.id)),
        });
        line(munich ? "methods.upstreamPeriod" : "methods.period", {month: current.month,
          category: current.category_label ?? t("methods.allCategories")});
        line(munich ? "methods.upstreamTotal" : "methods.total", {count: stats.loaded_announcements});
        line("methods.mapReferences", {count: stats.map_count_references});
        table("methods.categoryCaption", [
          ...stats.categories.map(item => ({label: options.categoryLabel?.(item.category) ?? item.category, fraction: item})),
          {label: t("methods.unclassified"), fraction: stats.unclassified},
        ]);
        line("methods.tagCoverage", {complete: stats.tag_assessment.complete, unknown: stats.tag_assessment.unknown});
        line("methods.tagDenominator");
        if (stats.tag_assessment.unknown > 0 &&
            stats.tags.every(item => item.observed_in_included_announcements.numerator === 0)) {
          line("methods.tagUnavailable");
        } else {
          table("methods.tagCaption", stats.tags.map(item => ({
            label: t(`tag.${item.tag}`), fraction: item.observed_in_included_announcements,
          })));
        }
        line("methods.dateUnknown", {count: stats.summary_event_date_missing.numerator});
        line("methods.dataAsOf", {date: metadata.data_as_of ?? t("methods.unknown")});
        line(metadata.missing_intervals.length ? "methods.gapsKnown" : "methods.gapsUnspecified");
        for (const gap of metadata.missing_intervals)
          line("methods.gapInterval", {from: gap.from, to: gap.to});
        // No internal hashes, enum values, reviewer notes or implementation failures in public UI.
      } catch {
        line("methods.statisticsUnavailable");
      }
    },
    destroy() { container.remove(); },
  };
}
