import {addVectorBasemap,removeVectorBasemap} from "./vector-basemap";
import {t} from "./i18n";
import type { ErrorEvent, Map, RasterSourceSpecification } from "maplibre-gl";

export type BasemapId = "street" | "aerial" | "local" | "vector";

export const basemapLabels: Record<BasemapId, string> = {
  vector:t("basemap.vector"),
  street: t("basemap.street"),
  aerial: t("basemap.aerial"),
  local: t("basemap.local"),
};

export function rasterSource(
  id: Exclude<BasemapId, "local" | "vector">,
): RasterSourceSpecification {
  if (id === "street")
    return {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>',
    };
  return {
    type: "raster",
    tiles: [
      "https://gdi.berlin.de/services/wms/truedop_2026?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=truedop_2026&STYLES=&CRS=EPSG%3A3857&WIDTH=256&HEIGHT=256&FORMAT=image%2Fjpeg&BBOX={bbox-epsg-3857}",
    ],
    tileSize: 256,
    maxzoom: 19,
    bounds: [13.04758, 52.31644, 13.76742, 52.6854],
    attribution:
      '<a href="https://gdi.berlin.de/services/wms/truedop_2026?SERVICE=WMS&amp;REQUEST=GetCapabilities" target="_blank" rel="noopener noreferrer">Geoportal Berlin · DOP 2026</a> · <a href="https://www.govdata.de/dl-de/zero-2-0" target="_blank" rel="noopener noreferrer">dl-de/zero-2.0</a>',
  };
}

/** Switch only background sources; data layers and the camera keep their state. */
export class Basemaps {
  selected: BasemapId = "local";
  rendered: BasemapId = "local";
  private failed = false;

  constructor(
    private map: Map,
    private changed: () => void,
    private failedSource: (id: BasemapId) => void,
  ) {
    map.on("error", this.error);
  }

  select(id: BasemapId) {
    if (id === this.selected && !this.failed) return;
    this.removeRaster();
    this.selected = id;
    this.rendered = id;
    this.failed = false;
    if(id==="vector")addVectorBasemap(this.map);
    else if (id !== "local") {
      const sourceId = `basemap-${id}`;
      this.map.addSource(sourceId, rasterSource(id));
      this.map.addLayer(
        {
          id: sourceId,
          type: "raster",
          source: sourceId,
          // No animated fade or extra background source; use browser HTTP caching.
          paint: { "raster-fade-duration": 0 },
        },
        "roads-line",
      );
    }
    this.showRoads();
    this.changed();
  }

  dispose() {
    this.map.off("error", this.error);
  }

  private removeRaster() {
    removeVectorBasemap(this.map);
    for (const id of ["basemap-street", "basemap-aerial"]) {
      if (this.map.getLayer(id)) this.map.removeLayer(id);
      if (this.map.getSource(id)) this.map.removeSource(id);
    }
  }

  private showRoads() {
    this.map.setLayoutProperty(
      "roads-line",
      "visibility",
      this.rendered === "local" ? "visible" : "none",
    );
  }

  private error = (event: ErrorEvent) => {
    const sourceId = (event as ErrorEvent & { sourceId?: string }).sourceId;
    if (!sourceId?.startsWith("basemap-")) {
      // Having an error listener suppresses MapLibre's default console reporting.
      console.error(event.error);
      return;
    }
    if (sourceId !== `basemap-${this.selected}` || this.failed) return;
    this.failed = true;
    // Removing the source cancels pending tiles and prevents automatic retries.
    this.removeRaster();
    this.rendered = "local";
    this.showRoads();
    this.changed();
    this.failedSource(this.selected);
  };
}
