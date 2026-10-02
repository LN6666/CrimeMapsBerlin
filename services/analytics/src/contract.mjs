export const CITIES = Object.freeze(['berlin','hamburg','munich','cologne','frankfurt','dusseldorf','stuttgart','leipzig','dortmund','bremen','essen','dresden','hannover','nuremberg']);
export const LANGUAGES = Object.freeze(['de', 'en', 'zh']);
export const MIN_PUBLIC_SAMPLE = 20;
export const ROUNDING = 10;
export const DAILY_CAP = 5000;
export const SHORT_LIMIT = 10;
export const MAX_BODY_BYTES = 4096;
export const ALLOWED_ORIGIN = 'https://ln6666.github.io';
export const pagePath = city => `/crimemaps-${city[0].toUpperCase()}${city.slice(1)}/`;
export const action = city => `pv_${city}`;
export function validCity(city) { return CITIES.includes(city); }
export function countryFromEdge(request) {
  // Never read CF-IPCountry or client JSON. Incoming request.cf is set by edge.
  const code = request.cf?.country;
  if (!/^[A-Z]{2}$/.test(code ?? '') || ['XX', 'T1', 'ZZ'].includes(code)) return 'ZZ';
  try { return new Intl.DisplayNames(['en'], {type:'region', fallback:'none'}).of(code) ? code : 'ZZ'; }
  catch { return 'ZZ'; }
}
export function publishStats(city, rows, now = new Date()) {
  const total = rows.reduce((n, r) => n + Number(r.pv), 0);
  const round = n => Math.floor(n / ROUNDING) * ROUNDING;
  // No dates of individual visits and no low-volume country entries.
  const visible = rows.filter(r => r.country !== 'ZZ' && r.pv >= MIN_PUBLIC_SAMPLE)
    .sort((a,b) => b.pv - a.pv || a.country.localeCompare(b.country)).slice(0,8);
  const published = new Set(visible.map(r => r.country));
  const other = rows.filter(r => !published.has(r.country)).reduce((n,r) => n + Number(r.pv),0);
  const countries = visible.map(r => ({code:r.country,pv:round(r.pv)}));
  if (other >= MIN_PUBLIC_SAMPLE) countries.push({code:'OTHER',pv:round(other)});
  return {
    schema_version:1, city, status:'live', metric:'accepted_opt_in_pageviews',
    total_pv:total >= MIN_PUBLIC_SAMPLE ? round(total) : null,
    countries, generated_at:now.toISOString(),
    collection_start_date:rows.map(r => r.started_at?.slice(0,10)).filter(Boolean).sort()[0] ?? null,
    unique_visitors:null, unique_visitors_measured:false,
    privacy:{minimum_sample:MIN_PUBLIC_SAMPLE,rounding:ROUNDING,omitted_small_groups:true},
    limits:{daily_accepted_cap:DAILY_CAP,cache_seconds:300,bot_filter:'turnstile_and_short_rate_limits'},
  };
}
