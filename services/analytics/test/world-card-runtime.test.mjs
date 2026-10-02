import test from 'node:test';import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {CITIES} from '../src/contract.mjs';
const modules=await Promise.all(['worker.mjs','contract.mjs','chart.mjs','world-card.mjs','world-boundaries.mjs'].map(async f=>({type:'ESModule',path:new URL('../src/'+f,import.meta.url).pathname,contents:await readFile(new URL('../src/'+f,import.meta.url),'utf8')})));
const mf=new Miniflare(convertV4MiniflareOptions({modules,compatibilityDate:'2026-10-01',d1Databases:{DB:'world-card-test'},bindings:{COLLECTION_ENABLED:'true',SITE_ORIGIN:'https://ln6666.github.io',TURNSTILE_SECRET:'test-local-secret-not-production',RATE_HMAC_SECRET:'only-test-local-64-character-rate-limit-secret-1234567890abcdefghijkl',REQUEST_LIMITER:{}},outboundService:()=>{throw new Error('Read-only charts must not contact a verifier');}}));
const db=await mf.getD1Database('DB');
const schema=await readFile(new URL('../migrations/0001_analytics.sql',import.meta.url),'utf8');
for(const sql of schema.replace(/--[^\n]*/g,'').match(/\s*CREATE TRIGGER[\s\S]*?END;|[^;]+;/g).map(s=>s.trim().replace(/\s+/g,' ')))await db.prepare(sql).run();
for(const [i,city] of CITIES.entries())await db.prepare("INSERT INTO country_totals(city,country,pv,started_at,updated_at) VALUES (?1,'JP',?2,'2026-10-01T00:00:00Z','2026-10-01T00:00:00Z')").bind(city,(i+2)*20).run();
const snapshot=async()=>JSON.stringify((await db.prepare('SELECT * FROM country_totals ORDER BY city,country').all()).results);
const before=await snapshot();
try{
 await test('actual workerd/D1: all14 chart/stats namespaces stay isolated and GET never increments page views',async()=>{
  for(const [i,city] of CITIES.entries())for(const lang of ['de','en','zh']){
   const pv=(i+2)*20;
   const stats=await (await mf.dispatchFetch(`https://analytics.example/v1/stats/${city}?city=berlin`)).json();assert.equal(stats.city,city);assert.equal(stats.total_pv,pv);
   for(const layout of ['wide','stacked']){
    const res=await mf.dispatchFetch(`https://analytics.example/v1/chart/${city}.svg?lang=${lang}&layout=${layout}&city=evil&count=999`);assert.equal(res.status,200);
    const svg=await res.text();assert(svg.includes(`data-city="${city}"`));assert(svg.includes(`data-layout="${layout}"`));assert(svg.includes(`data-country="JP" data-pv="${pv}"`));assert(svg.includes(`data-region="JP" data-pv="${pv}"`));
   }
  }
  assert.equal(await snapshot(),before);
 });
 await test('canonical chart cache distinguishes layout/lang and rejects unsafe enum values without writes',async()=>{
  for(const layout of ['wide','stacked','wide']){const r=await mf.dispatchFetch(`https://analytics.example/v1/chart/berlin.svg?lang=en&layout=${layout}&city=essen`);const s=await r.text();assert(s.includes(`data-layout="${layout}"`));assert(s.includes('data-city="berlin"'));}
  assert.equal((await mf.dispatchFetch('https://analytics.example/v1/chart/berlin.svg?lang=%3Cscript%3E')).status,400);
  assert.equal((await mf.dispatchFetch('https://analytics.example/v1/chart/berlin.svg?layout=%3Cscript%3E')).status,400);
  const head=await mf.dispatchFetch('https://analytics.example/v1/chart/berlin.svg?layout=stacked',{method:'HEAD'});assert.equal(head.status,200);assert.equal(await head.text(),'');
  assert.equal(await snapshot(),before);
 });
}finally{await mf.dispose();}
