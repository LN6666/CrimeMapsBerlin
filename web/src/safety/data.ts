import {assertManifestPaths,fetchDataJSON} from "./security";
import type { Bundle, FC, Month, PoliceEvent, Properties } from "./model";
import { empty } from "./model";
export interface Manifest {
  schema_version: 2;
  poi_encoding?: "point-radius-v1";
  poi_scope_groups?:Record<string,{label_key:string;kinds:string[]}>;
  translations?: Partial<Record<"de"|"en"|"zh",Record<string,string>>>;
  city: string;
  status?: string;
  owner_approved?: boolean;
  publication_ready?: boolean;
  publication_blocks?: string[];
  retrieved_at: string;
  generation: string;
  coverage: {
    discovered: number;
    fetched: number;
    failed: number;
    pending: number;
  };
  months: Record<string, { count: number }>;
  categories: string[];
  tile_index: { pois: string[]; roads: string[] };
  tile_size: [number, number];
  catalog: Bundle["catalog"];
  zones: Bundle["zones"];
  metadata: Properties;
}
interface MonthData extends Month {
  events: PoliceEvent[];
}
// Bounded LRU cache: tiles and months do not accumulate during long map sessions.
export class LRU<T> {
  private values = new Map<string, { value: T; weight: number }>();
  private used = 0;
  constructor(private capacity: number, private maxWeight = Infinity) {
    if (!Number.isInteger(capacity) || capacity < 1 || !(maxWeight > 0))
      throw Error("Invalid cache capacity");
  }
  get(key: string) {
    const entry = this.values.get(key);
    if (entry) { this.values.delete(key); this.values.set(key, entry); }
    return entry?.value;
  }
  set(key: string, value: T, weight = 1) {
    if (!Number.isFinite(weight) || weight < 0) throw Error("Invalid cache weight");
    const old = this.values.get(key);
    if (old) { this.used -= old.weight; this.values.delete(key); }
    // Oversize records can be displayed once but cannot defeat the session cache bound.
    if (weight > this.maxWeight) return;
    this.values.set(key, { value, weight }); this.used += weight;
    while (this.values.size > this.capacity || this.used > this.maxWeight) {
      const first = this.values.keys().next().value!;
      this.used -= this.values.get(first)!.weight; this.values.delete(first);
    }
  }
  get size() { return this.values.size; }
  get weight() { return this.used; }
}
export function tileKeys(
  bounds: [number, number, number, number],
  size: [number, number],
  available: Set<string>,
  max = 64,
) {
  const [west, south, east, north] = bounds,
    [dx, dy] = size;
  if (!bounds.every(Number.isFinite) || !size.every((v) => Number.isFinite(v) && v > 0) || Math.abs(west)>180 || Math.abs(east)>180 || Math.abs(south)>90 || Math.abs(north)>90 || west > east || south > north)
    throw Error("无效地图范围");
  const keys = [];
  // Never enumerate an unbounded world-sized grid.
  const x0 = Math.floor(west / dx),
    x1 = Math.floor(east / dx),
    y0 = Math.floor(south / dy),
    y1 = Math.floor(north / dy);
  if (![x0,x1,y0,y1].every(Number.isSafeInteger)) throw Error("Invalid tile grid");
  if ((x1 - x0 + 1) * (y1 - y0 + 1) > max) return [];
  for (let x = x0; x <= x1; x++)
    for (let y = y0; y <= y1; y++) {
      const key = `${x}_${y}`;
      if (available.has(key)) keys.push(key);
    }
  return keys;
}
export class DataClient {
  private tiles = new LRU<FC>(80, 20 * 1024 * 1024);
  private months = new LRU<MonthData>(3, 24 * 1024 * 1024);
  private poiCoordinates: Set<string>;
  private available: { pois: Set<string>; roads: Set<string> };
  readonly base: string;
  constructor(readonly manifest: Manifest, dataRoot = "/safety") {
    assertManifestPaths(manifest,dataRoot);
    if (
      manifest.schema_version !== 2 ||
      !/^[a-f0-9]{16}-\d{8}T\d{6}$/.test(manifest.generation)
    )
      throw Error("不支持的数据清单");
    if(manifest.poi_scope_groups){for(const [group,value] of Object.entries(manifest.poi_scope_groups)){if(!/^[a-z][a-z0-9_]{0,79}$/.test(group)||!value||!/^[a-zA-Z0-9_.]{1,100}$/.test(value.label_key)||!Array.isArray(value.kinds)||value.kinds.length>200||!value.kinds.every(k=>/^[a-z][a-z0-9_]{0,79}$/.test(k)))throw Error("Invalid POI display groups");}}
    this.poiCoordinates = new Set(manifest.tile_index.pois.map((key) => key.split("/")[1]));
    this.base = `${dataRoot}/${manifest.generation}`;
    this.available = {
      pois: new Set(manifest.tile_index.pois),
      roads: new Set(manifest.tile_index.roads),
    };
  }
  async month(
    key: string,
    signal: AbortSignal,
  ): Promise<MonthData | undefined> {
    signal.throwIfAborted();
    if (!Object.hasOwn(this.manifest.months, key)) return undefined;
    const cached = this.months.get(key);
    if (cached) return cached;
    const { value, bytes } = await this.read<MonthData>(
      `${this.base}/months/${key}.json`,
      signal,
    );
    signal.throwIfAborted();
    this.months.set(key, value, bytes);
    return value;
  }
  async viewport(
    kind: "pois" | "roads",
    bounds: [number, number, number, number],
    signal: AbortSignal,
    placeKinds: string[] = [],
  ): Promise<FC> {
    const available =
      kind === "pois"
        ? this.poiCoordinates
        : this.available.roads;
    const coordinates = tileKeys(bounds, this.manifest.tile_size, available);
    const groups=kind==="pois"?this.manifest.poi_scope_groups:undefined;
    const selected=new Set(placeKinds);
    const nativeKinds=groups?[...new Set(placeKinds.flatMap(group=>groups[group]?.kinds??[]))]:placeKinds;
    const keys =
      kind === "pois"
        ? nativeKinds
            .flatMap((type) => coordinates.map((c) => `${type}/${c}`))
            .filter((k) => this.available.pois.has(k))
        : coordinates;
    const features = new Map<string, FC["features"][number]>();
    // Four requests at a time, abortable; avoid dozens of simultaneous downloads.
    for (let i = 0; i < keys.length; i += 4) {
      signal.throwIfAborted();
      const results = await Promise.all(
        keys.slice(i, i + 4).map(async (key) => {
          const id = `${kind}/${key}`,
            cached = this.tiles.get(id);
          if (cached) return cached;
          const { value, bytes } = await this.read<FC>(`${this.base}/${id}.json`, signal);
          signal.throwIfAborted();
          this.tiles.set(id, value, bytes);
          return value;
        }),
      );
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      for (const fc of results)
        for (const f of fc.features) {
          const id = f.properties?.id;
          if (typeof id !== "string" || !id) throw Error("Missing stable object ID");
          if(groups){if(typeof f.properties.scope_category!=="string"||!Object.hasOwn(groups,f.properties.scope_category))throw Error("Missing POI display group");if(!selected.has(f.properties.scope_category))continue;}
          // One reviewed object may intersect several tiles; render it once.
          if (!features.has(id)) features.set(id, f);
        }
    }
    return { type: "FeatureCollection", features: [...features.values()] };
  }
  get cacheStats() {
    return { tiles: this.tiles.size, tileBytes: this.tiles.weight,
      months: this.months.size, monthBytes: this.months.weight };
  }
  private async read<T>(url: string, signal?: AbortSignal): Promise<{value:T;bytes:number}> {
    signal?.throwIfAborted();
    if (!url.startsWith(`${this.base}/`)) throw Error("Invalid generation data path");
    let bytes=0;
    const value=await fetchDataJSON<T>(url,signal,(weight)=>{bytes=weight;});
    signal?.throwIfAborted();
    return {value,bytes};
  }
  async json<T>(url: string, signal?: AbortSignal): Promise<T> {
    return (await this.read<T>(url, signal)).value;
  }
}
