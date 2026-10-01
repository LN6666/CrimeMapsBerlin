import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
maplibregl.setWorkerUrl(workerUrl);
maplibregl.setWorkerCount(2);
import "maplibre-gl/dist/maplibre-gl.css";
import "./style.css";
import {
  candidateRoadGeometry,
  candidateRoads,
  countableEventIds,
  empty,
  filteredHex,
  monthEvents,
  roadBounds,
  safeURL,
  sceneEventIds,
  sceneFeatures,
  sceneRoleLabel,
  styledPois,
  transitGeometryLabel,
} from "./model";
import type { Bundle, FC, PoliceEvent } from "./model";
import { DataClient } from "./data";
import type { Manifest } from "./data";
import { Basemaps, basemapLabels } from "./basemaps";
import type { BasemapId } from "./basemaps";
import { externalMaps, externalMapsDirectory } from "./external-maps";
import { cityGroups, requestedMapView } from "./cities";

const cityView = requestedMapView(window.location.search);
const currentCity = cityView.id;
document.title = `CrimeMapsDE · ${cityView.name}警情地图`;

const categoryLabels: Record<string, string> = {
  betrug: "诈骗",
  brand: "火灾",
  diebstahl: "盗窃",
  drogen: "毒品",
  einbruch: "入室盗窃",
  gewalt: "暴力",
  raub: "抢劫",
  sexualdelikte: "性犯罪",
  sonstige: "其他",
  verkehr: "交通",
};
const categoryLabel = (category: string) => categoryLabels[category] ?? category;

const reviewedTagLabels: Record<string, string> = {
  violent_assault: "暴力袭击线索",
  robbery: "抢劫线索",
  threat: "威胁线索",
  sexual_offence: "性犯罪线索",
  property_offence: "财产相关事件线索",
  possible_hate_crime: "可能仇恨犯罪",
};
const precisionLabels: Record<string, string> = {
  street: "道路范围参考",
  place: "场所近似位置",
  address: "地址近似位置",
  point: "点位",
  route: "路线/移动范围",
  district: "仅区域信息",
  city: "仅城市级位置",
  unknown: "位置待核验",
};
const locationScopeLabels: Record<string, string> = {
  in_city: "已通过市界核验",
  outside_city: `位于${cityView.name}市界外，不计入市域网格`,
  unresolved_no_upstream_coordinate: "上游未提供坐标，不计入市域网格",
};
const sourceStatusLabels: Record<string, string> = {
  current_cached_official_source_reviewed_with_declared_gaps:
    "当前缓存已逐篇复核；保留位置、POI和引用缺口，未批准发布",
  polizeikarte_complete_365_day_snapshot:
    "POLIZEIKARTE 滚动 365 天完整快照；保留对应警方原文链接",
  complete_official_archive_source_and_geometry_reviewed:
    "官方来源、场景、几何和地图语义已完成复核；等待所有者批准",
  complete_frozen_owner_batch_source_and_geometry_reviewed:
    "所有者冻结批次的原文、场景、几何和地图语义已复核；不代表全量犯罪清单；未批准发布",
};
const sceneRelationLabels: Record<string, string> = {
  independent_case: "独立案件或事故",
  same_case_phase: "同一事件的后续地点",
  search_arrest_operation: "警务行动地点",
  background_reference: "旧案或背景地点",
  unresolved_relation: "与其他场景的关联未明确",
};
const sceneColor: maplibregl.ExpressionSpecification = [
  "match", ["get", "role_group"],
  "incident", "#b43d4b",
  "discovery", "#2874a6",
  "operation", "#986223",
  "#677785",
];

