import { defineConfig } from "vite";
export default defineConfig({
  server: { host: "127.0.0.1", port: 5173 },
  build: {
    rollupOptions: {
      input: { main: new URL("./index.html", import.meta.url).pathname },
      output: { manualChunks: { maplibre: ["maplibre-gl"] } },
    },
  },
});
