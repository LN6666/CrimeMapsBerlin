import { test } from "@playwright/test";
import assert from "node:assert/strict";
import { uncertaintyRows, uncertaintyStats, uncertaintyPage } from "../src/safety/uncertainty";
import { UF_COPY, ufText } from "../src/safety/uncertainty-copy";
import { githubFeedbackLinks, GITHUB_FEEDBACK_COPY } from "../src/safety/github-feedback";
const event=(id,scenes)=>({id,title:id,category:'Gewalt',month:'2026-09',published_at:'2026-09-30T12:00:00+02:00',event_date:'2026-09-30',coordinates:null,location_precision:'unknown',location_label:'',source_url:'https://polizei.example/'+id,scene_locations:scenes});
const scene=(p,overrides={})=>({label:p,role:'incident',location_precision:p,geocode_method:'unresolved',primary_for_count:false,geometry_review:{verdict:'unresolved'},...overrides});
test('all five location groups preserve reviewed unknowns, exact points excluded, no coordinates are returned or fabricated',()=>{
 const events=[event('A',[scene('district'),scene('street'),scene('area'),scene('place'),scene('unknown'),scene('point',{coordinates:[13,52],geometry_review:{verdict:'resolved'},actual_event_position_known:true})])];
 const before=JSON.stringify(events),rows=uncertaintyRows(events);assert.deepEqual(rows.map(x=>x.kind),['district','street','area','venue_reference','no_location']);assert.equal(JSON.stringify(events),before);
 for(const r of rows) {assert.ok(!('coordinates' in r));assert.ok(!('geometry' in r));assert.equal(r.eventTime,null);assert.equal(r.publicationMonth,'2026-09');}
 assert.equal(uncertaintyStats(rows).announcements,1);assert.equal(uncertaintyStats(rows).scenes,5);
 const legacy={...event('legacy',undefined),location_precision:'point',coordinates:[13,52]};assert.equal(uncertaintyRows([legacy]).length,0);
 const unresolved=event('unresolved',[scene('point',{coordinates:[13,52]})]);assert.equal(uncertaintyRows([unresolved]).length,1);
});
test('native lines/footprints are references, nearby POI and generated district centre never become precise locations',()=>{
 const events=[event('road',[scene('route',{geometry_usage:'source_road_reference_only',geometry_review:{verdict:'resolved'},geometry:{type:'LineString',coordinates:[[13,52],[13.1,52.1]]}})]),event('district',[scene('district',{coordinates:[13,52],geometry_review:{verdict:'resolved'}})]),event('venue',[scene('point',{coordinates:[13,52],actual_event_position_known:false,geometry_usage:'source_footprint_reference_only',geometry_review:{verdict:'resolved'}})])];
 const rows=uncertaintyRows(events);assert.equal(rows.length,3);assert.equal(rows[0].referenceAvailable,true);assert.equal(rows[1].referenceAvailable,false);assert.equal(rows[2].kind,'venue_reference');
});
test('missing source event time remains unknown even with event_date and publication month',()=>{
 const time={display:'2 September, around 18:00',date:'2026-09-02',precision:'approximate',evidence_quote:'source time'};
 const rows=uncertaintyRows([event('dated',[scene('street',{event_time:time})]),event('undated',[scene('street')])]);
 assert.deepEqual(rows[0].eventTime,time);assert.equal(rows[1].eventTime,null);assert.ok(!JSON.stringify(rows[1]).includes('2026-09-30'));
});
test('source URL scheme and scope inclusion do not promote unsafe or out-of-city records',()=>{
 const bad={...event('bad',[scene('unknown')]),source_url:'javascript:alert(1)'};const out={...event('out',[scene('unknown')]),source_scope_verdict:'out_of_city'};
 const rows=uncertaintyRows([bad,out]);assert.equal(rows.length,1);assert.equal(rows[0].sourceURL,null);
});
test('pages are bounded, month replacement clears old rows, announcement groups may overlap but totals deduplicate',()=>{
 const rows=uncertaintyRows(Array.from({length:123},(_,i)=>event(String(i),[scene('district'),scene('street')])));
 assert.equal(uncertaintyStats(rows).announcements,123);assert.equal(uncertaintyStats(rows).scenes,246);assert.equal(uncertaintyStats(rows).byKind.district,123);
 assert.equal(uncertaintyPage(rows,'district',0).items.length,20);assert.equal(uncertaintyPage(rows,'district',999).items.length,3);assert.equal(uncertaintyPage(rows,'all',0,9999).items.length,50);
 assert.deepEqual(uncertaintyRows([]),[]);
});
test('all three languages have identical keys and parameters with plain-reader unknown/service limits',()=>{
 const keys=Object.keys(UF_COPY.en).sort();
 for(const language of ['en','de','zh']) {
  assert.deepEqual(Object.keys(UF_COPY[language]).sort(),keys);
  for(const key of keys)assert.deepEqual(UF_COPY[language][key].match(/\{\w+\}/g)??[],UF_COPY.en[key].match(/\{\w+\}/g)??[]);
  assert.ok(ufText(language,'unknown.stats',{announcements:2,scenes:5}).includes('2'));assert.ok(GITHUB_FEEDBACK_COPY[language]['project.contributionPrivacy'].includes('GitHub'));
 }
});
test('public feedback uses only the correct repository links; unknown or query-like city values have no destination',()=>{
 for(const city of ['berlin','hamburg','munich','cologne','frankfurt','dusseldorf','stuttgart','leipzig','dortmund','bremen','essen','dresden','hannover','nuremberg']){
  const repo='https://github.com/LN6666/crimemaps-'+city[0].toUpperCase()+city.slice(1);
  assert.deepEqual(githubFeedbackLinks(city),{repository:repo,discussions:repo+'/discussions',issues:repo+'/issues/new/choose'});
 }
 for(const city of ['Berlin','berlin?city=essen','../essen','https://attacker.example',''])assert.equal(githubFeedbackLinks(city),null);
});
test('publication month is source-native, independent of selected occurrence month, with no inferred fallback',()=>{
 const old={...event('old',[scene('unknown')]),month:'2000-11',published_at:'2026-05-25T10:15:00+02:00'};
 const explicit={...event('explicit',[scene('unknown')]),month:'2026-08',publication_month:'2026-09'};
 const absent={...event('absent',[scene('unknown')]),month:'2026-09',published_at:undefined};
 const invalid={...event('invalid',[scene('unknown')]),publication_month:'2026-13',published_at:'bad'};
 const boundary={...event('boundary',[scene('unknown')]),published_at:'2026-05-01T00:15:00+14:00'};
 const input=[old,explicit,absent,invalid,boundary],before=JSON.stringify(input);
 assert.deepEqual(uncertaintyRows(input).map(r=>r.publicationMonth),['2026-05','2026-09',null,null,'2026-05']);
 assert.equal(JSON.stringify(input),before);assert.equal(old.month,'2000-11');
});
test('legacy summary dates stay separate from scene-native times and never move to another scene',()=>{
 const legacy={...event('legacy',undefined),event_date:'2026-01-14'};
 const reviewed=event('reviewed',[scene('unknown',{event_time:{precision:'unknown',display:''}})]);
 const absent={...event('absent',undefined),event_date:null};
 const rows=uncertaintyRows([legacy,reviewed,absent]);
 assert.equal(rows[0].eventTime,null);assert.equal(rows[0].summaryEventDate,'2026-01-14');
 assert.equal(rows[1].summaryEventDate,null);assert.equal(rows[2].summaryEventDate,null);
});
