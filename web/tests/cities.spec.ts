import { expect, test } from "@playwright/test";

test("Hamburg preview reads only Hamburg data and shows city-specific sources", async ({ page }) => {
  const requested: string[] = [];
  const empty = { type: "FeatureCollection", features: [] };
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.fulfill({
      contentType: "image/png",
      headers: { "access-control-allow-origin": "*" },
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4+fYlAAWCAsAGiqfBAAAAAElFTkSuQmCC",
        "base64",
      ),
    }),
  );
  await page.route("http://127.0.0.1:4173/safety/**", (route) => {
    const url = route.request().url();
    requested.push(url);
    if (url.endsWith("/cities/hamburg/manifest.json"))
      return route.fulfill({
        json: {
          schema_version: 2,
          city: "Hamburg",
          generation: "0123456789abcdef-20260928T120000",
          retrieved_at: "2026-09-28T12:00:00Z",
          coverage: { discovered: 1, fetched: 1, pending: 0, failed: 0 },
          months: { "2026-09": { count: 1 } },
          categories: ["Diebstahl"],
          tile_index: { pois: [], roads: [] },
          tile_size: [0.04, 0.025],
          catalog: { poi_types: {}, sources: [], coverage: [], exhaustive: false },
          zones: { places: [], features: [], geometry_status: "not_applicable" },
          metadata: { zoom_threshold: 13 },
        },
      });
    if (url.includes("/months/"))
      return route.fulfill({
        json: {
          event_ids: ["1"],
          events: [{
            id: "1", title: "Test", category: "Diebstahl", month: "2026-09",
            coordinates: null, location_precision: "unknown", location_label: "",
            geocode_method: "multiple_official_scenes", poi_mentions: [],
            source_url: "https://www.presseportal.de/blaulicht/nr/6337",
          }],
          hex: { overview: empty, detail: empty },
          links: [],
        },
      });
    if (url.endsWith("/roads-overview.json")) return route.fulfill({ json: empty });
    return route.fulfill({ status: 404 });
  });

  await page.goto("/?city=hamburg");
  await expect(page.locator("h1")).toContainText("汉堡");
  await expect(page.locator("#city-switch")).toHaveValue("hamburg");
  await expect(page.locator("#stats .big")).toHaveText("1");
  await page.locator("#stats button").click();
  await expect(page.locator("#drawer-content")).toContainText("原文列出多个案发地点");
  await expect(page.locator("#kbo")).toBeHidden();
  await expect(page.locator("#basemap option[value='aerial']")).toHaveAttribute("disabled", "");
  await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText("Polizei Hamburg");
  expect(requested.some((url) => url.includes("/safety/manifest.json"))).toBe(false);
  expect(requested.every((url) => url.includes("/safety/cities/hamburg/"))).toBe(true);
});
