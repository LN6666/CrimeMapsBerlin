/** Validate routing fields before they become fetch paths. No semantic/GIS decisions here. */
const slug = /^[a-z][a-z0-9_]{0,79}$/;
const tile = /^-?\d{1,7}_-?\d{1,7}$/;
const month = /^\d{4}-(0[1-9]|1[0-2])$/;
function fail(): never { throw Error("Invalid data routing manifest"); }
export function safeLocalDataPath(path: string): string {
  if (typeof path !== "string" || path.length > 512 || !path.startsWith("/") ||
      path.startsWith("//") || !/^\/[A-Za-z0-9_./-]+$/.test(path) ||
      path.split("/").slice(1).some(p => !p || p === "." || p === "..")) fail();
  return path;
}
export function assertManifestPaths(value: {
  schema_version: number; generation: string; months: Record<string, unknown>;
  tile_index: { pois: string[]; roads: string[] }; tile_size: number[]; categories: string[];
}, dataRoot: string): void {
  safeLocalDataPath(dataRoot);
  if (!value || value.schema_version !== 2 ||
      !/^[a-f0-9]{16}-\d{8}T\d{6}$/.test(value.generation) ||
      !value.months || Array.isArray(value.months) ||
      Object.keys(value.months).length > 600 ||
      !Object.keys(value.months).every(k => month.test(k)) ||
      !Array.isArray(value.tile_size) || value.tile_size.length !== 2 ||
      !value.tile_size.every(n => Number.isFinite(n) && n > 0 && n <= 180) ||
      !Array.isArray(value.categories) || value.categories.length > 100 ||
      !value.categories.every(k => typeof k === "string" && slug.test(k)) ||
      !value.tile_index) fail();
  for (const kind of ["pois", "roads"] as const) {
    const keys = value.tile_index[kind];
    if (!Array.isArray(keys) || keys.length > 200000 || new Set(keys).size !== keys.length) fail();
    for (const key of keys) {
      if (typeof key !== "string") fail();
      const parts = key.split("/");
      if (kind === "roads" ? !tile.test(key) :
          parts.length !== 2 || !slug.test(parts[0]) || !tile.test(parts[1])) fail();
    }
  }
}
export function safeExternalURL(value: string): string | null {
  if (typeof value !== "string" || value.length > 4096 || /[\u0000-\u0020\u007f\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password &&
      (!url.port || url.port === "443") ? url.href : null;
  } catch { return null; }
}
/** Bound downloads even if Content-Length is absent or dishonest. Preserve caller cancellation. */
export async function fetchDataJSON<T>(url: string, signal?: AbortSignal, onRead?: (weight: number) => void): Promise<T> {
  safeLocalDataPath(url);
  const response = await fetch(url, { signal, redirect: "error", credentials: "omit", referrerPolicy: "no-referrer" });
  if (!response.ok) throw Error(`Data request failed (${response.status})`);
  const limit = 64 * 1024 * 1024;
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > limit)) {
    await response.body?.cancel(); throw Error("Data response exceeds limit");
  }
  const reader = response.body?.getReader();
  if (!reader) throw Error("Missing data response body");
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0, body = "";
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      const part = await reader.read();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > limit) throw Error("Data response exceeds limit");
      body += decoder.decode(part.value, { stream: true });
    }
    body += decoder.decode();
    // Serialized UTF-16 weight for cache budgets; this is not a JS heap bound.
    onRead?.(body.length * 2);
    return JSON.parse(body) as T;
  } catch (error) {
    await reader.cancel().catch(() => {}); throw error;
  } finally { reader.releaseLock(); }
}
