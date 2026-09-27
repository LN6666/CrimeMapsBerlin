import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
maplibregl.setWorkerUrl(workerUrl);
maplibregl.setWorkerCount(2);
import "maplibre-gl/dist/maplibre-gl.css";
import "./style.css";
import { empty, filteredHex, monthEvents, safeURL, styledPois } from "./model";
import type { Bundle, FC } from "./model";
import { DataClient } from "./data";
import type { Manifest } from "./data";
import { Basemaps, basemapLabels } from "./basemaps";
import type { BasemapId } from "./basemaps";

const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `<header><div><span class="brand">CRIMEMAPSBERLIN</span><h1>柏林 · 警情与城市场所</h1></div><div class="toolbar"><label>年份<select id="year" aria-label="年份"></select></label><label>月份<select id="month" aria-label="月份"></select></label><button id="overview">全市概览</button><button id="sources">警方来源</button></div></header>
<main><aside class="controls"><p class="eyebrow">BERLIN / PUBLIC REPORTS</p><h2>看事件，也看周边</h2><p id="coverage">读取本地数据…</p><label class="search-label">查找柏林场所<input id="search" placeholder="如 Kottbusser Tor、酒吧名称" autocomplete="off"></label><div id="search-results"></div><label>事件类别<select id="category"><option value="all">全部警方公告</option></select></label><div class="rule"></div><h3>六边形 · 公告数量</h3><div class="ramp"></div><div class="ends"><span>少</span><span>多</span></div><p id="resolution"></p><label class="toggle"><input id="hex-toggle" type="checkbox" checked> 显示六边形</label><h3>周边 POI</h3><div id="poi-filters"></div><label class="toggle"><input id="highlight" type="checkbox" checked> 报告提及类型 + 附近匹配时加深</label><p class="hint">小型场所：50 米圆。车站：已有面状范围；空心点表示范围缺失。加深表示关联记录数。</p><div class="rule"></div><button id="kbo">查看柏林 kbO 官方区域</button><p class="hint">警方划定区域与事件网格分别展示。</p><p id="freshness" class="hint"></p></aside>
<section class="map-wrap"><div id="map" aria-label="柏林警情交互地图"></div><div class="map-label"><span class="dot"></span><span id="map-status">正在准备地图</span></div><div class="basemap-picker"><label>底图<select id="basemap" aria-label="底图" disabled><option value="street">标准街道</option><option value="aerial">航空影像（2026）</option><option value="local">本地简图</option></select></label><div id="basemap-error" role="status" hidden><span></span><button id="basemap-fallback">使用本地简图</button></div></div><div class="map-note">浅色 POI 是城市设施，不代表被警方认定为高发场所</div></section>
<aside class="details"><div id="stats"></div><div id="selection"><h2>选择一个六边形或 POI</h2><p>查看该区域的事件、类别，以及可以追溯的警方原文。</p></div></aside></main>
<dialog id="drawer"><button id="close-dialog" class="close">关闭</button><div id="drawer-content"></div></dialog>`;
const el = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.getElementById(id) as T;
const text = (tag: string, value: string, parent: HTMLElement) => {
  const n = document.createElement(tag);
  n.textContent = value;
  parent.append(n);
  return n;
};
function link(parent: HTMLElement, label: string, url: string) {
  const safe = safeURL(url);
  if (!safe) return;
  const a = text("a", label, parent) as HTMLAnchorElement;
  a.href = safe;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
}
let data: Bundle;
let map: maplibregl.Map;
let basemaps: Basemaps;
let activeHex: FC = empty();
let activePois: FC = empty();
let loaded = false;
let expired = false;
let freshnessTimer: ReturnType<typeof setInterval>;
let selected: { type: "hex" | "poi"; id: string } | null = null;
let client: DataClient;
let manifest: Manifest;
let monthRequest = new AbortController();
let viewportRequest = new AbortController();
let viewportTimer: ReturnType<typeof setTimeout>;
let currentMode = "";
let searchIndex:
  | { name: string; kind: string; center: [number, number] }[]
  | undefined;
