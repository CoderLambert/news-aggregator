import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import process from "node:process";

// Server-only environment variable: never expose backend configuration via VITE_*.
// Fail closed rather than accidentally proxying a development UI to a remote site.
let apiTarget;
try {
  apiTarget = new URL(
    process.env.NEWSHUB_DEV_API_TARGET ?? "http://127.0.0.1:9527",
  );
  if (
    !["http:", "https:"].includes(apiTarget.protocol) ||
    !["127.0.0.1", "localhost", "[::1]"].includes(apiTarget.hostname) ||
    apiTarget.username || apiTarget.password ||
    apiTarget.pathname !== "/" || apiTarget.search || apiTarget.hash
  ) throw new Error("invalid target");
} catch {
  throw new Error("NEWSHUB_DEV_API_TARGET must be a loopback HTTP(S) origin without credentials, path, query or fragment.");
}

export default defineConfig({
  ...(process.env.NEWSHUB_DEV_CACHE_DIR
    ? { cacheDir: process.env.NEWSHUB_DEV_CACHE_DIR }
    : {}),
  plugins: [
    react({
      babel: {
        plugins: [
          // React Compiler — auto-memoizes components/hooks; eliminates most
          // useCallback / useMemo / React.memo needs. Requires React 19+.
          ["babel-plugin-react-compiler", { target: "19" }],
        ],
      },
    }),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@tests": path.resolve(import.meta.dirname, "tests"),
      "@": path.resolve(import.meta.dirname, "src"),
    },
  },
  server: {
    host: "127.0.0.1",
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget.origin,
        changeOrigin: true,
        timeout: 180000,
        proxyTimeout: 180000,
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            // Fix SSE streaming: disable buffering and set proper headers
            if (
              proxyRes.headers["content-type"]?.includes("text/event-stream")
            ) {
              proxyRes.headers["cache-control"] = "no-cache";
              proxyRes.headers["connection"] = "keep-alive";
              proxyRes.headers["x-accel-buffering"] = "no";
              // Disable Vite's internal response compression for SSE
              delete proxyRes.headers["content-encoding"];
            }
          });
        },
      },
    },
    fs: { allow: [".."] },
  },
  build: {
    // Let Rolldown preserve the lazy route boundaries. Manual vendor groups
    // pulled shared React helpers into the Markdown chunk and made it eager.
    chunkSizeWarningLimit: 1000,
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.js"],
    css: false,
    include: ["tests/**/*.{test,spec}.{js,jsx,ts,tsx}"],
  },
});
