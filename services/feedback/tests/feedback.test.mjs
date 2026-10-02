import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { handle, prune, CITIES } from '../worker.mjs';
class D1 {
  constructor() {this.sql = new DatabaseSync(':memory:'); this.sql.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));}
  prepare(sql) {const db=this.sql; let args=[]; return {
    bind(...v) {args=v;return this;},
    async first() {return db.prepare(sql).get(...args) ?? null;},
    async all() {return {results:db.prepare(sql).all(...args)};},
    async run() {return db.prepare(sql).run(...args);},
  };}
  async batch(statements) {this.sql.exec('BEGIN');try {const results=[];for(const s of statements)results.push(await s.run());this.sql.exec('COMMIT');return results;}catch(e){this.sql.exec('ROLLBACK');throw e;}}
}
const origin='https://ln6666.github.io', now=Date.parse('2026-10-03T00:00:00Z');
function setup() {return {DB:new D1(),REQUEST_LIMITER:{limit:async()=>({success:true})},ENABLED:'true',RATE_SECRET:'b'.repeat(64),ADMIN_TOKEN:'a'.repeat(64),TURNSTILE_SECRET:'real-secret-fixture-not-a-test-key',TURNSTILE_HOSTNAME:'ln6666.github.io',ALLOWED_ORIGINS:origin,OPERATOR_NAME:'Local test operator',PRIVACY_URL:origin+'/privacy'};}
const body=(city='berlin')=>({city,kind:'correction',message:'A source link is broken.',source_id:'test-001',challenge_token:'challenge-test-value'});
function request(path='/feedback',value=body(),headers={}) {const request = new Request('https://feedback.example'+path,{method:value?'POST':'GET',headers:{Origin:origin,'CF-Connecting-IP':'192.0.2.1',...value?{'Content-Type':'application/json'}:{},...headers},body:value?JSON.stringify(value):undefined}); Object.defineProperty(request,'cf',{value:{colo:'LOCAL-FIXTURE'}});return request;}
const challenge=async()=>new Response(JSON.stringify({success:true,hostname:'ln6666.github.io',action:'feedback'}));
async function send(env,value=body(),extra={}) {return handle(request('/feedback',value,extra),env,{now,fetch:challenge});}
test('14 cities accept private plain text, only hash deletion tokens and retain no raw IP/UA',async()=>{
  for (const city of CITIES) {
    const env=setup(),r=await send(env,body(city));assert.equal(r.status,201); const receipt=await r.json();
    const row=env.DB.sql.prepare('SELECT * FROM feedback').get();
    assert.equal(row.city,city); assert.equal(row.message,body().message);assert.equal(receipt.deletionToken.length,64);
    assert.notEqual(row.deletion_hash,receipt.deletionToken);assert.equal(row.expires_at-row.created_at,30*86400);
    assert.equal(r.headers.get('cache-control'),'no-store');assert.equal(r.headers.get('access-control-allow-origin'),origin);
    const dump=JSON.stringify({row,budgets:env.DB.sql.prepare('SELECT * FROM budget').all()});
    assert.ok(!dump.includes('192.0.2.1'));assert.ok(!dump.includes(receipt.deletionToken));assert.ok(!dump.includes('user_agent'));
  }
});
test('unknown fields, URLs, files, invalid city, short text and wrong content types fail before storage',async()=>{
  const cases=[{...body(),email:'not-collected@example.test'},{...body(),files:[]},{...body(),source_id:'https://evil.example'},{...body(),city:'not-a-city'},{...body(),message:'short'}];
  for(const b of cases) {const env=setup();assert.equal((await send(env,b)).status,400);assert.equal(env.DB.sql.prepare('SELECT count(*) n FROM feedback').get().n,0);}
  assert.equal((await handle(request('/feedback',body(),{'Content-Type':'text/plain'}),setup(),{now,fetch:challenge})).status,415);
  assert.equal((await send(setup(),{...body(),message:'a'.repeat(14000)})).status,413);
});
test('Origin, missing trusted IP, test secret, disabled and missing bindings fail closed',async()=>{
  assert.equal((await send(setup(),body(),{Origin:'https://ln6666.github.io.evil.test'})).status,403);
  const missing=request();missing.headers.delete('CF-Connecting-IP');assert.equal((await handle(missing,setup(),{now,fetch:challenge})).status,503);
  for(const change of [{ENABLED:'false'},{DB:null},{ADMIN_TOKEN:null},{REQUEST_LIMITER:null},{OPERATOR_NAME:'REPLACE_WITH_REAL_OPERATOR'},{PRIVACY_URL:'https://name:pass@evil.test'},{TURNSTILE_SECRET:'1x0000000000000000000000000000000AA'}]) {
    const r=await send({...setup(),...change});assert.equal(r.status,503);
    const health=await handle(request('/health?city=berlin',null),{...setup(),...change},{now});assert.equal((await health.json()).enabled,false);
  }
});
test('challenge success must match hostname/action and an upstream failure cannot store a message',async()=>{
  for(const result of [{success:false},{success:true,hostname:'evil.test',action:'feedback'},{success:true,hostname:'ln6666.github.io',action:'other'}]) {
    const env=setup(),r=await handle(request(),env,{now,fetch:async()=>new Response(JSON.stringify(result))});assert.equal(r.status,403);assert.equal(env.DB.sql.prepare('SELECT count(*) n FROM feedback').get().n,0);
  }
  assert.equal((await handle(request(),setup(),{now,fetch:async()=>{throw Error('upstream secret must not leak');}})).status,503);
});
test('IP rate limit and concurrent daily submission budget cannot be exceeded',async()=>{
  const env=setup();for(let i=0;i<5;i++)assert.equal((await send(env)).status,201);assert.equal((await send(env)).status,429);
  const limited=setup(),day=Math.floor(now/1000/86400);limited.DB.sql.prepare('INSERT INTO budget VALUES(?,?,?)').run(`received:${day}`,499,now/1000+86400);
  const results=await Promise.all(Array.from({length:8},(_,i)=>send(limited,body(),{'CF-Connecting-IP':`192.0.2.${i+10}`})));
  assert.equal(results.filter(r=>r.status===201).length,1);assert.equal(limited.DB.sql.prepare('SELECT count(*) n FROM feedback').get().n,1);
  const exhausted=setup();exhausted.DB.sql.prepare('INSERT INTO budget VALUES(?,?,?)').run(`attempts:${day}`,1000,now/1000+86400);assert.equal((await send(exhausted)).status,429);
  for(let i=0;i<20;i++)assert.equal((await send(exhausted,body(),{'CF-Connecting-IP':`198.51.100.${i+1}`})).status,429);
  assert.equal(exhausted.DB.sql.prepare('SELECT count(*) n FROM budget').get().n,1);
});
test('token deletion hides existence, stored messages have no public GET, admin token stays out of body',async()=>{
  const env=setup(),receipt=await (await send(env)).json();
  assert.equal((await handle(request('/feedback',null),env,{now})).status,404);
  assert.equal((await handle(request('/admin/feedback?city=berlin',null,{Authorization:`Bearer ${env.ADMIN_TOKEN}`}),env,{now})).status,404);
  const admin=request('/admin/feedback?city=berlin',null,{Authorization:`Bearer ${env.ADMIN_TOKEN}`});admin.headers.delete('Origin');
  const items=await (await handle(admin,env,{now})).json();assert.equal(items.items.length,1);assert.ok(!JSON.stringify(items).includes('deletion_hash'));
  const wrong=await handle(request('/retract',{id:receipt.id,deletion_token:'f'.repeat(64)}),env,{now});assert.equal(wrong.status,204);assert.equal(env.DB.sql.prepare('SELECT count(*) n FROM feedback').get().n,1);
  const right=await handle(request('/retract',{id:receipt.id,deletion_token:receipt.deletionToken}),env,{now});assert.equal(right.status,204);assert.equal(env.DB.sql.prepare('SELECT count(*) n FROM feedback').get().n,0);
  assert.equal((await handle(request('/retract',{id:receipt.id,deletion_token:receipt.deletionToken}),env,{now})).status,204);
});
test('expiry is enforced on operator reads and cleanup physically removes rows/budgets',async()=>{
  const env=setup();await send(env);const later=now+31*86400000;
  const admin=request('/admin/feedback?city=berlin',null,{Authorization:`Bearer ${env.ADMIN_TOKEN}`});admin.headers.delete('Origin');assert.equal((await (await handle(admin,env,{now:later})).json()).items.length,0);
  await prune(env,Math.floor(later/1000));assert.equal(env.DB.sql.prepare('SELECT count(*) n FROM feedback').get().n,0);
  // Current operator-rate buckets remain; expired original submission buckets do not.
  assert.equal(env.DB.sql.prepare('SELECT count(*) n FROM budget WHERE expires_at <= ?').get(later/1000).n,0);
});
test('platform burst limit rejects before D1 and challenge calls; preflight allows only intake methods/headers',async()=>{
  const env=setup();env.REQUEST_LIMITER.limit=async()=>({success:false});
  assert.equal((await send(env)).status,429);assert.equal(env.DB.sql.prepare('SELECT count(*) n FROM budget').get().n,0);
  const options = new Request('https://feedback.example/feedback',{method:'OPTIONS',headers:{Origin:origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'}});
  assert.equal((await handle(options,setup(),{now})).status,204);
  options.headers.set('Access-Control-Request-Headers','authorization');assert.equal((await handle(options,setup(),{now})).status,403);
});
test('local HTTP transport exercises the actual handler plus real SQLite, with challenge verification fixture only',async()=>{
  const env=setup();const server=createServer(async(req,res)=>{
    let data='';for await(const chunk of req)data+=chunk;
    const headers=new Headers(req.headers);headers.set('CF-Connecting-IP','192.0.2.3');
    const incoming=new Request('http://127.0.0.1'+req.url,{method:req.method,headers,body:data||undefined});Object.defineProperty(incoming,'cf',{value:{colo:'LOCAL-FIXTURE'}});
    const r=await handle(incoming,env,{now,fetch:challenge});
    res.writeHead(r.status,Object.fromEntries(r.headers));res.end(await r.text());
  });await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try {const endpoint=`http://127.0.0.1:${server.address().port}`;
    const r=await fetch(endpoint+'/feedback',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify(body())});
    assert.equal(r.status,201);const receipt=await r.json();assert.equal(env.DB.sql.prepare('SELECT count(*) n FROM feedback').get().n,1);
    const deleted=await fetch(endpoint+'/retract',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify({id:receipt.id,deletion_token:receipt.deletionToken})});assert.equal(deleted.status,204);
  }finally{await new Promise(resolve=>server.close(resolve));}
});
