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
export function cityDestination(city: CityId, search: string, month?: string) {
  const incoming = new URLSearchParams(search), outgoing = new URLSearchParams();
  const lang = incoming.get("lang");
  if (lang && ["de", "en", "zh", "zh-CN"].includes(lang)) outgoing.set("lang", lang);
  const selected = month ?? incoming.get("month");
  if (selected && /^\d{4}-(0[1-9]|1[0-2])$/.test(selected)) outgoing.set("month", selected);
  const query = outgoing.toString();
  return `https://ln6666.github.io/${repositoryName(city)}/${query ? `?${query}` : ""}`;
}
export function requestedMonth(search: string, available: readonly string[], fallback: string) {
  const key = new URLSearchParams(search).get("month");
  return key && available.includes(key) ? key : fallback;
}
