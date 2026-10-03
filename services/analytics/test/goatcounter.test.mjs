import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,mkdtemp,writeFile,mkdir,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {spawnSync} from 'node:child_process';
import vm from 'node:vm';
import {CITIES} from '../src/contract.mjs';
import {countPath,mountGoatCounter,mountGoatCounterConnectionTest,markAnalyticsLanguageNavigation,COUNT_ENDPOINT,SCRIPT_URL} from '../src/goatcounter-client.mjs';
import {statsFromExport} from '../src/goatcounter-export.mjs';
import {buildWorldCardModel,isPublicStats} from '../src/world-card.mjs';
const fixture = () => ({info:{export_version:'1.0',created_for:'ryoushunnei.goatcounter.com',created_at:'2026-10-03T12:00:00Z'},
 paths:[...CITIES.map((c,i)=>({id:i+1,path:countPath(c)})),{id:100,path:'/portal'},{id:101,path:'/_connection-test'}],
 locations:[{country:'JP',region:''},{country:'HK',region:''},{country:'DE',region:'BW'},{country:'',region:''}],
 locationStats:CITIES.flatMap((c,i)=>[{day:'2026-10-02',path_id:i+1,location:'JP',count:23+i*10},{day:'2026-10-02',path_id:i+1,location:'HK',count:21},{day:'2026-10-02',path_id:i+1,location:'DE-BW',count:3},{day:'2026-10-02',path_id:i+1,location:'',count:17}]).concat([{day:'2026-10-02',path_id:101,location:'JP',count:999}]),
 hitStats:CITIES.map((c,i)=>({hour:'2026-10-02T12:00:00Z',path_id:i+1,ref_id:0,count:64+i*10}))});