const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `<header><div><span class="brand">${currentCity === "berlin" ? "CRIMEMAPSBERLIN" : "CRIMEMAPS.DE"}</span><span id="review-badge" class="review-badge" hidden>本地所有者审核预览 · 未批准 · 不可发布</span><h1>${cityView.name} · 警情与城市场所</h1></div><div class="toolbar"><label class="city-switch">选择城市<select id="city-switch" aria-label="选择城市"></select></label><label>年份<select id="year" aria-label="年份"></select></label><label>月份<select id="month" aria-label="月份"></select></label><button id="overview">全市概览</button><button id="sources">警方来源</button></div></header>
<main><aside class="controls"><p class="eyebrow">${cityView.latin} / PUBLIC REPORTS</p><h2>看事件，也看周边</h2><p id="coverage">读取本地数据…</p><nav id="external-maps" class="external-maps" aria-label="外部警情网站"></nav><label class="search-label">查找${cityView.name}场所<input id="search" placeholder="${cityView.example}" autocomplete="off"></label><div id="search-results"></div><label>事件类别<select id="category"><option value="all">全部警方公告</option></select></label><div class="rule"></div><h3>六边形 · 公告数量</h3><div class="ramp"></div><div class="ends"><span>少</span><span>多</span></div><p id="resolution"></p><label class="toggle"><input id="hex-toggle" type="checkbox" checked> 显示六边形</label><label class="toggle"><input id="candidate-roads-toggle" type="checkbox" checked> 显示待定位道路范围</label><p class="hint"><span class="road-swatch" aria-hidden="true"></span>橙色虚线仅表示原文提到的道路候选范围，具体案发位置未知；不计入六边形或 POI 关联。</p><div class="scene-legend" aria-label="公告场景颜色"><span><i class="scene-swatch incident"></i>案发/事故</span><span><i class="scene-swatch discovery"></i>发现</span><span><i class="scene-swatch operation"></i>处置／行动</span><span><i class="scene-swatch context"></i>背景/待核</span><span><i class="route-swatch"></i>移动公交路线</span></div><h3>周边 POI</h3><div id="poi-filters"></div><label class="toggle"><input id="highlight" type="checkbox" checked> 经复核的同类场所上下文加深</label><p class="hint">加深仅表示原文复核确认的整条街道、路线沿线或附近同类场所上下文，不表示事件发生在具体场所内。</p><div class="rule"></div><button id="kbo">查看柏林 kbO 官方区域</button><p class="hint">警方划定区域与事件网格分别展示。</p><p id="freshness" class="hint"></p></aside>
<section class="map-wrap"><div id="map" aria-label="${cityView.name}警情交互地图"></div><div class="map-label"><span class="dot"></span><span id="map-status">正在准备地图</span></div><div class="basemap-picker"><label>底图<select id="basemap" aria-label="底图" disabled><option value="street">标准街道</option><option value="aerial">航空影像（2026）</option><option value="local">本地简图</option></select></label><div id="basemap-error" role="status" hidden><span></span><button id="basemap-fallback">使用本地简图</button></div></div><div class="map-note">浅色 POI 是城市设施，不代表被警方认定为高发场所</div></section>
<aside class="details"><div id="stats"></div><div id="selection"><h2>选择一个六边形或 POI</h2><p>查看该区域的事件、类别，以及可以追溯的警方原文。</p></div></aside></main>
<dialog id="drawer"><button id="close-dialog" class="close">关闭</button><div id="drawer-content"></div></dialog>`;
const el = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.getElementById(id) as T;
const citySelect = el<HTMLSelectElement>("city-switch");
for (const group of cityGroups) {
  const section = document.createElement("optgroup");
  section.label = group.label;
  for (const city of group.cities) {
    const option = new Option(
      city.name + (city.href ? "" : " · 制作中"),
      city.id,
    );
    option.disabled = !city.href && city.id !== currentCity;
    section.append(option);
  }
  citySelect.append(section);
}
citySelect.value = currentCity;
citySelect.onchange = () => {
  const destination = cityGroups.flatMap((group) => group.cities).find(
    (city) => city.id === citySelect.value,
  );
  if (destination?.href) window.location.assign(destination.href);
};
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
link(el("external-maps"), `POLIZEIKARTE ${cityView.name} ↗`, cityView.externalUrl);
if (!cityView.kbo) {
  el("kbo").hidden = true;
  el("kbo").nextElementSibling?.remove();
}
if (!cityView.aerial)
  el<HTMLSelectElement>("basemap").querySelector<HTMLOptionElement>("option[value='aerial']")!.disabled = true;
text("button", "德国其他城市", el("external-maps")).onclick =
  externalMapsDialog;
