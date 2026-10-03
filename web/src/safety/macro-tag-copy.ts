import reviewedGerman from './statistics-locales/macro-tags.de.json';
import reviewedChinese from './statistics-locales/macro-tags.zh.json';
import reviewedEnglish from './statistics-locales/macro-tags.en.json';
import type {MacroTag} from "./macro-tags";
export interface MacroCopy {
 title:string;caption:string;facetTitle:string;label:string;count:string;share:string;
 police:string;lead:string;coverage:string;uncertain:string;pending:string;noSupport:string;index:string;
 unavailable:string;unknown:string;methods:string;basis:string;formula:string;overlap:string;incomplete:string;
 tags:Record<MacroTag,string>;
}
export const MACRO_COPY:Record<"en"|"de"|"zh",MacroCopy>={
 en:reviewedEnglish,
 de:reviewedGerman,
 zh:reviewedChinese,
};
