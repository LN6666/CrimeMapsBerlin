import { ALLOWED_ORIGIN, MAX_BODY_BYTES, action, countryFromEdge, pagePath, publishStats, validCity, LANGUAGES } from './contract.mjs';
import { renderChart } from './chart.mjs';

const LIMIT_SQL = `INSERT INTO short_limits(bucket,used,expires_at,admission)
  SELECT ?1,1,?2,?3 WHERE COALESCE((SELECT accepted FROM daily_budget WHERE day=date('now')),0)<5000
  ON CONFLICT(bucket) DO UPDATE SET used=used+1,admission=excluded.admission
  WHERE used<10 RETURNING used`;
const TOTAL_SQL = `INSERT INTO country_totals(city,country,pv,started_at,updated_at)
  SELECT ?1,?2,1,?3,?3 WHERE EXISTS(SELECT 1 FROM short_limits WHERE bucket=?4 AND admission=?5)
  AND COALESCE((SELECT accepted FROM daily_budget WHERE day=date('now')),0)<5000
  ON CONFLICT(city,country) DO UPDATE SET pv=pv+1,updated_at=excluded.updated_at RETURNING pv`;

const HEADERS = {
  'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer',
  'Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'; sandbox",
  'Cross-Origin-Resource-Policy':'cross-origin',
};
function response(body, status=200, type='application/json; charset=utf-8', extra={}) {
  return new Response(type.startsWith('application/json') ? JSON.stringify(body) : body,
    {status,headers:{...HEADERS,'Content-Type':type,'Cache-Control':'no-store',...extra}});
}
const error = (code,status,extra={}) => response({error:code},status,undefined,extra);
function cors(request) {
  return request.headers.get('Origin') === ALLOWED_ORIGIN
    ? {'Access-Control-Allow-Origin':ALLOWED_ORIGIN,'Vary':'Origin'} : {};
}
function configured(env) {
  return env.COLLECTION_ENABLED === 'true' && env.SITE_ORIGIN === ALLOWED_ORIGIN && env.DB
    && env.REQUEST_LIMITER && typeof env.TURNSTILE_SECRET === 'string' && env.TURNSTILE_SECRET.length >= 20
    && typeof env.RATE_HMAC_SECRET === 'string' && env.RATE_HMAC_SECRET.length >= 43
    && !env.TURNSTILE_SECRET.startsWith('1x000000') && !env.TURNSTILE_SECRET.startsWith('2x000000')
    && !env.TURNSTILE_SECRET.startsWith('3x000000');
}
async function limitedJson(request) {
  const length = request.headers.get('Content-Length');
  if (length && (!/^\d+$/.test(length) || Number(length)>MAX_BODY_BYTES)) throw new Error('body_size');
  if (!request.body) throw new Error('body_missing');
  const reader=request.body.getReader();
  let size=0, chunks=[];
  try {
    while(true) {
      const {value,done}=await reader.read(); if(done) break;
      size+=value.byteLength;
      if(size>MAX_BODY_BYTES) { await reader.cancel(); throw new Error('body_size'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes=new Uint8Array(size); let offset=0;
  for(const c of chunks) {bytes.set(c,offset);offset+=c.byteLength;}
  return JSON.parse(new TextDecoder().decode(bytes));
}
async function minuteKey(ip, secret, now=Date.now()) {
  const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const digest=await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(`${Math.floor(now/60000)}:${ip}`));
  return Array.from(new Uint8Array(digest),x=>x.toString(16).padStart(2,'0')).join('');
}
async function verify(token,city,env) {
  const result=await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({secret:env.TURNSTILE_SECRET,response:token}), // remoteip is omitted
    signal:AbortSignal.timeout(4000),
  });
  if(!result.ok) throw new Error('verification_unavailable');
  const value=await result.json();
  return value.success === true && value.hostname === new URL(ALLOWED_ORIGIN).hostname
    && value.action === action(city) && value.cdata === city;
}
async function collect(request,env,city) {
  const headers=cors(request);
  if(request.headers.get('Origin')!==ALLOWED_ORIGIN) return error('origin_forbidden',403);
  // Origin is not authentication. Token validation is always mandatory below.
  const site=request.headers.get('Sec-Fetch-Site');
  if(site && !['cross-site','same-site','same-origin'].includes(site)) return error('fetch_forbidden',403,headers);
  if(!request.headers.get('Content-Type')?.toLowerCase().startsWith('application/json')) return error('json_required',415,headers);
  if(request.headers.get('Sec-GPC')==='1' || request.headers.get('DNT')==='1') return error('privacy_preference',403,headers);
  const ip=request.headers.get('CF-Connecting-IP');
  if(!ip || ip.length>64 || !/^[0-9a-fA-F:.]+$/.test(ip) || !request.cf) return error('edge_metadata_required',503,headers);
  const now=Date.now();
  const bucket=await minuteKey(ip,env.RATE_HMAC_SECRET,now);
  // No IP is persisted or forwarded; this non-stable pseudonym rotates each minute.
  const allowed=await env.REQUEST_LIMITER.limit({key:bucket});
  if(!allowed.success) return error('rate_limited',429,{...headers,'Retry-After':'60'});
  let body;
  try { body=await limitedJson(request); } catch { return error('invalid_body',400,headers); }
  if(!body || Array.isArray(body) || typeof body!=='object' || Object.keys(body).sort().join(',')!=='event,path,token'
    || body.event!=='pageview' || body.path!==pagePath(city) || typeof body.token!=='string' || body.token.length<1 || body.token.length>2048) return error('invalid_event',400,headers);
  if(!await verify(body.token,city,env)) return error('challenge_rejected',403,headers);
  const admission=crypto.randomUUID();
  // D1 batch is transactional. The admission nonce makes statement 2 conditional
  // on THIS request being admitted, even when an existing bucket is already full.
  const result=await env.DB.batch([
    env.DB.prepare(LIMIT_SQL).bind(bucket,Math.floor(now/60000)*60+120,admission),
    env.DB.prepare(TOTAL_SQL).bind(city,countryFromEdge(request),new Date(now).toISOString(),bucket,admission),
  ]);
  if(!result[1].results?.length) return error('collection_limit',429,{...headers,'Retry-After':'60'});
  return response({accepted:true},202,undefined,headers);
}
async function readStats(env,city) {
  const {results}=await env.DB.prepare('SELECT country,pv,started_at FROM country_totals WHERE city=?1').bind(city).all();
  return publishStats(city,results);
}
async function read(request,env,ctx,city,kind,lang) {
  // Canonical cache key ignores arbitrary query strings to prevent cache pollution.
  const u=new URL(request.url); u.search='';
  if(kind==='chart') u.searchParams.set('lang',lang);
  const key=new Request(u.toString());
  const cache=globalThis.caches?.default;
  const cached=cache && await cache.match(key);
  if(cached) {
    const h=new Headers(cached.headers); for(const [k,v] of Object.entries(cors(request))) h.set(k,v);
    return new Response(request.method==='HEAD'?null:cached.body,{status:cached.status,headers:h});
  }
  const stats=await readStats(env,city);
  const result=kind==='chart' ? response(renderChart(stats,lang),200,'image/svg+xml; charset=utf-8',{'Cache-Control':'public, max-age=300'})
    : response(stats,200,undefined,{'Cache-Control':'public, max-age=300'});
  if(cache && ctx?.waitUntil) ctx.waitUntil(cache.put(key,result.clone()));
  const h=new Headers(result.headers); for(const [k,v] of Object.entries(cors(request))) h.set(k,v);
  return new Response(request.method==='HEAD'?null:result.body,{status:result.status,headers:h});
}
export default {
  async fetch(request,env,ctx) {
    const u=new URL(request.url);
    const match=/^\/v1\/(events|stats|chart)\/([a-z]+)(\.svg)?$/.exec(u.pathname);
    if(!match || !validCity(match[2]) || (match[1]==='chart')!==!!match[3]) return error('not_found',404);
    const [,kind,city]=match;
    if(request.method==='OPTIONS' && kind==='events') {
      if(request.headers.get('Origin')!==ALLOWED_ORIGIN || request.headers.get('Access-Control-Request-Method')!=='POST') return error('origin_forbidden',403);
      const requested=(request.headers.get('Access-Control-Request-Headers')??'').toLowerCase().split(',').map(x=>x.trim()).filter(Boolean);
      if(requested.some(x=>!['content-type'].includes(x))) return error('headers_forbidden',403);
      return new Response(null,{status:204,headers:{...HEADERS,...cors(request),'Access-Control-Allow-Methods':'POST','Access-Control-Allow-Headers':'Content-Type','Access-Control-Max-Age':'600'}});
    }
    if((kind==='events' && request.method!=='POST') || (kind!=='events' && !['GET','HEAD'].includes(request.method))) return error('method_not_allowed',405,{'Allow':kind==='events'?'POST, OPTIONS':'GET, HEAD'});
    if(!configured(env)) return error('not_connected',503,cors(request));
    const lang=u.searchParams.get('lang')??'en';
    if(kind==='chart' && !LANGUAGES.includes(lang)) return error('language_invalid',400);
    try {
      return kind==='events' ? await collect(request,env,city) : await read(request,env,ctx,city,kind,lang);
    } catch {
      // Do not log request, IP, token, secrets, or provider error bodies.
      return error('analytics_unavailable',503,cors(request));
    }
  },
  async scheduled(_event,env,ctx) {
    const clean=async()=>{
      if(!env.DB) return;
      await env.DB.batch([
        env.DB.prepare("DELETE FROM short_limits WHERE expires_at<=unixepoch('now')"),
        env.DB.prepare("DELETE FROM daily_budget WHERE day<date('now','-2 days')"),
      ]);
    };
    ctx.waitUntil(clean());
  },
};
