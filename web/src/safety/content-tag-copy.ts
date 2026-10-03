import reviewedGerman from './statistics-locales/content-tags.de.json';
import reviewedChinese from './statistics-locales/content-tags.zh.json';
import reviewedEnglish from './statistics-locales/content-tags.en.json';
import type {ContentTag} from "./content-tags";
export interface ContentTagCopy {
  title: string; caption: string; scope: string; total: string;
  label: string; supported: string; share: string; coverage: string;
  uncertain: string; pending: string; noSupport: string; index: string; unknown: string;
  formula: string; incomplete: string; overlap: string; basis: string;
  hate: string; summaryScope: string; unavailable: string;
  composite: string; compositeFormula: string;
  launcher: string; askMe: string; open: string; close: string; dragHint: string;
  preview: string; previewPending: string; scopeChoice: string; timeScope: string; mixedScope: string; methodInfo: string;
  savedStatistics: string; answerUnavailable: string;
  staticReport: string;
  tags: Record<ContentTag, string>;
}
export const CONTENT_TAG_COPY: Record<"en" | "de" | "zh", ContentTagCopy> = {
  en: reviewedEnglish,
  de: reviewedGerman,
  zh: reviewedChinese,
};
