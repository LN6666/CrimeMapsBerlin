import {test as base, expect, type Page} from "@playwright/test";

export async function mockVectorBasemap(page: Page) {
  await page.route("https://vector.openstreetmap.org/**", (route) => {
    const headers = {"access-control-allow-origin":"*"};
    if (route.request().url().endsWith("tilejson.json"))
      return route.fulfill({headers,json:{tilejson:"3.0.0",minzoom:0,maxzoom:14,
        tiles:["https://vector.openstreetmap.org/fixture/{z}/{x}/{y}.pbf"]}});
    return route.fulfill({headers,contentType:"application/x-protobuf",body:Buffer.alloc(0)});
  });
  await page.route("https://demotiles.maplibre.org/font/**", (route) =>
    route.fulfill({headers:{"access-control-allow-origin":"*"},contentType:"application/x-protobuf",body:Buffer.alloc(0)}));
}

export const test = base.extend({page: async ({page}, use) => {
  await mockVectorBasemap(page);
  await use(page);
}});
export {expect};
