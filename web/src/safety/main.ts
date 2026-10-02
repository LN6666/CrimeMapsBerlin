import {catalogSummary,loadCatalogTranslations} from "./catalog-translations";
import {DynamicTranslations} from "./dynamic-translations";
import {mountAnnouncementMethods} from "./methods";
import {mountUncertaintyPanel} from "./uncertainty-panel";
import {mountFeedbackPanel} from "./feedback";
import {mountAnalytics} from "./analytics";
import "./analytics.css";
import {installMobileLayout} from "./mobile-layout";
import {t,locale,localeCode,number,date,html,cityName,poiName,sourceContextName,languageURL} from "./i18n";
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
  locationCoverage,
  monthEvents,
  roadBounds,
  safeURL,
  sceneEventIds,
  sceneFeatures,
  sceneRoleLabel,
  SCENE_CLICK_LAYERS,
  styledPois,
  unplacedStages,
  sourcePoiReferences,
  SOURCE_POI_CLICK_LAYERS,
  renderPois,
  poiGeometryLabel,
  transitGeometryLabel,
} from "./model";
import type { Bundle, FC, PoliceEvent } from "./model";
import {fetchDataJSON} from "./security";
import { DataClient } from "./data";
import type { Manifest } from "./data";
import { Basemaps, basemapLabels } from "./basemaps";
import type { BasemapId } from "./basemaps";
import { externalMaps, externalMapsDirectory } from "./external-maps";
import { cityGroups, requestedMapView } from "./cities";
import { cityDestination, requestedMonth } from "./deployment";

const cityView = requestedMapView(window.location.search);
const currentCity = cityView.id;
const localizedCity=cityName(currentCity,cityView.latin);
document.title = t("app.title",{city:localizedCity});

const categoryLabels: Record<string, string> = {
  betrug: t("category.betrug"),
  brand: t("category.brand"),
  diebstahl: t("category.diebstahl"),
  drogen: t("category.drogen"),
  einbruch: t("category.einbruch"),
  gewalt: t("category.gewalt"),
  raub: t("category.raub"),
  sexualdelikte: t("category.sexualdelikte"),
  sonstige: t("category.sonstige"),
  verkehr: t("category.verkehr"),
};
const categoryLabel = (category: string) => categoryLabels[category] ?? category;

const reviewedTagLabels: Record<string, string> = {
  violent_assault: t("tag.violent_assault"),
  robbery: t("tag.robbery"),
  threat: t("tag.threat"),
  sexual_offence: t("tag.sexual_offence"),
  property_offence: t("tag.property_offence"),
  possible_hate_crime: t("tag.possible_hate_crime"),
};
const precisionLabels: Record<string, string> = {
  street: t("precision.street"),
  place: t("precision.place"),
  address: t("precision.address"),
  point: t("precision.point"),
  route: t("precision.route"),
  district: t("precision.district"),
  city: t("precision.city"),
  unknown: t("precision.unknown"),
};
const locationScopeLabels: Record<string, string> = {
  in_city: t("scope.in_city"),
  outside_city: t("scope.outside_city",{city:localizedCity}),
  unresolved_no_upstream_coordinate: t("scope.unresolved_no_upstream_coordinate"),
};
const sourceStatusLabels: Record<string, string> = {
  polizeikarte_complete_365_day_snapshot: t("sourceStatus.polizeikarte_complete_365_day_snapshot"),
  complete_official_archive_source_and_geometry_reviewed: t("sourceStatus.complete_official_archive_source_and_geometry_reviewed"),
  complete_frozen_owner_batch_source_and_geometry_reviewed: t("sourceStatus.complete_frozen_owner_batch_source_and_geometry_reviewed"),
  source_geometry_map_decision_coverage_verified_not_full_acceptance: t("sourceStatus.source_geometry_map_decision_coverage_verified_not_full_acceptance"),
  frozen_owner_batch_decision_coverage_verified_not_full_acceptance: t("sourceStatus.frozen_owner_batch_decision_coverage_verified_not_full_acceptance"),
};
const sceneRelationLabels: Record<string, string> = {
  independent_case: t("relation.independent_case"),
  same_case_phase: t("relation.same_case_phase"),
  search_arrest_operation: t("relation.search_arrest_operation"),
  background_reference: t("relation.background_reference"),
  unresolved_relation: t("relation.unresolved_relation"),
};
const sceneColor: maplibregl.ExpressionSpecification = [
  "match", ["get", "role_group"],
  "incident", "#b43d4b",
  "discovery", "#2874a6",
  "operation", "#986223",
  "#677785",
];

