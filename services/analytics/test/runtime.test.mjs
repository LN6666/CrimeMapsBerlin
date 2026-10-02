import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Miniflare,convertV4MiniflareOptions,Response as MFResponse} from 'miniflare';
import {CITIES,publishStats,countryFromEdge} from '../src/contract.mjs';
import {renderChart,validateStats} from '../src/chart.mjs';
import worker from '../src/worker.mjs';
const schema=await readFile(new URL('../migrations/0001_analytics.sql',import.meta.url),'utf8');
const modules=await Promise.all(['worker.mjs','contract.mjs','chart.mjs','world-card.mjs','world-boundaries.mjs'].map(async file=>({type:'ESModule',path:new URL('../src/'+file,import.meta.url).pathname,contents:await readFile(new URL('../src/'+file,import.meta.url),'utf8')})));
const captures=[];
const usedTokens=new Set();
let verifierMode='good';
const mf=new Miniflare(convertV4MiniflareOptions({
  modules,
  compatibilityDate:'2026-10-01',cf:{country:'DE'},d1Databases:{DB:'analytics-test'},
  bindings:{COLLECTION_ENABLED:'true',SITE_ORIGIN:'https://ln6666.github.io',TURNSTILE_SECRET:'test-local-secret-not-production',RATE_HMAC_SECRET:'only-test-local-64-character-rate-limit-secret-1234567890abcdefghijkl'},
  ratelimits:{REQUEST_LIMITER:{namespace_id:'81001',simple:{limit:30,period:60}}},
  outboundService:async req=>{
    assert.equal(req.url,'https://challenges.cloudflare.com/turnstile/v0/siteverify');
    const data=await req.json(); captures.push(data);
    if(verifierMode==='unavailable')return new MFResponse('{}',{status:503});
    const [,city]=data.response.split(':');
    const valid=verifierMode==='good' && !usedTokens.has(data.response); usedTokens.add(data.response);
    return new MFResponse(JSON.stringify({success:valid,hostname:verifierMode==='hostname'?'evil.example':'ln6666.github.io',action:verifierMode==='action'?'pv_essen':`pv_${city}`,cdata:verifierMode==='cdata'?'essen':city}),{headers:{'Content-Type':'application/json'}});
  },
}));
const db=await mf.getD1Database('DB');
// D1 exec accepts one SQL statement per line. Remove comments and preserve the
// two trigger programs as complete statements instead of splitting their bodies.
const statements=schema.replace(/--[^\n]*/g,'').match(/\s*CREATE TRIGGER[\s\S]*?END;|[^;]+;/g).map(s=>s.trim().replace(/\s+/g,' '));
for(const sql of statements) await db.prepare(sql).run();
let seq=0;
// Repository spelling is independent of the lowercase city IDs and API routes.
const expectedPaths={berlin:'/crimemaps-Berlin/',hamburg:'/crimemaps-Hamburg/',munich:'/crimemaps-Munich/',cologne:'/crimemaps-Cologne/',frankfurt:'/crimemaps-Frankfurt/',dusseldorf:'/crimemaps-Dusseldorf/',stuttgart:'/crimemaps-Stuttgart/',leipzig:'/crimemaps-Leipzig/',dortmund:'/crimemaps-Dortmund/',bremen:'/crimemaps-Bremen/',essen:'/crimemaps-Essen/',dresden:'/crimemaps-Dresden/',hannover:'/crimemaps-Hannover/',nuremberg:'/crimemaps-Nuremberg/'};
const request=(city,opts={})=>mf.dispatchFetch(`https://analytics.example/v1/events/${city}`,{
  method:'POST',cf:{country:opts.country??'DE'},
  headers:{Origin:'https://ln6666.github.io','Content-Type':'application/json','CF-Connecting-IP':opts.ip??`198.51.100.${++seq%240+1}`,...opts.headers},
  body:JSON.stringify({event:'pageview',path:expectedPaths[city],token:opts.token??`token:${city}:${++seq}`,...opts.body}),
});
const total=async()=>Number((await db.prepare('SELECT COALESCE(sum(pv),0) as n FROM country_totals').first()).n);