let searchLoading: Promise<void> | undefined;
function monthKey() {
  return `${el<HTMLSelectElement>("year").value}-${el<HTMLSelectElement>("month").value}`;
}
function events() {
  return monthEvents(data, monthKey(), el<HTMLSelectElement>("category").value);
}
function kinds() {
  return new Set(
    [
      ...document.querySelectorAll<HTMLInputElement>(
        "#poi-filters input:checked",
      ),
    ].map((x) => x.value),
  );
}
function setSource(id: string, fc: FC) {
  (map.getSource(id) as maplibregl.GeoJSONSource).setData(fc);
}
function listReports(parent: HTMLElement, ids: string[]) {
  for (const e of data.events.filter((e) => ids.includes(e.id))) {
    const card = document.createElement("article");
    card.className = "report";
    parent.append(card);
    text(
      "small",
      `${e.event_date ?? `${e.month}（公布月份）`} · ${e.category} · ${{ street: "街道近似位置", place: "场所近似位置", address: "地址近似位置", point: "点位", district: "仅区域信息", unknown: "位置待核验" }[e.location_precision] ?? "位置待核验"}`,
      card,
    );
    if (e.source_status && e.source_status !== "available")
      text(
        "small",
        e.source_status === "unavailable"
          ? "原文目前不可用；保留先前采集记录"
          : "原文刷新失败，正在使用先前记录",
        card,
      );
    text("h4", e.title, card);
    text("p", e.location_label, card);
    if (e.location_selection === "first_explicit_incident_scene")
      text(
        "small",
        e.coordinates
          ? "案发地优先：采用原文首个明确案发场景"
          : "已识别案发场景，空间位置待核验",
        card,
      );
    const otherScenes = [
      ...new Set(e.other_scene_candidates?.map((s) => s.name) ?? []),
    ];
    if (otherScenes.length)
      text(
        "small",
        `原文还描述其他案发地点候选：${otherScenes.join("、")}；本公告在网格中只计一条`,
        card,
      );
    if (e.location_extent_m !== undefined && e.location_extent_m > 75)
      text(
        "small",
        `匹配对象跨度约 ${e.location_extent_m.toLocaleString()} 米；六边形采用近似位置`,
        card,
      );
    link(card, "警方原文 ↗", e.source_url);
    if (e.poi_mentions.length)
      text(
        "small",
        `原文关键词类型：${e.poi_mentions.map((k) => data.catalog.poi_types[k]?.label ?? k).join("、")}`,
        card,
      );
  }
}
function showSelection() {
  const panel = el("selection");
  panel.replaceChildren();
  setSource("reported-sections", empty());
  if (!selected) {
    text("h2", "选择一个六边形或 POI", panel);
    text("p", "点击地图查看事件与来源。", panel);
    return;
  }
  const f = (selected.type === "hex" ? activeHex : activePois).features.find(
    (f) => f.properties.id === selected!.id,
  );
  if (!f) {
    selected = null;
    text("p", "所选对象在当前筛选下没有记录。", panel);
    return;
  }
  const p = f.properties;
  setSource("reported-sections", {
    type: "FeatureCollection",
    features: data.events
      .filter(
        (e) =>
          (p.event_ids ?? []).includes(e.id) && e.reported_location_geometry,
      )
      .map((e) => ({
        type: "Feature",
        geometry: e.reported_location_geometry!,
        properties: { id: e.id },
      })),
  });
  if (
    data.events.some(
      (e) => (p.event_ids ?? []).includes(e.id) && e.reported_location_geometry,
    )
  )
    text("p", "紫色线：警方描述的案发路段；网格按近似位置统计。", panel);
  if (selected.type === "hex") {
    text("p", "HEXAGON / 事件统计", panel).className = "eyebrow";
    text("h2", `${p.count} 条已收录警情`, panel);
    text("p", `边长 ${p.edge_m} 米 · ${monthKey()}`, panel);
    const rows = data.events.filter((e) =>
      (p.event_ids as string[]).includes(e.id),
    );
    const counts: Record<string, number> = {};
    for (const e of rows) counts[e.category] = (counts[e.category] ?? 0) + 1;
    for (const [key, n] of Object.entries(counts))
      text("p", `${key}　${n}`, panel);
    text("p", "办案结果：数据未提供。街道级坐标是近似位置。", panel).className =
      "hint";
  } else {
    text(
      "p",
      data.catalog.poi_types[p.kind]?.label ?? p.kind,
      panel,
    ).className = "eyebrow";
    text("h2", p.name, panel);
    text(
      "p",
      p.geometry_mode === "50m_circle"
        ? "展示范围：半径 50 米"
        : p.geometry_mode === "footprint_missing"
          ? "缺少面状范围：仅显示定位点"
          : "展示范围：OSM 已绘制区域",
      panel,
    );
    text(
      "p",
      `附近同类提及 ${p.count} 条；街道近似坐标候选 ${p.candidate_count} 条`,
      panel,
    );
    text("p", "这些是附近匹配，不表示案件发生在这家店内。", panel).className =
      "hint";
    if (p.opening_hours) text("p", `OSM 营业时间：${p.opening_hours}`, panel);
    link(panel, "OSM 对象 ↗", p.source_url);
    const sources = data.catalog.sources.filter((s) =>
      s.poi_types.includes(p.kind),
    );
    const details = document.createElement("details");
    panel.append(details);
    text(
      "summary",
      `为什么收录这种场所？${sources.length} 项警方来源`,
      details,
    );
    for (const s of sources) {
      text("p", `${s.country} · ${s.place} · ${s.evidence_type}`, details);
      link(details, s.publisher, s.url);
      text("p", s.summary, details);
    }
  }
  listReports(panel, p.event_ids ?? []);
}
function paintOverlays() {
  const max = Math.max(1, ...activeHex.features.map((f) => f.properties.count));
  const base = basemaps?.rendered ?? "local";
  map.setPaintProperty("hex-fill", "fill-opacity", [
    "interpolate",
    ["linear"],
    ["get", "count"],
    0,
    base === "street" ? 0.06 : 0.1,
    max,
    base === "local" ? 0.68 : base === "aerial" ? 0.52 : 0.46,
  ]);
  map.setPaintProperty(
    "hex-line",
    "line-color",
    base === "aerial" ? "#ffb4aa" : "#ac3737",
  );
  map.setPaintProperty(
    "hex-line",
    "line-opacity",
    base === "aerial" ? 0.75 : 0.45,
  );
  map.setPaintProperty("poi-fill", "fill-opacity", [
    "*",
    ["get", "opacity"],
    base === "street" ? 0.8 : 1,
  ]);
}
function refresh() {
  if (!loaded || expired) return;
  const month = data.months[monthKey()],
    rows = events(),
    ids = new Set(rows.map((e) => e.id));
  const mode =
    map.getZoom() >= data.metadata.zoom_threshold ? "detail" : "overview";
  activeHex = month ? filteredHex(month.hex[mode], ids) : empty();
  activePois = styledPois(
    data,
    month?.links ?? [],
    ids,
    kinds(),
    el<HTMLInputElement>("highlight").checked,
  );
  setSource("hex", activeHex);
  setSource("pois", activePois);
  map.setLayoutProperty(
    "hex-fill",
    "visibility",
    el<HTMLInputElement>("hex-toggle").checked ? "visible" : "none",
  );
  map.setLayoutProperty(
    "hex-line",
    "visibility",
    el<HTMLInputElement>("hex-toggle").checked ? "visible" : "none",
  );
  currentMode = mode;
  paintOverlays();
  el("resolution").textContent =
    `边长 ${mode === "detail" ? "275" : "1,100"} 米 · 缩放自动切换`;
  el("map-status").textContent = month
    ? `${monthKey()} · ${rows.length} 条已收录警情`
    : `${monthKey()} · 未获取该月数据`;
  el("stats").replaceChildren();
  text("div", month ? String(rows.length) : "—", el("stats")).className = "big";
  text("p", month ? "当前筛选 · 已收录警情" : "该月尚无数据包", el("stats"));
  if (month) {
    const unmapped = rows.filter(
      (e) =>
        !e.coordinates ||
        !["street", "point", "place", "address"].includes(e.location_precision),
    );
    const btn = text(
      "button",
      `${unmapped.length} 条位置不足，查看列表`,
      el("stats"),
    );
    btn.onclick = () => {
      selected = null;
      const p = el("selection");
      p.replaceChildren();
      text("h2", "位置不足的警情", p);
      listReports(
        p,
        unmapped.map((e) => e.id),
      );
    };
  }
  showSelection();
}
function openDialog(title: string) {
  const p = el("drawer-content");
  p.replaceChildren();
  text("h2", title, p);
  el<HTMLDialogElement>("drawer").showModal();
  return p;
}
function sourcesDialog() {
  const p = openDialog("欧洲警方场所来源目录");
  const n = data.catalog.coverage.filter(
    (c) => c.status === "sources_verified_partial",
  ).length;
  text(
    "p",
    `已核验 ${n} 个国家的部分来源，${data.catalog.sources.length} 项材料。尚未完成全欧洲穷尽检索。`,
    p,
  );
  text(
    "p",
    "一般预防建议用于场所分类；它不把柏林同类商户自动标记为犯罪高发。",
    p,
  );
  for (const s of data.catalog.sources) {
    const card = document.createElement("article");
    p.append(card);
    text("h3", `${s.country} / ${s.place}`, card);
    text("small", `${s.evidence_type} · 核查 ${s.verified_on}`, card);
    text("p", s.summary, card);
    link(card, s.publisher + " ↗", s.url);
  }
  text(
    "p",
    "待核验国家：" +
      data.catalog.coverage
        .filter((c) => c.status === "not_yet_verified")
        .map((c) => c.country)
        .join("、"),
    p,
  );
}
function kboDialog() {
  const p = openDialog("柏林 kbO · 官方划定区域");
  text(
    "p",
    "已登记七个区域及警方原始边界图。精确矢量边界尚未获取；下面的定位只用于导航，不冒充法定边界。",
    p,
  );
  for (const zone of data.zones.places) {
    const card = document.createElement("article");
    p.append(card);
    text("h3", zone.name, card);
    link(card, "官方边界图 ↗", zone.official_map_url);
    link(card, "警方说明 ↗", zone.source_url);
    const b = text("button", "定位周边", card);
    b.onclick = () => {
      map.flyTo({ center: zone.navigation_center, zoom: 15 });
      el<HTMLDialogElement>("drawer").close();
    };
  }
}
async function loadMonth() {
  monthRequest.abort();
  monthRequest = new AbortController();
  const signal = monthRequest.signal;
  const key = monthKey();
  el("map-status").textContent = "读取所选月份…";
  try {
    const value = await client.month(key, signal);
    if (signal.aborted || key !== monthKey()) return;
    data.events = value?.events ?? [];
    data.months = value ? { [key]: value } : {};
    selected = null;
    refresh();
  } catch (error) {
    if (!signal.aborted) {
      data.events = [];
      data.months = {};
      refresh();
      el("map-status").textContent = String(error);
    }
  }
}
async function loadViewport() {
  if (!loaded) return;
  viewportRequest.abort();
  viewportRequest = new AbortController();
  const signal = viewportRequest.signal;
  const b = map.getBounds(),
    bounds: [number, number, number, number] = [
      b.getWest(),
      b.getSouth(),
      b.getEast(),
      b.getNorth(),
    ];
  const detail = map.getZoom() >= 12.5;
  // Clear stale places immediately; details are requested only at useful scale.
  data.pois = empty();
  activePois = empty();
  setSource("pois", empty());
  try {
    const [roads, pois] = await Promise.all([
      detail
        ? client.viewport("roads", bounds, signal)
        : client.json<FC>(`${client.base}/roads-overview.json`, signal),
      detail
        ? client.viewport("pois", bounds, signal, [...kinds()])
        : Promise.resolve(empty()),
    ]);
    if (signal.aborted) return;
    setSource("roads", roads);
    data.pois = pois;
    refresh();
    if (!detail) el("map-status").textContent += " · 放大后加载场所";
  } catch (error) {
    if (!signal.aborted) el("map-status").textContent = String(error);
  }
}
async function start() {
  try {
    const response = await fetch("/safety/manifest.json", {
      cache: "no-store",
    });
    if (!response.ok)
      throw Error("未找到有效的本地警情数据，请运行数据构建命令。");
    manifest = (await response.json()) as Manifest;
    client = new DataClient(manifest);
    data = {
      ...manifest,
      schema_version: 1,
      coverage: "official_archive",
      expires_at: "",
      events: [],
      months: {},
      pois: empty(),
    };
    const months = Object.keys(manifest.months).sort();
    const latest = months.at(-1) ?? data.retrieved_at.slice(0, 7);
    const years = [
      ...new Set([...months.map((m) => m.slice(0, 4)), latest.slice(0, 4)]),
    ];
    for (const y of years) el<HTMLSelectElement>("year").add(new Option(y, y));
    for (let m = 1; m <= 12; m++)
      el<HTMLSelectElement>("month").add(
        new Option(`${m} 月`, String(m).padStart(2, "0")),
      );
    el<HTMLSelectElement>("year").value = latest.slice(0, 4);
    el<HTMLSelectElement>("month").value = latest.slice(5, 7);
    for (const c of manifest.categories)
      el<HTMLSelectElement>("category").add(new Option(c, c));
    for (const [key, value] of Object.entries(data.catalog.poi_types)) {
      const label = document.createElement("label");
      label.className = "toggle";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = key;
      input.checked = ["bar", "nightclub", "station", "shop"].includes(key);
      input.onchange = () => void loadViewport();
      label.append(input);
      const swatch = document.createElement("i");
      swatch.style.background = value.color;
      label.append(swatch, document.createTextNode(value.label));
      el("poi-filters").append(label);
    }
    el("coverage").textContent =
      `警方档案发现 ${manifest.coverage.discovered} 条，已获取 ${manifest.coverage.fetched} 条，待获取 ${manifest.coverage.pending} 条。按公布月份筛选；并非全部报案记录。`;
    el("freshness").textContent =
      `快照：${new Date(data.retrieved_at).toLocaleString("zh-CN")}。更新流程由本地采集任务维护。`;
    map = new maplibregl.Map({
      container: "map",
      center: [13.411, 52.508],
      zoom: 12.1,
      attributionControl: false,
      maxTileCacheSize: 64,
      cancelPendingTileRequestsWhileZooming: true,
      refreshExpiredTiles: false,
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "background",
            type: "background",
            paint: { "background-color": "#edf1ed" },
          },
        ],
      },
    });
    map.addControl(new maplibregl.NavigationControl(), "bottom-right");
    map.addControl(
      new maplibregl.ScaleControl({ maxWidth: 100, unit: "metric" }),
      "bottom-left",
    );
    map.addControl(
      new maplibregl.AttributionControl({
        compact: false,
        customAttribution:
          '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">场所/道路：© OpenStreetMap contributors</a> / <a href="https://www.geofabrik.de/" target="_blank" rel="noopener noreferrer">Geofabrik</a> · <a href="https://www.berlin.de/polizei/polizeimeldungen/" target="_blank" rel="noopener noreferrer">警情：Polizei Berlin</a>',
      }),
    );
    map.once("load", async () => {
      for (const id of ["roads", "hex", "pois", "kbo", "reported-sections"])
        map.addSource(id, { type: "geojson", data: empty() });
      map.addLayer({
        id: "roads-line",
        type: "line",
        source: "roads",
        paint: {
          "line-color": "#bac6c0",
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.5, 16, 2],
        },
      });
      map.addLayer({
        id: "hex-fill",
        type: "fill",
        source: "hex",
        paint: { "fill-color": "#d54949", "fill-opacity": 0.4 },
      });
      map.addLayer({
        id: "hex-line",
        type: "line",
        source: "hex",
        paint: {
          "line-color": "#ac3737",
          "line-width": 0.6,
          "line-opacity": 0.45,
        },
      });
      map.addLayer({
        id: "poi-fill",
        type: "fill",
        source: "pois",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "fill-color": ["get", "color"],
          "fill-opacity": ["get", "opacity"],
        },
      });
      map.addLayer({
        id: "poi-line",
        type: "line",
        source: "pois",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["case", [">", ["get", "association_count"], 0], 2, 1],
          "line-opacity": 0.75,
        },
      });
      map.addLayer({
        id: "poi-point",
        type: "circle",
        source: "pois",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": 4,
          "circle-color": "#ffffff",
          "circle-stroke-width": 2,
          "circle-stroke-color": ["get", "color"],
        },
      });
      map.addLayer({
        id: "kbo-boundary",
        type: "line",
        source: "kbo",
        paint: {
          "line-color": "#171717",
          "line-width": 2,
          "line-dasharray": [4, 2],
        },
      });
      map.addLayer({
        id: "reported-sections-line",
        type: "line",
        source: "reported-sections",
        paint: { "line-color": "#7c3aed", "line-width": 5 },
      });
      setSource("kbo", {
        type: "FeatureCollection",
        features: data.zones.features,
      });
      basemaps = new Basemaps(map, paintOverlays, (id) => {
        const error = el("basemap-error");
        error.querySelector("span")!.textContent =
          `${basemapLabels[id]}加载失败，当前显示简化道路。`;
        error.hidden = false;
      });
      const changeBasemap = (id: BasemapId) => {
        el("basemap-error").hidden = true;
        el<HTMLSelectElement>("basemap").value = id;
        basemaps.select(id);
      };
      el<HTMLSelectElement>("basemap").disabled = false;
      el("basemap").onchange = () =>
        changeBasemap(el<HTMLSelectElement>("basemap").value as BasemapId);
      el("basemap-fallback").onclick = () => changeBasemap("local");
      changeBasemap("street");
      loaded = true;
      await Promise.all([loadMonth(), loadViewport()]);
      map.on("click", (e) => {
        if (expired) return;
        const fs = map.queryRenderedFeatures(e.point, {
          layers: ["poi-fill", "poi-point", "hex-fill"],
        });
        if (!fs.length) return;
        const f = fs[0];
        selected = {
          type: f.layer.id.startsWith("poi") ? "poi" : "hex",
          id: f.properties.id,
        };
        showSelection();
      });
      map.on("movestart", () => viewportRequest.abort());
      map.on("moveend", () => {
        clearTimeout(viewportTimer);
        viewportTimer = setTimeout(() => void loadViewport(), 120);
        if (currentMode !== (map.getZoom() >= 13 ? "detail" : "overview"))
          refresh();
      });
    });
    for (const id of ["category", "highlight", "hex-toggle"])
      el(id).onchange = () => {
        selected = null;
        refresh();
      };
    for (const id of ["year", "month"])
      el(id).onchange = () => void loadMonth();
    el("overview").onclick = () =>
      map.flyTo({ center: [13.411, 52.508], zoom: 10.5 });
    el("sources").onclick = sourcesDialog;
    el("kbo").onclick = kboDialog;
    freshnessTimer = setInterval(async () => {
      if (document.hidden) return;
      try {
        const r = await fetch("/safety/manifest.json", { cache: "no-store" });
        if (!r.ok) return;
        const latest = (await r.json()) as Manifest;
        if (latest.generation !== manifest.generation) {
          el("freshness").replaceChildren();
          const button = text(
            "button",
            "有新的警方数据，点击刷新地图",
            el("freshness"),
          );
          button.onclick = () => location.reload();
        }
      } catch {
        /* Keep the currently loaded snapshot while offline. */
      }
    }, 300000);
    el("close-dialog").onclick = () => el<HTMLDialogElement>("drawer").close();
    let searchTimer: ReturnType<typeof setTimeout>;
    el<HTMLInputElement>("search").oninput = () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(async () => {
        const q = el<HTMLInputElement>("search")
          .value.trim()
          .toLocaleLowerCase();
        const box = el("search-results");
        box.replaceChildren();
        if (q.length < 2) return;
        if (!searchIndex) {
          searchLoading ??= client
            .json<typeof searchIndex>(`${client.base}/search.json`)
            .then((v) => {
              searchIndex = v;
            })
            .catch(() => {
              text("p", "场所索引读取失败", box);
              searchLoading = undefined;
            });
          await searchLoading;
        }
        if (
          el<HTMLInputElement>("search").value.trim().toLocaleLowerCase() !== q
        )
          return;
        const matches = (searchIndex ?? [])
          .filter((f) => f.name.toLocaleLowerCase().includes(q))
          .slice(0, 8);
        if (!matches.length) text("p", "没有匹配的已收录 POI", box);
        for (const f of matches) {
          const b = text(
            "button",
            `${f.name} · ${data.catalog.poi_types[f.kind]?.label}`,
            box,
          );
          b.onclick = () => {
            map.flyTo({ center: f.center, zoom: 16 });
            box.replaceChildren();
          };
        }
      }, 160);
    };
  } catch (error) {
    el("coverage").textContent = String(error);
    el("map-status").textContent = "数据未就绪";
  }
}
window.addEventListener("pagehide", () => {
  monthRequest.abort();
  viewportRequest.abort();
  clearTimeout(viewportTimer);
  clearInterval(freshnessTimer);
  basemaps?.dispose();
  map?.remove();
});
void start();
