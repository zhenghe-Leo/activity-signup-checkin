import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时把 /api 代理到后端 8000 端口；构建产物 dist/ 由 FastAPI 托管（03 §10.1）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: { outDir: 'dist', chunkSizeWarningLimit: 2000 },
})
