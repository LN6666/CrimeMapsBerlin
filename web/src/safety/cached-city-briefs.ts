import reviewedGerman from './statistics-locales/city-briefs.de.json';
import reviewedChinese from './statistics-locales/city-briefs.zh.json';
import reviewedEnglish from './statistics-locales/city-briefs.en.json';
import {CONTENT_TAG_CITIES} from './content-tags';
import {ALL_MACRO_TAGS, MACRO_TAGS, type MacroCount} from './macro-tags';
export const BRIEF_PERIODS=['ytd2026','last7','last30','last90'] as const;
export type BriefPeriod=typeof BRIEF_PERIODS[number];
export interface BriefWindow {period:BriefPeriod;start:string;end:string;records:number;
 fully_evaluated_records:number;records_with_any_evaluation:number;tags:readonly MacroCount[]}
export interface WindowCatalogue {version:'macro-window-summary-v1';mapping_sha256:string;overlay_sha256:string;
 publication_dates_sha256:string;as_of:string;timezone:'Europe/Berlin';date_basis:'police_announcement_publication';
 inclusive_calendar_days:true;unknown_dates_excluded:true;scopes:readonly {key:string;total_selected_records:number;
 unknown_publication_dates:number;windows:readonly BriefWindow[]}[]}
export interface CachedBrief {period:BriefPeriod;status:'awaiting_labels'|'generated_preview'|'generated';
 zh:string;en:string;de:string;referenced_tags:readonly string[]}
export interface BriefCatalogue {version:'cached-city-briefs-v1';model:'gemini-3.5-flash-lite';input_sha256:string;
 mapping_sha256:string;overlay_sha256:string;publication_dates_sha256:string;as_of:string;generated_at:string;
 visitor_model_calls:0;scopes:readonly {key:string;briefs:readonly CachedBrief[]}[]}
