import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { port: 5273, strictPort: true, proxy: { '/api': { target: process.env.ASTRA_API_URL || 'http://127.0.0.1:8200', changeOrigin: true } } },
  build: { target: 'es2022', sourcemap: false, rollupOptions: { output: { manualChunks: { three: ['three'], components: ['element-plus'], vue: ['vue', 'vue-router'] } } } },
})
