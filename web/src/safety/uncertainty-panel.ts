import type { PoliceEvent } from "./model";
import { UNCERTAINTY_KINDS, uncertaintyPage, uncertaintyRows, uncertaintyStats, type UncertaintyKind, type UncertaintyRow } from "./uncertainty";
import { ufText, type UFLocale } from "./uncertainty-copy";
export function mountUncertaintyPanel(container: HTMLElement, options: {
  locale: UFLocale; city: string; translate?: (key: Parameters<typeof ufText>[1], params?: Record<string, string | number>) => string; onSelect?: (sourceId: string) => void;
  sourceUncertaintyNotice?: string;
}) {
  const t = (key: Parameters<typeof ufText>[1], params = {}) => options.translate?.(key, params) ?? ufText(options.locale, key, params);
  let rows: UncertaintyRow[] = [], page = 0;
  const section = document.createElement("section"); section.className = "uncertainty-panel"; section.id = "unknown-locations";
  const add = (tag: string, value: string, parent: HTMLElement = section) => {
    const el = document.createElement(tag); el.textContent = value; parent.append(el); return el;
  };
  const header = add("div", ""); header.className = "uncertainty-header";
  add("h3", t("unknown.title"), header); add("p", t("unknown.intro"), header);
  const stats = add("p", ""); stats.className = "uncertainty-stats"; stats.setAttribute("role", "status"); stats.setAttribute("aria-live", "polite");
  const groups = add("ul", ""); groups.className = "uncertainty-groups";
  add("p", t("unknown.counts")).className = "hint";
  const label = add("label", t("unknown.filter")); label.className = "uncertainty-filter-label";
  const filter = document.createElement("select"); filter.className = "uncertainty-filter";
  filter.append(new Option(t("unknown.all"), "all"));
  for (const k of UNCERTAINTY_KINDS) filter.append(new Option(t(`unknown.${k}`), k)); label.append(filter);
  const list = add("ol", ""); list.className = "uncertainty-list";
  const nav = add("nav", ""); nav.className = "uncertainty-pagination"; nav.setAttribute("aria-label", t("unknown.title"));
  const previous = add("button", t("unknown.previous"), nav) as HTMLButtonElement;
  const pageStatus = add("span", "", nav);
  const next = add("button", t("unknown.next"), nav) as HTMLButtonElement;
  previous.type = next.type = "button";
  function render() {
    list.replaceChildren(); const p = uncertaintyPage(rows, filter.value as UncertaintyKind | "all", page); page = p.page;
    previous.disabled = !page; next.disabled = page >= p.pages - 1;
    pageStatus.textContent = t("unknown.page", {page: page + 1, pages: p.pages});
    if (!p.items.length) add("li", t("unknown.empty"), list).className = "uncertainty-empty";
    for (const r of p.items) {
      const item = add("li", "", list); add("h4", r.title, item);
      if (r.sourceStatus === "uncertain" && options.sourceUncertaintyNotice)
        add("p", options.sourceUncertaintyNotice, item).className = "hint";
      const tags = add("div", "", item); tags.className = "uncertainty-tags";
      add("span", t(`unknown.${r.kind}`), tags); add("span", t(`unknown.role.${r.role}`), tags);
      if (r.label) add("p", r.label, item).className = "uncertainty-location";
      const metadata = add("div", "", item); metadata.className = "uncertainty-metadata";
      add("p", r.eventTime?.precision !== "unknown" && r.eventTime?.display ? t("unknown.originalTime", {time: r.eventTime.display}) : r.summaryEventDate ? t("unknown.summaryDate", {date: r.summaryEventDate}) : t("unknown.timeUnknown"), metadata);
      add("p", r.publicationMonth ? t("unknown.published", {month: r.publicationMonth}) : t("unknown.monthUnknown"), metadata);
      add("p", t(r.referenceAvailable ? "unknown.reference" : "unknown.noReference"), item).className = "uncertainty-reference";
      const actions = add("div", "", item); actions.className = "uncertainty-actions";
      if (r.sourceURL) {
        const link = add("a", t("unknown.source"), actions) as HTMLAnchorElement;
        link.href = r.sourceURL; link.target = "_blank"; link.rel = "noopener noreferrer"; link.referrerPolicy = "no-referrer";
      } else add("span", t("unknown.sourceUnavailable"), actions);
      if (options.onSelect) {
        const button = add("button", t("unknown.show"), actions) as HTMLButtonElement; button.type = "button";
        button.onclick = () => options.onSelect?.(r.sourceId);
      }
    }
  }
  filter.onchange = () => {page = 0; render();};
  previous.onclick = () => {page--; render();}; next.onclick = () => {page++; render();};
  container.append(section);
  return {
    update(events: readonly PoliceEvent[]) {
      rows = uncertaintyRows(events); page = 0;
      const s = uncertaintyStats(rows); stats.textContent = t("unknown.stats", s); groups.replaceChildren();
      for (const k of UNCERTAINTY_KINDS) {
        const group = add("li", "", groups);
        add("span", t(`unknown.${k}`), group); add("strong", String(s.byKind[k]), group);
      }
      render();
    },
    destroy() {section.remove(); rows = [];},
  };
}
