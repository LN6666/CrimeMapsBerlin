import type { Bundle, FC, Month, PoliceEvent, Properties } from "./model";
import { empty } from "./model";
export interface Manifest {
  schema_version: 2;
  city: string;
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
  private values = new Map<string, T>();
  constructor(private capacity: number) {}
  get(key: string) {
    const value = this.values.get(key);
    if (value !== undefined) {
      this.values.delete(key);
      this.values.set(key, value);
    }
    return value;
  }
  set(key: string, value: T) {
    this.values.delete(key);
    this.values.set(key, value);
    while (this.values.size > this.capacity)
      this.values.delete(this.values.keys().next().value!);
  }
  get size() {
    return this.values.size;
  }
}
export function tileKeys(
  bounds: [number, number, number, number],
  size: [number, number],
  available: Set<string>,
  max = 64,
) {
  const [west, south, east, north] = bounds,
    [dx, dy] = size;
  if (!bounds.every(Number.isFinite) || west > east || south > north)
    throw Error("无效地图范围");
  const keys = [];
  // Never enumerate an unbounded world-sized grid.
  const x0 = Math.floor(west / dx),
    x1 = Math.floor(east / dx),
    y0 = Math.floor(south / dy),
    y1 = Math.floor(north / dy);
  if ((x1 - x0 + 1) * (y1 - y0 + 1) > max) return [];
  for (let x = x0; x <= x1; x++)
    for (let y = y0; y <= y1; y++) {
      const key = `${x}_${y}`;
      if (available.has(key)) keys.push(key);
    }
  return keys;
}
export class DataClient {
  private tiles = new LRU<FC>(80);
  private months = new LRU<MonthData>(3);
  private available: { pois: Set<string>; roads: Set<string> };
  readonly base: string;
  constructor(readonly manifest: Manifest) {
    if (
      manifest.schema_version !== 2 ||
      !/^[a-f0-9]{16}-\d{8}T\d{6}$/.test(manifest.generation)
    )
      throw Error("不支持的数据清单");
    this.base = `/safety/${manifest.generation}`;
    this.available = {
      pois: new Set(manifest.tile_index.pois),
      roads: new Set(manifest.tile_index.roads),
    };
  }
  async month(
    key: string,
    signal: AbortSignal,
  ): Promise<MonthData | undefined> {
    if (!Object.hasOwn(this.manifest.months, key)) return undefined;
    const cached = this.months.get(key);
    if (cached) return cached;
    const value = await this.json<MonthData>(
      `${this.base}/months/${key}.json`,
      signal,
    );
    this.months.set(key, value);
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
        ? new Set([...this.available.pois].map((k) => k.split("/")[1]))
        : this.available.roads;
    const coordinates = tileKeys(bounds, this.manifest.tile_size, available);
    const keys =
      kind === "pois"
        ? placeKinds
            .flatMap((type) => coordinates.map((c) => `${type}/${c}`))
            .filter((k) => this.available.pois.has(k))
        : coordinates;
    const features = new Map<string, FC["features"][number]>();
    // Four requests at a time, abortable; avoid dozens of simultaneous downloads.
    for (let i = 0; i < keys.length; i += 4) {
      const results = await Promise.all(
        keys.slice(i, i + 4).map(async (key) => {
          const id = `${kind}/${key}`,
            cached = this.tiles.get(id);
          if (cached) return cached;
          const value = await this.json<FC>(`${this.base}/${id}.json`, signal);
          this.tiles.set(id, value);
          return value;
        }),
      );
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      for (const fc of results)
        for (const f of fc.features) features.set(String(f.properties.id), f);
    }
    return { type: "FeatureCollection", features: [...features.values()] };
  }
  async json<T>(url: string, signal?: AbortSignal): Promise<T> {
    const r = await fetch(url, { signal });
    if (!r.ok) throw Error(`数据读取失败（${r.status}）`);
    return r.json();
  }
}
