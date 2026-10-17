import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, type Plugin } from "vite";
import vue from "@vitejs/plugin-vue";

const root = fileURLToPath(new URL(".", import.meta.url));

function missingWorkspaceBundle(): Plugin {
  const reject = (req: { url?: string }, res: { statusCode: number; setHeader: (name: string, value: string) => void; end: (body: string) => void }, next: () => void) => {
    const url = (req.url ?? "").split("?")[0];
    if (!url.startsWith("/opencode-workspace/")) return next();
    const file = path.join(root, "public", decodeURIComponent(url));
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.statusCode = 404;
      res.end("OpenCode Workspace UI bundle is not installed");
      return;
    }
    res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    next();
  };
  return {
    name: "opencode-workspace-missing",
    configureServer(server) {
      server.middlewares.use(reject);
    },
    configurePreviewServer(server) {
      server.middlewares.use(reject);
    },
  };
}

export default defineConfig({
  plugins: [vue(), missingWorkspaceBundle()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 15174,
    proxy: {
      "/api/v1": "http://127.0.0.1:18120",
      "/api": "http://127.0.0.1:18100",
      "/v1": "http://127.0.0.1:18110",
    },
  },
});
