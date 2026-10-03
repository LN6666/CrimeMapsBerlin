import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import ts from 'typescript';

const require=createRequire(import.meta.url),cache=new Map();
function load(name){
 if(name.endsWith('.json'))return JSON.parse(readFileSync(new URL(`../src/safety/${name}`,import.meta.url),'utf8'));
 if(cache.has(name))return cache.get(name);
 const out={};cache.set(name,out);
 const code=ts.transpileModule(readFileSync(new URL(`../src/safety/${name}.ts`,import.meta.url),'utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true},
 }).outputText;
 new Function('exports','require',code)(out,n=>n.startsWith('./')?load(n.slice(2)):require(n));
 return out;
}
const ordinary=load('content-tags'),macro=load('macro-tags');
const counts=()=>({supported:2,no_support:1,uncertain:1,not_evaluated:1});
const common={key:'berlin',records:5,fully_evaluated_records:4,mapping_sha256:'a'.repeat(64),overlay_sha256:'b'.repeat(64),time_scope:'all_selected_months',text_scope:'full_official_text'};
const summary=(layer,zero=false)=>({...common,records:zero?0:5,fully_evaluated_records:zero?0:4,
 version:layer==='ordinary'?ordinary.CONTENT_TAG_VERSION:macro.MACRO_TAG_VERSION,
 tags:(layer==='ordinary'?ordinary.CONTENT_TAGS:[...macro.MACRO_TAGS,...macro.HATE_FACETS]).map(tag=>({tag,counts:zero?{supported:0,no_support:0,uncertain:0,not_evaluated:0}:counts(),
  ...(layer==='macro'?{police_category_stated:zero?0:1,narrative_lead:zero?0:1}:{}),
 })),
});
test('uncertain and unassessed records stay in both content-index denominators',()=>{
 const o=ordinary.contentTagStatisticsForSummary(summary('ordinary')),m=macro.macroStatisticsForSummary(summary('macro'));
 for(const result of [o,m]){
  assert(result.tags.every(tag=>tag.content_index===40));
  assert(result.tags.every(tag=>tag.counts.supported===2&&tag.counts.no_support===1&&tag.counts.uncertain===1&&tag.counts.not_evaluated===1));
  assert.equal(result.crime_rate,null);assert.equal(result.city_risk_score,null);
 }
 assert(o.tags.every(t=>t.evaluation_coverage.value===.8));assert(m.tags.every(t=>t.evaluated===.8));assert.equal(o.composite,null);
});
test('zero denominators stay unavailable and reviewed no-support retains zero index',()=>{
 for(const layer of ['ordinary','macro']){
  const stats=layer==='ordinary'?ordinary.contentTagStatisticsForSummary:macro.macroStatisticsForSummary;
  assert(stats(summary(layer,true)).tags.every(tag=>tag.content_index===null));
  const negative=summary(layer);negative.fully_evaluated_records=5;
  for(const t of negative.tags){t.counts={supported:0,no_support:5,uncertain:0,not_evaluated:0};if(layer==='macro'){t.police_category_stated=0;t.narrative_lead=0;}}
  assert(stats(negative).tags.every(tag=>tag.content_index===0));
 }
});
test('four-state totals and macro attribution cannot be fabricated',()=>{
 const o=summary('ordinary');o.tags[0].counts.no_support++;
 assert.throws(()=>ordinary.contentTagStatisticsForSummary(o));
 const m=summary('macro');m.tags[0].narrative_lead++;
 assert.throws(()=>macro.macroStatisticsForSummary(m));
});
test('both tables expose a no-support column in every shipped interface language',()=>{
 for(const language of ['en','de','zh']){
  assert.equal(typeof load('content-tag-copy').CONTENT_TAG_COPY[language].noSupport,'string');
  assert.equal(typeof load('macro-tag-copy').MACRO_COPY[language].noSupport,'string');
 }
});
