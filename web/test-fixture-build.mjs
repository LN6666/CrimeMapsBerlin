// The regression fixtures exercise Berlin-specific camera and aerial imagery.
// Build the same source with a separate synthetic config, preserving this repo's config.
import {cp, mkdtemp, mkdir, readFile, rm, symlink, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {dirname, join, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {spawnSync} from "node:child_process";

const web = dirname(fileURLToPath(import.meta.url));
const temporary = await mkdtemp(join(tmpdir(), "crimemaps-browser-fixture-"));
try {
  const fixtureWeb = join(temporary, "web");
  await mkdir(fixtureWeb);
  for (const path of ["src", "index.html", "package.json", "tsconfig.json", "vite.config.ts"])
    await cp(join(web, path), join(fixtureWeb, path), {recursive:true});
  await symlink(resolve(web, "node_modules"), join(fixtureWeb, "node_modules"), "dir");
  await cp(resolve(web, "../config"), join(temporary, "config"), {recursive:true});
  // The lazy statistics card imports the shared inert renderer. Preserve the
  // same relative module paths in this isolated synthetic-city build.
  const analyticsSource = join(temporary, "services", "analytics", "src");
  await mkdir(analyticsSource, {recursive:true});
  for (const path of ["contract.mjs", "world-card.mjs", "world-card.d.mts", "world-boundaries.mjs", "goatcounter-client.mjs", "goatcounter-client.d.mts"])
    await cp(resolve(web, "../services/analytics/src", path), join(analyticsSource, path));
  await mkdir(join(temporary, "assets", "brand"), {recursive:true});
  for (const asset of ["github-mark-black.svg", "github-mark-white.svg", "police-eagle.png", "crime-map-en.png", "crime-map-de.png"])
    await cp(resolve(web, "../assets/brand", asset), join(temporary, "assets", "brand", asset));
  const config = JSON.parse(await readFile(join(web, "../city-config.json"), "utf8"));
  Object.assign(config, {city:"berlin", repository:"crimemaps-Berlin", base_path:"/crimemaps-Berlin/"});
  await writeFile(join(temporary, "city-config.json"), JSON.stringify(config));
  const result = spawnSync("npm", ["run", "build"], {
    cwd:fixtureWeb, env:{...process.env, VITE_BASE_PATH:"/"}, stdio:"inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw Error(`Fixture build exited ${result.status}`);
  await rm(join(web, "dist-fixture"), {recursive:true, force:true});
  await cp(join(fixtureWeb, "dist"), join(web, "dist-fixture"), {recursive:true});
} finally {
  await rm(temporary, {recursive:true, force:true});
}
