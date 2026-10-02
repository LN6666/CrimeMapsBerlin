/** Verified outbound resources; these sites are not map data providers. */
export const externalMaps = [
  { id: "berlin", city: "柏林", url: "https://polizeikarte.de/berlin" },
  { id: "frankfurt", city: "法兰克福（美因河畔）", url: "https://polizeikarte.de/frankfurt" },
  { id: "hamburg", city: "汉堡", url: "https://polizeikarte.de/hamburg" },
  { id: "munich", city: "慕尼黑", url: "https://polizeikarte.de/muenchen" },
  { id: "cologne", city: "科隆", url: "https://polizeikarte.de/koeln" },
  { id: "dusseldorf", city: "杜塞尔多夫", url: "https://polizeikarte.de/duesseldorf" },
  { id: "leipzig", city: "莱比锡", url: "https://polizeikarte.de/leipzig" },
] as const;

export const externalMapsDirectory = "https://polizeikarte.de/staedte";
