import { assetPath, repositoryCity, cityIds, cityDestination } from "./deployment";
import type { CityId } from "./deployment";
export interface City { id: CityId; name: string; href?: string; }
interface MapView {
 id: CityId; manifestCity: string; name: string; latin: string; center: [number, number];
 manifestPath: string; dataRoot: string; example: string; aerial: boolean; kbo: boolean;
 policeUrl: string; policeName: string; externalUrl: string;
}
const settings: Record<CityId, {name: string; native: string; center: [number,number]; source: string; police: string; upstream: string}> = {
 berlin: {name:"柏林",native:"Berlin",center:[13.411,52.508],source:"https://www.berlin.de/polizei/polizeimeldungen/",police:"Polizei Berlin",upstream:"berlin"},
 hamburg: {name:"汉堡",native:"Hamburg",center:[9.9937,53.5511],source:"https://www.presseportal.de/blaulicht/nr/6337",police:"Polizei Hamburg",upstream:"hamburg"},
 munich: {name:"慕尼黑",native:"München",center:[11.5755,48.1374],source:"https://polizeikarte.de/muenchen",police:"POLIZEIKARTE / Polizei München",upstream:"muenchen"},
 cologne: {name:"科隆",native:"Köln",center:[6.9603,50.9375],source:"https://koeln.polizei.nrw/presse/pressemitteilungen",police:"Polizei Köln",upstream:"koeln"},
 frankfurt: {name:"法兰克福",native:"Frankfurt",center:[8.6821,50.1109],source:"https://www.presseportal.de/blaulicht/nr/4970",police:"Polizei Frankfurt",upstream:"frankfurt"},
 dusseldorf: {name:"杜塞尔多夫",native:"Düsseldorf",center:[6.7735,51.2277],source:"https://www.presseportal.de/blaulicht/nr/13248",police:"Polizei Düsseldorf",upstream:"duesseldorf"},
 stuttgart: {name:"斯图加特",native:"Stuttgart",center:[9.1829,48.7758],source:"https://www.presseportal.de/blaulicht/nr/110977",police:"Polizei Stuttgart",upstream:"stuttgart"},
 leipzig: {name:"莱比锡",native:"Leipzig",center:[12.3731,51.3397],source:"https://www.medienservice.sachsen.de/medien/?search%5Binstitution_ids%5D%5B%5D=10976",police:"Polizeidirektion Leipzig",upstream:"leipzig"},
 dortmund: {name:"多特蒙德",native:"Dortmund",center:[7.4653,51.5136],source:"https://dortmund.polizei.nrw/presse/pressemitteilungen",police:"Polizei Dortmund",upstream:"dortmund"},
 bremen: {name:"不来梅",native:"Bremen",center:[8.8017,53.0793],source:"https://www.presseportal.de/blaulicht/nr/35235",police:"Polizei Bremen",upstream:"bremen"},
 essen: {name:"埃森",native:"Essen",center:[7.0123,51.4556],source:"https://essen.polizei.nrw/presse/pressemitteilungen",police:"Polizei Essen",upstream:"essen"},
 dresden: {name:"德累斯顿",native:"Dresden",center:[13.7373,51.0504],source:"https://www.medienservice.sachsen.de/medien/?search%5Binstitution_ids%5D%5B%5D=10997",police:"Polizeidirektion Dresden",upstream:"dresden"},
 hannover: {name:"汉诺威",native:"Hannover",center:[9.732,52.3759],source:"https://www.presseportal.de/blaulicht/nr/66841",police:"Polizeidirektion Hannover",upstream:"hannover"},
 nuremberg: {name:"纽伦堡",native:"Nürnberg",center:[11.0775,49.4539],source:"https://www.presseportal.de/blaulicht/nr/6013",police:"Polizeipräsidium Mittelfranken",upstream:"nuernberg"},
};
export const mapViews = Object.fromEntries(cityIds.map(id => {
 const s = settings[id];
 return [id, {id, manifestCity:s.native,name:s.name,latin:s.native.toLocaleUpperCase("de"),center:s.center,
 manifestPath:assetPath("/safety/manifest.json"),dataRoot:assetPath("/safety"),
 example:s.native,aerial:id === "berlin", kbo:id === "berlin",policeUrl:s.source,policeName:s.police,
 externalUrl:`https://polizeikarte.de/${s.upstream}`}];
})) as Record<CityId,MapView>;
// A query cannot change this repository's city or make it load another city's data.
export function requestedMapView(_search: string) { return mapViews[repositoryCity]; }
const published = new Set((import.meta.env?.VITE_PUBLISHED_CITIES || "").split(","));
export const cityGroups: readonly {label: string; cities: readonly City[]}[] = [{
 label:"14 城",cities:cityIds.map(id => ({id,name:settings[id].name,
 href:id === repositoryCity ? import.meta.env?.BASE_URL || "/" : published.has(id) ? cityDestination(id,"") : undefined})),
}];
