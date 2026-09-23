import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8100'
const gatewayProxyTarget =
  process.env.VITE_GATEWAY_PROXY_TARGET ?? 'http://127.0.0.1:8110'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': proxyTarget, '/v1': gatewayProxyTarget },
  },
  preview: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': proxyTarget, '/v1': gatewayProxyTarget },
  },
})
