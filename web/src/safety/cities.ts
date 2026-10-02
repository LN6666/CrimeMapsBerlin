/** Owner-selected order and repository split. Publish a URL only after its map passes review. */
export interface City {
  id: string;
  name: string;
  href?: string;
}

/** Map settings may exist before a city has an approved public manifest. */
export const mapViews = {
  berlin: {
    id: "berlin", manifestCity: "Berlin",
    name: "柏林", latin: "BERLIN", center: [13.411, 52.508] as [number, number],
    manifestPath: "/safety/manifest.json", dataRoot: "/safety",
    example: "如 Kottbusser Tor、酒吧名称", aerial: true, kbo: true,
    policeUrl: "https://www.berlin.de/polizei/polizeimeldungen/",
    policeName: "Polizei Berlin", externalUrl: "https://polizeikarte.de/berlin",
  },
  hamburg: {
    id: "hamburg", manifestCity: "Hamburg",
    name: "汉堡", latin: "HAMBURG", center: [9.9937, 53.5511] as [number, number],
    manifestPath: "/safety/cities/hamburg/manifest.json", dataRoot: "/safety/cities/hamburg",
    example: "如 Jungfernstieg、酒吧名称", aerial: false, kbo: false,
    policeUrl: "https://www.presseportal.de/blaulicht/nr/6337",
    policeName: "Polizei Hamburg", externalUrl: "https://polizeikarte.de/hamburg",
  },
  munich: {
    id: "munich", manifestCity: "München",
    name: "慕尼黑", latin: "MÜNCHEN", center: [11.5755, 48.1374] as [number, number],
    manifestPath: "/safety/cities/munich/manifest.json", dataRoot: "/safety/cities/munich",
    example: "如 Marienplatz、酒吧名称", aerial: false, kbo: false,
    policeUrl: "https://polizeikarte.de/muenchen",
    policeName: "POLIZEIKARTE / Polizei München 原文",
    externalUrl: "https://polizeikarte.de/muenchen",
  },
  cologne: {
    id: "cologne", manifestCity: "Köln",
    name: "科隆", latin: "KÖLN", center: [6.9603, 50.9375] as [number, number],
    manifestPath: "/safety/cities/cologne/manifest.json", dataRoot: "/safety/cities/cologne",
    example: "如 Neumarkt、公园或街道名称", aerial: false, kbo: false,
    policeUrl: "https://koeln.polizei.nrw/presse/pressemitteilungen",
    policeName: "Polizei Köln", externalUrl: "https://polizeikarte.de/koeln",
  },
  nuremberg: {
    id: "nuremberg", manifestCity: "Nürnberg",
    name: "纽伦堡", latin: "NÜRNBERG", center: [11.0775, 49.4539] as [number, number],
    manifestPath: "/safety/cities/nuremberg/manifest.json", dataRoot: "/safety/cities/nuremberg",
    example: "如 Hauptbahnhof、公园或街道名称", aerial: false, kbo: false,
    policeUrl: "https://www.presseportal.de/blaulicht/nr/6013",
    policeName: "Polizeipräsidium Mittelfranken", externalUrl: "https://polizeikarte.de/nuernberg",
  },
} as const;

export function requestedMapView(search: string) {
  const requested = new URLSearchParams(search).get("city");
  return requested && Object.hasOwn(mapViews, requested)
    ? mapViews[requested as keyof typeof mapViews]
    : mapViews.berlin;
}

/** The static-site assembly embeds only manifest/receipt-verified releases. */
export function approvedCityLinks(value: unknown): Map<string, string> {
  const links = new Map<string, string>();
  if (!value || typeof value !== "object") return links;
  const directory = value as { schema_version?: unknown; cities?: unknown };
  if (directory.schema_version !== 1 || !Array.isArray(directory.cities)) return links;
  for (const entry of directory.cities) {
    if (!entry || typeof entry !== "object") continue;
    const city = entry as Record<string, unknown>;
    if (
      typeof city.id !== "string" || !Object.hasOwn(mapViews, city.id) ||
      city.owner_approved !== true || city.publication_ready !== true ||
      typeof city.manifest_sha256 !== "string" || !/^[a-f0-9]{64}$/.test(city.manifest_sha256) ||
      typeof city.packet_digest !== "string" || !/^[a-f0-9]{64}$/.test(city.packet_digest)
    ) continue;
    links.set(city.id, `${import.meta.env.BASE_URL}?city=${encodeURIComponent(city.id)}`);
  }
  return links;
}

export const cityGroups: readonly { label: string; cities: readonly City[] }[] = [
  {
    label: "第 1 组 · 5 城",
    cities: [
      { id: "berlin", name: "柏林", href: import.meta.env.BASE_URL },
      { id: "hamburg", name: "汉堡" },
      { id: "munich", name: "慕尼黑" },
      { id: "cologne", name: "科隆" },
      { id: "frankfurt", name: "法兰克福" },
    ],
  },
  {
    label: "第 2 组 · 5 城",
    cities: [
      { id: "dusseldorf", name: "杜塞尔多夫" },
      { id: "stuttgart", name: "斯图加特" },
      { id: "leipzig", name: "莱比锡" },
      { id: "dortmund", name: "多特蒙德" },
      { id: "bremen", name: "不来梅" },
    ],
  },
  {
    label: "第 3 组 · 4 城",
    cities: [
      { id: "essen", name: "埃森" },
      { id: "dresden", name: "德累斯顿" },
      { id: "hannover", name: "汉诺威" },
      { id: "nuremberg", name: "纽伦堡" },
    ],
  },
];