const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `<header><div><span class="brand">${currentCity === "berlin" ? "CRIMEMAPSBERLIN" : "CRIMEMAPS.DE"}</span><span id="review-badge" class="review-badge" hidden>${html(t("app.preview"))}</span><h1>${html(t("app.heading",{city:localizedCity}))}</h1></div><div class="toolbar"><label>${html(t("nav.language"))}<select id="language" aria-label="${html(t("nav.language"))}"><option value="de">Deutsch</option><option value="en">English</option><option value="zh">中文</option></select></label><label class="city-switch">${html(t("nav.city"))}<select id="city-switch" aria-label="${html(t("nav.city"))}"></select></label><label>${html(t("nav.year"))}<select id="year" aria-label="${html(t("nav.year"))}"></select></label><label>${html(t("nav.month"))}<select id="month" aria-label="${html(t("nav.month"))}"></select></label><button id="overview">${html(t("nav.overview"))}</button><button id="sources">${html(t("nav.sources"))}</button></div></header>
<main><aside class="controls"><p class="eyebrow">${html(localizedCity)} / ${html(t("app.publicReports"))}</p><h2>${html(t("app.tagline"))}</h2><p id="coverage">${html(t("map.loadingData"))}</p><nav id="external-maps" class="external-maps" aria-label="${html(t("external.aria"))}"></nav><label class="search-label">${html(t("search.label",{city:localizedCity}))}<input id="search" placeholder="${html(t("search.placeholder",{},cityView.latin))}" autocomplete="off"></label><div id="search-results"></div><label>${html(t("filter.category"))}<select id="category"><option value="all">${html(t("filter.allReports"))}</option></select></label><div class="rule"></div><h3>${html(t("legend.hex"))}</h3><div class="ramp"></div><div class="ends"><span>${html(t("legend.low"))}</span><span>${html(t("legend.high"))}</span></div><p id="resolution"></p><label class="toggle"><input id="hex-toggle" type="checkbox" checked> ${html(t("legend.showHex"))}</label><label class="toggle"><input id="candidate-roads-toggle" type="checkbox" checked> ${html(t("legend.showRoads"))}</label><p class="hint"><span class="road-swatch" aria-hidden="true"></span>${html(t("legend.roadNote"))}</p><div class="scene-legend" aria-label="${html(t("legend.scenesAria"))}"><span><i class="scene-swatch incident"></i>${html(t("legend.incident"))}</span><span><i class="scene-swatch discovery"></i>${html(t("legend.discovery"))}</span><span><i class="scene-swatch operation"></i>${html(t("legend.operation"))}</span><span><i class="scene-swatch context"></i>${html(t("legend.context"))}</span><span><i class="route-swatch"></i>${html(t("legend.transit"))}</span></div><h3>${html(t("legend.pois"))}</h3><div id="poi-filters"></div><label class="toggle"><input id="highlight" type="checkbox" checked> ${html(t("legend.highlight"))}</label><p class="hint">${html(t("legend.highlightNote"))}</p><div class="rule"></div><button id="kbo">${html(t("kbo.button"))}</button><p class="hint">${html(t("kbo.separate"))}</p><p id="freshness" class="hint"></p></aside>
<section class="map-wrap"><div id="map" aria-label="${html(t("map.aria",{city:localizedCity}))}"></div><div class="map-label"><span class="dot"></span><span id="map-status" role="status" aria-live="polite">${html(t("map.preparing"))}</span></div><div class="basemap-picker"><label>${html(t("map.basemap"))}<select id="basemap" aria-label="${html(t("map.basemap"))}" disabled><option value="vector">${html(t("basemap.vector"))}</option><option value="street">${html(t("basemap.street"))}</option><option value="aerial">${html(t("basemap.aerial"))}</option><option value="local">${html(t("basemap.local"))}</option></select></label><div id="basemap-error" role="status" hidden><span></span><button id="basemap-fallback">${html(t("basemap.fallback"))}</button></div></div><div class="map-note">${html(t("map.poiNote"))}</div><p class="hint basemap-language-note">${html(t("basemap.languageNote"))}</p></section>
<aside class="details"><div id="stats"></div><div id="methods-panel"></div><div id="selection"><h2>${html(t("selection.prompt"))}</h2><p>${html(t("selection.intro"))}</p></div><div id="uncertainty-panel"></div><div id="feedback-panel"></div><div id="analytics-panel"></div></aside></main>
<dialog id="drawer"><button id="close-dialog" class="close">${html(t("action.close"))}</button><div id="drawer-content"></div></dialog>`;
const el = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.getElementById(id) as T;
el<HTMLSelectElement>("language").value=locale;
el("language").onchange=()=>{const url=new URL(location.href);url.searchParams.set("lang",el<HTMLSelectElement>("language").value);url.searchParams.set("month",monthKey());location.assign(url.href);};
const citySelect = el<HTMLSelectElement>("city-switch");
for (const group of cityGroups) {
  const section = document.createElement("optgroup");
  section.label = t("nav.cities");
  for (const city of group.cities) {
    const option = new Option(
      cityName(city.id,city.id) + (city.href ? "" : ` · ${t("nav.preparing")}`),
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
  if (destination?.href) {
    const query = new URLSearchParams(window.location.search);
    query.set("lang", locale);
    window.location.assign(cityDestination(destination.id, query.toString(), monthKey()));
  }
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
link(el("external-maps"), `POLIZEIKARTE ${localizedCity} ↗`, cityView.externalUrl);
if (!cityView.kbo) {
  el("kbo").hidden = true;
  el("kbo").nextElementSibling?.remove();
}
if (!cityView.aerial)
  el<HTMLSelectElement>("basemap").querySelector<HTMLOptionElement>("option[value='aerial']")!.disabled = true;
text("button", t("nav.otherCities"), el("external-maps")).onclick =
  externalMapsDialog;
const dynamicText=new DynamicTranslations();
const methodsPanel=mountAnnouncementMethods(el("methods-panel"),{t,locale,categoryLabel});
const uncertaintyPanel=mountUncertaintyPanel(el("uncertainty-panel"),{locale,city:currentCity,translate:t,onSelect:(id)=>{const p=openDialog(t("report.scenes"));listReports(p,[id]);}});
const feedbackPanel=mountFeedbackPanel(el("feedback-panel"),{locale,city:currentCity,translate:t});
const analyticsPanel=mountAnalytics(el("analytics-panel"),{language:locale,city:currentCity,translate:(key,params)=>t(key,params)});
let data: Bundle;
let map: maplibregl.Map;
const mobileLayout=installMobileLayout(app,{labels:{filters:t("mobile.filters"),showFilters:t("mobile.showFilters"),hideFilters:t("mobile.hideFilters"),map:t("mobile.map"),details:t("mobile.details"),skipToMap:t("mobile.skipToMap")},onLayoutChange:()=>map?.resize()});
let basemaps: Basemaps;
let activeHex: FC = empty();
let activePois: FC = empty();
let activeRoads: FC = empty();
let activeScenes: FC = empty();
let activeSourcePois:FC=empty();
let loaded = false;
let expired = false;
let freshnessTimer: ReturnType<typeof setInterval>;
let selected:
  | { type: "hex" | "poi"; id: string }
  | { type: "road"; ids: string[] }
  | { type: "scene"; ids: string[] }
  | { type: "source_poi"; ids: string[] }
  | null = null;
let pendingSearchPoiId: string | null = null;
let client: DataClient;
let manifest: Manifest;
let monthRequest = new AbortController();
let viewportRequest = new AbortController();
let viewportTimer: ReturnType<typeof setTimeout>;
let currentMode = "";
let searchIndex:
  | { id: string; name: string; kind: string; scope_category?:string; center: [number, number] }[]
  | undefined;
let searchLoading: Promise<void> | undefined;
const searchRequest=new AbortController();
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
  pendingSearchPoiId = null;
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
function listReports(parent: HTMLElement, ids: string[]) {
  const wanted = new Set(ids);
  for (const e of dynamicText.displayRows(data.events).filter((e) => wanted.has(e.id))) {
    const card = document.createElement("article");
    card.className = "report";
    parent.append(card);
    text(
      "small",
      `${e.event_date ? date(e.event_date) : t("report.publishedMonth",{month:e.month??"—"})} · ${categoryLabel(e.category)} · ${precisionLabels[e.location_precision] ?? t("precision.unknown")}`,
      card,
    );
    if (e.source_status && ["unavailable","refresh_failed"].includes(e.source_status)) {
      const status = sourceStatusLabels[e.source_status];
      text(
        "small",
        status ?? (e.source_status === "unavailable"
          ? t("report.sourceUnavailable")
          : t("report.sourceRefreshFailed")),
        card,
      );
    }
    if (e.source_scope_verdict === "uncertain")
      text("small", t("report.cityUncertain"), card);
    text("h4", e.title, card);
    if(dynamicText.missingFor(e))text("small",t("report.translationMissing"),card);
    for (const tag of e.reviewed_tags ?? []) {
      const label = reviewedTagLabels[tag.tag];
      if (label)
        text("small", t("report.aiLead",{label,quote:tag.evidence_quote}), card);
    }
    text("p", e.location_label, card);
    if (e.location_scope && locationScopeLabels[e.location_scope])
      text("small", locationScopeLabels[e.location_scope], card);
    if (e.scene_locations?.length) {
      const heading = text("small", t("report.scenes"), card);
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
          `${scene.case_relation ? `${sceneRelationLabels[scene.case_relation]} · ` : ""}${precisionLabels[scene.location_precision] ?? t("precision.unknown")} · ${scene.primary_for_count ? t("report.primary") : t("report.displayOnly")}${scene.candidate_road_geometry ? ` · ${t("report.roadPending")}` : ""}`,
          item,
        );
        const eventTimes = [
          scene.event_time?.display,
          ...(scene.incidents ?? []).map((incident) => incident.event_time?.display),
        ].filter((value): value is string => Boolean(value));
        const uniqueTimes = [...new Set(eventTimes)];
        if (uniqueTimes.length)
          text("small", t("report.originalTime",{times:uniqueTimes.join("; ")}), item);
        if (scene.transit_route)
          text(
            "small",
            `${scene.transit_route.mode} ${scene.transit_route.line} · ${transitGeometryLabel(scene)}`,
            item,
          );
        if (scene.geometry_usage === "source_native_collection_reference_only")
          text("small", t("geometry.collectionReference"), item);
        if (scene.geometry_usage === "source_footprint_reference_only")
          text("small", scene.geocode_method === "official_district_footprint_reference"
            ? t("geometry.districtReference")
            : scene.geocode_method === "osm_water_footprint_reference"
            ? t("geometry.waterReference")
            : scene.actual_non_transit_extent_known === false
            ? t("geometry.nonTransitReference")
            : t("geometry.footprintReference"), item);
        if (scene.geometry_usage === "source_road_reference_only" && !scene.transit_route)
          text("small", t("geometry.roadNoPoint",{reference:transitGeometryLabel(scene)}), item);
        if (scene.geometry_usage === "source_junction_reference_only")
          text("small", t("geometry.junctionReference"), item);
        const details = [
          scene.details,
          ...(scene.incidents ?? []).map((incident) => incident.details),
        ].filter((value): value is string => Boolean(value));
        for (const detail of [...new Set(details)]) text("small", detail, item);

        if (scene.poi_contexts?.length) {
          const kinds = [...new Set(scene.poi_contexts.map((context) =>
            sourceContextName(context.kind)))];
          text(
            "small",
            t("report.poiContext",{types:kinds.join(", ")}),
            item,
          );
        }
      }
      text(
        "small",
        t("report.countPolicy"),
        card,
      );
    }
    const otherStages=unplacedStages(e);
    if(otherStages.length){
      text("small",t("report.otherStages"),card).className="scene-heading";
      const list=document.createElement("ul");list.className="scene-list unplaced-stages";card.append(list);
      for(const stage of otherStages){const item=document.createElement("li");item.dataset.incidentId=stage.incident_id;list.append(item);
       text("strong",t(stage.formal_location_ids?.length?"report.stagePlaceUnmatched":"report.stagePlaceUnknown"),item);
       if(stage.event_time?.display)text("small",t("report.originalTime",{times:stage.event_time.display}),item);
       if(stage.details)text("small",stage.details,item);
      }
    }
    if (e.geocode_method === "multiple_official_scenes")
      text(
        "small",
        e.coordinates
          ? t("report.multiPlacesCount")
          : t("report.multiPlacesNoCount"),
        card,
      );
    if (e.geocode_method === "multi_event_summary")
      text("small", t("report.multiSummary"), card);
    if (e.location_selection === "first_explicit_incident_scene")
      text(
        "small",
        e.coordinates
          ? t("report.incidentFirst")
          : t("report.incidentUnresolved"),
        card,
      );
    const otherScenes = [
      ...new Set(e.other_scene_candidates?.map((s) => s.name) ?? []),
    ];
    if (otherScenes.length)
      text(
        "small",
        t("report.otherScenes",{places:otherScenes.join(", "),countStatus:t(e.coordinates?"report.countedOnce":"report.notCounted")}),
        card,
      );
    const road = candidateRoadGeometry(e);
    if (road) {
      text(
        "small",
        t("report.roadUnresolved",{reason:t(e.geocode_method==="disconnected_street_review"?"report.roadDisconnected":"report.roadAmbiguous")}),
        card,
      ).className = "road-caution";
      if (e.location_scope)
        text("small", t("report.locationScope",{scope:e.location_scope}), card);
      const button = text("button", t("report.showRoad"), card);
      button.className = "road-focus";
      button.onclick = () => focusRoad(e);
    }
    if (e.location_extent_m !== undefined && e.location_extent_m > 75)
      text(
        "small",
        t("report.locationExtent",{metres:number(e.location_extent_m),locationStatus:t(e.coordinates?"report.approximateCount":"report.exactUnresolved")}),
        card,
      );
    link(card, t("report.source"), e.source_url);
    if (e.poi_mentions.length)
      text(
        "small",
        t("report.sourcePlaceTypes",{types:e.poi_mentions.map(sourceContextName).join(", ")}),
        card,
      );
  }
}
function showSelection() {
  const panel = el("selection");
  panel.replaceChildren();
  setSource("reported-sections", empty());
  if (!selected) {
    text("h2", t("selection.prompt"), panel);
    text("p", t("selection.intro"), panel);
    return;
  }
  if(selected.type==="source_poi"){
    const available=new Set(sceneEventIds(activeSourcePois.features));selected.ids=selected.ids.filter(id=>available.has(id));
    if(!selected.ids.length){selected=null;text("p",t("selection.objectEmpty"),panel);return;}
    text("h2",t("selection.announcementCount",{count:number(selected.ids.length)}),panel);text("p",t("rules.context_limitation"),panel);listReports(panel,selected.ids);return;
  }
  if (selected.type === "scene") {
    const available = new Set(sceneEventIds(activeScenes.features));
    selected.ids = selected.ids.filter((id) => available.has(id));
    if (!selected.ids.length) {
      selected = null;
      text("p", t("selection.sceneEmpty"), panel);
      return;
    }
    text("p", t("selection.scenes"), panel).className = "eyebrow";
    text("h2", t("selection.announcementCount",{count:number(selected.ids.length)}), panel);
    text("p", t("selection.sceneNote"), panel);
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
      text("p", t("selection.roadEmpty"), panel);
      return;
    }
    text("p", t("selection.road"), panel).className = "eyebrow";
    text("h2", t("selection.roadCount",{count:number(selected.ids.length)}), panel);
    text(
      "p",
      t("selection.roadNote"),
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
    if (selection.type === "poi" && pendingSearchPoiId === selection.id) {
      text("p", t("map.loadingPlace"), panel);
      return;
    }
    selected = null;
    text("p", t("selection.objectEmpty"), panel);
    return;
  }
  pendingSearchPoiId = null;
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
    text("p", t("selection.reportedSection"), panel);
  if (selected.type === "hex") {
    text("p", t("selection.hex"), panel).className = "eyebrow";
    text("h2", t("selection.announcementCount",{count:number(p.count)}), panel);
    text("p", t("selection.hexSize",{metres:number(p.edge_m),month:monthKey()}), panel);
    const rows = data.events.filter((e) =>
      (p.event_ids as string[]).includes(e.id),
    );
    const counts: Record<string, number> = {};
    for (const e of rows) counts[e.category] = (counts[e.category] ?? 0) + 1;
    for (const [key, n] of Object.entries(counts))
      text("p", `${categoryLabel(key)}　${n}`, panel);
    text("p", t("selection.outcomeUnknown"), panel).className =
      "hint";
  } else {
    text(
      "p",
      poiName(p.kind,data.catalog.poi_types[p.kind]?.label ?? p.kind),
      panel,
    ).className = "eyebrow";
    text("h2", p.name, panel);
    text(
      "p",
      poiGeometryLabel(p.geometry_mode),
      panel,
    );
    text(
      "p",
      t("selection.poiCounts",{mentions:number(p.count),candidates:number(p.candidate_count),contexts:number(p.context_count??0)}),
      panel,
    );
    text("p", t("selection.poiNote"), panel).className =
      "hint";
    if (p.opening_hours) text("p", t("selection.openingHours",{hours:p.opening_hours}), panel);
    link(panel, t("selection.osm"), p.source_url);
    const sources = data.catalog.sources.filter((s) =>
      s.poi_types.includes(p.kind),
    );
    const details = document.createElement("details");
    panel.append(details);
    text(
      "summary",
      t("selection.poiSources",{count:number(sources.length)}),
      details,
    );
    for (const s of sources) {
      text("p", `${s.country} · ${s.place} · ${s.evidence_type}`, details);
      link(details, s.publisher, s.url);
      text("p", catalogSummary(s), details);
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
  map.setPaintProperty("poi-circle", "circle-opacity", ["*", ["get", "opacity"], base === "street" ? 0.8 : 1]);
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
  activeSourcePois=sourcePoiReferences(rows,month?.source_poi_reference_features);
  setSource("hex", activeHex);
  setSource("pois", renderPois(activePois));
  setSource("candidate-roads", activeRoads);
  setSource("scenes", activeScenes);
  setSource("source-poi-references",activeSourcePois);
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
    t("legend.resolution",{metres:number(mode === "detail" ? 275 : 1100)});
  el("map-status").textContent = month
    ? t("map.monthCount",{month:monthKey(),count:number(rows.length)})
    : t("map.monthMissing",{month:monthKey()});
  el("stats").replaceChildren();
  text("div", month ? number(rows.length) : "—", el("stats")).className = "big";
  text("p", month ? t("coverage.filtered") : t("coverage.noMonth"), el("stats"));
  if (month) {
    const coverage = locationCoverage(rows, activeScenes);
    const noCountIds = new Set(coverage.withoutCountPointIds);
    const unmapped = rows.filter((event) => noCountIds.has(event.id));
    const sceneAware = rows.some((event) => event.scene_locations !== undefined);
    text(
      "p",
      sceneAware
        ? t("coverage.countPoints",{countable:number(coverage.countableAnnouncements),without:number(unmapped.length),references:number(coverage.withoutCountPointWithDisplayGeometry)})
        : t("coverage.located",{located:number(rows.length-unmapped.length),unresolved:number(unmapped.length),roads:number(activeRoads.features.length)}),
      el("stats"),
    );
    const btn = text(
      "button",
      t(sceneAware ? "coverage.noPointList" : "coverage.unresolvedList",{count:number(unmapped.length)}),
      el("stats"),
    );
    btn.onclick = () => {
      const p = openDialog(sceneAware ? t("coverage.noPointTitle") : t("coverage.unresolvedTitle"));
      text(
        "p",
        data.metadata.upstream_provider === "POLIZEIKARTE"
          ? t("coverage.munichUnknown")
          : sceneAware
            ? t("coverage.noPointNote")
            : t("coverage.roadUnknownNote"),
        p,
      );
      listReports(
        p,
        unmapped.map((e) => e.id),
      );
    };
  }
  methodsPanel.update(rows,{month:monthKey(),city:currentCity,generation:manifest.generation,category:el<HTMLSelectElement>("category").value,metadata:manifest.metadata,countReferenceIds:[...countable]});
  uncertaintyPanel.update(dynamicText.displayRows(rows));
  showSelection();
}
function openDialog(title: string) {
  const p = el("drawer-content");
  p.replaceChildren();
  text("h2", title, p).id="drawer-title";
  el("drawer").setAttribute("aria-labelledby","drawer-title");
  el<HTMLDialogElement>("drawer").showModal();
  return p;
}
function externalMapsDialog() {
  const p = openDialog(t("external.title"));
  text(
    "p",
    t("external.note"),
    p,
  );
  const nav = text("nav", "", p);
  nav.className = "city-map-links";
  nav.setAttribute("aria-label", t("external.polizeikarteAria"));
  for (const item of externalMaps) link(nav, `${cityName(item.id,item.city)} ↗`, item.url);
  link(p, t("external.allCities"), externalMapsDirectory);
}
function sourcesDialog() {
  const p = openDialog(
    data.metadata.upstream_provider === "POLIZEIKARTE"
      ? t("sources.munichTitle")
      : t("sources.title"),
  );
  if (data.metadata.upstream_provider === "POLIZEIKARTE") {
    text(
      "p",
      t("sources.munichNote"),
      p,
    );
    link(p, t("sources.munichLink"), cityView.policeUrl);
  }
  const n = data.catalog.coverage.filter(
    (c) => c.status === "sources_verified_partial",
  ).length;
  text(
    "p",
    t("sources.coverage",{countries:number(n),materials:number(data.catalog.sources.length)}),
    p,
  );
  text(
    "p",
    t("sources.prevention",{city:localizedCity}),
    p,
  );
  for (const s of data.catalog.sources) {
    const card = document.createElement("article");
    p.append(card);
    text("h3", `${s.country} / ${s.place}`, card);
    text("small", t("sources.verified",{type:s.evidence_type,date:date(s.verified_on)}), card);
    text("p", catalogSummary(s), card);
    link(card, s.publisher + " ↗", s.url);
  }
  text(
    "p",
    t("sources.pendingCountries",{countries:
      data.catalog.coverage
        .filter((c) => c.status === "not_yet_verified")
        .map((c) => c.country)
        .join(", ")}),
    p,
  );
}
function kboDialog() {
  const p = openDialog(t("kbo.title"));
  text(
    "p",
    t("kbo.note"),
    p,
  );
  for (const zone of data.zones.places) {
    const card = document.createElement("article");
    p.append(card);
    text("h3", zone.name, card);
    link(card, t("kbo.boundary"), zone.official_map_url);
    link(card, t("kbo.source"), zone.source_url);
    const b = text("button", t("kbo.navigate"), card);
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
  data.events = [];
  data.months = {};
  dynamicText.clear();
  refresh();
  el("map-status").textContent = t("map.loadingMonth");
  try {
    const value = await client.month(key, signal);
    if (signal.aborted || key !== monthKey()) return;
    data.events = value?.events ?? [];
    data.months = value ? { [key]: value } : {};
    try {await dynamicText.load(data.events,manifest,client,key,locale,signal,currentCity);}catch(error){if(signal.aborted)throw error;dynamicText.clear();dynamicText.missing=data.events.length;}
    if(signal.aborted||key!==monthKey())return;
    pendingSearchPoiId = null;
    selected = null;
    refresh();
  } catch (error) {
    if (!signal.aborted) {
      data.events = [];
      data.months = {};
      refresh();
      console.error(error);
      el("map-status").textContent = t("map.loadFailed");
      el("stats").replaceChildren();text("p",t("map.loadFailed"),el("stats"));
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
  setSource("roads", empty());
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
    if (!detail) el("map-status").textContent += ` · ${t("map.zoomForPlaces")}`;
  } catch (error) {
    if (!signal.aborted) { console.error(error);el("map-status").textContent = t("map.loadFailed"); }
  }
}
async function start() {
  try {
    manifest = await fetchDataJSON<Manifest>(cityView.manifestPath);
    if (manifest.city !== cityView.manifestCity)
      throw Error(t("error.cityMismatch"));
    if (new URLSearchParams(location.search).has("diagnostics") && (
      manifest.owner_approved === false ||
      manifest.publication_ready === false ||
      manifest.status?.includes("unapproved")
    ))
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
    await loadCatalogTranslations(data.catalog.sources);
    const months = Object.keys(manifest.months).sort();
    const latest = requestedMonth(window.location.search, months, months.at(-1) ?? data.retrieved_at.slice(0, 7));
    const years = [
      ...new Set([...months.map((m) => m.slice(0, 4)), latest.slice(0, 4)]),
    ];
    for (const y of years) el<HTMLSelectElement>("year").add(new Option(y, y));
    for (let m = 1; m <= 12; m++)
      el<HTMLSelectElement>("month").add(
        new Option(new Intl.DateTimeFormat(localeCode,{month:"long"}).format(new Date(2026,m-1,1)), String(m).padStart(2, "0")),
      );
    el<HTMLSelectElement>("year").value = latest.slice(0, 4);
    el<HTMLSelectElement>("month").value = latest.slice(5, 7);
    for (const c of manifest.categories)
      el<HTMLSelectElement>("category").add(new Option(categoryLabel(c), c));
    const filters=manifest.poi_scope_groups?Object.fromEntries(Object.entries(manifest.poi_scope_groups).map(([key,value])=>[key,{label:t(value.label_key),color:data.catalog.poi_types[value.kinds[0]]?.color??"#64748b"}])):data.catalog.poi_types;
    for (const [key, value] of Object.entries(filters)) {
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
      label.append(swatch, document.createTextNode(poiName(key,value.label)));
      el("poi-filters").append(label);
    }
    const outside = Number(manifest.metadata.known_outside_municipality ?? 0);
    const cityPoints = Number(manifest.metadata.point_entries_in_city ?? 0);
    el("coverage").textContent = manifest.metadata.upstream_provider === "POLIZEIKARTE"
      ? t("coverage.munich",{fetched:number(manifest.coverage.fetched),points:number(cityPoints),outside:number(outside)})
      : t("coverage.official",{discovered:number(manifest.coverage.discovered),fetched:number(manifest.coverage.fetched),pending:number(manifest.coverage.pending)});
    el("freshness").textContent =
      t("coverage.snapshot",{date:date(data.retrieved_at)});
    map = new maplibregl.Map({
      container: "map",
      center: cityView.center,
      zoom: 12.1,
      attributionControl: false,
      locale: {"NavigationControl.ZoomIn":t("aria.zoomIn"),"NavigationControl.ZoomOut":t("aria.zoomOut"),"NavigationControl.ResetBearing":t("aria.resetBearing"),"Map.Title":t("map.aria",{city:localizedCity}),"AttributionControl.ToggleAttribution":t("aria.toggleAttribution")},
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
        // MapLibre collapses attribution automatically on narrow maps.
        customAttribution:
          `<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">${html(t("map.attributionPlaces"))}: © OpenStreetMap contributors</a> / <a href="https://www.geofabrik.de/" target="_blank" rel="noopener noreferrer">Geofabrik</a> · <a href="${cityView.policeUrl}" target="_blank" rel="noopener noreferrer">${html(t("report.source"))}: ${cityView.policeName}</a>`,
      }),
    );
    map.once("load", async () => {
      for (const id of [
        "roads",
        "source-poi-references",
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
        filter: ["any", ["==", ["geometry-type"], "Polygon"], ["==", ["geometry-type"], "LineString"]],
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["case", [">", ["get", "association_count"], 0], 2, 1],
          "line-opacity": ["get", "opacity"],
        },
      });
      map.addLayer({
        id: "poi-circle",
        type: "circle",
        source: "pois",
        filter: ["has", "display_radius_m"],
        paint: {
          "circle-radius": ["interpolate", ["exponential", 2], ["zoom"],
            0, ["get", "radius_px_z0"], 24, ["*", 16777216, ["get", "radius_px_z0"]]],
          "circle-pitch-alignment": "map",
          "circle-pitch-scale": "map",
          "circle-color": ["get", "color"],
          "circle-opacity": ["get", "opacity"],
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": ["case", [">", ["get", "association_count"], 0], 2, 1],
          "circle-stroke-opacity": ["get", "opacity"],
        },
      });
      map.addLayer({
        id: "poi-point",
        type: "circle",
        source: "pois",
        filter: ["all", ["==", ["geometry-type"], "Point"], ["!", ["has", "display_radius_m"]]],
        paint: {
          "circle-radius": 4,
          "circle-color": "#ffffff",
          "circle-stroke-width": 2,
          "circle-stroke-color": ["get", "color"],
          "circle-opacity": ["get", "opacity"],
          "circle-stroke-opacity": ["get", "opacity"],
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
        paint: { "fill-color": sceneColor, "fill-opacity": 0.22 },
      });
      map.addLayer({
        id: "scene-area-outline",
        type: "line",
        source: "scenes",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "line-color": sceneColor, "line-width": 2 },
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
        id: "scene-transit-line-reference-hit",
        type: "line",
        source: "scenes",
        filter: ["==", ["get", "geometry_kind"], "transit_line_reference"],
        paint: { "line-width": 14, "line-opacity": 0 },
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
          "circle-color": sceneColor,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({id:"source-poi-reference-fill",type:"fill",source:"source-poi-references",filter:["==",["geometry-type"],"Polygon"],paint:{"fill-color":"#677785","fill-opacity":0.12}});
      map.addLayer({id:"source-poi-reference-line",type:"line",source:"source-poi-references",filter:["!=",["geometry-type"],"Point"],paint:{"line-color":"#677785","line-width":2,"line-opacity":0.7}});
      map.addLayer({id:"source-poi-reference-point",type:"circle",source:"source-poi-references",filter:["==",["geometry-type"],"Point"],paint:{"circle-radius":5,"circle-color":"#677785","circle-opacity":0.5,"circle-stroke-width":1,"circle-stroke-color":"#ffffff"}});
      setSource("kbo", {
        type: "FeatureCollection",
        features: data.zones.features,
      });
      basemaps = new Basemaps(map, paintOverlays, (id) => {
        const error = el("basemap-error");
        error.querySelector("span")!.textContent =
          t("basemap.failed",{basemap:basemapLabels[id]});
        error.hidden = false;
      });
      const changeBasemap = (id: BasemapId) => {
        el("basemap-error").hidden = true;
        el<HTMLSelectElement>("basemap").value = id;
        basemaps.select(id);
        document.querySelector(".basemap-language-note")!.textContent=t(id==="vector"?"basemap.vectorLanguageNote":"basemap.languageNote");
      };
      el<HTMLSelectElement>("basemap").disabled = false;
      el("basemap").onchange = () =>
        changeBasemap(el<HTMLSelectElement>("basemap").value as BasemapId);
      el("basemap-fallback").onclick = () => changeBasemap("local");
      changeBasemap("vector");
      loaded = true;
      await Promise.all([loadMonth(), loadViewport()]);
      if(new URLSearchParams(location.search).has("diagnostics")) {
        const output=document.createElement("output"); output.id="vector-label-proof";output.hidden=true;app.append(output);
        const detailProof=document.createElement("output");detailProof.id="map-detail-proof";detailProof.hidden=true;app.append(detailProof);
        map.on("idle",()=>{detailProof.textContent=JSON.stringify({cache:client.cacheStats,translations:{matched:dynamicText.matched,missing:dynamicText.missing},circles:map.queryRenderedFeatures({layers:["poi-circle"]}).map(f=>({id:f.properties.id,name:f.properties.name,radius:f.properties.display_radius_m})),month:monthKey()});if(map.getLayer("basemap-vector-place-labels"))output.textContent=JSON.stringify(map.queryRenderedFeatures({layers:["basemap-vector-place-labels"]}).map(f=>({name:f.properties.name,localized:f.properties[`name_${locale}`]??null,display:f.properties[`name_${locale}`]??f.properties.name})));});
      }
      map.on("click", (e) => {
        if (expired) return;
        const fs = map.queryRenderedFeatures(e.point, {
          layers: [
            ...SCENE_CLICK_LAYERS,
            ...SOURCE_POI_CLICK_LAYERS,
            "candidate-roads-hit", "poi-fill", "poi-line", "poi-point", "poi-circle", "hex-fill",
          ],
        });
        if (!fs.length) return;
        pendingSearchPoiId = null;
        const scenes = fs.filter((f) => f.layer.id.startsWith("scene-"));
        if (scenes.length) {
          selected = { type: "scene", ids: sceneEventIds(scenes) };
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
        const references=fs.filter(f=>SOURCE_POI_CLICK_LAYERS.includes(f.layer.id));
        if(references.length){selected={type:"source_poi",ids:sceneEventIds(references)};showSelection();return;}
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
        pendingSearchPoiId = null;
        selected = null;
        refresh();
      };
    el("candidate-roads-toggle").onchange = () => {
      if (loaded) setRoadVisibility();
    };
    for (const id of ["year", "month"])
      el(id).onchange = () => {const url=new URL(location.href);url.searchParams.set("month",monthKey());history.replaceState(null,"",url.href);void loadMonth();};
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
            t("error.newData"),
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
            .json<typeof searchIndex>(`${client.base}/search.json`,searchRequest.signal)
            .then((v) => {
              searchIndex = v;
            })
            .catch(() => {
              text("p", t("search.failed"), box);
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
        if (!matches.length) text("p", t("search.noResults"), box);
        for (const f of matches) {
          const b = text(
            "button",
            `${f.name} · ${poiName(f.kind,data.catalog.poi_types[f.kind]?.label ?? f.kind)}`,
            box,
          );
          b.onclick = () => {
            for (const input of document.querySelectorAll<HTMLInputElement>("#poi-filters input")) {
              if (input.value === (f.scope_category??f.kind) || (!f.scope_category&&manifest.poi_scope_groups?.[input.value]?.kinds.includes(f.kind))) input.checked = true;
            }
            pendingSearchPoiId = f.id;
            selected = { type: "poi", id: f.id };
            refresh();
            map.flyTo({ center: f.center, zoom: 16 });
            box.replaceChildren();
          };
        }
      }, 160);
    };
  } catch (error) {
    console.error(error);
    el("coverage").textContent = t("map.loadFailed");
    el("map-status").textContent = t("map.notReady");
  }
}
window.addEventListener("pageshow",(event)=>{el<HTMLSelectElement>("language").value=locale;if(event.persisted&&loaded){map.resize();void loadMonth();void loadViewport();}});
window.addEventListener("pagehide", (event) => {
  if(event.persisted){monthRequest.abort();viewportRequest.abort();clearTimeout(viewportTimer);return;}
  searchRequest.abort();
  monthRequest.abort();
  viewportRequest.abort();
  clearTimeout(viewportTimer);
  clearInterval(freshnessTimer);
  methodsPanel.destroy();
  uncertaintyPanel.destroy();
  feedbackPanel.destroy();
  analyticsPanel.destroy();
  mobileLayout.destroy();
  basemaps?.dispose();
  map?.remove();
});
void start();
