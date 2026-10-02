import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,writeFile,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {CITIES,publishStats} from '../src/contract.mjs';
import {buildWorldCardModel,buildPlaceholderModel,renderWorldCardSvg,NO_DATA_COLOR,isPublicStats} from '../src/world-card.mjs';
import {renderChart,renderPlaceholder} from '../src/chart.mjs';
const rows=[['JP',2303],['CN',1217],['US',727],['SG',196],['HK',108],['KR',104],['TW',84],['DE',19],['ZZ',41]].map(([country,pv])=>({country,pv,started_at:'2026-10-01T01:01:01Z'}));
const stats=publishStats('berlin',rows,new Date('2026-10-03T00:00:00Z'));
test('map and ranking share only sorted published/suppressed/rounded data in three languages',()=>{
 const before=JSON.stringify(stats);
 for(const lang of ['de','en','zh']){
  const model=buildWorldCardModel(stats,lang,'berlin');
  assert.deepEqual(model.regions.map(r=>[r.code,r.pv]),stats.countries.map(r=>[r.code,r.pv]).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])));
  for(const p of model.paths){const published=model.regions.find(r=>r.code===p.code);assert.equal(p.pv,published?.pv??null);assert.equal(p.color,published?.color??NO_DATA_COLOR);}
  assert.equal(model.paths.find(p=>p.code==='DE').pv,null);
  assert.equal(model.paths.find(p=>p.code==='HK').pv,100);assert.equal(model.paths.find(p=>p.code==='TW').pv,80);assert.equal(model.paths.find(p=>p.code==='SG').pv,190);
  assert(!model.paths.some(p=>p.code==='OTHER'));assert.equal(model.regions.find(r=>r.code==='OTHER').pv,60);
  assert(model.paths.filter(p=>p.pv!==null).every(p=>p.pv>=20&&p.pv%10===0));
 }
 assert.equal(JSON.stringify(stats),before);
});
test('SVG uses safe XML, matching map/rank attributes and bounded wide/mobile layouts',()=>{
 for(const lang of ['de','en','zh'])for(const layout of ['wide','stacked']){
  const svg=renderChart(stats,lang,layout);assert(svg.includes('data-city="berlin"'));assert(svg.includes(`data-layout="${layout}"`));
  assert(!/<(?:script|image|foreignObject|iframe)|href=|\bon[a-z]+=|https?:\/\//i.test(svg.replace('http://www.w3.org/2000/svg','')));
  for(const [code,pv] of stats.countries.map(r=>[r.code,r.pv])){assert(svg.includes(`data-region="${code}" data-pv="${pv}"`));if(code!=='OTHER')assert(svg.includes(`data-country="${code}" data-pv="${pv}"`));}
  assert(Number(svg.match(/height="(\d+)"/)[1])<850);assert(svg.length<200000);
 }
});
test('all14 disconnected images and low-volume maps contain no invented country counts',()=>{
 for(const city of CITIES)for(const lang of ['de','en','zh']){
  const m=buildPlaceholderModel(city,lang);assert.equal(m.total,null);assert.deepEqual(m.regions,[]);assert(m.paths.every(p=>p.pv===null&&p.color===NO_DATA_COLOR));
  const svg=renderPlaceholder(city,lang);assert(svg.includes('data-status="not_connected"'));assert(!/data-pv="\d|data-region=/.test(svg));
 }
 const small=publishStats('berlin',[{country:'JP',pv:19}]);assert.equal(buildWorldCardModel(small).total,null);assert(buildWorldCardModel(small).paths.every(p=>p.pv===null));
});
test('unmapped regions remain ranked without parent-country assignment',()=>{
 const s=publishStats('berlin',[{country:'AQ',pv:20}]);const m=buildWorldCardModel(s);
 assert.equal(m.regions[0].pv,20);assert.equal(m.regions[0].mapped,false);assert.equal(m.unmapped.length,1);assert(m.paths.every(p=>p.pv===null));
});
test('untrusted data cannot change city, bypass privacy gates or create SVG/HTML',()=>{
 for(const bad of [{...stats,city:'<svg/onload=1>'},{...stats,countries:[{code:'<script>',pv:20}]},{...stats,countries:[{code:'JP',pv:19}]},{...stats,total_pv:null},{...stats,total_pv:20},{...stats,metric:'unique_visitors'},{...stats,privacy:{minimum_sample:1,rounding:1}},{...stats,generated_at:'<script>'}]){assert(!isPublicStats(bad));assert.throws(()=>buildWorldCardModel(bad));}
 assert.throws(()=>buildWorldCardModel(stats,'en','essen'));assert.throws(()=>buildWorldCardModel(stats,'<script>'));assert.throws(()=>renderWorldCardSvg(buildWorldCardModel(stats),'evil'));
});
test('placeholder CLI preserves an existing live image or an image missing its sidecar',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'world-placeholder-'));const assets=join(dir,'docs/assets');await mkdir(assets,{recursive:true});
 const image=join(assets,'visitors-by-country.de.svg');await writeFile(image,'previous-good');
 try{
  const cli=new URL('../src/placeholders.mjs',import.meta.url).pathname;
  const missing=spawnSync(process.execPath,[cli,'berlin',dir],{encoding:'utf8'});assert.notEqual(missing.status,0);assert.equal(await readFile(image,'utf8'),'previous-good');
  await writeFile(image.replace(/\.svg$/,'.json'),JSON.stringify({source_kind:'live_aggregate',sha256:'wrong'}));
  const live=spawnSync(process.execPath,[cli,'berlin',dir],{encoding:'utf8'});assert.notEqual(live.status,0);assert.equal(await readFile(image,'utf8'),'previous-good');
 }finally{await rm(dir,{recursive:true,force:true});}
});
