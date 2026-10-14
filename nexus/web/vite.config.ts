import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      "/api/v1": "http://127.0.0.1:8120",
      "/api": "http://127.0.0.1:8100",
    },
  },
});
