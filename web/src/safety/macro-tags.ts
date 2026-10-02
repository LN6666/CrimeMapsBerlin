import {CONTENT_TAG_CITIES, type ContentRecord, type TagVerdict, type ContentTagCounts} from "./content-tags";

export const MACRO_TAG_VERSION="macro-social-tags-v1";
export const MACRO_TAGS=["community_safety","hate_discrimination","political_motivation","extremism_terrorism",
  "domestic_partner_violence","gender_based_violence","organized_crime","trafficking_exploitation"] as const;
export const HATE_FACETS=["anti_lgbt","racism","xenophobia","religious_bias"] as const;
export const ALL_MACRO_TAGS=[...MACRO_TAGS,...HATE_FACETS] as const;
export type MacroTag=typeof ALL_MACRO_TAGS[number];
export type MacroBasis="police_category_stated"|"narrative_lead";
export interface MacroDecision {
  tag:MacroTag; verdict:TagVerdict; evidence_quotes:readonly string[]; basis?:MacroBasis;
}
export interface MacroAssessment extends ContentRecord {
  version:typeof MACRO_TAG_VERSION;content_sha256:string|null;
  text_scope:"full_official_text"|"accepted_upstream_summary"|"unavailable";
  reviewer:string|null;evidence_checked:boolean;decisions:readonly MacroDecision[];
}
export interface MacroCount {
  tag:MacroTag;counts:ContentTagCounts;police_category_stated:number;narrative_lead:number;
}
export interface MacroSummary {
  version:typeof MACRO_TAG_VERSION;key:string;records:number;fully_evaluated_records:number;
  mapping_sha256:string;overlay_sha256:string;time_scope:"all_selected_months";
  text_scope:"full_official_text"|"accepted_upstream_summary"|"mixed";tags:readonly MacroCount[];
}
const sha=(value:string)=>/^[a-f0-9]{64}$/.test(value);
const identity=(row:ContentRecord)=>JSON.stringify([row.city,row.id]);
const verdicts=["supported","no_support","uncertain","not_evaluated"] as const;

