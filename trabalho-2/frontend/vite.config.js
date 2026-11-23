import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const backend = { target: env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000", changeOrigin: true };
  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: { "/api": backend, "/healthz": backend },
    },
  };
});
