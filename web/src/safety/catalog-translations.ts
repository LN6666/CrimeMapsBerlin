import en from './locales/catalog.en.json' with {type:'json'};
import de from './locales/catalog.de.json' with {type:'json'};
import zh from './locales/catalog.zh.json' with {type:'json'};
import {locale} from './i18n';
import {textHash} from './dynamic-translations';
import type {Properties} from './model';
const packs:Record<string,Record<string,Record<string,string>>>={en,de,zh:Object.fromEntries(zh.sources.map(s=>[s.source_id,{source_url:s.source_url,source_summary_sha256:s.source_summary_sha256,summary_zh:s.zh_summary}]))};
const checked=new Map<string,string>();
/** Auxiliary summaries are bound to the exact original summary and source URL. */
export async function loadCatalogTranslations(sources:Properties[]):Promise<void> {
 checked.clear();const pack=packs[locale];
 await Promise.all(sources.map(async s=>{const item=pack[s.id];if(item&&item.source_url===s.url&&item.source_summary_sha256===await textHash(s.summary)&&item[`summary_${locale}`])checked.set(s.id,item[`summary_${locale}`]);}));
}
export function catalogSummary(source:Properties):string {return checked.get(source.id)??source.summary;}
