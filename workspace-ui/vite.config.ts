import { defineConfig } from 'vite'
import opencode from './upstream/packages/app/vite.js'

export default defineConfig({
  base: '/opencode-workspace/',
  plugins: [opencode],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { target: 'esnext', outDir: '../frontend/public/opencode-workspace', emptyOutDir: true },
})
