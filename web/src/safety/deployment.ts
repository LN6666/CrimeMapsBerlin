export const cityIds = [
  "berlin", "hamburg", "munich", "cologne", "frankfurt", "dusseldorf",
  "stuttgart", "leipzig", "dortmund", "bremen", "essen", "dresden", "hannover", "nuremberg",
] as const;
export type CityId = (typeof cityIds)[number];
export function cityId(value: string): CityId {
  if (!cityIds.includes(value as CityId)) throw new Error("Unknown repository city");
  return value as CityId;
}
export const repositoryCity = cityId(import.meta.env?.VITE_CRIMEMAPS_CITY || "berlin");
export function repositoryName(city: CityId) {
  return `crimemaps-${city[0].toUpperCase()}${city.slice(1)}`;
}
export function assetPath(path: string, base = import.meta.env?.BASE_URL || "/") {
  if (!base.startsWith("/") || !base.endsWith("/") || base.includes(".."))
    throw new Error("Invalid application base path");
  if (!path.startsWith("/") || path.includes("..") || path.includes("\\"))
    throw new Error("Invalid application asset path");
  return `${base}${path.slice(1)}`;
}
export interface NavigationTargets {
  origin: string;
  portalPath: string;
  berlinMapPath: string;
}
const navigationTargets: NavigationTargets = {
  origin: import.meta.env?.VITE_MAP_ORIGIN || "https://ln6666.github.io",
  portalPath: import.meta.env?.VITE_PORTAL_PATH || "/crimemaps-Berlin/",
  berlinMapPath: import.meta.env?.VITE_BERLIN_MAP_PATH || "/crimemaps-Berlin/map/",
};
function navigationURL(path: string, targets: NavigationTargets) {
  const origin = new URL(targets.origin);
  if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password ||
      origin.search || origin.hash || origin.pathname !== "/" ||
      !/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(path)) throw new Error("Invalid navigation target");
  return new URL(path, origin.origin);
}
function addLanguage(outgoing: URLSearchParams, search: string) {
  const lang = new URLSearchParams(search).get("lang");
  if (lang === "zh-CN") outgoing.set("lang", "zh");
  else if (lang && ["de", "en", "zh"].includes(lang)) outgoing.set("lang", lang);
}
export function portalDestination(search: string, targets = navigationTargets) {
  const url = navigationURL(targets.portalPath, targets);
  addLanguage(url.searchParams, search);
  return url.href;
}
export function cityDestination(city: CityId, search: string, month?: string, targets = navigationTargets) {
  cityId(city);
  const incoming = new URLSearchParams(search), outgoing = new URLSearchParams();
  addLanguage(outgoing, search);
  const selected = month && /^\d{4}-(0[1-9]|1[0-2])$/.test(month) ? month : incoming.get("month");
  if (selected && /^\d{4}-(0[1-9]|1[0-2])$/.test(selected)) outgoing.set("month", selected);
  const url = navigationURL(city === "berlin" ? targets.berlinMapPath : `/${repositoryName(city)}/`, targets);
  url.search = outgoing.toString();
  return url.href;
}
export function requestedMonth(search: string, available: readonly string[], fallback: string) {
  const key = new URLSearchParams(search).get("month");
  return key && available.includes(key) ? key : fallback;
}