const count=(n:number)=>Number.isSafeInteger(n)&&n>=0;
const hash=(s:string)=>/^[a-f0-9]{64}$/.test(s);
export function validateBriefCatalogues(w:WindowCatalogue,b:BriefCatalogue){
 if(w.version!=='macro-window-summary-v1'||b.version!=='cached-city-briefs-v1'||b.model!=='gemini-3.5-flash-lite'||
  w.timezone!=='Europe/Berlin'||w.date_basis!=='police_announcement_publication'||!w.inclusive_calendar_days||
  !w.unknown_dates_excluded||!/^2026-\d{2}-\d{2}$/.test(w.as_of)||b.as_of!==w.as_of||b.visitor_model_calls!==0||
  !hash(b.input_sha256)||!Number.isFinite(Date.parse(b.generated_at)))throw Error('Invalid cached brief metadata');
 for(const field of ['mapping_sha256','overlay_sha256','publication_dates_sha256'] as const)
  if(!hash(w[field])||b[field]!==w[field])throw Error('Brief and window source versions differ');
 const expected=['all14',...CONTENT_TAG_CITIES];
 for(const keys of [w.scopes.map(s=>s.key),b.scopes.map(s=>s.key)])
  if(keys.length!==15||new Set(keys).size!==15||keys.some(k=>!expected.includes(k)))throw Error('Expected fifteen brief scopes');
 for(const scope of w.scopes){
  if(!count(scope.total_selected_records)||!count(scope.unknown_publication_dates)||
   scope.unknown_publication_dates>scope.total_selected_records||scope.windows.length!==4||
   new Set(scope.windows.map(i=>i.period)).size!==4)throw Error('Invalid dated scope');
  const briefs=b.scopes.find(s=>s.key===scope.key)!.briefs;
  if(briefs.length!==4||new Set(briefs.map(i=>i.period)).size!==4)throw Error('Four distinct brief periods required');
  for(const window of scope.windows){
   const offset={last7:6,last30:29,last90:89},start=window.period==='ytd2026'?'2026-01-01':
    new Date(Date.parse(w.as_of+'T12:00:00Z')-offset[window.period]*86400000).toISOString().slice(0,10);
   if(!BRIEF_PERIODS.includes(window.period)||window.start!==start||window.end!==w.as_of||
    !count(window.records)||window.records>scope.total_selected_records-scope.unknown_publication_dates||
    !count(window.fully_evaluated_records)||!count(window.records_with_any_evaluation)||
    window.fully_evaluated_records>window.records_with_any_evaluation||window.records_with_any_evaluation>window.records||
    window.tags.length!==12||new Set(window.tags.map(t=>t.tag)).size!==12)throw Error('Invalid dated window');
   for(const item of window.tags){
    if(!ALL_MACRO_TAGS.includes(item.tag)||Object.keys(item.counts).length!==4||
     ['supported','no_support','uncertain','not_evaluated'].some(v=>!count(item.counts[v as keyof typeof item.counts]))||
     Object.values(item.counts).reduce((s,n)=>s+n,0)!==window.records||!count(item.police_category_stated)||!count(item.narrative_lead)||
     item.police_category_stated+item.narrative_lead!==item.counts.supported||
     (MACRO_TAGS.includes(item.tag as typeof MACRO_TAGS[number])&&window.fully_evaluated_records>window.records-item.counts.not_evaluated))
      throw Error('Invalid window tag counts');
   }
   const brief=briefs.find(i=>i.period===window.period);
   if(!brief||!['awaiting_labels','generated_preview','generated'].includes(brief.status)||
    (brief.status==='generated'&&window.fully_evaluated_records!==window.records)||
    (brief.status==='generated_preview'&&!window.records_with_any_evaluation)||
    new Set(brief.referenced_tags).size!==brief.referenced_tags.length||brief.referenced_tags.some(tag=>
      !MACRO_TAGS.includes(tag as typeof MACRO_TAGS[number])||!window.tags.find(t=>t.tag===tag)?.counts.supported)||
    ['zh','en','de'].some(l=>typeof brief[l as 'zh'|'en'|'de']!=='string'||brief[l as 'zh'|'en'|'de'].trim().length<8||
      brief[l as 'zh'|'en'|'de'].length>400||/[<>\r\n]/.test(brief[l as 'zh'|'en'|'de'])))throw Error('Invalid cached brief');
  }
 }
 const all=w.scopes.find(s=>s.key==='all14')!,cities=w.scopes.filter(s=>s.key!=='all14');
 for(const field of ['total_selected_records','unknown_publication_dates'] as const)
  if(cities.reduce((sum,s)=>sum+s[field],0)!==all[field])throw Error('Dated city denominators do not sum');
 for(const period of BRIEF_PERIODS){const total=all.windows.find(i=>i.period===period)!;
  for(const field of ['records','fully_evaluated_records','records_with_any_evaluation'] as const)
   if(cities.reduce((sum,s)=>sum+s.windows.find(i=>i.period===period)![field],0)!==total[field])throw Error('Window city counts do not sum');
  for(const t of total.tags){
   for(const verdict of ['supported','no_support','uncertain','not_evaluated'] as const)
    if(cities.reduce((sum,s)=>sum+s.windows.find(i=>i.period===period)!.tags.find(i=>i.tag===t.tag)!.counts[verdict],0)!==t.counts[verdict])throw Error('Window tag sums differ');
   for(const basis of ['police_category_stated','narrative_lead'] as const)
    if(cities.reduce((sum,s)=>sum+s.windows.find(i=>i.period===period)!.tags.find(i=>i.tag===t.tag)![basis],0)!==t[basis])throw Error('Window attribution sums differ');
  }
 }
}
export const BRIEF_COPY={
 zh:reviewedChinese,
 en:reviewedEnglish,
 de:reviewedGerman
} as const;
export function mountCachedBriefs(parent:HTMLElement,locale:'zh'|'en'|'de'){
 const c=BRIEF_COPY[locale],root=document.createElement('section'),title=document.createElement('h3'),label=document.createElement('label');
 root.className='content-tag-city-brief';title.textContent=c.title;label.textContent=c.period;
 const select=document.createElement('select');select.setAttribute('aria-label',c.period);
 BRIEF_PERIODS.forEach((p,i)=>{const o=document.createElement('option');o.value=p;o.textContent=c.periods[i];select.append(o);});select.value='ytd2026';label.append(select);
 const prose=document.createElement('p'),date=document.createElement('p'),coverage=document.createElement('p'),unknown=document.createElement('p'),status=document.createElement('small');
 prose.className='content-tag-brief-prose';root.append(title,label,prose,date,coverage,unknown,status);root.hidden=true;parent.append(root);
 let windows:WindowCatalogue|null=null,briefs:BriefCatalogue|null=null,key='all14';
 const update=()=>{
  const scope=windows?.scopes.find(s=>s.key===key),w=scope?.windows.find(w=>w.period===select.value),b=briefs?.scopes.find(s=>s.key===key)?.briefs.find(b=>b.period===select.value);
  root.hidden=!w||!b;if(!w||!b||!scope)return;
  prose.textContent=b[locale];date.textContent=`${w.start} — ${w.end} · ${c.date}`;
  const n=new Intl.NumberFormat(locale);coverage.textContent=c.counts.replace('{records}',n.format(w.records)).replace('{evaluated}',n.format(w.fully_evaluated_records));
  unknown.hidden=!scope.unknown_publication_dates;unknown.textContent=c.unknown.replace('{unknown}',n.format(scope.unknown_publication_dates));
  status.textContent=(b.status==='awaiting_labels'?c.pending:c.model)+(b.status==='generated_preview'?` · ${c.preview}`:'')+` · ${c.saved}`;
 };
 select.addEventListener('change',update);
 return {setCatalogues(w:WindowCatalogue,b:BriefCatalogue){windows=null;briefs=null;root.hidden=true;validateBriefCatalogues(w,b);windows=w;briefs=b;update();},
  setScope(value:string){key=value;update();},invalidate(){windows=null;briefs=null;root.hidden=true;},destroy(){root.remove();}};
}
