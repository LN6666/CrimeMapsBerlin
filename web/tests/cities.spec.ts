import {test, expect} from "./fixture";
import {readFileSync} from "node:fs";

const config = JSON.parse(readFileSync(new URL("../../city-config.json", import.meta.url), "utf8"));
const native: Record<string,string> = {
  berlin:"Berlin",hamburg:"Hamburg",munich:"München",cologne:"Köln",frankfurt:"Frankfurt",
  dusseldorf:"Düsseldorf",stuttgart:"Stuttgart",leipzig:"Leipzig",dortmund:"Dortmund",
  bremen:"Bremen",essen:"Essen",dresden:"Dresden",hannover:"Hannover",nuremberg:"Nürnberg",
};
const english = JSON.parse(readFileSync(new URL("../src/safety/locales/en.json", import.meta.url), "utf8"));
const empty = {type:"FeatureCollection",features:[]};
const foreignCity = config.city === "berlin" ? "hamburg" : "berlin";
function manifest(city = native[config.city]) {
  return {schema_version:2,city,generation:"0123456789abcdef-20260928T120000",
    retrieved_at:"2026-09-28T12:00:00Z",coverage:{discovered:1,fetched:1,pending:0,failed:0},
    months:{"2026-09":{count:1}},categories:["diebstahl"],tile_index:{pois:[],roads:[]},
    tile_size:[0.04,0.025],catalog:{poi_types:{},sources:[],coverage:[],exhaustive:false},
    zones:{places:[],features:[],geometry_status:"not_applicable"},metadata:{zoom_threshold:13}};
}

test("production repository prefix retains its city and ignores a foreign city query", async ({page}) => {
  const requested: string[] = [];
  await page.route("**/safety/**", (route) => {
    const url = route.request().url();
    requested.push(url);
    if (url.endsWith("/manifest.json")) return route.fulfill({json:manifest()});
    if (url.includes("/months/")) return route.fulfill({json:{
      event_ids:["fixture:1"],events:[{id:"fixture:1",title:"Synthetic unknown-location fixture",
        category:"diebstahl",month:"2026-09",coordinates:null,location_precision:"unknown",
        location_label:"",poi_mentions:[],source_url:"https://example.org/fixture"}],
      hex:{overview:empty,detail:empty},links:[]}});
    return route.fulfill({json:empty});
  });
  await page.goto(`./?lang=en&month=2026-09&city=${foreignCity}`);
  await expect(page.locator("#city-switch")).toHaveValue(config.city);
  await expect(page.locator("#stats .big")).toHaveText("1");
  await expect(page.locator("#year")).toHaveValue("2026");
  await expect(page.locator("#month")).toHaveValue("09");
  await expect(page.locator("#language")).toHaveValue("en");
  await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText(
    config.city === "munich" ? "POLIZEIKARTE" : native[config.city]);
  if (config.city !== "berlin")
    await expect(page.locator("#basemap option[value='aerial']")).toHaveAttribute("disabled", "");
  expect(requested.length).toBeGreaterThan(1);
  expect(requested.every(url => new URL(url).pathname.startsWith(`${config.base_path}safety/`))).toBe(true);
  expect(requested.some(url => url.includes(`/cities/${foreignCity}/`))).toBe(false);
});

test("production entry rejects a manifest belonging to another city", async ({page}) => {
  const requested: string[] = [];
  await page.route("**/safety/**", (route) => {
    requested.push(route.request().url());
    return route.fulfill({json:manifest(native[foreignCity])});
  });
  await page.goto("./?lang=en&month=2026-09");
  await expect(page.locator("#city-switch")).toHaveValue(config.city);
  await expect(page.locator("#coverage")).toHaveText(english["map.loadFailed"]);
  await expect(page.locator("#map-status")).toHaveText(english["map.notReady"]);
  await expect(page.locator("#basemap")).toBeDisabled();
  expect(requested).toHaveLength(1);
  expect(requested[0]).toContain(`${config.base_path}safety/manifest.json`);
});
