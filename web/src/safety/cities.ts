/** Owner-selected order and repository split. Publish a URL only after its map passes review. */
export interface City {
  id: string;
  name: string;
  href?: string;
}

/** Map settings may exist before a city has an approved public manifest. */
export const mapViews = {
  berlin: {
    name: "柏林", latin: "BERLIN", center: [13.411, 52.508] as [number, number],
    manifestPath: "/safety/manifest.json", dataRoot: "/safety",
    example: "如 Kottbusser Tor、酒吧名称", aerial: true, kbo: true,
    policeUrl: "https://www.berlin.de/polizei/polizeimeldungen/",
    policeName: "Polizei Berlin", externalUrl: "https://polizeikarte.de/berlin",
  },
  hamburg: {
    name: "汉堡", latin: "HAMBURG", center: [9.9937, 53.5511] as [number, number],
    manifestPath: "/safety/cities/hamburg/manifest.json", dataRoot: "/safety/cities/hamburg",
    example: "如 Jungfernstieg、酒吧名称", aerial: false, kbo: false,
    policeUrl: "https://www.presseportal.de/blaulicht/nr/6337",
    policeName: "Polizei Hamburg", externalUrl: "https://polizeikarte.de/hamburg",
  },
} as const;

export function requestedMapView(search: string) {
  return new URLSearchParams(search).get("city") === "hamburg"
    ? mapViews.hamburg : mapViews.berlin;
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
