import { defineConfig, loadEnv } from "vite";
import { readFileSync } from "node:fs";
const cityNames: Record<string, string> = {
  berlin: "Berlin", hamburg: "Hamburg", munich: "München", cologne: "Köln", frankfurt: "Frankfurt",
  dusseldorf: "Düsseldorf", stuttgart: "Stuttgart", leipzig: "Leipzig", dortmund: "Dortmund",
  bremen: "Bremen", essen: "Essen", dresden: "Dresden", hannover: "Hannover", nuremberg: "Nürnberg",
};
export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const config = JSON.parse(readFileSync(new URL("../city-config.json", import.meta.url), "utf8"));
  if (!Object.hasOwn(cityNames, config.city) || config.repository !== `crimemaps-${config.city[0].toUpperCase()}${config.city.slice(1)}` ||
      config.base_path !== `/${config.repository}/`) throw Error("Invalid single-city configuration");
  return {
  base: env.VITE_BASE_PATH || (command === "serve" ? "/" : config.base_path),
  define: { "import.meta.env.VITE_CRIMEMAPS_CITY": JSON.stringify(config.city) },
  plugins: [{name:"city-document-title", transformIndexHtml: (html) =>
    html.replace(/<title>.*?<\/title>/, `<title>CrimeMaps · ${cityNames[config.city]} · Polizeimeldungen</title>`)}],
  server: { host: "127.0.0.1", port: 5173 },
  build: {
    rollupOptions: {
      input: { main: new URL("./index.html", import.meta.url).pathname },
      output: { manualChunks: { maplibre: ["maplibre-gl"] } },
    },
  },
  };
});
