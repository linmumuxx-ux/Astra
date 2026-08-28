import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8100'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': proxyTarget },
  },
  preview: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': proxyTarget },
  },
})