class Element extends EventTarget {constructor(){super();this.dataset={};} remove(){this.removed=true;} }
function browser({host='ln6666.github.io',protocol='https:',visible='visible',gpc=false}={}) {
 const scripts=[],requests=[],doc=new EventTarget();doc.visibilityState=visible;doc.referrer='https://example.invalid/private?secret=hidden';doc.title='Sensitive selected police report';doc.body={};
 doc.querySelector=q=>q==='script[data-goatcounter]'?scripts.find(s=>!s.removed)||null:null;doc.createElement=()=>new Element();doc.head={append:s=>scripts.push(s)};
 const location={hostname:host,protocol,pathname:'/crimemaps-Berlin/',search:'?search=SECRET&source_id=123&lng=13.5',hash:'#police-report'};
 const win={document:doc,location,navigator:{globalPrivacyControl:gpc,sendBeacon(){throw Error('beacon must not run');}},screen:{width:900,height:600},fetch:async(url,options)=>{requests.push({url,options});return {};},console:{warn(){}},localStorage:{getItem(){return null;}},Math,URL};win.window=win;win.parent=win;return {win,doc,scripts,requests};
}
const scriptFile=process.env.GOATCOUNTER_SOURCE_FIXTURE;
const official=scriptFile?await readFile(scriptFile,'utf8'):null;
test('all 15 fixed paths, distinct city exports, PV source and public suppression',()=>{
 const e=fixture();assert.equal(new Set(['portal',...CITIES].map(countPath)).size,15);
 for(const [i,city] of CITIES.entries()){
  const s=statsFromExport(e,city);assert.equal(s.source_path,countPath(city));assert.equal(s.metric,'goatcounter_pageviews');assert.equal(s.total_pv,60+i*10);assert.equal(s.countries.find(c=>c.code==='JP').pv,20+i*10);
  assert.equal(s.countries.find(c=>c.code==='HK').pv,20);assert.equal(s.countries.find(c=>c.code==='OTHER').pv,20);assert(!s.countries.some(c=>c.code==='DE'));assert(isPublicStats(s,city));assert(!isPublicStats(s,CITIES[(i+1)%14]));
  assert(!JSON.stringify(s).includes('path_id'));assert(!JSON.stringify(s).includes('ref_id'));assert(!JSON.stringify(s).includes('999'));
  for(const lang of ['de','en','zh']){const m=buildWorldCardModel(s,lang,city);assert(!m.copy.privacy.includes('Opt-in'));assert(m.paths.find(p=>p.code==='HK').pv===20);}
 }
});
test('corrupt/overlapping/foreign exports or ambiguous paths cannot replace statistics',()=>{
 const cases=[e=>e.info.created_for='other.goatcounter.com',e=>e.paths.push({...e.paths[0]}),e=>e.paths[0].path='/cities/berlin?secret=1',e=>e.locationStats.push({...e.locationStats[0]}),e=>e.locationStats[0].count=-1,e=>e.locationStats[0].day='2026-13-01',e=>e.locationStats[0].location='XX',e=>e.hitStats[0].count++,e=>e.locations.push({...e.locations[0]})];
 for(const change of cases){const e=fixture();change(e);assert.throws(()=>statsFromExport(e,'berlin'));}
 assert.throws(()=>statsFromExport(fixture(),'portal'));assert.throws(()=>statsFromExport(fixture(),'../berlin'));
});
test('low sample stays unknown; unknown country is not assigned to a parent',()=>{
 const e=fixture();e.locationStats=e.locationStats.filter(r=>r.path_id!==1).concat([{day:'2026-10-02',path_id:1,location:'JP',count:19}]);e.hitStats[0].count=19;
 const s=statsFromExport(e,'berlin');assert.equal(s.total_pv,null);assert.deepEqual(s.countries,[]);assert(buildWorldCardModel(s).paths.every(p=>p.pv===null));
});
test('unrelated legacy dictionary entries in a real-format export cannot block valid city totals',()=>{
 const e=fixture();e.locations.push({country:'Not an ISO country',region:'legacy'});assert.equal(statsFromExport(e,'berlin').total_pv,60);
 e.locationStats[0].location='Not an ISO country-legacy';assert.throws(()=>statsFromExport(e,'berlin'));
});
test('disabled, local, GPC, unconfigured and duplicate installation sends nothing',()=>{
 for(const opts of [{host:'localhost'}, {protocol:'http:'},{gpc:true}]){const b=browser(opts);mountGoatCounter({city:'berlin',enabled:true},b.win);assert.equal(b.scripts.length,0);assert.equal(b.requests.length,0);}
 const b=browser();mountGoatCounter({city:'berlin'},b.win);mountGoatCounter({city:'invalid',enabled:true},b.win);assert.equal(b.scripts.length,0);
 mountGoatCounter({city:'berlin',enabled:true},b.win);mountGoatCounter({city:'berlin',enabled:true},b.win);assert.equal(b.scripts.length,1);assert.equal(b.scripts[0].src,SCRIPT_URL);assert.equal(b.scripts[0].dataset.goatcounter,COUNT_ENDPOINT);
});
test('real pinned official script serializes only fixed data, once, for all 15 scopes', {skip:!official},()=>{
 for(const city of ['portal',...CITIES]){
  const b=browser();const component=mountGoatCounter({city,enabled:true},b.win);const context=vm.createContext(b.win);vm.runInContext(official,context);
  assert.equal(b.requests.length,0);b.scripts[0].dispatchEvent(new Event('load'));assert.equal(b.requests.length,1);
  const request=b.requests[0],url=new URL(request.url);assert.equal(url.origin+url.pathname,COUNT_ENDPOINT);assert.equal(url.searchParams.get('p'),countPath(city));assert.equal(url.searchParams.get('r'),null);assert.equal(url.searchParams.get('q'),null);assert.equal(url.searchParams.get('s'),null);
  assert.deepEqual([...url.searchParams.keys()].sort(),['b','p','rnd','t']);assert(!request.url.includes('SECRET'));assert(!request.url.includes('Sensitive'));assert.equal(request.options.referrerPolicy,'no-referrer');assert.equal(request.options.credentials,'omit');assert.equal(request.options.method,'POST');
  b.doc.dispatchEvent(new Event('visibilitychange'));component.destroy();mountGoatCounter({city,enabled:true},b.win);assert.equal(b.requests.length,1);
 }
});
test('hidden page waits, destruction prevents late collection', {skip:!official},()=>{
 const b=browser({visible:'hidden'});const c=mountGoatCounter({city:'essen',enabled:true},b.win);vm.runInContext(official,vm.createContext(b.win));b.scripts[0].dispatchEvent(new Event('load'));assert.equal(b.requests.length,0);b.doc.visibilityState='visible';b.doc.dispatchEvent(new Event('visibilitychange'));assert.equal(b.requests.length,1);c.destroy();
 const a=browser();const d=mountGoatCounter({city:'essen',enabled:true},a.win);d.destroy();a.scripts[0].dispatchEvent(new Event('load'));assert.equal(a.requests.length,0);
});
test('explicit localhost connection test uses a separate excluded path', {skip:!official},()=>{
 const b=browser({host:'localhost',protocol:'http:'});mountGoatCounterConnectionTest({enabled:true},b.win);vm.runInContext(official,vm.createContext(b.win));assert.equal(b.requests.length,0);b.scripts[0].dispatchEvent(new Event('load'));assert.equal(new URL(b.requests[0].url).searchParams.get('p'),'/_connection-test');assert.equal(b.requests.length,1);
 const a=browser({host:'unreviewed.example'});mountGoatCounterConnectionTest({enabled:true},a.win);assert.equal(a.scripts.length,0);
});
test('language navigation skips only its next same-city load; ordinary refresh still counts',{skip:!official},()=>{
 const storage=new Map(),sessionStorage={getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
 const from=browser();from.win.sessionStorage=sessionStorage;markAnalyticsLanguageNavigation('berlin',from.win);
 const next=browser();next.win.sessionStorage=sessionStorage;mountGoatCounter({city:'berlin',enabled:true},next.win);assert.equal(next.scripts.length,0);
 const refreshed=browser();refreshed.win.sessionStorage=sessionStorage;mountGoatCounter({city:'berlin',enabled:true},refreshed.win);vm.runInContext(official,vm.createContext(refreshed.win));refreshed.scripts[0].dispatchEvent(new Event('load'));assert.equal(refreshed.requests.length,1);assert.equal(storage.size,0);
 for(const variant of ['other-city','expired','storage-unavailable']){
  markAnalyticsLanguageNavigation('berlin',from.win);
  if(variant==='expired')for(const [key,raw] of storage){const m=JSON.parse(raw);m.at-=16000;storage.set(key,JSON.stringify(m));}
  const fallback=browser();fallback.win.sessionStorage=variant==='storage-unavailable'?{getItem(){throw Error('blocked');}}:sessionStorage;
  mountGoatCounter({city:variant==='other-city'?'hamburg':'berlin',enabled:true},fallback.win);vm.runInContext(official,vm.createContext(fallback.win));fallback.scripts[0].dispatchEvent(new Event('load'));assert.equal(fallback.requests.length,1);
 }
 const blocked=browser();blocked.win.localStorage.getItem=()=>{throw Error('blocked');};mountGoatCounter({city:'berlin',enabled:true},blocked.win);vm.runInContext(official,vm.createContext(blocked.win));assert.doesNotThrow(()=>blocked.scripts[0].dispatchEvent(new Event('load')));assert.equal(blocked.requests.length,0);
});
test('query stripping preserves the official script bot flag instead of overriding detection',{skip:!official},()=>{
 for(const [key,value,expected] of [['__nightmare',true,151],['phantom',true,150]]){
  const b=browser();b.win[key]=value;mountGoatCounter({city:'berlin',enabled:true},b.win);vm.runInContext(official,vm.createContext(b.win));b.scripts[0].dispatchEvent(new Event('load'));assert.equal(new URL(b.requests[0].url).searchParams.get('b'),String(expected));assert.equal(new URL(b.requests[0].url).searchParams.get('q'),null);
 }
});
test('snapshot CLI shares one aggregate across site and six README images; failure preserves last good',async()=>{
 const root=await mkdtemp(join(tmpdir(),'goat-export-')),exp=join(root,'export'),repo=join(root,'repo');await mkdir(exp);const e=fixture();
 const files={'info.json':JSON.stringify(e.info),'paths.jsonl':e.paths.map(JSON.stringify).join('\n'),'locations.jsonl':e.locations.map(JSON.stringify).join('\n'),'location_stats.jsonl':e.locationStats.map(JSON.stringify).join('\n'),'hit_stats.jsonl':e.hitStats.map(JSON.stringify).join('\n')};
 const run=()=>spawnSync(process.execPath,[new URL('../src/goatcounter-snapshot.mjs',import.meta.url).pathname,'berlin',exp,repo],{encoding:'utf8'});
 try{
  for(const [name,raw] of Object.entries(files))await writeFile(join(exp,name),raw);
  const r=run();assert.equal(r.status,0,r.stderr);const pub=await readFile(join(repo,'web/public/safety/analytics/visitors-by-country.json'),'utf8');assert.equal(pub,await readFile(join(repo,'docs/assets/visitors-by-country.data.json'),'utf8'));
  for(const lang of ['de','en','zh'])for(const mobile of ['', '.mobile']){const svg=await readFile(join(repo,`docs/assets/visitors-by-country.${lang}${mobile}.svg`),'utf8');assert(svg.includes('data-city="berlin"'));assert(svg.includes('data-country="JP" data-pv="20"'));}
  await writeFile(join(exp,'info.json'),JSON.stringify({...e.info,created_for:'other'}));assert.notEqual(run().status,0);assert.equal(await readFile(join(repo,'web/public/safety/analytics/visitors-by-country.json'),'utf8'),pub);
 }finally{await rm(root,{recursive:true,force:true});}
});