/** These are social-context labels, separate from the report's ordinary offence types. */
export function macroStatistics(records:readonly ContentRecord[],reviews:readonly MacroAssessment[]) {
  const selected=new Map<string,ContentRecord>(),assessed=new Map<string,MacroAssessment>();
  for(const row of records){
    if(!CONTENT_TAG_CITIES.includes(row.city as typeof CONTENT_TAG_CITIES[number])||!row.id||
      !sha(row.source_sha256)||new URL(row.source_url).protocol!=="https:")throw Error("Invalid macro source identity");
    if(selected.has(identity(row)))throw Error("Duplicate selected identity");selected.set(identity(row),row);
  }
  for(const row of reviews){
    const source=selected.get(identity(row));
    if(!source||source.source_url!==row.source_url||source.source_sha256!==row.source_sha256||
      row.version!==MACRO_TAG_VERSION||assessed.has(identity(row))||row.decisions.length!==ALL_MACRO_TAGS.length||
      new Set(row.decisions.map(item=>item.tag)).size!==ALL_MACRO_TAGS.length||
      !["full_official_text","accepted_upstream_summary","unavailable"].includes(row.text_scope))
      throw Error("Stale, duplicate or malformed macro review");
    for(const d of row.decisions){
      if(!ALL_MACRO_TAGS.includes(d.tag)||!verdicts.includes(d.verdict))throw Error("Unknown macro decision");
      if(d.verdict!=="not_evaluated"&&(!row.reviewer?.trim()||!row.evidence_checked||!row.content_sha256||
        !sha(row.content_sha256)||row.text_scope==="unavailable"))throw Error("Checked source text required");
      if(d.verdict==="supported"&&(!d.evidence_quotes.length||d.evidence_quotes.some(q=>q.trim().length<15||q.trim().length>240)||
        !["police_category_stated","narrative_lead"].includes(d.basis??"")))throw Error("Macro support needs evidence and attribution");
      if(HATE_FACETS.includes(d.tag as typeof HATE_FACETS[number])&&d.verdict==="supported"&&
        row.decisions.find(item=>item.tag==="hate_discrimination")?.verdict!=="supported")
        throw Error("A supported hate facet requires supported parent evidence");
    }
    assessed.set(identity(row),row);
  }
  const counts=ALL_MACRO_TAGS.map(tag=>{
    const item:MacroCount={tag,counts:{supported:0,no_support:0,uncertain:0,not_evaluated:0},police_category_stated:0,narrative_lead:0};
    for(const row of selected.values()){
      const d=assessed.get(identity(row))?.decisions.find(d=>d.tag===tag);item.counts[d?.verdict??"not_evaluated"]++;
      if(d?.verdict==="supported")item[d.basis!]++;
    }
    return item;
  });
  return fromCounts(selected.size,counts);
}
export function macroStatisticsForSummary(source:MacroSummary){
  if(source.version!==MACRO_TAG_VERSION||!source.key||!Number.isSafeInteger(source.records)||source.records<0||
    !Number.isSafeInteger(source.fully_evaluated_records)||source.fully_evaluated_records<0||
    source.fully_evaluated_records>source.records||!sha(source.mapping_sha256)||!sha(source.overlay_sha256)||
    source.time_scope!=="all_selected_months"||!["full_official_text","accepted_upstream_summary","mixed"].includes(source.text_scope)||
    source.tags.length!==ALL_MACRO_TAGS.length||new Set(source.tags.map(item=>item.tag)).size!==ALL_MACRO_TAGS.length)
    throw Error("Invalid macro summary");
  for(const item of source.tags){
    if(!ALL_MACRO_TAGS.includes(item.tag)||Object.keys(item.counts).length!==4||
      verdicts.some(v=>!Number.isSafeInteger(item.counts[v])||item.counts[v]<0)||
      Object.values(item.counts).reduce((sum,n)=>sum+n,0)!==source.records||
      !Number.isSafeInteger(item.police_category_stated)||item.police_category_stated<0||
      !Number.isSafeInteger(item.narrative_lead)||item.narrative_lead<0||
      item.police_category_stated+item.narrative_lead!==item.counts.supported||
      (MACRO_TAGS.includes(item.tag as typeof MACRO_TAGS[number])&&
        source.fully_evaluated_records>source.records-item.counts.not_evaluated))throw Error("Invalid macro counts or attribution");
  }
  const hate=source.tags.find(item=>item.tag==="hate_discrimination")!;
  if(source.tags.some(item=>HATE_FACETS.includes(item.tag as typeof HATE_FACETS[number])&&item.counts.supported>hate.counts.supported))
    throw Error("Hate-facet count exceeds parent");
  return fromCounts(source.records,source.tags);
}
function fromCounts(total:number,counts:readonly MacroCount[]){
  return {version:MACRO_TAG_VERSION,records:total,tags:ALL_MACRO_TAGS.map(tag=>{
    const item=counts.find(item=>item.tag===tag)!,c=item.counts;
    return {...item,share:total?c.supported/total:null,
      evaluated:total?1-c.not_evaluated/total:null,
      content_index:total&&c.uncertain+c.not_evaluated===0?100*c.supported/total:null};
  }),crime_rate:null,city_risk_score:null};
}
/** The caller supplies one checked, count-only catalogue; no country lookup or API calls. */
export function validateMacroCatalogue(sources:readonly MacroSummary[]){
  const total=sources.find(item=>item.key==="all14"),cities=sources.filter(item=>item.key!=="all14");
  if(!total||sources.length!==15||cities.length!==14||new Set(sources.map(item=>item.key)).size!==15||
    cities.some(item=>!CONTENT_TAG_CITIES.includes(item.key as typeof CONTENT_TAG_CITIES[number])))throw Error("Expected 14 macro city scopes and total");
  for(const source of sources){macroStatisticsForSummary(source);
    if(source.mapping_sha256!==total.mapping_sha256||source.overlay_sha256!==total.overlay_sha256)throw Error("Macro version bindings differ");}
  if(cities.reduce((s,item)=>s+item.records,0)!==total.records||
    cities.reduce((s,item)=>s+item.fully_evaluated_records,0)!==total.fully_evaluated_records)throw Error("Macro city totals differ");
  for(const tag of ALL_MACRO_TAGS){
    const target=total.tags.find(item=>item.tag===tag)!;
    for(const v of verdicts)if(cities.reduce((s,item)=>s+item.tags.find(t=>t.tag===tag)!.counts[v],0)!==target.counts[v])throw Error("Macro verdict sums differ");
    for(const basis of ["police_category_stated","narrative_lead"] as const)
      if(cities.reduce((s,item)=>s+item.tags.find(t=>t.tag===tag)![basis],0)!==target[basis])throw Error("Macro attribution sums differ");
  }
}
