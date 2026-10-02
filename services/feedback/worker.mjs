export const CITIES = ['berlin','hamburg','munich','cologne','frankfurt','dusseldorf','stuttgart','leipzig','dortmund','bremen','essen','dresden','hannover','nuremberg'];
export const POLICY = 'private-feedback-v1';
const encoder = new TextEncoder(), RETENTION = 30 * 86400;
const validID = v => typeof v === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const tokenOK = v => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
const hex = data => Array.from(new Uint8Array(data), b => b.toString(16).padStart(2, '0')).join('');
async function hash(value) { return hex(await crypto.subtle.digest('SHA-256', encoder.encode(value))); }
async function hmac(secret, value) {
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), {name:'HMAC',hash:'SHA-256'}, false, ['sign']);
  return hex(await crypto.subtle.sign('HMAC', key, encoder.encode(value)));
}
function safeHTTPS(value, originOnly = false) {
  if (typeof value !== 'string' || /[\u0000-\u0020\u007f]/.test(value)) return null;
  try {const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password && !u.port &&
    (!originOnly || u.origin === value) ? u.href : null;} catch {return null;}
}
function origins(env) {
  return (env.ALLOWED_ORIGINS ?? '').split(',').map(v => v.trim()).filter(v => safeHTTPS(v,true));
}
function configured(env) {
  return env.ENABLED === 'true' && env.DB && typeof env.REQUEST_LIMITER?.limit === 'function' && tokenOK(env.RATE_SECRET) && tokenOK(env.ADMIN_TOKEN) &&
    typeof env.TURNSTILE_SECRET === 'string' && env.TURNSTILE_SECRET.length >= 20 && !/^[123]x0{10}/.test(env.TURNSTILE_SECRET) &&
    typeof env.TURNSTILE_HOSTNAME === 'string' && /^[a-z0-9.-]+$/.test(env.TURNSTILE_HOSTNAME) &&
    typeof env.OPERATOR_NAME === 'string' && env.OPERATOR_NAME.trim() && !/REPLACE|PLACEHOLDER|TODO/i.test(env.OPERATOR_NAME) &&
    safeHTTPS(env.PRIVACY_URL) && origins(env).length > 0;
}
function response(status, value, origin = null) {
  const headers = {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
    'Referrer-Policy':'no-referrer','Vary':'Origin','Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'"};
  if (origin) {headers['Access-Control-Allow-Origin'] = origin; headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'; headers['Access-Control-Allow-Headers'] = 'Content-Type';}
  return new Response(status === 204 ? null : JSON.stringify(value), {status, headers});
}
async function readBody(request) {
  if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') throw {status:415};
  const length = Number(request.headers.get('content-length') ?? 0);
  if (length > 12288) throw {status:413};
  const reader = request.body?.getReader(); if (!reader) throw {status:400};
  let total = 0; const parts = [];
  try {
    for (;;) {
      const {done,value} = await reader.read(); if (done) break;
      total += value.length; if (total > 12288) {await reader.cancel(); throw {status:413};} parts.push(value);
    }
  } finally {reader.releaseLock();}
  const bytes = new Uint8Array(total); let offset = 0;
  for (const p of parts) {bytes.set(p,offset); offset += p.length;}
  try {const body = JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw Error(); return body;
  } catch {throw {status:400};}
}
function keys(body, allowed) {return Object.keys(body).every(k => allowed.includes(k));}
async function bump(db, bucket, limit, expiry) {
  const result = await db.prepare('INSERT INTO budget(bucket,n,expires_at) VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET n=n+1 WHERE n < ? RETURNING n').bind(bucket,expiry,limit).first();
  return !!result;
}
async function rate(request, env, action, now, limit) {
  // Cloudflare supplies this header; no forwarded/user agent/cookie identifiers are read.
  const ip = request.headers.get('CF-Connecting-IP');
  let validIP = !!ip && /^(\d{1,3}\.){3}\d{1,3}$/.test(ip) && ip.split('.').every(n => Number(n) <= 255);
  if (ip?.includes(':')) {try {validIP = new URL(`http://[${ip}]/`).hostname.startsWith('[');} catch {validIP = false;}}
  if (!request.cf?.colo || !validIP || ip.length > 64) throw {status:503};
  const day = Math.floor(now / 86400), hour = Math.floor(now / 3600);
  // Check the global cap first; exhausted budgets cannot allocate new IP buckets.
  if (!await bump(env.DB, `attempts:${day}`,1000,(day + 1) * 86400)) throw {status:429};
  const digest = await hmac(env.RATE_SECRET, `${day}:${ip}`);
  if (!await bump(env.DB, `${action}:${hour}:${digest}`,limit,(day + 1) * 86400)) throw {status:429};
}
async function challenge(token, env, fetcher) {
  const r = await fetcher('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
    method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams({secret:env.TURNSTILE_SECRET,response:token}), signal:AbortSignal.timeout(8000),
  });
  if (!r.ok) return false;
  const result = await r.json();
  return result.success === true && result.hostname === env.TURNSTILE_HOSTNAME && result.action === 'feedback';
}
async function adminAuthorised(request, env) {
  if (!tokenOK(env.ADMIN_TOKEN)) return false;
  const provided = request.headers.get('authorization') ?? '';
  if (!/^Bearer [0-9a-f]{64}$/.test(provided)) return false;
  const a = await hash(provided.slice(7)), b = await hash(env.ADMIN_TOKEN);
  let diff = 0; for (let i=0;i<a.length;i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i); return diff === 0;
}
export async function prune(env, now = Math.floor(Date.now()/1000)) {
  await env.DB.batch([
    env.DB.prepare('DELETE FROM feedback WHERE expires_at <= ?').bind(now),
    env.DB.prepare('DELETE FROM budget WHERE expires_at <= ?').bind(now),
  ]);
}
export async function handle(request, env, runtime = {}) {
  const fetcher = runtime.fetch ?? fetch, now = Math.floor((runtime.now ?? Date.now())/1000);
  const url = new URL(request.url), origin = request.headers.get('origin'), allowed = origin && origins(env).includes(origin);
  if (url.username || url.password) return response(400,{error:'invalid_request'});
  const admin = url.pathname.startsWith('/admin/');
  if (admin) {
    // Browser access is denied even when its Origin would be allowed for public intake.
    if (origin || !configured(env) || !await adminAuthorised(request,env)) return response(404,{error:'not_found'});
  } else if (!allowed) return response(403,{error:'origin_denied'});
  const cors = admin ? null : origin;
  try {
    if (request.method === 'OPTIONS' && !admin) {
      const method = request.headers.get('Access-Control-Request-Method');
      const headers = (request.headers.get('Access-Control-Request-Headers') ?? '').toLowerCase().split(',').map(h=>h.trim()).filter(Boolean);
      if (!['GET','POST'].includes(method) || headers.some(h=>h!=='content-type')) return response(403,{error:'preflight_denied'},cors);
      return response(204,null,cors);
    }
    if (url.pathname === '/health' && request.method === 'GET') {
      const city = url.searchParams.get('city'); if (!CITIES.includes(city)) return response(400,{error:'invalid_city'},cors);
      return response(200,{enabled:!!configured(env),city,policyVersion:POLICY},cors);
    }
    if (!configured(env)) return response(503,{error:'unavailable'},cors);
    const platformBudget = await env.REQUEST_LIMITER.limit({key:'private-feedback-receiver'});
    if (!platformBudget.success) return response(429,{error:'rate_limited'},cors);
    if (admin) {
      await rate(request,env,'admin',now,60);
      if (url.pathname === '/admin/feedback' && request.method === 'GET') {
        const city = url.searchParams.get('city'), after = url.searchParams.get('after') ?? '';
        if (!CITIES.includes(city) || after && !/^\d{1,12}\/[0-9a-f-]{36}$/.test(after)) return response(400,{error:'invalid_request'});
        const [created,id] = after ? after.split('/') : ['0',''];
        const rows = await env.DB.prepare('SELECT id,city,kind,source_id,message,created_at,expires_at FROM feedback WHERE city=? AND expires_at>? AND (created_at>? OR (created_at=? AND id>?)) ORDER BY created_at,id LIMIT 50')
          .bind(city,now,Number(created),Number(created),id).all();
        const last = rows.results.at(-1);
        return response(200,{items:rows.results,next:last ? `${last.created_at}/${last.id}` : null});
      }
      if (url.pathname === '/admin/feedback' && request.method === 'POST') {
        const body = await readBody(request); if (!keys(body,['id','action']) || !validID(body.id) || body.action !== 'delete') throw {status:400};
        await env.DB.prepare('DELETE FROM feedback WHERE id=?').bind(body.id).run(); return response(204,null);
      }
      return response(404,{error:'not_found'});
    }
    if (request.method !== 'POST' || !['/feedback','/retract'].includes(url.pathname)) return response(404,{error:'not_found'},cors);
    const body = await readBody(request);
    if (url.pathname === '/retract') {
      if (!keys(body,['id','deletion_token']) || !validID(body.id) || !tokenOK(body.deletion_token)) throw {status:400};
      await rate(request,env,'retract',now,20);
      await env.DB.prepare('DELETE FROM feedback WHERE id=? AND deletion_hash=?').bind(body.id,await hash(body.deletion_token)).run();
      // Do not expose existence or token validity to a visitor.
      return response(204,null,cors);
    }
    if (!keys(body,['city','kind','message','source_id','challenge_token']) || !CITIES.includes(body.city) ||
        !['correction','accessibility','privacy','other'].includes(body.kind) || typeof body.message !== 'string' ||
        body.message.trim().length < 10 || body.message.trim().length > 2000 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(body.message) ||
        body.source_id != null && (typeof body.source_id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$/.test(body.source_id)) ||
        typeof body.challenge_token !== 'string' || body.challenge_token.length < 10 || body.challenge_token.length > 2048) throw {status:400};
    await rate(request,env,'feedback',now,5);
    if (!await challenge(body.challenge_token,env,fetcher)) return response(403,{error:'challenge_failed'},cors);
    const day = Math.floor(now / 86400);
    if (!await bump(env.DB,`received:${day}`,500,(day + 1) * 86400)) throw {status:429};
    // Requests also remove expired rows; cron handles inactive periods.
    await prune(env,now);
    const id = crypto.randomUUID(), deletionToken = hex(crypto.getRandomValues(new Uint8Array(32))), expiresAt = now + RETENTION;
    await env.DB.prepare('INSERT INTO feedback(id,city,kind,source_id,message,created_at,expires_at,deletion_hash) VALUES(?,?,?,?,?,?,?,?)')
      .bind(id,body.city,body.kind,body.source_id ?? null,body.message.trim(),now,expiresAt,await hash(deletionToken)).run();
    return response(201,{id,deletionToken,expiresAt:new Date(expiresAt*1000).toISOString()},cors);
  } catch (error) {
    // Never log a request, message, IP, token, source text or database error.
    const status = [400,413,415,429,503].includes(error?.status) ? error.status : 503;
    return response(status,{error:status===429?'rate_limited':status===503?'unavailable':'invalid_request'},cors);
  }
}
export default {fetch:handle, async scheduled(_event,env) {if (env.DB) await prune(env);}};
