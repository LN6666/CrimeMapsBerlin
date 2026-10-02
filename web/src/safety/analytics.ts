import { analyticsCopy, type AnalyticsKey, type AnalyticsLanguage } from "./analytics-copy";
export type { AnalyticsLanguage } from "./analytics-copy";
export interface AnalyticsOptions {
  city: string;
  language: AnalyticsLanguage;
  endpoint?: string;
  siteKey?: string; // Public Turnstile sitekey; server secrets never belong here.
  translate?: (key: AnalyticsKey, values?: Record<string, string>) => string;
}
interface PublicStats {
  schema_version: number; city: string; status: string; metric: string;
  total_pv: number | null; countries: { code: string; pv: number }[];
  generated_at: string; unique_visitors_measured: boolean;
  privacy: { minimum_sample: number; rounding: number };
}
interface Turnstile {
  render: (container: HTMLElement, options: Record<string, unknown>) => string;
  remove: (id: string) => void;
}
type AnalyticsWindow = Window & { turnstile?: Turnstile };
const cities = new Set(["berlin", "hamburg", "munich", "cologne", "frankfurt", "dusseldorf", "stuttgart", "leipzig", "dortmund", "bremen", "essen", "dresden", "hannover", "nuremberg"]);
const attempted = new Set<string>(); // In-memory lifecycle guard, never a visitor counter.
let turnstileLoad: Promise<Turnstile> | undefined;
function loadTurnstile(): Promise<Turnstile> {
  const w = window as AnalyticsWindow;
  if (w.turnstile) return Promise.resolve(w.turnstile);
  if (turnstileLoad) return turnstileLoad;
  turnstileLoad = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true; script.referrerPolicy = "no-referrer";
    const timer = window.setTimeout(() => { script.remove(); reject(new Error("challenge_timeout")); }, 10000);
    script.onload = () => { window.clearTimeout(timer); w.turnstile ? resolve(w.turnstile) : reject(new Error("challenge_missing")); };
    script.onerror = () => { window.clearTimeout(timer); script.remove(); reject(new Error("challenge_unavailable")); };
    document.head.append(script);
  });
  turnstileLoad.catch(() => { turnstileLoad = undefined; });
  return turnstileLoad;
}
function validStats(s: unknown, city: string): s is PublicStats {
  if (!s || typeof s !== "object") return false;
  const v = s as PublicStats;
  return v.schema_version === 1 && v.status === "live" && v.city === city && v.metric === "accepted_opt_in_pageviews"
    && v.unique_visitors_measured === false && v.privacy?.minimum_sample === 20 && v.privacy?.rounding === 10
    && (v.total_pv === null || (Number.isSafeInteger(v.total_pv) && v.total_pv >= 20 && v.total_pv % 10 === 0))
    && Array.isArray(v.countries) && v.countries.length <= 9
    && v.countries.every(r => /^(?:[A-Z]{2}|OTHER)$/.test(r.code) && Number.isSafeInteger(r.pv) && r.pv >= 20 && r.pv % 10 === 0)
    && new Set(v.countries.map(r => r.code)).size === v.countries.length && Number.isFinite(Date.parse(v.generated_at));
}
export function mountAnalytics(container: HTMLElement, options: AnalyticsOptions) {
  let language = options.language, alive = true, stats: PublicStats | undefined;
  let dataState: AnalyticsKey = "analytics.loading", countState: AnalyticsKey | undefined;
  let widgetId: string | undefined, api: Turnstile | undefined;
  let started = false;
  const controllers = new Set<AbortController>();
  const city = options.city, lifecycleKey = `${city}:${window.location.pathname}`;
  let endpoint: string | undefined;
  try {
    const u = new URL(options.endpoint ?? "");
    if (u.protocol === "https:" && !u.username && !u.password && !u.search && !u.hash && u.pathname === "/" && cities.has(city)) endpoint = u.origin;
  } catch { /* Explicit disconnected state below. */ }
  const privacyBlocked = (navigator as Navigator & {globalPrivacyControl?: boolean}).globalPrivacyControl === true || navigator.doNotTrack === "1";
  const text = (key: AnalyticsKey, values: Record<string, string> = {}) => {
    if (options.translate) return options.translate(key, values);
    let value: string = analyticsCopy[language][key];
    for (const [k, v] of Object.entries(values)) value = value.replace(`{${k}}`, v);
    return value;
  };
  const element = <T extends keyof HTMLElementTagNameMap>(tag: T, className = "") => {
    const e = document.createElement(tag); e.className = className; return e;
  };
  const section = element("section", "analytics-summary");
  const title = element("h2"), summary = element("p"), details = element("details"), caption = element("summary");
  const list = element("ul"), updated = element("p"), note = element("p"), privacy = element("p");
  const provider = element("p"), retention = element("p"), providerLink = element("a");
  providerLink.href = "https://www.cloudflare.com/turnstile-privacy-policy/"; providerLink.target = "_blank"; providerLink.rel = "noopener noreferrer";
  const button = element("button"), count = element("p"), challenge = element("div", "analytics-challenge");
  summary.setAttribute("role", "status"); count.setAttribute("role", "status");
  button.type = "button";
  details.append(caption, list, updated, note); section.append(title, summary, details, privacy, provider, retention, providerLink, button, count, challenge); container.replaceChildren(section);
  const render = () => {
    if (!alive) return;
    title.textContent = text("analytics.title"); section.setAttribute("aria-label", text("analytics.title"));
    summary.textContent = stats ? stats.total_pv === null ? text("analytics.small") : text("analytics.pv", {count: new Intl.NumberFormat(language).format(stats.total_pv)}) : text(dataState);
    details.hidden = !stats; caption.textContent = text("analytics.countries"); list.replaceChildren();
    for (const row of stats?.countries ?? []) {
      const li = element("li");
      const name = row.code === "OTHER" ? text("analytics.other") : new Intl.DisplayNames([language], {type: "region"}).of(row.code) ?? row.code;
      li.textContent = `${name}: ${new Intl.NumberFormat(language).format(row.pv)}`; list.append(li);
    }
    updated.textContent = stats ? text("analytics.generated", {time: new Date(stats.generated_at).toLocaleString(language, {timeZoneName: "short"})}) : "";
    note.textContent = text("analytics.note"); privacy.textContent = text("analytics.privacy");
    privacy.hidden = !endpoint || !options.siteKey;
    provider.textContent = text("analytics.providerProcessing"); retention.textContent = text("analytics.retention"); providerLink.textContent = text("analytics.providerPolicy");
    provider.hidden = privacy.hidden; retention.hidden = privacy.hidden; providerLink.hidden = privacy.hidden;
    button.textContent = text("analytics.enable"); button.hidden = !endpoint || !options.siteKey || privacyBlocked || attempted.has(lifecycleKey);
    button.disabled = started || !stats; count.textContent = countState ? text(countState) : privacyBlocked && endpoint ? text("analytics.preference") : "";
  };
  async function request(path: string, init: RequestInit = {}) {
    const controller = new AbortController(); controllers.add(controller);
    const timer = window.setTimeout(() => controller.abort(), 4500);
    try {
      const response = await fetch(`${endpoint}${path}`, {...init, mode: "cors", credentials: "omit", referrerPolicy: "no-referrer", cache: "no-store", signal: controller.signal});
      const data: unknown = response.ok ? await response.json() : null;
      return {ok: response.ok, status: response.status, data};
    } finally { window.clearTimeout(timer); controllers.delete(controller); }
  }
  async function refresh() {
    try {
      const response = await request(`/v1/stats/${city}`);
      if (!response.ok) throw new Error("unavailable");
      const result: unknown = response.data;
      if (!validStats(result, city)) throw new Error("invalid_stats");
      if (alive) {stats = result; render();}
    } catch {
      if (alive) {stats = undefined; dataState = "analytics.unavailable"; render();}
    }
  }
  const removeChallenge = () => {
    if (api && widgetId) { api.remove(widgetId); widgetId = undefined; }
    challenge.replaceChildren();
  };
  async function submit(token: string) {
    if (!alive || attempted.has(lifecycleKey)) return;
    attempted.add(lifecycleKey); render();
    try {
      const response = await request(`/v1/events/${city}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({event: "pageview", path: `/crimemaps-${city[0].toUpperCase()}${city.slice(1)}/`, token})});
      const result: unknown = response.data;
      countState = response.status === 202 && (result as {accepted?: boolean} | null)?.accepted === true ? "analytics.accepted" : "analytics.notCounted";
      if (alive && countState === "analytics.accepted") void refresh();
    } catch {countState = "analytics.notCounted";}
    finally {if (alive) { removeChallenge(); render(); }}
  }
  button.addEventListener("click", async () => {
    if (started || !alive || privacyBlocked || !stats || attempted.has(lifecycleKey)) return;
    started = true; countState = "analytics.verifying"; render();
    try {
      api = await loadTurnstile(); if (!alive) return;
      widgetId = api.render(challenge, {
        sitekey: options.siteKey, action: `pv_${city}`, cData: city, language: language === "zh" ? "zh-cn" : language,
        size: "compact", appearance: "interaction-only", "response-field": false,
        callback: (token: string) => { void submit(token); },
        "error-callback": () => {countState = "analytics.notCounted"; removeChallenge(); render();},
        "expired-callback": () => {countState = "analytics.notCounted"; removeChallenge(); render();},
        "timeout-callback": () => {countState = "analytics.notCounted"; removeChallenge(); render();},
      });
    } catch { if (alive) {countState = "analytics.notCounted"; render();} }
  });
  if (!endpoint) dataState = "analytics.notConnected";
  render(); if (endpoint) void refresh();
  return {
    setLanguage(next: AnalyticsLanguage) { language = next; render(); },
    destroy() { alive = false; for (const c of controllers) c.abort(); controllers.clear(); removeChallenge(); section.remove(); },
  };
}
