import { expect, test } from "@playwright/test";

for (const [ownerApproved, publicationReady] of [[false, false], [true, true], [true, false]]) {
  test(`Hamburg data and approval labels agree with manifest ${ownerApproved}/${publicationReady}`, async ({ page }) => {
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
            owner_approved: ownerApproved,
            publication_ready: publicationReady,
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
              source_status: "complete_official_archive_source_and_geometry_reviewed",
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
    await expect(page.locator("#drawer-content")).toContainText("原文列出多个地点；逐处展示");
    if (ownerApproved && publicationReady) {
      await expect(page.locator("#review-badge")).toBeHidden();
      await expect(page.locator("#city-switch option:checked")).toHaveText("汉堡");
      await expect(page.locator("#drawer-content")).toContainText("所有者已检查并批准当前版本");
      await expect(page.locator("#drawer-content")).not.toContainText("等待所有者批准");
    } else {
      await expect(page.locator("#review-badge")).toBeVisible();
      await expect(page.locator("#city-switch option:checked")).toHaveText("汉堡 · 制作中");
      await expect(page.locator("#drawer-content")).toContainText("等待所有者批准");
    }
    await expect(page.locator("#kbo")).toBeHidden();
    await expect(page.locator("#basemap option[value='aerial']")).toHaveAttribute("disabled", "");
    await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText("Polizei Hamburg");
    expect(requested.some((url) => url.includes("/safety/manifest.json"))).toBe(false);
    expect(requested.every((url) => url.includes("/safety/cities/hamburg/"))).toBe(true);
  });
}

test("Munich candidate preview stays on its city data and upstream attribution", async ({ page }) => {
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
    if (url.endsWith("/cities/munich/manifest.json"))
      return route.fulfill({
        json: {
          schema_version: 2,
          city: "München",
          generation: "0123456789abcdef-20260928T184246",
          retrieved_at: "2026-09-28T18:42:46Z",
          coverage: { discovered: 1, fetched: 1, pending: 0, failed: 0 },
          months: { "2026-09": { count: 1 } },
          categories: ["raub"],
          tile_index: { pois: [], roads: [] },
          tile_size: [0.04, 0.025],
          catalog: { poi_types: {}, sources: [], coverage: [], exhaustive: false },
          zones: { places: [], features: [], geometry_status: "not_applicable" },
          metadata: {
            zoom_threshold: 13,
            semantic_basis: "owner_accepted_polizeikarte_upstream",
            upstream_provider: "POLIZEIKARTE",
            point_entries_in_city: 1,
            known_outside_municipality: 0,
          },
        },
      });
    if (url.includes("/months/"))
      return route.fulfill({
        json: {
          event_ids: ["polizeikarte:1"],
          events: [{
            id: "polizeikarte:1", title: "Test", category: "raub", month: "2026-09",
            event_date: "2026-09-20", coordinates: [11.5755, 48.1374],
            location_precision: "street", location_label: "München · Teststraße",
            geocode_method: "polizeikarte_supplied_street_coordinate", poi_mentions: [],
            source_url: "https://www.polizei.bayern.de/aktuelles/pressemitteilungen/1/index.html",
          }],
          hex: { overview: empty, detail: empty },
          links: [],
        },
      });
    if (url.endsWith("/roads-overview.json")) return route.fulfill({ json: empty });
    return route.fulfill({ status: 404 });
  });

  await page.goto("/?city=munich");
  await expect(page).toHaveTitle("CrimeMapsDE · 慕尼黑警情地图");
  await expect(page.locator("h1")).toContainText("慕尼黑");
  await expect(page.locator("#city-switch")).toHaveValue("munich");
  await expect(page.locator("#stats .big")).toHaveText("1");
  await expect(page.locator("#kbo")).toBeHidden();
  await expect(page.locator("#basemap option[value='aerial']")).toHaveAttribute("disabled", "");
  await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText("POLIZEIKARTE");
  await expect(page.locator("#coverage")).toContainText("1 条街道点通过慕尼黑市界核验");
  expect(requested.some((url) => url.includes("/safety/manifest.json"))).toBe(false);
  expect(requested.every((url) => url.includes("/safety/cities/munich/"))).toBe(true);
});
