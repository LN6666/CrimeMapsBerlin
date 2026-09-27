/** Verified outbound resources; these sites are not map data providers. */
export const externalMaps = [
  { city: "柏林", url: "https://polizeikarte.de/berlin" },
  { city: "法兰克福（美因河畔）", url: "https://polizeikarte.de/frankfurt" },
  { city: "汉堡", url: "https://polizeikarte.de/hamburg" },
  { city: "慕尼黑", url: "https://polizeikarte.de/muenchen" },
  { city: "科隆", url: "https://polizeikarte.de/koeln" },
  { city: "杜塞尔多夫", url: "https://polizeikarte.de/duesseldorf" },
  { city: "莱比锡", url: "https://polizeikarte.de/leipzig" },
] as const;

export const externalMapsDirectory = "https://polizeikarte.de/staedte";
