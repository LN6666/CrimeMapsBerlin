export interface MobileLabels {
  filters: string;
  showFilters: string;
  hideFilters: string;
  map: string;
  details: string;
  skipToMap: string;
}

export const mobileLabels: Record<"de" | "en" | "zh", MobileLabels> = {
  de: { filters: "Filter", showFilters: "Filter anzeigen", hideFilters: "Filter ausblenden", map: "Karte", details: "Einzelheiten", skipToMap: "Zur Karte springen" },
  en: { filters: "Filters", showFilters: "Show filters", hideFilters: "Hide filters", map: "Map", details: "Details", skipToMap: "Skip to map" },
  zh: { filters: "筛选", showFilters: "显示筛选", hideFilters: "收起筛选", map: "地图", details: "详情", skipToMap: "跳到地图" },
};

/** DOM layout only: no map sources, gestures, data requests or history changes. */
export function installMobileLayout(root: HTMLElement, options: {
  labels: MobileLabels;
  onLayoutChange?: () => void;
}) {
  const controls = root.querySelector<HTMLElement>(".controls");
  const mapRegion = root.querySelector<HTMLElement>(".map-wrap");
  const details = root.querySelector<HTMLElement>(".details");
  const main = root.querySelector<HTMLElement>("main");
  if (!controls || !mapRegion || !details || !main) throw Error("Missing map layout regions");
  const controlsRegion = controls;
  const detailsRegion = details;
  const namedMapRegion = mapRegion;
  const abort = new AbortController();
  const signal = abort.signal;
  const mobile = matchMedia("(max-width: 760px), (max-width: 1000px) and (max-height: 500px)");
  let labels = options.labels;
  let expanded = false;
  let frame = 0;
  const toolbar = root.querySelector<HTMLElement>(".toolbar");
  const settings = document.createElement("details");
  settings.className = "mobile-view-settings";
  const settingsSummary = document.createElement("summary");
  const currentView = document.createElement("span");
  const currentCity = document.createElement("span");
  currentCity.className = "mobile-view-city";
  const currentPeriod = document.createElement("span");
  currentPeriod.className = "mobile-view-period";
  currentView.append(currentCity, currentPeriod);
  const settingsIcon = document.createElement("span");
  settingsIcon.className = "mobile-disclosure-icon";
  settingsIcon.textContent = "⌄";
  settingsIcon.setAttribute("aria-hidden", "true");
  settingsSummary.append(currentView, settingsIcon);
  if (toolbar) { toolbar.before(settings); settings.append(settingsSummary, toolbar); }
  function updateViewSummary() {
    const value = (id: string) => root.querySelector<HTMLSelectElement>(`#${id}`)?.selectedOptions[0]?.textContent?.trim() || "";
    const city = value("city-switch");
    const period = [value("month"), value("year")].filter(Boolean).join(" ");
    currentCity.textContent = city;
    currentPeriod.textContent = period ? `${city ? "· " : ""}${period}` : "";
    settingsSummary.setAttribute("aria-label", [city, period].filter(Boolean).join(" · "));
    currentCity.title = city;
  }
  const toolbarObserver = new MutationObserver(updateViewSummary);
  if (toolbar) toolbarObserver.observe(toolbar, { childList: true, subtree: true, characterData: true });
  toolbar?.addEventListener("change", updateViewSummary, { signal });
  window.addEventListener("pageshow", updateViewSummary, { signal });
  settings.addEventListener("toggle", () => notifyLayout(), { signal });
  settings.addEventListener("keydown", event => {
    if (event.key === "Escape" && mobile.matches && settings.open) { event.preventDefault(); settings.open = false; settingsSummary.focus(); }
  }, { signal });
  const notesHost = document.createElement("div");
  notesHost.className = "mobile-map-notes";
  const movedNotes = [...root.querySelectorAll<HTMLElement>(".map-wrap > .map-note, .map-wrap > .basemap-language-note")].map(note => {
    const marker = document.createComment("map note position"); note.before(marker); return { note, marker };
  });
  function adaptHeader() {
    settings.open = !mobile.matches;
    basemapSettings.open = !mobile.matches || (basemapError ? !basemapError.hidden : false);
    if (mobile.matches) { detailsRegion.prepend(notesHost); for (const { note } of movedNotes) notesHost.append(note); }
    else { for (const { note, marker } of movedNotes) marker.after(note); notesHost.remove(); }
    updateViewSummary();
  }
  const basemapPicker = root.querySelector<HTMLElement>(".basemap-picker");
  const basemapSettings = document.createElement("details");
  basemapSettings.className = "mobile-basemap-settings";
  const basemapSummary = document.createElement("summary");
  basemapSummary.textContent = basemapPicker?.querySelector("label")?.firstChild?.textContent?.trim() || options.labels.map;
  const basemapContent = document.createElement("div");
  basemapContent.className = "mobile-basemap-content";
  if (basemapPicker) { basemapContent.append(...basemapPicker.childNodes); basemapSettings.append(basemapSummary, basemapContent); basemapPicker.append(basemapSettings); }
  const basemapError = root.querySelector<HTMLElement>("#basemap-error");
  const errorObserver = new MutationObserver(() => { if (basemapError && !basemapError.hidden) basemapSettings.open = true; });
  if (basemapError) errorObserver.observe(basemapError, { attributes: true, attributeFilter: ["hidden"] });
  const initialAttribution = new WeakSet<Element>();
  const attributionObserver = new MutationObserver(() => {
    if (!mobile.matches) return;
    for (const control of mapRegion.querySelectorAll(".maplibregl-ctrl-attrib.maplibregl-compact")) {
      if (initialAttribution.has(control)) continue;
      initialAttribution.add(control);
      if (control.classList.contains("maplibregl-compact-show")) control.querySelector<HTMLElement>("summary")?.click();
    }
  });
  attributionObserver.observe(mapRegion, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
  const content = document.createElement("div");
  content.className = "mobile-filter-content";
  content.id = "mobile-filter-content";
  content.append(...controls.childNodes);
  controls.append(content);
  controls.id ||= "map-filters";
  mapRegion.id ||= "map-region";
  details.id ||= "map-details";
  mapRegion.tabIndex = -1;
  details.tabIndex = -1;
  details.setAttribute("role", "region");
  const nav = document.createElement("nav");
  nav.className = "mobile-navigation";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.id = "mobile-filter-toggle";
  toggle.setAttribute("aria-controls", content.id);
  const mapLink = document.createElement("a");
  const detailsLink = document.createElement("a");
  mapLink.href = `#${mapRegion.id}`;
  detailsLink.href = `#${details.id}`;
  nav.append(toggle, mapLink, detailsLink);
  main.before(nav);
  const skip = document.createElement("a");
  skip.className = "skip-to-map";
  skip.href = `#${mapRegion.id}`;
  root.prepend(skip);
  root.classList.add("mobile-layout-ready");
  const status = root.querySelector("#map-status");
  status?.setAttribute("role", "status");
  status?.setAttribute("aria-live", "polite");

  function notifyLayout() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => options.onLayoutChange?.());
  }
  function render() {
    content.hidden = mobile.matches && !expanded;
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.textContent = labels.filters;
    toggle.setAttribute("aria-label", expanded ? labels.hideFilters : labels.showFilters);
    nav.setAttribute("aria-label", labels.map);
    controlsRegion.setAttribute("aria-label", labels.filters);
    namedMapRegion.setAttribute("aria-label", labels.map);
    detailsRegion.setAttribute("aria-label", labels.details);
    mapLink.textContent = labels.map;
    detailsLink.textContent = labels.details;
    skip.textContent = labels.skipToMap;
    notifyLayout();
  }
  function setExpanded(value: boolean) {
    // Do not leave focus in content that becomes hidden after an orientation change.
    if (!value && mobile.matches && content.contains(document.activeElement)) toggle.focus({ preventScroll: true });
    expanded = value;
    render();
  }
  function goTo(region: HTMLElement) {
    region.focus({ preventScroll: true });
    region.scrollIntoView({ block: "start", behavior: "instant" });
  }
  toggle.addEventListener("click", () => setExpanded(!expanded), { signal });
  content.addEventListener("keydown", event => {
    if (event.key === "Escape" && mobile.matches) { event.preventDefault(); setExpanded(false); }
  }, { signal });
  for (const [link, region] of [[mapLink, mapRegion], [detailsLink, details], [skip, mapRegion]] as const) {
    link.addEventListener("click", event => {
      event.preventDefault();
      if (mobile.matches) setExpanded(false);
      if (mobile.matches) settings.open = false;
      goTo(region);
    }, { signal });
  }
  mobile.addEventListener("change", () => { adaptHeader(); setExpanded(false); }, { signal });

  // visualViewport shrinks with the on-screen keyboard. Scale changes are pinch zoom,
  // so preserve user zoom rather than resizing the map from a magnified viewport.
  function viewportChanged() {
    const viewport = window.visualViewport;
    const height = viewport && viewport.scale === 1 ? viewport.height : window.innerHeight;
    root.style.setProperty("--mobile-visible-height", `${Math.round(height)}px`);
    document.documentElement.style.setProperty("--mobile-visible-height", `${Math.round(height)}px`);
    notifyLayout();
  }
  window.addEventListener("resize", viewportChanged, { signal });
  window.visualViewport?.addEventListener("resize", viewportChanged, { signal });
  // A translated map status can wrap to several lines; keep the picker below it.
  const statusLabel = root.querySelector<HTMLElement>(".map-label");
  const statusObserver = new ResizeObserver(() => {
    if (statusLabel) mapRegion.style.setProperty("--map-label-height", `${Math.ceil(statusLabel.getBoundingClientRect().height)}px`);
    const height = `${Math.ceil(nav.getBoundingClientRect().height)}px`;
    root.style.setProperty("--mobile-navigation-height", height);
    document.documentElement.style.setProperty("--mobile-navigation-height", height);
  });
  if (statusLabel) statusObserver.observe(statusLabel);
  statusObserver.observe(nav);
  adaptHeader();
  viewportChanged();
  render();
  return {
    setLabels(next: MobileLabels) { labels = next; render(); },
    revealDetails() { if (mobile.matches) { setExpanded(false); goTo(details); } },
    destroy() {
      abort.abort();
      statusObserver.disconnect();
      toolbarObserver.disconnect();
      errorObserver.disconnect();
      attributionObserver.disconnect();
      cancelAnimationFrame(frame);
      content.hidden = false;
      content.replaceWith(...content.childNodes);
      nav.remove(); skip.remove();
      if (toolbar) settings.replaceWith(toolbar);
      if (basemapPicker) basemapSettings.replaceWith(...basemapContent.childNodes);
      for (const { note, marker } of movedNotes) { marker.after(note); marker.remove(); }
      notesHost.remove();
      root.classList.remove("mobile-layout-ready");
      root.style.removeProperty("--mobile-visible-height");
      document.documentElement.style.removeProperty("--mobile-visible-height");
      root.style.removeProperty("--mobile-navigation-height");
      document.documentElement.style.removeProperty("--mobile-navigation-height");
    },
  };
}