await test('actual workerd/D1: all 14 city namespaces and GET is read-only',async()=>{
  for(const city of CITIES) assert.equal((await request(city)).status,202,city);
  assert.equal(await total(),14);
  for(const city of CITIES){
    const r=await mf.dispatchFetch(`https://analytics.example/v1/stats/${city}`,{headers:{Origin:'https://ln6666.github.io'}});
    assert.equal(r.status,200); const s=await r.json(); assert.equal(s.city,city); assert.equal(s.total_pv,null);assert.deepEqual(s.countries,[]);
    assert.equal(r.headers.get('Access-Control-Allow-Origin'),'https://ln6666.github.io');
  }
  assert.equal(await total(),14);
  const head=await mf.dispatchFetch('https://analytics.example/v1/chart/berlin.svg?lang=de',{method:'HEAD'});
  assert.equal(head.status,200);assert.equal(await head.text(),'');
});
await test('untrusted cities, origin, body fields, path, country, headers and token replay cannot write',async()=>{
  const before=await total();
  assert.equal((await request('notacity')).status,404);
  assert.equal((await request('berlin',{headers:{Origin:'https://evil.example'}})).status,403);
  assert.equal((await request('berlin',{headers:{Origin:'null'}})).status,403);
  assert.equal((await request('berlin',{body:{country:'CN'}})).status,400);
  assert.equal((await request('berlin',{body:{path:'/crimemaps-Essen/'}})).status,400);
  for(const path of ['/crimemapsberlin/','/crimemaps-berlin/','/crimemaps-BERLIN/']) {
    assert.equal((await request('berlin',{body:{path}})).status,400,path);
  }
  assert.equal((await request('berlin',{body:{url:'https://evil.example/'}})).status,400);
  assert.equal((await request('berlin',{body:{token:'x'.repeat(4097)}})).status,400);
  assert.equal((await request('berlin',{headers:{'Content-Type':'text/plain'}})).status,415);
  assert.equal((await request('berlin',{headers:{'DNT':'1'}})).status,403);
  assert.equal((await request('berlin',{headers:{'Sec-GPC':'1'}})).status,403);
  const withoutEdge=new Request('https://analytics.example/v1/events/berlin',{method:'POST',headers:{Origin:'https://ln6666.github.io','Content-Type':'application/json'},body:'{}'});
  assert.equal((await worker.fetch(withoutEdge,{COLLECTION_ENABLED:'true',SITE_ORIGIN:'https://ln6666.github.io',DB:{},REQUEST_LIMITER:{},TURNSTILE_SECRET:'test-local-secret-not-production',RATE_HMAC_SECRET:'only-test-local-64-character-rate-limit-secret-1234567890abcdefghijkl'})).status,503);
  assert.equal((await request('berlin',{body:{event:'unique_visitor'}})).status,400);
  assert.equal(await total(),before);
  const token='token:berlin:single-use';
  assert.equal((await request('berlin',{token,headers:{'CF-IPCountry':'CN'}})).status,202);
  assert.equal((await request('berlin',{token})).status,403);
  assert.equal(await total(),before+1);
  assert.equal((await db.prepare("SELECT count(*) AS n FROM country_totals WHERE country='CN'").first()).n,0);
});
await test('server validates hostname, action, city cdata and verifier failure',async()=>{
  const before=await total();
  for(const mode of ['hostname','action','cdata','reject']) {
    verifierMode=mode; assert.equal((await request('berlin')).status,403,mode);
  }
  verifierMode='good';assert.equal(await total(),before);
  assert(captures.every(x=>!('remoteip' in x) && Object.keys(x).sort().join(',')==='response,secret'));
});
await test('exact persistent minute rate limit holds with concurrent workerd requests',async()=>{
  const before=await total();
  const responses=await Promise.all(Array.from({length:24},()=>request('hamburg',{ip:'203.0.113.240'})));
  assert.equal(responses.filter(r=>r.status===202).length,10);
  assert.equal(responses.filter(r=>r.status===429).length,14);
  assert.equal(await total(),before+10);
  const row=await db.prepare('SELECT max(used) AS n FROM short_limits').first();assert.equal(row.n,10);
});
await test('database never stores IP, tokens or user-agent; only rotating HMAC and admission nonce',async()=>{
  const fields=(await db.prepare('PRAGMA table_info(short_limits)').all()).results.map(x=>x.name);
  assert.deepEqual(fields,['bucket','used','admission','expires_at']);
  const rows=(await db.prepare('SELECT * FROM short_limits').all()).results;
  assert(rows.every(r=>/^[a-f0-9]{64}$/.test(r.bucket) && r.expires_at*1000-Date.now()<120000));
  const tables=(await db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_cf_%'").all()).results.map(x=>x.name).sort();
  assert.deepEqual(tables,['country_totals','daily_budget','short_limits']);
});
await test('global daily budget is atomic across cities, limits fail closed',async()=>{
  await db.prepare("UPDATE daily_budget SET accepted=4995 WHERE day=date('now')").run();
  const before=await total();
  const results=await Promise.all(Array.from({length:18},(_,i)=>request(CITIES[i%CITIES.length])));
  assert.equal(results.filter(r=>r.status===202).length,5);
  assert.equal(results.filter(r=>r.status===429).length,13);
  assert.equal(await total(),before+5);
  assert.equal((await db.prepare("SELECT accepted FROM daily_budget WHERE day=date('now')").first()).accepted,5000);
});
await test('privacy suppression and safe localized SVG are derived from actual aggregates',async()=>{
  const stats=publishStats('berlin',[{country:'DE',pv:27,started_at:'2026-01-01T00:00:01Z'},{country:'JP',pv:4,started_at:'2026-01-01T00:00:02Z'},{country:'ZZ',pv:22,started_at:'2026-01-01T00:00:03Z'}]);
  assert.equal(stats.total_pv,50);assert.deepEqual(stats.countries,[{code:'DE',pv:20},{code:'OTHER',pv:20}]);
  assert.equal(stats.collection_start_date,'2026-01-01');assert(!JSON.stringify(stats).includes('00:00:01'));
  assert(validateStats(stats));
  for(const lang of ['de','en','zh']) {
    const svg=renderChart(stats,lang);assert(svg.includes('<title')&&svg.includes('<desc')&&svg.includes(stats.generated_at));
    assert(!/<(?:script|foreignObject|image)|href=|onload=/i.test(svg));
  }
  assert.throws(()=>renderChart({...stats,city:'<script>evil</script>'},'en'));
  assert.throws(()=>renderChart({...stats,countries:[{code:'<img>',pv:20}]},'en'));
  assert.equal(countryFromEdge({headers:{'CF-IPCountry':'DE'}}),'ZZ');
  assert.equal(countryFromEdge({cf:{country:'XX'}}),'ZZ');
});
await test('CORS preflight and error endpoints do not collect or allow arbitrary headers',async()=>{
  const before=await total();
  const pre=await mf.dispatchFetch('https://analytics.example/v1/events/berlin',{method:'OPTIONS',headers:{Origin:'https://ln6666.github.io','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'}});
  assert.equal(pre.status,204);
  assert.equal(pre.headers.get('Access-Control-Allow-Credentials'),null);
  const bad=await mf.dispatchFetch('https://analytics.example/v1/events/berlin',{method:'OPTIONS',headers:{Origin:'https://ln6666.github.io','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization'}});
  assert.equal(bad.status,403);
  assert.equal((await mf.dispatchFetch('https://analytics.example/v1/events/berlin')).status,405);
  assert.equal((await mf.dispatchFetch('https://analytics.example/v1/chart/berlin.svg?lang=<script>')).status,400);
  assert.equal(await total(),before);
});
await test('verification outages and database failures fail closed',async()=>{
  verifierMode='unavailable'; assert.equal((await request('berlin')).status,503); verifierMode='good';
  const before=await total();
  await db.prepare('DROP TABLE short_limits').run();
  assert.equal((await request('berlin')).status,503);assert.equal(await total(),before);
  await mf.purgeCache();await db.prepare('DROP TABLE country_totals').run();
  assert.equal((await mf.dispatchFetch('https://analytics.example/v1/stats/berlin')).status,503);
});
await mf.dispose();
await test('unconnected production configuration cannot return manufactured zeroes',async()=>{
  const off=new Miniflare(convertV4MiniflareOptions({modules,compatibilityDate:'2026-10-01',bindings:{COLLECTION_ENABLED:'false'},cf:false}));
  try { const r=await off.dispatchFetch('https://analytics.example/v1/stats/berlin');assert.equal(r.status,503);assert.deepEqual(await r.json(),{error:'not_connected'}); }
  finally {await off.dispose();}
});
