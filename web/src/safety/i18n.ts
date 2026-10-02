import contextPolicy from '../../../config/public-context-policy.v1.json' with {type:'json'};
import en from './locales/en.json' with {type:'json'};
import de from './locales/de.json' with {type:'json'};
import zh from './locales/zh.json' with {type:'json'};
export type Locale = 'de' | 'en' | 'zh';
const dictionaries: Record<Locale, Record<string,string>> = {en,de,zh};
const requested = new URLSearchParams(typeof location === 'undefined' ? '?lang=zh' : location.search).get('lang');
export const locale: Locale = requested === 'de' || requested === 'en' || requested === 'zh' ? requested : 'de';
export const localeCode = {de:'de-DE',en:'en-GB',zh:'zh-CN'}[locale];
if(typeof document !== "undefined")document.documentElement.lang = localeCode;
export function t(key: string, params: Record<string,string|number> = {}, fallback = key): string {
  const value = dictionaries[locale][key] ?? dictionaries.en[key] ?? fallback;
  return value.replace(/\{(\w+)\}/g, (_,name:string) => String(params[name] ?? `{${name}}`));
}
export const number = (value:number) => new Intl.NumberFormat(localeCode).format(value);
export function date(value:string):string {
  const parsed=new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat(localeCode,{timeZone:'Europe/Berlin',dateStyle:'medium',timeStyle: value.includes('T') ? 'short' : undefined}).format(parsed);
}
export function html(value:string):string {
  return value.replace(/[&<>"']/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
}
export function cityName(id:string,fallback:string):string { return t(`city.${id}`,{},fallback); }
export function poiName(kind:string,fallback:string):string {return t(`poi.${kind === "source_linked_context" ? "context" : kind}`,{},t("poi.unknown",{},fallback));}
export function languageURL(destination:string):string {
  const url=new URL(destination,location.href);url.searchParams.set('lang',locale);
  const month=document.querySelector<HTMLSelectElement>('#month')?.value;
  const year=document.querySelector<HTMLSelectElement>('#year')?.value;
  if(month&&year)url.searchParams.set('month',`${year}-${month}`);
  return url.href;
}

export function sourceContextName(kind:string):string {const allowed=(contextPolicy.allowlist as Record<string,{label_key:string}>)[kind];return t(allowed?.label_key??"sourceContext.generic",{},t("sourceContext.generic"));}
