import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// В разработке фронтенд и бэкенд живут на разных портах, поэтому запросы к API
// и веб-сокетам проксируются: в браузере адрес один и тот же, что и в бою.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
