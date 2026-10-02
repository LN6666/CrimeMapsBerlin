import {assetPath} from "./deployment";
import {fetchDataJSON} from "./security";
import {statisticsBinding} from "./statistics-binding";
import type {ContentTagSummary} from "./content-tags";
import type {MacroSummary} from "./macro-tags";
import type {WindowCatalogue, BriefCatalogue} from "./cached-city-briefs";

/** One bounded, cancellable load per map snapshot. Period changes use the saved data. */
export async function loadSavedStatistics(city: string, generation: string, announcements: number, signal: AbortSignal) {
  const path = (name: string) => assetPath(`/statistics/${name}.json`);
  const binding = statisticsBinding(await fetchDataJSON<unknown>(path("manifest"), signal), city, generation, announcements);
  const [ordinary, macro, windows, briefs] = await Promise.all([
    fetchDataJSON<{summaries: ContentTagSummary[]}>(path("content-tag-summary"), signal),
    fetchDataJSON<{summaries: MacroSummary[]}>(path("macro-tag-summary"), signal),
    fetchDataJSON<WindowCatalogue>(path("window-summary"), signal),
    fetchDataJSON<BriefCatalogue>(path("cached-briefs"), signal),
  ]);
  if (signal.aborted) throw new DOMException("Aborted", "AbortError");
  if (!Array.isArray(ordinary.summaries) || !Array.isArray(macro.summaries) ||
      ordinary.summaries.some(item => item.mapping_sha256 !== binding.mapping_sha256) ||
      macro.summaries.some(item => item.mapping_sha256 !== binding.mapping_sha256) ||
      windows.mapping_sha256 !== binding.mapping_sha256 || briefs.mapping_sha256 !== binding.mapping_sha256 ||
      ordinary.summaries.find(item => item.key === city)?.records !== announcements ||
      macro.summaries.find(item => item.key === city)?.records !== announcements)
    throw Error("Saved statistics source/count bindings differ from the loaded map");
  return {binding, ordinary: ordinary.summaries, macro: macro.summaries, windows, briefs};
}