let data: Bundle;
let map: maplibregl.Map;
let basemaps: Basemaps;
let activeHex: FC = empty();
let activePois: FC = empty();
let activeRoads: FC = empty();
let activeScenes: FC = empty();
let loaded = false;
let expired = false;
let freshnessTimer: ReturnType<typeof setInterval>;
let selected:
  | { type: "hex" | "poi"; id: string }
  | { type: "road"; ids: string[] }
  | { type: "scene"; ids: string[] }
  | null = null;
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
function focusRoad(event: PoliceEvent) {
  const geometry = candidateRoadGeometry(event);
  if (!geometry) return;
  selected = { type: "road", ids: [event.id] };
  el<HTMLInputElement>("candidate-roads-toggle").checked = true;
  setRoadVisibility();
  const [west, south, east, north] = roadBounds(geometry);
  map.fitBounds(
    [
      [west, south],
      [east, north],
    ],
    { padding: 55, maxZoom: 14 },
  );
  el<HTMLDialogElement>("drawer").close();
  showSelection();
}
function focusReviewedScenes(event: PoliceEvent, scenes = event.scene_locations ?? []) {
  let west = Infinity, east = -Infinity, south = Infinity, north = -Infinity, count = 0;
  function visit(value: unknown): void {
    if (!Array.isArray(value)) return;
    if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
      west = Math.min(west, value[0]); east = Math.max(east, value[0]);
      south = Math.min(south, value[1]); north = Math.max(north, value[1]); count += 1;
      return;
    }
    value.forEach(visit);
  }
  for (const scene of scenes) {
    const geometry = scene.geometry;
    if (geometry && "coordinates" in geometry) visit(geometry.coordinates);
  }
  if (!count) return;
  map.fitBounds([[west, south], [east, north]], {padding:55, maxZoom:scenes.some(scene => scene.static_scene_reference === true) ? 17 : 14});
  el<HTMLDialogElement>("drawer").close();
}
function listReports(parent: HTMLElement, ids: string[]) {
  const wanted = new Set(ids);
  for (const e of data.events.filter((e) => wanted.has(e.id))) {
    const card = document.createElement("article");
    card.className = "report";
    card.dataset.sourceId = e.id;
    parent.append(card);
    text(
      "small",
      `${e.event_date ?? `${e.month}（公布月份）`} · ${categoryLabel(e.category)} · ${precisionLabels[e.location_precision] ?? "位置待核验"}`,
      card,
    );
    if (e.source_status && e.source_status !== "available") {
      const status = sourceStatusLabels[e.source_status];
      text(
        "small",
        status ?? (e.source_status === "unavailable"
          ? "原文目前不可用；保留先前采集记录"
          : "原文刷新失败，正在使用先前记录"),
        card,
      );
    }
    if (e.source_scope_verdict === "uncertain")
      text("small", "市域位置不确定：保留原文和未定位场景，不计入六边形", card);
    text("h4", e.title, card);
    if (e.map_review_note) text("p", `分类及计数说明：${e.map_review_note}`, card);
    for (const attachment of e.source_attachments ?? []) {
      const details = document.createElement("details");
      card.append(details);
      text("summary", `已复核官方附件 · ${attachment.page_count}页`, details);
      text("p", attachment.note, details);
      link(details, "查看已复核官方附件", attachment.source_url);
      text("small", `附件 SHA-256：${attachment.source_sha256}`, details);
    }
    for (const claim of e.current_claim_overlays ?? [])
      text("p", `后续来源修订：${claim.display_note}`, card);
    for (const history of e.historical_source_reviews ?? []) {
      const disclosure = document.createElement("details");
      disclosure.className = "historical-source-review";
      card.append(disclosure);
      text("summary", `官方补充公告 · ${history.source_incidents.length}个来源阶段`, disclosure);
      const sourceLink = document.createElement("a");
      sourceLink.href = history.source_url;
      sourceLink.target = "_blank";
      sourceLink.rel = "noopener noreferrer";
      sourceLink.textContent = history.title;
      disclosure.append(sourceLink);
      text("small", `公布时间：${history.published_at_source_literal}（来源字面）`, disclosure);
      text("p", history.review_note, disclosure);
      for (const incident of history.source_incidents) {
        const stage = document.createElement("section");
        disclosure.append(stage);
        text("strong", `原始事件时间：${incident.event_time.display}`, stage);
        text("p", incident.details, stage);
        for (const location of history.formal_locations.filter((location) =>
          incident.formal_location_ids.includes(location.location_id))) {
          text("small", `${sceneRoleLabel(location.role)} · ${location.label} · ${precisionLabels[location.precision] ?? "位置未知"}`, stage);
          text("small", `场所判断：${location.poi_review.note}`, stage);
          text("small", `交通判断：${location.transit_review.note}`, stage);
        }
      }
    }
    for (const comparison of e.source_reference_comparisons ?? [])
      text("small", `补充来源关系：${comparison.review_note}`, card);
    for (const tag of e.reviewed_tags ?? []) {
      const label = reviewedTagLabels[tag.tag];
      if (label)
        text("small", `${label}（AI 线索，非警方定性）· 原文依据：“${tag.evidence_quote}”`, card);
    }
    text("p", e.location_label, card);
    if (e.location_scope && locationScopeLabels[e.location_scope])
      text("small", locationScopeLabels[e.location_scope], card);
    if (e.scene_locations?.length) {
      const heading = text("small", "公告中的地点场景：", card);
      heading.className = "scene-heading";
      const scenes = document.createElement("ul");
      scenes.className = "scene-list";
      card.append(scenes);
      for (const scene of e.scene_locations) {
        const item = document.createElement("li");
        scenes.append(item);
        text("strong", `${sceneRoleLabel(scene.role)} · ${scene.label}`, item);
        text(
          "small",
          `${scene.case_relation ? `${sceneRelationLabels[scene.case_relation]} · ` : ""}${scene.geometry_usage === "official_attachment_horizontal_reference_only" ? "附件水平范围参考" : (precisionLabels[scene.location_precision] ?? "位置待核验")} · ${scene.primary_for_count ? "主场景" : "仅展示，不计入六边形"}${scene.candidate_road_geometry ? " · 道路范围待核验" : ""}`,
          item,
        );
        const eventTimes = [
          scene.event_time?.display,
          ...(scene.incidents ?? []).map((incident) => incident.event_time?.display),
        ].filter((value): value is string => Boolean(value));
        const uniqueTimes = [...new Set(eventTimes)];
        if (uniqueTimes.length)
          text("small", `原始事件时间：${uniqueTimes.join("；")}`, item);
        if (scene.transit_route)
          text(
            "small",
            `${scene.transit_route.mode} ${scene.transit_route.line} · ${transitGeometryLabel(scene)}`,
            item,
          );
        if (scene.geometry_usage === "source_native_platform_points_reference_only") {
          text("small", `原生站台集合参考 · ${scene.native_platform_count ?? "多"}个原始节点；实际站台侧和案发位置未知，不计入六边形。`, item);
          const focus = text("button", "查看原生站台参考", item);
          focus.onclick = () => focusReviewedScenes(e, [scene]);
        }
        if (scene.geometry_usage === "official_attachment_horizontal_reference_only") {
          text("small", "警方附件水平范围参考；高度、坐标基准及完整法定条件未核。历史管理范围，不计为犯罪地点。", item);
          if (scene.source_attachment_url) link(item, "查看警方原始PDF附件", scene.source_attachment_url);
          const focus = text("button", "查看附件水平范围", item);
          focus.onclick = () => focusReviewedScenes(e, [scene]);
        }
        if (scene.source_attachment_url && scene.geometry && scene.geometry_usage !== "official_attachment_horizontal_reference_only") {
          text("small", "附件补证的道路或联系机关范围参考；不证明精确案发地，不计入六边形。", item);
          const focus = text("button", "查看附件补证范围参考", item);
          focus.onclick = () => focusReviewedScenes(e, [scene]);
        }
        if (scene.geometry_usage === "source_footprint_reference_only")
          text("small", scene.actual_non_transit_extent_known === false
            ? "原生地名轮廓参考；实际非公交轨迹及精确事件位置未知，不生成计数点。"
            : "原生地名轮廓参考；精确事件位置未知，不生成计数点。", item);
        if (scene.geometry_usage === "source_road_reference_only" && !scene.transit_route)
          text("small", `${transitGeometryLabel(scene)}；不生成精确案发或计数点。`, item);
        if (scene.static_scene_reference === true && scene.geometry) {
          const focus = text("button", "查看场景参考范围", item);
          focus.onclick = () => focusReviewedScenes(e, [scene]);
        }
        if (scene.geometry_usage === "source_junction_reference_only")
          text("small", "原生路口候选节点参考；实际事件点未知，不计入六边形。", item);
        const details = [
          scene.details,
          ...(scene.incidents ?? []).map((incident) => incident.details),
        ].filter((value): value is string => Boolean(value));
        for (const detail of [...new Set(details)]) text("small", detail, item);
        for (const note of new Set((scene.source_relations ?? []).map((r) => r.decision.review_note)))
          text("small", `来源阶段关系：${note}`, item);
        if (scene.poi_review)
          text("small", `场所判断：${scene.poi_review.note}`, item);
        if (scene.transit_review)
          text("small", `交通判断：${scene.transit_review.note}`, item);
        if (scene.geometry_review?.review_note)
          text("small", `定位复核说明：${scene.geometry_review.review_note}`, item);
        if (scene.poi_contexts?.length) {
          const kinds = [...new Set(scene.poi_contexts.map((context) =>
            data.catalog.poi_types[context.kind]?.label ?? context.kind))];
          text(
            "small",
            `经原文复核的场所上下文：${kinds.join("、")}；仅作地点上下文，不表示事件发生在具名场所内。`,
            item,
          );
        }
      }
      text(
        "small",
        "只有具备可计数点位的主场景进入公告级六边形；同一公告最多计一次。",
        card,
      );
    }
    if (e.geocode_method === "multiple_official_scenes")
      text(
        "small",
        e.coordinates
          ? "原文列出多个地点；逐处展示，并以经复核的一个主场景计入公告级网格。"
          : "原文列出多个地点；逐处展示，当前没有可用于公告级网格的主场景点位。",
        card,
      );
    if (e.geocode_method === "multi_event_summary")
      text("small", "多起事件汇总公告；没有可归属整篇公告的单一点位。", card);
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
        `原文还描述其他案发地点候选：${otherScenes.join("、")}；${e.coordinates ? "本公告在网格中只计一条" : "本公告未计入网格"}`,
        card,
      );
    const road = candidateRoadGeometry(e);
    if (road) {
      text(
        "small",
        `待定位道路：${e.geocode_method === "disconnected_street_review" ? "本地道路数据包含不连续片段" : "道路范围较长或存在歧义"}；具体案发位置未知，未计入六边形或 POI 关联。`,
        card,
      ).className = "road-caution";
      if (e.location_scope)
        text("small", `匹配街区范围：${e.location_scope}`, card);
      const button = text("button", "在地图查看道路范围", card);
      button.className = "road-focus";
      button.onclick = () => focusRoad(e);
    }
    if (e.location_extent_m !== undefined && e.location_extent_m > 75)
      text(
        "small",
        `匹配对象跨度约 ${e.location_extent_m.toLocaleString()} 米；${e.coordinates ? "六边形采用近似位置" : "具体案发位置待核验"}`,
        card,
      );
    if (e.scene_locations?.some(scene => scene.geometry)) {
      const button = text("button", "在地图查看已复核场景范围", card);
      button.className = "reviewed-scene-focus";
      button.onclick = () => focusReviewedScenes(e);
    }
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
    text("h2", "选择六边形、POI、公告场景或道路范围", panel);
    text("p", "点击地图查看事件与来源。", panel);
    return;
  }
  if (selected.type === "scene") {
    const available = new Set(sceneEventIds(activeScenes.features));
    selected.ids = selected.ids.filter((id) => available.has(id));
    if (!selected.ids.length) {
      selected = null;
      text("p", "所选场景在当前筛选下没有记录。", panel);
      return;
    }
    text("p", "SCENES / 公告地点", panel).className = "eyebrow";
    text("h2", `${selected.ids.length} 条公告`, panel);
    text("p", "场景位置按警方叙述角色展示；背景和行动地点不自动成为案发点。", panel);
    listReports(panel, selected.ids);
    return;
  }
  if (selected.type === "road") {
    const available = new Set(
      activeRoads.features.map((f) => String(f.properties.id)),
    );
    selected.ids = selected.ids.filter((id) => available.has(id));
    if (!selected.ids.length) {
      selected = null;
      text("p", "所选道路在当前筛选下没有记录。", panel);
      return;
    }
    text("p", "ROAD RANGE / 待定位公告", panel).className = "eyebrow";
    text("h2", `${selected.ids.length} 条待定位道路公告`, panel);
    text(
      "p",
      "橙色虚线是原文提到的道路候选范围；具体案发位置未知，不代表整条道路发生案件。这些公告仍未定位，未计入六边形或 POI 关联。",
      panel,
    ).className = "road-caution";
    listReports(panel, selected.ids);
    return;
  }
  const selection = selected;
  const f = (selection.type === "hex" ? activeHex : activePois).features.find(
    (f) => f.properties.id === selection.id,
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
      text("p", `${categoryLabel(key)}　${n}`, panel);
    text("p", "办案结果：数据未提供。街道级坐标是近似位置。", panel).className =
      "hint";
  } else {
    text(
      "p",
      (p.context_kinds ?? [p.kind]).map((kind: string) => data.catalog.poi_types[kind]?.label ?? kind).join(" / "),
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
    if (p.native_reference_extent === "named_park_building_only")
      text("p", "这里只显示园区的一处建筑；整个园区边界仍未知。", panel);
    if ((p.context_kinds ?? [p.kind]).includes("industrial_company"))
      text("p", "工业用途依OSM现有标注；实际经营状态和完整厂区范围未核实。", panel);
    text(
      "p",
      `附近同类提及 ${p.count} 条；街道近似坐标候选 ${p.candidate_count} 条；经复核上下文 ${p.context_count ?? 0} 条`,
      panel,
    );
    text("p", "这些是经原文复核的场所上下文，不表示事件发生在这家店内。", panel).className =
      "hint";
    if ((p.context_count ?? 0) > 0 && p.native_type_addition_binding?.source_venue_identity_verified === false)
      text("p", "关联公告未确认这是原文所指场所；仅保留同类道路上下文。", panel);
    if (p.opening_hours) text("p", `OSM 营业时间：${p.opening_hours}`, panel);
    link(panel, "OSM 对象 ↗", p.source_url);
    const sources = data.catalog.sources.filter((s) =>
      s.poi_types.some((kind: string) => (p.context_kinds ?? [p.kind]).includes(kind)),
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
function setRoadVisibility() {
  const visibility = el<HTMLInputElement>("candidate-roads-toggle").checked
    ? "visible"
    : "none";
  for (const layer of ["candidate-roads-line", "candidate-roads-hit"])
    map.setLayoutProperty(layer, "visibility", visibility);
}
function refresh() {
  if (!loaded || expired) return;
  const month = data.months[monthKey()],
    rows = events(),
    ids = new Set(rows.map((e) => e.id)),
    countable = countableEventIds(rows);
  const mode =
    map.getZoom() >= data.metadata.zoom_threshold ? "detail" : "overview";
  activeHex = month ? filteredHex(month.hex[mode], countable) : empty();
  activePois = styledPois(
    data,
    month?.links ?? [],
    ids,
    kinds(),
    el<HTMLInputElement>("highlight").checked,
  );
  activeRoads = candidateRoads(rows);
  activeScenes = sceneFeatures(rows);
  setSource("hex", activeHex);
  setSource("pois", activePois);
  setSource("candidate-roads", activeRoads);
  setSource("scenes", activeScenes);
  setRoadVisibility();
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
        e.scene_locations !== undefined
          ? !countable.has(e.id)
          : !e.coordinates ||
            !["street", "point", "place", "address"].includes(e.location_precision),
    );
    text(
      "p",
      `可计数点位 ${rows.length - unmapped.length} 篇 · 无精确计数点位 ${unmapped.length} 篇 · ${rows.filter(event => event.scene_locations?.some(scene => scene.geometry)).length} 篇有场景展示参考`,
      el("stats"),
    );
    const roadReferences = unmapped.filter(event => candidateRoadGeometry(event)).length;
    if (roadReferences) {
      text("p", `其中 ${roadReferences} 条可查看道路范围`, el("stats"));
    }
    const btn = text(
      "button",
      `${unmapped.length} 条位置不足，查看列表`,
      el("stats"),
    );
    btn.onclick = () => {
      const p = openDialog("位置不足的警情");
      text(
        "p",
        data.metadata.upstream_provider === "POLIZEIKARTE"
          ? "上游没有提供可计入慕尼黑市域网格的街道点，或坐标位于市界外；记录及来源仍完整保留。"
          : "已复核的道路或设施参考不等于精确案件点；没有精确点的公告及全部地点场景继续保留。",
        p,
      );
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
function externalMapsDialog() {
  const p = openDialog("德国城市 · 外部警情网站");
  text(
    "p",
    "POLIZEIKARTE 是独立数据项目。可查看公报列表、地图及原文链接；各城市的覆盖和定位精度不同。链接在新标签页打开。",
    p,
  );
  const nav = text("nav", "", p);
  nav.className = "city-map-links";
  nav.setAttribute("aria-label", "POLIZEIKARTE 城市页面");
  for (const item of externalMaps) link(nav, `${item.city} ↗`, item.url);
  link(p, "查看全部城市 ↗", externalMapsDirectory);
}
function sourcesDialog() {
  const p = openDialog(
    data.metadata.upstream_provider === "POLIZEIKARTE"
      ? "慕尼黑数据与场所来源"
      : "欧洲警方场所来源目录",
  );
  if (data.metadata.upstream_provider === "POLIZEIKARTE") {
    text(
      "p",
      "慕尼黑地图直接采用所有者接受的 POLIZEIKARTE 分类与地点成果。POLIZEIKARTE 是独立项目；每条记录仍链接警方原文，市界外及非点位记录不进入六边形。",
      p,
    );
    link(p, "POLIZEIKARTE 慕尼黑数据页 ↗", cityView.policeUrl);
  }
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
    `一般预防建议用于场所分类；它不把${cityView.name}同类商户自动标记为犯罪高发。`,
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
    const response = await fetch(cityView.manifestPath, {
      cache: "no-store",
    });
    if (!response.ok)
      throw Error("未找到有效的本地警情数据，请运行数据构建命令。");
    manifest = (await response.json()) as Manifest;
    if (manifest.city !== cityView.manifestCity)
      throw Error("城市数据清单与所选城市不匹配。");
    if (
      manifest.owner_approved === false ||
      manifest.publication_ready === false ||
      manifest.status?.includes("unapproved")
    )
      el("review-badge").hidden = false;
    client = new DataClient(manifest, cityView.dataRoot);
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
      el<HTMLSelectElement>("category").add(new Option(categoryLabel(c), c));
    const baselinePoiKinds = new Set(["airport", "attraction", "bar", "cafe", "fast_food", "hotel", "marketplace", "nightclub", "park", "parking", "restaurant", "shop", "station"]);
    const visibleAddedKinds = new Set(["healthcare", "school", "bus_stop"]);
    const extraTypes = document.createElement("details");
    extraTypes.id = "additional-poi-types";
    const extraTypeCount = Object.keys(data.catalog.poi_types)
      .filter((kind) => !baselinePoiKinds.has(kind) && !visibleAddedKinds.has(kind)).length;
    text("summary", `其他场所类型（${extraTypeCount}类）`, extraTypes);
    for (const [key, value] of Object.entries(data.catalog.poi_types)) {
      const label = document.createElement("label");
      label.className = "toggle";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = key;
      const memberships = manifest.metadata.poi_membership_counts;
      const nativeCount = memberships ? Number(memberships[key] ?? 0) : undefined;
      input.disabled = nativeCount === 0;
      input.checked = ["bar", "nightclub", "station", "shop"].includes(key);
      input.onchange = () => void loadViewport();
      label.append(input);
      const swatch = document.createElement("i");
      swatch.style.background = value.color;
      label.append(swatch, document.createTextNode(`${value.label}${nativeCount === undefined ? "" : ` · ${nativeCount}${nativeCount === 0 ? "（原生对象待核）" : ""}`}`));
      (baselinePoiKinds.has(key) || visibleAddedKinds.has(key) ? el("poi-filters") : extraTypes).append(label);
    }
    el("poi-filters").append(extraTypes);
    if (manifest.metadata.candidate_notice) {
      const notice = document.createElement("p");
      notice.id = "current-candidate-notice";
      notice.textContent = String(manifest.metadata.candidate_notice);
      notice.className = "hint";
      el("coverage").after(notice);
    }
    if (manifest.metadata.source_reference_review_url) {
      const link = document.createElement("a");
      link.id = "official-reference-reviews";
      link.href = `/safety/cities/hamburg/${String(manifest.metadata.source_reference_review_url)}`;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "查看官方补充公告与逐篇说明（含市域未知记录）";
      el("coverage").after(link);
    }
    const outside = Number(manifest.metadata.known_outside_municipality ?? 0);
    const cityPoints = Number(manifest.metadata.point_entries_in_city ?? 0);
    el("coverage").textContent = manifest.metadata.upstream_provider === "POLIZEIKARTE"
      ? `POLIZEIKARTE 收录 ${manifest.coverage.fetched} 条；${cityPoints} 条街道点通过慕尼黑市界核验。${outside} 条已知市外记录及其他非点记录保留来源，但不计入市域六边形。`
      : `来源数据发现 ${manifest.coverage.discovered} 条，已获取 ${manifest.coverage.fetched} 条，待获取 ${manifest.coverage.pending} 条。按月份筛选；并非全部报案记录。`;
    el("freshness").textContent =
      `快照：${new Date(data.retrieved_at).toLocaleString("zh-CN")}。更新流程由本地采集任务维护。`;
    map = new maplibregl.Map({
      container: "map",
      center: cityView.center,
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
          `<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">场所/道路：© OpenStreetMap contributors</a> / <a href="https://www.geofabrik.de/" target="_blank" rel="noopener noreferrer">Geofabrik</a> · <a href="${cityView.policeUrl}" target="_blank" rel="noopener noreferrer">警情：${cityView.policeName}</a>`,
      }),
    );
    map.once("load", async () => {
      for (const id of [
        "roads",
        "hex",
        "pois",
        "kbo",
        "reported-sections",
        "candidate-roads",
        "scenes",
      ])
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
      map.addLayer({
        id: "candidate-roads-line",
        type: "line",
        source: "candidate-roads",
        paint: {
          "line-color": "#e87917",
          "line-width": 4,
          "line-dasharray": [2, 1.5],
        },
      });
      map.addLayer({
        id: "candidate-roads-hit",
        type: "line",
        source: "candidate-roads",
        paint: { "line-width": 14, "line-opacity": 0 },
      });
      map.addLayer({
        id: "scene-area-fill",
        type: "fill",
        source: "scenes",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": sceneColor, "fill-opacity": ["case", ["any", ["==", ["get", "role_group"], "context"], ["in", ["get", "location_precision"], ["literal", ["district", "area"]]]], 0, 0.22] },
      });
      map.addLayer({
        id: "scene-area-outline",
        type: "line",
        source: "scenes",
        filter: ["all", ["==", ["geometry-type"], "Polygon"], ["!", ["any", ["==", ["get", "role_group"], "context"], ["in", ["get", "location_precision"], ["literal", ["district", "area"]]]]]],
        paint: { "line-color": sceneColor, "line-width": 2 },
      });
      map.addLayer({
        id: "scene-context-boundary", type: "line", source: "scenes",
        filter: ["all", ["==", ["geometry-type"], "Polygon"], ["any", ["==", ["get", "role_group"], "context"], ["in", ["get", "location_precision"], ["literal", ["district", "area"]]]]],
        paint: {"line-color": sceneColor, "line-width": ["case", ["==", ["get", "geometry_usage"], "official_attachment_horizontal_reference_only"], 2, 0.8], "line-opacity": ["case", ["==", ["get", "geometry_usage"], "official_attachment_horizontal_reference_only"], 0.7, 0.2]},
      });
      map.addLayer({
        id: "scene-line",
        type: "line",
        source: "scenes",
        filter: [
          "all",
          ["==", ["geometry-type"], "LineString"],
          ["!=", ["get", "geometry_kind"], "candidate_road"],
          ["!=", ["get", "geometry_kind"], "transit_route"],
          ["!=", ["get", "geometry_kind"], "transit_line_reference"],
        ],
        paint: { "line-color": sceneColor, "line-width": 4 },
      });
      map.addLayer({
        id: "scene-line-hit", type: "line", source: "scenes",
        filter: ["all", ["==", ["geometry-type"], "LineString"],
          ["!=", ["get", "geometry_kind"], "candidate_road"],
          ["!=", ["get", "geometry_kind"], "transit_route"],
          ["!=", ["get", "geometry_kind"], "transit_line_reference"]],
        paint: { "line-width": 14, "line-opacity": 0 },
      });
      map.addLayer({
        id: "scene-transit-route",
        type: "line",
        source: "scenes",
        filter: ["==", ["get", "geometry_kind"], "transit_route"],
        paint: {
          "line-color": "#6d4bc3",
          "line-width": 5,
          "line-dasharray": [2, 1.2],
        },
      });
      map.addLayer({
        id: "scene-transit-line-reference",
        type: "line",
        source: "scenes",
        filter: ["==", ["get", "geometry_kind"], "transit_line_reference"],
        paint: {
          "line-color": "#6d4bc3",
          "line-width": 2,
          "line-opacity": 0.45,
          "line-dasharray": [1, 3],
        },
      });
      map.addLayer({
        id: "scene-candidate-road-line",
        type: "line",
        source: "scenes",
        filter: ["==", ["get", "geometry_kind"], "candidate_road"],
        paint: {
          "line-color": sceneColor,
          "line-width": 3,
          "line-dasharray": [2, 1.5],
        },
      });
      map.addLayer({
        id: "scene-candidate-road-hit",
        type: "line",
        source: "scenes",
        filter: ["==", ["get", "geometry_kind"], "candidate_road"],
        paint: { "line-width": 14, "line-opacity": 0 },
      });
      map.addLayer({
        id: "scene-point",
        type: "circle",
        source: "scenes",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": 6,
          "circle-color": ["case", ["==", ["get", "geometry_usage"], "source_native_platform_points_reference_only"], "#fff", sceneColor],
          "circle-stroke-color": ["case", ["==", ["get", "geometry_usage"], "source_native_platform_points_reference_only"], "#a16207", "#fff"],
          "circle-stroke-width": 2,
        },
      });
      // Show selectable POIs above broad scene areas and road references;
      // exact native scene points remain visible above the contextual POIs.
      for (const layer of ["poi-fill", "poi-line", "poi-point"])
        map.moveLayer(layer, "scene-point");
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
          layers: [
            "scene-point", "scene-candidate-road-hit", "scene-line", "scene-line-hit", "scene-transit-route",
            "scene-area-fill", "scene-area-outline", "scene-context-boundary",
            "candidate-roads-hit", "poi-fill", "poi-point", "hex-fill",
          ],
        });
        if (!fs.length) return;
        const pointScenes = fs.filter((f) => f.layer.id === "scene-point");
        if (pointScenes.length) {
          selected = { type: "scene", ids: sceneEventIds(pointScenes) };
          showSelection();
          return;
        }
        const poi = fs.find((f) => f.layer.id.startsWith("poi-"));
        if (poi) {
          selected = { type: "poi", id: poi.properties.id };
          showSelection();
          return;
        }
        const coarseArea = (f: (typeof fs)[number]) =>
          ["scene-area-fill", "scene-area-outline", "scene-context-boundary"].includes(f.layer.id) &&
          (f.properties.role_group === "context" || ["district", "area"].includes(f.properties.location_precision));
        const scenes = fs.filter((f) => f.layer.id.startsWith("scene-") &&
          !(f.layer.id === "scene-area-fill" && coarseArea(f)));
        const specificScenes = scenes.filter((f) => !coarseArea(f));
        if (scenes.length) {
          selected = { type: "scene", ids: sceneEventIds(specificScenes.length ? specificScenes : scenes) };
          showSelection();
          return;
        }
        const roadIds = [
          ...new Set(
            fs
              .filter((f) => f.layer.id === "candidate-roads-hit")
              .map((f) => String(f.properties.id)),
          ),
        ];
        if (roadIds.length) {
          selected = { type: "road", ids: roadIds };
          showSelection();
          return;
        }
        const f = fs.find((f) => f.layer.id === "hex-fill");
        if (!f) return;
        selected = { type: "hex", id: f.properties.id };
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
    el("candidate-roads-toggle").onchange = () => {
      if (loaded) setRoadVisibility();
    };
    for (const id of ["year", "month"])
      el(id).onchange = () => void loadMonth();
    el("overview").onclick = () =>
      map.flyTo({ center: cityView.center, zoom: 10.5 });
    el("sources").onclick = sourcesDialog;
    if (cityView.kbo) el("kbo").onclick = kboDialog;
    freshnessTimer = setInterval(async () => {
      if (document.hidden) return;
      try {
        const r = await fetch(cityView.manifestPath, { cache: "no-store" });
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
